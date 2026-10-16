import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import tasks

CONFIG_PATH = Path(__file__).with_name("rift_config.json")

# ---------- Settings you can edit ----------
RIFT_INTERVAL = timedelta(hours=3)   # A rift opens every 3 hours
DEFAULT_ANCHOR = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)  # A known opening: 00:00 UTC
WARNING = timedelta(minutes=10)      # Ping this long before the rift opens
LATE_LIMIT = timedelta(minutes=5)    # Skip the ping if the bot would be this late
PORTAL_MINUTES = 10                  # The portal stays open this long
# --------------------------------------------


def utcnow():
    return datetime.now(timezone.utc)


def ts(dt, style="R"):
    # Discord shows these in each member's own time zone
    return f"<t:{int(dt.timestamp())}:{style}>"


def load_config():
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    cfg.setdefault("channel_id", None)
    cfg.setdefault("role_id", None)
    cfg.setdefault("anchor", int(DEFAULT_ANCHOR.timestamp()))
    cfg.setdefault("last_alerted", None)
    cfg.setdefault("last_message_id", None)
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def next_rift_open(cfg, now):
    """The next rift opening, counted in 3-hour steps from the saved anchor time."""
    interval = int(RIFT_INTERVAL.total_seconds())
    steps = math.ceil((now.timestamp() - cfg["anchor"]) / interval)
    return datetime.fromtimestamp(cfg["anchor"] + steps * interval, tz=timezone.utc)


def build_embed(open_at, test=False):
    minutes = int(WARNING.total_seconds() // 60)
    embed = discord.Embed(
        title=f"Spacetime Rift opens in {minutes} minutes",
        description=f"A Spacetime Rift opens {ts(open_at)} ({ts(open_at, 't')} your time).\n"
                    f"The portal stays open for the first {PORTAL_MINUTES} minutes, "
                    "and the event runs for the full hour.",
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="Before you go",
        value="You need to be level 45. Pick up the Spacetime Rift regional quests first, "
              "since their objectives only count in enemy territory.",
        inline=False,
    )
    if test:
        embed.set_footer(text="Sample alert")
    return embed


async def post_alert(bot, cfg, open_at, test=False):
    channel_id = cfg["channel_id"]
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    role_id = cfg.get("role_id")
    content = f"<@&{role_id}>" if role_id else None
    old_message_id = cfg.get("last_message_id")

    message = await channel.send(
        content=content,
        embed=build_embed(open_at, test),
        allowed_mentions=discord.AllowedMentions(roles=True),
    )
    cfg["last_message_id"] = message.id
    save_config(cfg)

    # Delete the previous alert now that the new one is posted
    if old_message_id:
        try:
            old_message = await channel.fetch_message(old_message_id)
            await old_message.delete()
        except discord.HTTPException:
            pass  # Already deleted or not found


class RiftWatcher:
    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(seconds=30)
    async def watch_loop(self):
        cfg = load_config()
        if not cfg.get("channel_id"):
            return
        now = utcnow()
        open_at = next_rift_open(cfg, now)
        alert_at = open_at - WARNING
        open_ts = int(open_at.timestamp())
        if alert_at <= now < alert_at + LATE_LIMIT and cfg.get("last_alerted") != open_ts:
            try:
                await post_alert(self.bot, cfg, open_at)
            except Exception as error:
                print(f"Could not post rift alert: {error}")
                return
            cfg["last_alerted"] = open_ts
            save_config(cfg)

    @watch_loop.before_loop
    async def before_watch_loop(self):
        await self.bot.wait_until_ready()


def register(bot):
    """Adds the rift commands and starts the rift watcher. Called from bot.py."""
    RiftWatcher(bot).watch_loop.start()

    @app_commands.command(name="rift", description="Show the next Spacetime Rift openings")
    async def rift(interaction: discord.Interaction):
        cfg = load_config()
        first = next_rift_open(cfg, utcnow())
        lines = []
        for i in range(4):
            open_at = first + i * RIFT_INTERVAL
            lines.append(f"{ts(open_at, 'f')} ({ts(open_at)})")
        embed = discord.Embed(
            title="Next Spacetime Rifts",
            description="\n".join(lines),
            color=discord.Color.purple(),
        )
        embed.set_footer(text="A rift opens every 3 hours. Times show in your own time zone.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setriftchannel", description="Choose the channel for Spacetime Rift alerts")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setriftchannel(interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        cfg["channel_id"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(
            f"Rift alerts will post in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="setriftrole", description="Choose a role to ping for rift alerts (leave empty for no ping)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setriftrole(interaction: discord.Interaction, role: Optional[discord.Role] = None):
        cfg = load_config()
        cfg["role_id"] = role.id if role else None
        save_config(cfg)
        message = f"Rift alerts will ping {role.mention}." if role else "Rift alerts will not ping anyone."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="testrift", description="Post a sample rift alert to the alert channel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def testrift(interaction: discord.Interaction):
        cfg = load_config()
        if not cfg.get("channel_id"):
            await interaction.response.send_message("Run /setriftchannel first.", ephemeral=True)
            return
        try:
            await post_alert(bot, cfg, next_rift_open(cfg, utcnow()), test=True)
        except Exception as error:
            await interaction.response.send_message(f"Couldn't post: {error}", ephemeral=True)
            return
        await interaction.response.send_message("Sample alert posted.", ephemeral=True)

    @app_commands.command(name="riftsync", description="Re-align the rift schedule using the in-game timer")
    @app_commands.describe(minutes="Minutes until the next rift opens, as shown by the in-game or website timer")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def riftsync(interaction: discord.Interaction, minutes: app_commands.Range[int, 0, 179]):
        cfg = load_config()
        target = (utcnow() + timedelta(minutes=minutes, seconds=30)).replace(second=0, microsecond=0)
        cfg["anchor"] = int(target.timestamp())
        cfg["last_alerted"] = None
        save_config(cfg)
        await interaction.response.send_message(
            f"Schedule re-aligned. The next rift opens {ts(target, 'f')} ({ts(target)}). "
            "Every opening after that follows at 3-hour steps.",
            ephemeral=True,
        )

    bot.tree.add_command(rift)
    bot.tree.add_command(setriftchannel)
    bot.tree.add_command(setriftrole)
    bot.tree.add_command(testrift)
    bot.tree.add_command(riftsync)