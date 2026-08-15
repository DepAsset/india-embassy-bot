from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.embassy_members import EmbassyMemberImporter


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    ok: bool
    status: str
    message: str
    request: dict[str, Any] | None = None


class EmbassyApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def assignment_type(member: discord.Member) -> str:
        citizen_role_id = getattr(settings, "indian_citizen_role_id", None)
        if citizen_role_id is not None and any(role.id == citizen_role_id for role in member.roles):
            return "indian_ambassador"
        if any(role.name.casefold().strip() == "indian citizen" for role in member.roles):
            return "indian_ambassador"
        return "foreign_diplomat"

    async def pending_for(self, member: discord.Member) -> list[dict[str, Any]]:
        return await self.database.fetch_pending_requests_for_member(member.id)

    async def approve(
        self,
        *,
        guild: discord.Guild,
        request_id: str,
        actor: discord.Member,
    ) -> ApprovalResult:
        request = await self.database.fetch_embassy_request(request_id)
        if request is None:
            return ApprovalResult(False, "not_found", "That embassy request no longer exists.")
        if request.get("verification_status") != "verified":
            return ApprovalResult(False, "not_verified", "This request cannot be approved until WarEra verification has passed.", request)

        assignment_type = self.assignment_type(await guild.fetch_member(int(request["applicant_discord_id"])))
        try:
            updated = await self.database.decide_embassy_request(
                request_id=request_id,
                actor_discord_id=actor.id,
                decision="approved",
                assignment_type=assignment_type,
            )
        except PermissionError:
            return ApprovalResult(False, "forbidden", "You are not an active member of this embassy.", request)
        except ValueError as exc:
            return ApprovalResult(False, "invalid", str(exc), request)
        except LookupError:
            return ApprovalResult(False, "not_found", "That embassy request no longer exists.")

        applicant = guild.get_member(int(updated["applicant_discord_id"]))
        if applicant is None:
            try:
                applicant = await guild.fetch_member(int(updated["applicant_discord_id"]))
            except (discord.NotFound, discord.HTTPException):
                return ApprovalResult(False, "approved_member_missing", "The request was approved, but the applicant is no longer in the server.", updated)

        embassy = await self.database.fetch_embassy(str(updated["embassy_id"]))
        if embassy is None or not embassy.get("channel_id"):
            return ApprovalResult(False, "approved_channel_missing", "The request was approved, but the embassy channel could not be found.", updated)

        channel = guild.get_channel(int(embassy["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return ApprovalResult(False, "approved_channel_missing", "The request was approved, but the embassy channel is unavailable.", updated)

        overwrite = channel.overwrites_for(applicant)
        for permission_name in EmbassyMemberImporter.HARD_CODED_PERMISSIONS:
            setattr(overwrite, permission_name, True)
        try:
            await channel.set_permissions(
                applicant,
                overwrite=overwrite,
                reason="RAJDOOT approved embassy access request",
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return ApprovalResult(False, "approved_access_failed", "The request was approved, but Discord access could not be applied. An administrator should reconcile access.", updated)

        await self.database.add_request_event(
            request_id=request_id,
            event_type="REQUEST_APPROVED",
            actor_discord_id=actor.id,
            embassy_id=str(updated["embassy_id"]),
            details={"assignment_type": assignment_type},
        )
        return ApprovalResult(True, "approved", "Embassy access approved and Discord access granted.", updated)

    async def reject(
        self,
        *,
        request_id: str,
        actor: discord.Member,
        reason: str | None = None,
    ) -> ApprovalResult:
        try:
            updated = await self.database.decide_embassy_request(
                request_id=request_id,
                actor_discord_id=actor.id,
                decision="rejected",
                reason=reason,
            )
        except PermissionError:
            return ApprovalResult(False, "forbidden", "You are not an active member of this embassy.")
        except ValueError as exc:
            return ApprovalResult(False, "invalid", str(exc))
        except LookupError:
            return ApprovalResult(False, "not_found", "That embassy request no longer exists.")

        await self.database.add_request_event(
            request_id=request_id,
            event_type="REQUEST_REJECTED",
            actor_discord_id=actor.id,
            embassy_id=str(updated["embassy_id"]),
            details={"reason": reason} if reason else {},
        )
        return ApprovalResult(True, "rejected", "Embassy request rejected.", updated)


def approval_request_embed(request: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title="📨 Embassy Access Request", colour=discord.Colour.blurple())
    embed.add_field(name="Embassy", value=str(request.get("country_name", "Unknown")), inline=True)
    embed.add_field(name="WarEra User", value=f"`{request.get('warera_user_id') or 'unknown'}`", inline=True)
    embed.add_field(name="Verification", value="✅ Verified", inline=True)
    profile = request.get("warera_profile_snapshot") or {}
    if isinstance(profile, dict):
        name = profile.get("name") or profile.get("username") or profile.get("displayName")
        if name:
            embed.add_field(name="WarEra Profile", value=str(name)[:1024], inline=False)
    embed.set_footer(text=f"Request {request['id']}")
    return embed


class EmbassyApprovalView(discord.ui.View):
    def __init__(self, database: Database, request: dict[str, Any]) -> None:
        super().__init__(timeout=900)
        self.database = database
        self.request = request
        self.service = EmbassyApprovalService(database)

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("This action is only available to embassy members.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.service.approve(
            guild=interaction.guild,
            request_id=str(self.request["id"]),
            actor=interaction.user,
        )
        if result.ok:
            button.disabled = True
            self.reject.disabled = True
            await interaction.message.edit(view=self)
        await interaction.followup.send(result.message, ephemeral=True)

    @discord.ui.button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("This action is only available to embassy members.", ephemeral=True)
            return
        await interaction.response.send_modal(RejectRequestModal(self.database, str(self.request["id"]), interaction.user.id, self))


class RejectRequestModal(discord.ui.Modal, title="Reject Embassy Request"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Optional reason for rejection",
        required=False,
        max_length=500,
    )

    def __init__(self, database: Database, request_id: str, actor_id: int, parent_view: EmbassyApprovalView) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.request_id = request_id
        self.actor_id = actor_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available to embassy members.", ephemeral=True)
            return
        if interaction.user.id != self.actor_id:
            await interaction.response.send_message("This rejection belongs to another moderator action.", ephemeral=True)
            return
        result = await EmbassyApprovalService(self.database).reject(
            request_id=self.request_id,
            actor=interaction.user,
            reason=str(self.reason.value).strip() or None,
        )
        if result.ok:
            self.parent_view.approve.disabled = True
            self.parent_view.reject.disabled = True
            if interaction.message:
                await interaction.message.edit(view=self.parent_view)
        await interaction.response.send_message(result.message, ephemeral=True)
