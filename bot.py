import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
import patchnews as patchnews
import checklist as checklist
import rolepanel as rolepanel
import riftalert as riftalert

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ---------- Settings you can edit ----------
RESET_HOUR_UTC = 7                      # Daily and weekly reset: 07:00 UTC (16:00 KST)
WEEKLY_RESET_WEEKDAY = 2                # 0 = Monday ... 2 = Wednesday
DAILY_WARNING = timedelta(hours=4)      # Post the daily alert 4 hours before reset
WEEKLY_WARNING = timedelta(days=1)      # Post the weekly alert 1 day before reset
SEASON_NAME = "Season 1 Daeva Pass"
SEASON_END = datetime(2026, 12, 16, RESET_HOUR_UTC, 0, tzinfo=timezone.utc)
GRACE = timedelta(minutes=30)           # Skip a missed alert if the bot was off longer than this
CONFIG_PATH = Path(__file__).with_name("config.json")
# --------------------------------------------


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"channel_id": None, "role_id": None, "posted": []}


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def utcnow():
    return datetime.now(timezone.utc)


def next_daily_reset(now):
    candidate = now.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def next_weekly_reset(now):
    days_ahead = (WEEKLY_RESET_WEEKDAY - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def ts(dt, style="R"):
    # Discord shows these in each member's own time zone
    return f"<t:{int(dt.timestamp())}:{style}>"


def season_line(now, reset_at):
    if now >= SEASON_END:
        return f"{SEASON_NAME} has ended."
    if SEASON_END <= reset_at:
        return f"{SEASON_NAME} ends at this reset ({ts(SEASON_END, 'F')})."
    days_left = (SEASON_END - now).days
    return f"{SEASON_NAME} ends {ts(SEASON_END)} ({days_left} days left)."


def build_alert_embed(kind, reset_at, now):
    if kind == "daily":
        embed = discord.Embed(
            title="Daily reset coming up",
            description=f"Daily reset {ts(reset_at)} ({ts(reset_at, 't')} your time). "
                        "Finish your daily tasks before then.",
            color=discord.Color.blue(),
        )
        if reset_at.weekday() == WEEKLY_RESET_WEEKDAY:
            embed.description += "\nThis is also the **weekly reset**."
    else:
        embed = discord.Embed(
            title="Weekly reset in 1 day",
            description=f"Weekly reset {ts(reset_at)} ({ts(reset_at, 'F')}). "
                        "Spend unused raid attempts, Daily Dungeon entries, and Abyss time "
                        "before then, since they don't carry over.",
            color=discord.Color.orange(),
        )
    embed.add_field(name="Season", value=season_line(now, reset_at), inline=False)
    return embed


class GameBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        patchnews.register(self)
        checklist.register(self, next_daily_reset, next_weekly_reset, ts)
        rolepanel.register(self)
        riftalert.register(self)
        synced = await self.tree.sync()
        print("Synced commands:", [c.name for c in synced])
        self.alert_loop.start()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def post_alert(self, cfg, kind, reset_at, now):
        channel = self.get_channel(cfg["channel_id"]) or await self.fetch_channel(cfg["channel_id"])

        # Ping the role if one is set, otherwise ping everyone
        if cfg.get("role_id"):
            content = f"<@&{cfg['role_id']}>"
        else:
            content = "@everyone"

        # Daily and weekly alerts each remember their own last message
        old_message_id = cfg.get(f"last_message_id_{kind}")

        message = await channel.send(
            content=content,
            embed=build_alert_embed(kind, reset_at, now),
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=True),
        )
        cfg[f"last_message_id_{kind}"] = message.id
        save_config(cfg)

        # Delete only the previous alert of the same kind
        if old_message_id:
            try:
                old_message = await channel.fetch_message(old_message_id)
                await old_message.delete()
            except discord.HTTPException:
                pass  # Already deleted or not found

    @tasks.loop(seconds=60)
    async def alert_loop(self):
        cfg = load_config()
        if not cfg.get("channel_id"):
            return
        now = utcnow()
        checks = (
            ("daily", next_daily_reset(now), DAILY_WARNING),
            ("weekly", next_weekly_reset(now), WEEKLY_WARNING),
        )
        for kind, reset_at, lead in checks:
            alert_at = reset_at - lead
            key = f"{kind}:{int(reset_at.timestamp())}"
            if alert_at <= now < alert_at + GRACE and key not in cfg["posted"]:
                try:
                    await self.post_alert(cfg, kind, reset_at, now)
                except Exception as error:
                    print(f"Could not post {kind} alert: {error}")
                    continue
                cfg["posted"] = (cfg["posted"] + [key])[-20:]
                save_config(cfg)

    @alert_loop.before_loop
    async def before_alert_loop(self):
        await self.wait_until_ready()


bot = GameBot()


@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms")


@bot.tree.command(name="reset", description="Show the next daily and weekly reset")
async def reset(interaction: discord.Interaction):
    now = utcnow()
    daily, weekly = next_daily_reset(now), next_weekly_reset(now)
    embed = discord.Embed(title="Aion 2 resets", color=discord.Color.blue())
    embed.add_field(name="Daily reset", value=f"{ts(daily)}\n{ts(daily, 'F')}", inline=False)
    embed.add_field(name="Weekly reset", value=f"{ts(weekly)}\n{ts(weekly, 'F')}", inline=False)
    embed.add_field(name="Season", value=season_line(now, weekly), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="season", description="Show the season countdown")
async def season(interaction: discord.Interaction):
    now = utcnow()
    embed = discord.Embed(title=SEASON_NAME, color=discord.Color.purple())
    if now >= SEASON_END:
        embed.description = "This season has ended."
    else:
        embed.description = f"Ends {ts(SEASON_END)}\n{ts(SEASON_END, 'F')}"
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setchannel", description="Choose the channel for reset alerts")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = load_config()
    cfg["channel_id"] = channel.id
    save_config(cfg)
    await interaction.response.send_message(
        f"Reset alerts will post in {channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="setrole", description="Choose a role to ping with alerts (leave empty to ping @everyone)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setrole(interaction: discord.Interaction, role: Optional[discord.Role] = None):
    cfg = load_config()
    cfg["role_id"] = role.id if role else None
    save_config(cfg)
    message = f"Alerts will ping {role.mention}." if role else "Alerts will ping @everyone."
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="testalert", description="Post a sample alert to the alert channel")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def testalert(interaction: discord.Interaction, kind: Literal["daily", "weekly"]):
    cfg = load_config()
    if not cfg.get("channel_id"):
        await interaction.response.send_message("Run /setchannel first.", ephemeral=True)
        return
    now = utcnow()
    reset_at = next_daily_reset(now) if kind == "daily" else next_weekly_reset(now)
    try:
        await bot.post_alert(cfg, kind, reset_at, now)
    except Exception as error:
        await interaction.response.send_message(f"Couldn't post: {error}", ephemeral=True)
        return
    await interaction.response.send_message("Sample alert posted.", ephemeral=True)


if TOKEN is None:
    raise SystemExit("DISCORD_TOKEN not found. Check your .env file.")

bot.run(TOKEN)