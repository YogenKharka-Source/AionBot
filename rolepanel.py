import json
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands

CONFIG_PATH = Path(__file__).with_name("rolepanel_config.json")
MAX_ROLES = 25  # Discord allows 25 buttons on one message

# Roles with any of these permissions can never go on the panel
BLOCKED_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_messages", "manage_threads", "manage_webhooks", "manage_nicknames",
    "kick_members", "ban_members", "moderate_members", "mention_everyone",
    "manage_expressions",
)

# Remembers each member's latest private message so the next one can replace it
_last_reply = {}


def load_config():
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    cfg.setdefault("roles", [])
    cfg.setdefault("panel", None)
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def risky_permissions(role):
    return [
        name.replace("_", " ")
        for name in BLOCKED_PERMISSIONS
        if getattr(role.permissions, name, False)
    ]


def build_embed(guild, cfg):
    lines = []
    for entry in cfg["roles"]:
        role = guild.get_role(entry["role_id"])
        if role is None:
            continue
        line = f"{role.mention}"
        if entry.get("description"):
            line += f": {entry['description']}"
        lines.append(line)
    return discord.Embed(
        title="Pick your roles",
        description="Click a button to get a role. Click it again to remove it.\n\n"
                    + ("\n".join(lines) if lines else "No roles on the panel yet."),
        color=discord.Color.blurple(),
    )


async def send_reply(interaction, text):
    """Send a private message, then delete this member's previous one."""
    previous = _last_reply.get(interaction.user.id)
    await interaction.response.send_message(text, ephemeral=True)
    _last_reply[interaction.user.id] = interaction
    if previous is not None:
        try:
            await previous.delete_original_response()
        except discord.HTTPException:
            pass  # Already dismissed, or too old for Discord to let us delete


class RoleButton(discord.ui.Button):
    def __init__(self, role_id, label):
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"rolepanel:{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await send_reply(interaction, "That role no longer exists.")
            return
        if risky_permissions(role):
            await send_reply(interaction, "That role can't be self-assigned anymore. Ask an admin.")
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Role panel")
                text = f"Your {role.mention} role has been removed."
            else:
                await member.add_roles(role, reason="Role panel")
                text = f"You have been assigned the {role.mention} role."
        except discord.Forbidden:
            text = (
                "I can't change that role. An admin needs to move my role above it "
                "in the server's role list."
            )
        await send_reply(interaction, text)


class RolePanelView(discord.ui.View):
    def __init__(self, entries):
        super().__init__(timeout=None)
        for entry in entries[:MAX_ROLES]:
            self.add_item(RoleButton(entry["role_id"], entry["label"]))


async def refresh_panel(bot):
    """Update the posted panel message after the role list changes."""
    cfg = load_config()
    panel = cfg.get("panel")
    if not panel:
        return False
    try:
        channel = bot.get_channel(panel["channel_id"]) or await bot.fetch_channel(panel["channel_id"])
        message = await channel.fetch_message(panel["message_id"])
        await message.edit(embed=build_embed(channel.guild, cfg), view=RolePanelView(cfg["roles"]))
    except discord.HTTPException:
        return False
    return True


def register(bot):
    """Adds the role panel commands. Called from bot.py."""
    # Lets the buttons keep working after a bot restart
    bot.add_view(RolePanelView(load_config()["roles"]))

    @app_commands.command(name="addpanelrole", description="Add a role to the self-assign panel")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def addpanelrole(
        interaction: discord.Interaction,
        role: discord.Role,
        label: Optional[str] = None,
        description: Optional[str] = None,
    ):
        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "That role can't be self-assigned (it's @everyone or managed by a bot).",
                ephemeral=True,
            )
            return
        risky = risky_permissions(role)
        if risky:
            await interaction.response.send_message(
                f"I won't put {role.mention} on the panel because it has powerful permissions: "
                f"{', '.join(risky)}.",
                ephemeral=True,
            )
            return

        cfg = load_config()
        entry = next((e for e in cfg["roles"] if e["role_id"] == role.id), None)
        if entry is None:
            if len(cfg["roles"]) >= MAX_ROLES:
                await interaction.response.send_message(
                    f"The panel is full ({MAX_ROLES} roles max).", ephemeral=True
                )
                return
            entry = {"role_id": role.id}
            cfg["roles"].append(entry)
        entry["label"] = (label or role.name)[:80]
        entry["description"] = (description or "")[:100]
        save_config(cfg)

        notes = []
        if role.position >= interaction.guild.me.top_role.position:
            notes.append(
                "My role sits below it, so move my role above it in Server Settings, then Roles."
            )
        if not await refresh_panel(bot):
            notes.append("Run /postpanel to post or refresh the panel.")
        reply = f"Added {role.mention} to the panel."
        if notes:
            reply += "\n" + "\n".join(notes)
        await interaction.response.send_message(reply, ephemeral=True)

    @app_commands.command(name="removepanelrole", description="Remove a role from the self-assign panel")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def removepanelrole(interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        before = len(cfg["roles"])
        cfg["roles"] = [e for e in cfg["roles"] if e["role_id"] != role.id]
        if len(cfg["roles"]) == before:
            await interaction.response.send_message(
                f"{role.mention} isn't on the panel.", ephemeral=True
            )
            return
        save_config(cfg)
        await refresh_panel(bot)
        await interaction.response.send_message(f"Removed {role.mention} from the panel.", ephemeral=True)

    @app_commands.command(name="postpanel", description="Post the role panel in a channel")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def postpanel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        cfg = load_config()
        if not cfg["roles"]:
            await interaction.response.send_message(
                "Add at least one role first with /addpanelrole.", ephemeral=True
            )
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Pick a regular text channel for the panel.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Remove the old panel so there's only ever one
        old = cfg.get("panel")
        if old:
            try:
                old_channel = bot.get_channel(old["channel_id"]) or await bot.fetch_channel(old["channel_id"])
                old_message = await old_channel.fetch_message(old["message_id"])
                await old_message.delete()
            except discord.HTTPException:
                pass

        try:
            message = await target.send(
                embed=build_embed(interaction.guild, cfg),
                view=RolePanelView(cfg["roles"]),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"I can't post in {target.mention}. Give the AionBot role View Channel, "
                "Send Messages, and Embed Links there.",
                ephemeral=True,
            )
            return

        cfg["panel"] = {"channel_id": target.id, "message_id": message.id}
        save_config(cfg)
        await interaction.followup.send(f"Role panel posted in {target.mention}.", ephemeral=True)

    bot.tree.add_command(addpanelrole)
    bot.tree.add_command(removepanelrole)
    bot.tree.add_command(postpanel)