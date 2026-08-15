from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Iterable

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.workflow_store import WorkflowStore


EMBASSY_PERMISSIONS = (
    "view_channel",
    "send_messages",
    "read_message_history",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
    "add_reactions",
    "embed_links",
    "attach_files",
)

WELCOME_MESSAGES = (
    "🎉 Welcome to the embassy! Your chair has been dusted, your diplomatic coffee is ready, and the paperwork has been politely frightened away.",
    "🌍 Welcome, diplomat! May your negotiations be smooth, your pings be few, and your coffee remain dangerously effective.",
    "🕊️ A new diplomat has entered the building. Please remain calm; diplomacy is now officially in session.",
    "🏛️ Welcome aboard! Your embassy access is live. Go forth, represent well, and try not to start an international incident before lunch.",
    "✨ Welcome to the mission! The door is open, the files are waiting, and RAJDOOT promises to only summon you for important things... mostly.",
)


def _role(member: discord.Member, role_id: int | None, names: Iterable[str] = ()) -> discord.Role | None:
    if role_id:
        role = member.guild.get_role(role_id)
        if role:
            return role
    wanted = {name.casefold().strip() for name in names}
    return next((r for r in member.roles if r.name.casefold().strip() in wanted), None)


def is_government(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    return any(role.name.casefold().strip() == settings.eam_role_name.casefold().strip() for role in member.roles)


def has_ambassador_role(member: discord.Member) -> bool:
    return _role(member, settings.ambassador_role_id, ("Ambassador",)) is not None


def has_foreign_diplomat_role(member: discord.Member) -> bool:
    return _role(member, settings.foreign_diplomat_role_id, ("Foreign Diplomat",)) is not None


def apply_embassy_permissions(channel: discord.TextChannel, member: discord.Member) -> discord.PermissionOverwrite:
    overwrite = channel.overwrites_for(member)
    for permission in EMBASSY_PERMISSIONS:
        setattr(overwrite, permission, True)
    return overwrite


class EmbassyAccessService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.store = WorkflowStore(database)

    async def grant(self, guild: discord.Guild, member: discord.Member, embassy: dict, *, actor_id: int | None,
                    assignment_type: str = "foreign_diplomat") -> None:
        channel_id = embassy.get("channel_id")
        if not channel_id:
            raise RuntimeError("Embassy has no Discord channel")
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("Embassy Discord channel is unavailable")
        await self.store.upsert_assignment(
            user_discord_id=member.id,
            embassy_id=str(embassy["id"]),
            assignment_type=assignment_type,
            granted_by=actor_id,
        )
        await channel.set_permissions(
            member,
            overwrite=apply_embassy_permissions(channel, member),
            reason="RAJDOOT embassy access grant",
        )
        if not has_foreign_diplomat_role(member):
            role = _role(member, settings.foreign_diplomat_role_id, ("Foreign Diplomat",))
            if role:
                await member.add_roles(role, reason="RAJDOOT embassy access grant")
        await self.store.log_audit(
            actor=actor_id,
            action="EMBASSY_ACCESS_GRANTED",
            target_type="user",
            target_id=str(member.id),
            embassy_id=str(embassy["id"]),
            result="SUCCESS",
            metadata={"assignment_type": assignment_type},
        )
        await self._welcome(channel, member, embassy)

    async def revoke(self, guild: discord.Guild, member: discord.Member, embassy: dict, *, actor_id: int) -> bool:
        changed = await self.store.revoke_assignment(member.id, str(embassy["id"]), actor_id)
        if not changed:
            return False
        channel_id = embassy.get("channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.set_permissions(member, overwrite=None, reason="RAJDOOT embassy access revoked")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
        assignments = await self.store.active_assignments_for_user(member.id)
        if not assignments:
            role = _role(member, settings.foreign_diplomat_role_id, ("Foreign Diplomat",))
            if role:
                try:
                    await member.remove_roles(role, reason="RAJDOOT no active embassy assignments remain")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await self.store.log_audit(
            actor=actor_id,
            action="EMBASSY_ACCESS_REVOKED",
            target_type="user",
            target_id=str(member.id),
            embassy_id=str(embassy["id"]),
            result="SUCCESS",
        )
        return True

    async def _welcome(self, channel: discord.TextChannel, member: discord.Member, embassy: dict) -> None:
        index = (member.id + int(embassy["id"].int if hasattr(embassy["id"], "int") else 0)) % len(WELCOME_MESSAGES)
        message = await channel.send(
            f"{member.mention}\n{WELCOME_MESSAGES[index]}\n\n"
            f"🏛️ **{embassy.get('country_name', 'Embassy')} Embassy** access has been granted.",
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        try:
            await message.add_reaction("🎉")
        except discord.HTTPException:
            pass


class EmbassySelectView(discord.ui.View):
    def __init__(self, database: Database, *, member: discord.Member, action: str) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.member = member
        self.action = action
        self.store = WorkflowStore(database)
        self.select = discord.ui.Select(
            placeholder="Select one or more embassies",
            min_values=1,
            max_values=min(25, 25),
            options=[],
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def populate(self) -> None:
        embassies = await self.database.fetch_active_embassies()
        self.select.options = [
            discord.SelectOption(
                label=str(e["country_name"])[:100],
                value=str(e["id"]),
                description=f"#{e.get('channel_name') or 'embassy channel'}"[:100],
            )
            for e in embassies[:25]
        ]

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.user.id != self.member.id:
            await interaction.response.send_message("This menu belongs to another diplomat action.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        embassies = {str(e["id"]): e for e in await self.database.fetch_active_embassies()}
        service = EmbassyAccessService(self.database)
        changed = 0
        for embassy_id in self.select.values:
            embassy = embassies.get(embassy_id)
            if not embassy:
                continue
            if self.action == "assign":
                if not has_ambassador_role(self.member):
                    await interaction.followup.send("❌ The selected user no longer has the Ambassador role.", ephemeral=True)
                    return
                await service.grant(
                    interaction.guild,
                    self.member,
                    embassy,
                    actor_id=interaction.user.id,
                    assignment_type="foreign_diplomat",
                )
                changed += 1
            else:
                if await service.revoke(interaction.guild, self.member, embassy, actor_id=interaction.user.id):
                    changed += 1
        verb = "assigned" if self.action == "assign" else "revoked"
        await interaction.followup.send(f"✅ Embassy access {verb} for **{changed}** embassy/embassies.", ephemeral=True)
        self.stop()


class EmbassyManagementCommands(app_commands.Group):
    def __init__(self, database: Database) -> None:
        super().__init__(name="diplomacy", description="Embassy and diplomat management")
        self.database = database
        self.store = WorkflowStore(database)

    async def _authorized_for_embassy(self, member: discord.Member, embassy_id: str) -> bool:
        if is_government(member):
            return True
        assignments = await self.store.active_assignments_for_user(member.id)
        return any(str(a["embassy_id"]) == embassy_id for a in assignments)

    @app_commands.command(name="preapproval", description="Pre-approve a WarEra visitor for one of your embassies")
    @app_commands.describe(embassy="Embassy UUID", profile="WarEra profile URL", hours="Optional expiry in hours", reason="Optional reason")
    async def preapproval(self, interaction: discord.Interaction, embassy: str, profile: str, hours: int = 72, reason: str | None = None) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("This command must be used in the embassy server.", ephemeral=True)
            return
        embassy_row = await self.database.fetch_embassy(embassy)
        if not embassy_row or embassy_row.get("status") != "active":
            await interaction.response.send_message("❌ That embassy is not active.", ephemeral=True)
            return
        if not await self._authorized_for_embassy(interaction.user, embassy):
            await interaction.response.send_message("🔐 You can only pre-approve visitors for embassies you manage.", ephemeral=True)
            return
        match = re.search(r"/user/([A-Za-z0-9_-]+)", profile.strip())
        if not match:
            await interaction.response.send_message("❌ Please provide a valid WarEra profile URL.", ephemeral=True)
            return
        if hours < 1 or hours > 720:
            await interaction.response.send_message("❌ Expiry must be between 1 and 720 hours.", ephemeral=True)
            return
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        row = await self.store.create_preapproval(
            embassy_id=embassy,
            diplomat_discord_id=interaction.user.id,
            visitor_warera_id=match.group(1),
            visitor_profile_url=profile.strip(),
            expires_at=expires_at,
            reason=reason,
        )
        await self.store.log_audit(
            actor=interaction.user.id,
            action="PREAPPROVAL_CREATED",
            target_type="preapproval",
            target_id=str(row["id"]),
            embassy_id=embassy,
            result="SUCCESS",
            metadata={"visitor_warera_id": match.group(1), "expires_at": expires_at.isoformat()},
        )
        await interaction.response.send_message(
            f"🤝 Pre-approval created for WarEra user `{match.group(1)}`.\nExpires: <t:{int(expires_at.timestamp())}:R>",
            ephemeral=True,
        )

    @app_commands.command(name="removediplomat", description="Revoke one user's access to selected embassies")
    @app_commands.describe(user="Diplomat whose embassy access should be revoked")
    async def removediplomat(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            assignments = await self.store.active_assignments_for_user(interaction.user.id) if isinstance(interaction.user, discord.Member) else []
            allowed = {str(a["embassy_id"]) for a in assignments}
            if not allowed:
                await interaction.response.send_message("🔐 You do not manage any embassies.", ephemeral=True)
                return
        view = EmbassySelectView(self.database, member=user, action="revoke")
        await view.populate()
        await interaction.response.send_message("🧹 Select the embassy access to revoke:", view=view, ephemeral=True)

    @app_commands.command(name="listembassies", description="List active embassies alphabetically")
    async def listembassies(self, interaction: discord.Interaction) -> None:
        if isinstance(interaction.user, discord.Member) and has_foreign_diplomat_role(interaction.user):
            await interaction.response.send_message("🔐 Foreign Diplomats cannot use this command.", ephemeral=True)
            return
        embassies = await self.database.fetch_active_embassies()
        lines = [f"**{i}. {e['country_name']}**" for i, e in enumerate(embassies, start=1)]
        if not lines:
            lines = ["No active embassies are registered."]
        await interaction.response.send_message(
            embed=discord.Embed(title="🏛️ Embassy Directory", description="\n".join(lines[:50]), colour=discord.Colour.blurple()),
            ephemeral=True,
        )

    @app_commands.command(name="listdiplomats", description="List active diplomats by embassy")
    async def listdiplomats(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can use this command.", ephemeral=True)
            return
        embassies = await self.database.fetch_active_embassies()
        chunks: list[str] = []
        for embassy in embassies:
            members = await self.store.active_embassy_members(str(embassy["id"]))
            names = [m.get("discord_username") or str(m.get("discord_user_id")) for m in members]
            chunks.append(f"**{embassy['country_name']}** — {', '.join(names) if names else 'No active diplomats'}")
        await interaction.response.send_message(
            embed=discord.Embed(title="👥 Diplomats by Embassy", description="\n".join(chunks[:50]) or "No embassies.", colour=discord.Colour.blurple()),
            ephemeral=True,
        )

    @app_commands.command(name="diplomatprofile", description="Show a diplomat's verified profile and embassy assignments")
    async def diplomatprofile(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            allowed = await self.store.active_assignments_for_user(interaction.user.id) if isinstance(interaction.user, discord.Member) else []
            if not any(a["user_discord_id"] == user.id for a in allowed):
                await interaction.response.send_message("🔐 You cannot inspect that diplomat's profile.", ephemeral=True)
                return
        assignments = await self.store.active_assignments_for_user(user.id)
        embed = discord.Embed(title="👤 Diplomatic Profile", colour=discord.Colour.blurple())
        embed.add_field(name="Discord", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Embassies", value="\n".join(a["country_name"] for a in assignments) or "None", inline=False)
        embed.add_field(name="Assignment Types", value="\n".join(a["assignment_type"] for a in assignments) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="assignambassador", description="Assign an Ambassador to one or more embassies")
    async def assignambassador(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can assign ambassadors.", ephemeral=True)
            return
        if not has_ambassador_role(user):
            await interaction.response.send_message("❌ The selected user does not have the Ambassador role.", ephemeral=True)
            return
        view = EmbassySelectView(self.database, member=user, action="assign")
        await view.populate()
        await interaction.response.send_message("🏛️ Select the embassies to assign:", view=view, ephemeral=True)

    @app_commands.command(name="dismissambassador", description="Revoke an Ambassador's access to one or more embassies")
    async def dismissambassador(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("🔐 Only Admin/EAM can dismiss ambassadors.", ephemeral=True)
            return
        view = EmbassySelectView(self.database, member=user, action="revoke")
        await view.populate()
        await interaction.response.send_message("🧹 Select the embassy access to revoke:", view=view, ephemeral=True)
