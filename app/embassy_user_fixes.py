from __future__ import annotations

import discord

from app.cogs.embassy_flow import EmbassyFlow, EmbassyApprovalView
from app.cogs.embassy_requests import CompanyVerificationView
from verification.flow import VerificationFlow


# Keep the OTP available only while verification is pending. The Copy OTP
# button reveals it ephemerally in a Discord code block; Discord bots cannot
# directly write to a user's device clipboard.
_original_issue_otp = VerificationFlow.issue_company_otp
_original_verify_ownership = VerificationFlow.verify_company_ownership
_original_verify_otp = VerificationFlow.verify_company_otp


async def _issue_otp_with_copy_value(self, request_id: str, actor_id: int) -> str:
    otp = await _original_issue_otp(self, request_id, actor_id)
    await self.otp.update_one(
        {"request_id": request_id},
        {"$set": {"otp_plaintext": otp}},
    )
    return otp


async def _verify_ownership_and_clear(self, request_id: str, actor_id: int):
    result = await _original_verify_ownership(self, request_id, actor_id)
    if result[0]:
        await self.otp.update_one({"request_id": request_id}, {"$unset": {"otp_plaintext": ""}})
    return result


async def _verify_otp_and_clear(self, request_id: str, candidate: str, actor_id: int):
    result = await _original_verify_otp(self, request_id, candidate, actor_id)
    if result[0]:
        await self.otp.update_one({"request_id": request_id}, {"$unset": {"otp_plaintext": ""}})
    return result


VerificationFlow.issue_company_otp = _issue_otp_with_copy_value
VerificationFlow.verify_company_ownership = _verify_ownership_and_clear
VerificationFlow.verify_company_otp = _verify_otp_and_clear


_original_company_view_init = CompanyVerificationView.__init__


def _company_view_init(self, service):
    _original_company_view_init(self, service)
    copy_button = discord.ui.Button(
        label="Copy OTP",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="embassy:copy-otp",
    )
    copy_button.callback = self._copy_otp
    self.add_item(copy_button)


async def _copy_otp(self, interaction: discord.Interaction) -> None:
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("This button can only be used inside your Embassy request thread.", ephemeral=True)
        return
    request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
    if not request or request.get("discord_user_id") != interaction.user.id:
        await interaction.response.send_message("Only the applicant can copy this OTP.", ephemeral=True)
        return
    record = await self.service.database.collection("verification_attempts").find_one({"request_id": request["request_id"]})
    otp = str((record or {}).get("otp_plaintext") or "").strip()
    if not otp:
        await interaction.response.send_message("The OTP is no longer available. Please restart verification if you need a new one.", ephemeral=True)
        return
    await interaction.response.send_message(f"📋 **Your OTP**\n```{otp}```\nTap and hold the code on mobile to copy it.", ephemeral=True)


CompanyVerificationView.__init__ = _company_view_init
CompanyVerificationView._copy_otp = _copy_otp


# A user must never be able to approve or decline their own request, even if
# they are already an active diplomat of the requested Embassy.
_original_decide = EmbassyFlow.decide


async def _guarded_decide(self, interaction, request_id, decision, route):
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if request and int(request.get("discord_user_id", 0)) == interaction.user.id:
        await interaction.response.send_message(
            "🔒 You cannot approve or decline your own Embassy access request.",
            ephemeral=True,
        )
        return
    return await _original_decide(self, interaction, request_id, decision, route)


EmbassyFlow.decide = _guarded_decide


# Do not send an Embassy approval request to the applicant themselves when
# they already happen to be an active diplomat of that Embassy.
async def _notify_diplomats_without_applicant(self, guild, request, embassy):
    channel = guild.get_channel(embassy.channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Embassy channel is missing")
    assignments = await self.access.active_for_embassy(embassy.embassy_id)
    mentions = []
    applicant_id = int(request.get("discord_user_id", 0))
    for assignment in assignments:
        diplomat_id = int(assignment["discord_user_id"])
        if diplomat_id == applicant_id:
            continue
        member = guild.get_member(diplomat_id)
        if member:
            mentions.append(member.mention)
    content = " ".join(mentions) if mentions else "📨 Embassy access request"
    embed = self._approval_embed(request, embassy, "Active Embassy diplomats must review this request.")
    message = await channel.send(
        content=content,
        embed=embed,
        view=EmbassyApprovalView(self.bot, request["request_id"], "FOREIGN_DIPLOMAT"),
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await self.db.collection("requests").update_one(
        {"request_id": request["request_id"]},
        {"$set": {"approval_message_id": message.id}},
    )


EmbassyFlow._notify_diplomats = _notify_diplomats_without_applicant


# Selecting the applicant's own Embassy should never automatically close the
# request when they already have active access there. The thread remains open
# so they can choose another Embassy instead.
_original_handle_own_country = EmbassyFlow._handle_own_country


async def _guarded_own_country(self, interaction, request):
    country_id = str(request.get("verified_country_id") or "").strip()
    country_name = str(request.get("verified_country_name") or "").strip()
    embassy = await self.registry.get_by_country(country_id) if country_id else None
    if embassy is None and country_name:
        embassy = await self.registry.get_by_country(country_name)
    if embassy and embassy.active and await self.access.has_access(interaction.user.id, embassy.embassy_id):
        await interaction.followup.send(
            f"🏛️ **You are already a diplomat in the {country_name} Embassy.**\n\n"
            "No changes were made to this request. If you meant to apply for a different Embassy, use **another Embassy** below.",
            ephemeral=True,
        )
        return
    return await _original_handle_own_country(self, interaction, request)


EmbassyFlow._handle_own_country = _guarded_own_country
