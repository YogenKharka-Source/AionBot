import json
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

DATA_PATH = Path(__file__).with_name("checklist_data.json")
THREADS_PATH = Path(__file__).with_name("checklist_threads.json")
CONFIG_PATH = Path(__file__).with_name("checklist_config.json")

# ---------- Edit these lists to change the checklist ----------
# Each line is: (unique id, name shown, short description). Max 25 per list.
DAILY_TASKS = [
    ("duty", "Duty Missions", "5 completions a day (counted per server)"),
    ("nightmare", "Nightmare attempts", "Use your 2 daily attempts"),
    ("odyle", "Spend Odyle Energy", "Conquest/Transcendence cubes before it caps"),
    ("shugo", "Shugo Festival keys", "3 a day"),
    ("invasion", "Dimensional Invasion key", "1 a day"),
    ("fissure", "Daily dungeon", "2 Unknown Fissure entries a day"),
]

WEEKLY_TASKS = [
    ("raids", "Sanctuary raids", "4 attempts per raid"),
    ("ascension", "Ascension Trial", "3 entries"),
    ("subjugation", "Subjugation", "3 tickets"),
    ("exploration", "Exploration dungeons", "7 reward counts per dungeon"),
    ("abyss", "Abyss time", "7 hours in each layer"),
    ("growth", "Growth dungeons", "7 hours in each"),
    ("daevapass", "Daeva Pass weekly EXP", "Reach the weekly pass EXP limit"),
    ("seasonmission", "Season Mission", "Weekly points before the reset"),
]
# ---------------------------------------------------------------

_helpers = {}


def utcnow():
    return datetime.now(timezone.utc)


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def get_entry(data, user_id):
    """Get a member's saved progress, clearing anything from a past reset."""
    now = utcnow()
    daily_reset = _helpers["daily"](now)
    weekly_reset = _helpers["weekly"](now)
    entry = data.setdefault(str(user_id), {})
    if entry.get("daily_key") != int(daily_reset.timestamp()):
        entry["daily_key"] = int(daily_reset.timestamp())
        entry["daily_done"] = []
    if entry.get("weekly_key") != int(weekly_reset.timestamp()):
        entry["weekly_key"] = int(weekly_reset.timestamp())
        entry["weekly_done"] = []
    return entry, daily_reset, weekly_reset


def checklist_lines(task_list, done):
    return "\n".join(
        f"{'✅' if task_id in done else '⬜'} {label}" for task_id, label, _ in task_list
    )


def build_embed(user_id):
    data = load_json(DATA_PATH)
    entry, daily_reset, weekly_reset = get_entry(data, user_id)
    save_json(DATA_PATH, data)
    ts = _helpers["ts"]

    daily_done = entry["daily_done"]
    weekly_done = entry["weekly_done"]
    all_done = len(daily_done) == len(DAILY_TASKS) and len(weekly_done) == len(WEEKLY_TASKS)

    embed = discord.Embed(
        title="Your Aion 2 checklist",
        description="Use the menus below to tick off what you've finished. "
                    "This thread closes at the next reset, or when you press Close checklist.",
        color=discord.Color.green() if all_done else discord.Color.blue(),
    )
    embed.add_field(
        name=f"Daily ({len(daily_done)}/{len(DAILY_TASKS)})",
        value=f"{checklist_lines(DAILY_TASKS, daily_done)}\n\nResets {ts(daily_reset)}",
        inline=False,
    )
    embed.add_field(
        name=f"Weekly ({len(weekly_done)}/{len(WEEKLY_TASKS)})",
        value=f"{checklist_lines(WEEKLY_TASKS, weekly_done)}\n\nResets {ts(weekly_reset)}",
        inline=False,
    )
    return embed


def owner_of(thread_id):
    """Find which member a checklist thread belongs to."""
    for user_id, record in load_json(THREADS_PATH).items():
        if record["thread_id"] == thread_id:
            return int(user_id)
    return None


async def delete_thread(thread_id):
    bot = _helpers["bot"]
    try:
        thread = bot.get_channel(thread_id) or await bot.fetch_channel(thread_id)
        await thread.delete()
    except discord.NotFound:
        pass  # Already gone
    except discord.HTTPException as error:
        print(f"Could not close checklist thread {thread_id}: {error}")


async def end_checklist(user_id):
    records = load_json(THREADS_PATH)
    record = records.pop(str(user_id), None)
    save_json(THREADS_PATH, records)
    if record:
        await delete_thread(record["thread_id"])


async def check_owner(interaction):
    """Return the owner's id if this member may use the checklist, otherwise reply and return None."""
    owner_id = owner_of(interaction.channel_id)
    if owner_id is None:
        await interaction.response.send_message(
            "This checklist has expired. Run /checklist to open a new one.", ephemeral=True
        )
        return None
    if interaction.user.id != owner_id:
        await interaction.response.send_message("This isn't your checklist.", ephemeral=True)
        return None
    return owner_id


class TaskSelect(discord.ui.Select):
    def __init__(self, kind, task_list, done):
        options = [
            discord.SelectOption(
                label=label,
                value=task_id,
                description=description,
                default=task_id in done,
            )
            for task_id, label, description in task_list
        ]
        super().__init__(
            custom_id=f"checklist:{kind}",
            placeholder=f"{kind.capitalize()} tasks: pick what you've finished",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        self.kind = kind

    async def callback(self, interaction: discord.Interaction):
        owner_id = await check_owner(interaction)
        if owner_id is None:
            return
        data = load_json(DATA_PATH)
        entry, _, _ = get_entry(data, owner_id)
        entry[f"{self.kind}_done"] = list(self.values)
        save_json(DATA_PATH, data)
        await interaction.response.edit_message(
            embed=build_embed(owner_id), view=ChecklistView(owner_id)
        )


class CloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Close checklist",
            style=discord.ButtonStyle.danger,
            custom_id="checklist:close",
        )

    async def callback(self, interaction: discord.Interaction):
        owner_id = await check_owner(interaction)
        if owner_id is None:
            return
        await interaction.response.defer()
        await end_checklist(owner_id)


class ChecklistView(discord.ui.View):
    def __init__(self, user_id=None):
        super().__init__(timeout=None)
        daily_done, weekly_done = [], []
        if user_id is not None:
            data = load_json(DATA_PATH)
            entry, _, _ = get_entry(data, user_id)
            daily_done, weekly_done = entry["daily_done"], entry["weekly_done"]
        self.add_item(TaskSelect("daily", DAILY_TASKS, daily_done))
        self.add_item(TaskSelect("weekly", WEEKLY_TASKS, weekly_done))
        self.add_item(CloseButton())


class ThreadCloser:
    """Closes checklist threads once the reset passes."""

    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(minutes=1)
    async def close_loop(self):
        now = int(utcnow().timestamp())
        records = load_json(THREADS_PATH)
        due = [user_id for user_id, record in records.items() if record["close_at"] <= now]
        for user_id in due:
            await end_checklist(int(user_id))

    @close_loop.before_loop
    async def before_close_loop(self):
        await self.bot.wait_until_ready()


def register(bot, next_daily_reset, next_weekly_reset, ts):
    """Adds the checklist commands. Called from bot.py."""
    _helpers.update(bot=bot, daily=next_daily_reset, weekly=next_weekly_reset, ts=ts)

    # Lets the menus and button keep working after a bot restart
    bot.add_view(ChecklistView())
    ThreadCloser(bot).close_loop.start()

    @app_commands.command(name="setchecklistchannel", description="Choose the channel where /checklist can be used")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setchecklistchannel(interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_json(CONFIG_PATH)
        cfg["channel_id"] = channel.id
        save_json(CONFIG_PATH, cfg)
        await interaction.response.send_message(
            f"/checklist can now only be used in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="checklist", description="Open your private daily and weekly checklist")
    async def checklist(interaction: discord.Interaction):
        cfg = load_json(CONFIG_PATH)
        allowed_channel_id = cfg.get("channel_id")

        if not allowed_channel_id:
            await interaction.response.send_message(
                "The checklist channel isn't set up yet. Ask an admin to run /setchecklistchannel.",
                ephemeral=True,
            )
            return
        if interaction.channel_id != allowed_channel_id:
            await interaction.response.send_message(
                f"Please use /checklist in <#{allowed_channel_id}>.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Run /checklist in the checklist channel itself, not inside a thread.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        records = load_json(THREADS_PATH)

        # If they already have a checklist open, close it and start fresh.
        # Their ticked items are stored separately, so nothing is lost.
        existing = records.pop(str(user.id), None)
        if existing:
            await delete_thread(existing["thread_id"])
            save_json(THREADS_PATH, records)

        try:
            thread = await channel.create_thread(
                name=f"checklist-{user.display_name}"[:90],
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440,
            )
            await thread.add_user(user)
            await thread.send(
                content=user.mention,
                embed=build_embed(user.id),
                view=ChecklistView(user.id),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to make private threads here. Give the AionBot role "
                "Create Private Threads, Send Messages in Threads, and Manage Threads.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            await interaction.followup.send(f"Couldn't open your checklist: {error}", ephemeral=True)
            return

        records[str(user.id)] = {
            "thread_id": thread.id,
            "close_at": int(next_daily_reset(utcnow()).timestamp()),
        }
        save_json(THREADS_PATH, records)
        message = "Your checklist has been reopened" if existing else "Your private checklist is ready"
        await interaction.followup.send(f"{message}: {thread.mention}", ephemeral=True)

    bot.tree.add_command(setchecklistchannel)
    bot.tree.add_command(checklist)