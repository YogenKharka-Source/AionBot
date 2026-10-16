import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

# ---------- Settings you can edit ----------
STEAM_APP_ID = 3393110                  # AION 2 global on Steam
STEAM_FEEDS = "steam_community_announcements"  # Official posts only. Use "" to include every feed.
NEWS_POLL_MINUTES = 10                  # How often to check for new posts
NEWS_MAX_CHARS = 3000                   # Longest post body shown before trimming
CONFIG_PATH = Path(__file__).with_name("news_config.json")
# --------------------------------------------

STEAM_TAGS = (
    r"list|olist|quote|code|strike|spoiler|noparse|hr|table|tr|td|th|"
    r"url|b|i|u|h1|h2|h3|img|previewyoutube|p"
)


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"channel_id": None, "role_id": None, "seen": None}


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _table_to_text(match):
    """Turn a Steam [table] into 'Label: value' lines."""
    lines = []
    for row in re.findall(r"\[tr[^\]]*\](.*?)\[/tr\]", match.group(1), flags=re.S | re.I):
        cells = re.findall(r"\[t[hd][^\]]*\](.*?)\[/t[hd]\]", row, flags=re.S | re.I)
        cells = [re.sub(r"\s+", " ", c.replace("**", "")).strip() for c in cells]
        cells = [c for c in cells if c]
        if len(cells) == 2:
            lines.append(f"**{cells[0]}** {cells[1]}")
        elif cells:
            lines.append(" | ".join(cells))
    return "\n" + "\n".join(lines) + "\n"


def clean_steam_text(text):
    """Turn Steam's BBCode-style post text into clean Discord markdown."""
    text = text.replace("\r", "")
    text = re.sub(r"\[img[^\]]*\].*?\[/img\]", "", text, flags=re.S | re.I)
    text = re.sub(r"\[previewyoutube[^\]]*\].*?\[/previewyoutube\]", "", text, flags=re.S | re.I)
    text = re.sub(r"\{STEAM_CLAN_IMAGE\}\S*", "", text)

    # Paragraphs and list items
    text = re.sub(r"\[p(?:\s[^\]]*)?\]", "", text, flags=re.I)
    text = re.sub(r"\[/p\]", "\n", text, flags=re.I)
    text = re.sub(r"\[/\*\]", "", text)
    text = re.sub(r"\[\*\]", "\n• ", text)

    # Inline formatting
    text = re.sub(r"\[h[1-3]\](.*?)\[/h[1-3]\]", r"\n**\1**\n", text, flags=re.S | re.I)
    text = re.sub(r"\[b\](.*?)\[/b\]", r"**\1**", text, flags=re.S | re.I)
    text = re.sub(r"\[i\](.*?)\[/i\]", r"*\1*", text, flags=re.S | re.I)
    text = re.sub(r"\[u\](.*?)\[/u\]", r"__\1__", text, flags=re.S | re.I)
    text = re.sub(r"\[strike\](.*?)\[/strike\]", r"~~\1~~", text, flags=re.S | re.I)
    text = re.sub(r"\[spoiler\](.*?)\[/spoiler\]", r"||\1||", text, flags=re.S | re.I)
    text = re.sub(r"\[url=([^\]]+)\](.*?)\[/url\]", r"[\2](\1)", text, flags=re.S | re.I)

    # Tables -> "**Label:** value" lines
    text = re.sub(r"\[table[^\]]*\](.*?)\[/table\]", _table_to_text, text, flags=re.S | re.I)

    # Strip any leftover tags (allows attributes like colwidth="151")
    text = re.sub(rf"\[/?(?:{STEAM_TAGS})(?:[=\s][^\]]*)?\]", "\n", text, flags=re.I)

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_text(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "\n" in cut:
        cut = cut[: cut.rfind("\n")]
    return cut.rstrip() + "\n…"


def build_news_embed(item):
    link = item["url"]
    body = truncate_text(clean_steam_text(item.get("contents", "")), NEWS_MAX_CHARS)
    embed = discord.Embed(
        title=item["title"][:256],
        url=link,
        description=f"{body}\n\n[Read the full post]({link})".strip(),
        color=discord.Color.green(),
        timestamp=datetime.fromtimestamp(item["date"], tz=timezone.utc),
    )
    embed.set_footer(text="AION 2 official news (Steam)")
    return embed


async def fetch_steam_news(count=10):
    url = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
    params = {"appid": STEAM_APP_ID, "count": count, "maxlength": 0, "format": "json"}
    if STEAM_FEEDS:
        params["feeds"] = STEAM_FEEDS
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
    return data.get("appnews", {}).get("newsitems", [])


class NewsFeed:
    def __init__(self, bot):
        self.bot = bot

    async def post_news(self, cfg, item):
        channel_id = cfg["channel_id"]
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        role_id = cfg.get("role_id")
        content = f"<@&{role_id}>" if role_id else None
        await channel.send(
            content=content,
            embed=build_news_embed(item),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

    @tasks.loop(minutes=NEWS_POLL_MINUTES)
    async def news_loop(self):
        cfg = load_config()
        if not cfg.get("channel_id"):
            return
        try:
            items = await fetch_steam_news(10)
        except Exception as error:
            print(f"Could not check Steam news: {error}")
            return

        seen = cfg.get("seen")
        if seen is None:
            # First run: remember what already exists and post nothing
            cfg["seen"] = [item["gid"] for item in items]
            save_config(cfg)
            return

        new_items = [item for item in items if item["gid"] not in seen]
        for item in reversed(new_items):  # Oldest first
            try:
                await self.post_news(cfg, item)
            except Exception as error:
                print(f"Could not post news '{item.get('title')}': {error}")
                continue
            seen.append(item["gid"])
            cfg["seen"] = seen[-50:]
            save_config(cfg)

    @news_loop.before_loop
    async def before_news_loop(self):
        await self.bot.wait_until_ready()


def register(bot):
    """Adds the news commands and starts the news checker. Called from bot.py."""
    feed = NewsFeed(bot)

    @app_commands.command(name="setnewschannel", description="Choose the channel for official news and patch notes")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setnewschannel(interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        cfg["channel_id"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(
            f"Official news will post in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="setnewsrole", description="Choose a role to ping for news (leave empty for no ping)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setnewsrole(interaction: discord.Interaction, role: Optional[discord.Role] = None):
        cfg = load_config()
        cfg["role_id"] = role.id if role else None
        save_config(cfg)
        message = f"News posts will ping {role.mention}." if role else "News posts will not ping anyone."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="latestnews", description="Post the latest official news item to the news channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def latestnews(interaction: discord.Interaction):
        cfg = load_config()
        if not cfg.get("channel_id"):
            await interaction.response.send_message("Run /setnewschannel first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            items = await fetch_steam_news(10)
        except Exception as error:
            await interaction.followup.send(f"Couldn't reach Steam: {error}", ephemeral=True)
            return
        if not items:
            await interaction.followup.send(
                "Steam returned no news for this game. Try setting STEAM_FEEDS to an empty "
                "string at the top of patchnews.py.",
                ephemeral=True,
            )
            return
        try:
            await feed.post_news(cfg, items[0])
        except Exception as error:
            await interaction.followup.send(f"Couldn't post: {error}", ephemeral=True)
            return
        seen = cfg.get("seen")
        if seen is None:
            seen = [item["gid"] for item in items]
        elif items[0]["gid"] not in seen:
            seen.append(items[0]["gid"])
        cfg["seen"] = seen[-50:]
        save_config(cfg)
        await interaction.followup.send("Posted the latest news item.", ephemeral=True)

    bot.tree.add_command(setnewschannel)
    bot.tree.add_command(setnewsrole)
    bot.tree.add_command(latestnews)
    feed.news_loop.start()