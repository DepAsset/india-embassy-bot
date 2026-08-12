from __future__ import annotations

import discord

from access.models import AccessSource
from app.cogs.embassy_flow import EmbassyFlow
from approval.workflow import Decision


_original_handle_own_country = EmbassyFlow._handle_own_country
_original_decide = EmbassyFlow.decide


async def _handle_own_country_guard(self, interaction: discord.Interaction, request: dict):
    """Keep the request open when the applicant already has that Embassy."""
    country_id = str(request.get("verified_country_id") or "").strip()
    country_name = str(request.get("verified_country_name") or "").strip()
    embassy = await self.registry.get_by_country(country_id) if country_id else None
    if embassy is None:
        embassy = await self.registry.get_by_country(country_name)

    if embassy and embassy.active and await self.access.has_access(interaction.user.id, embassy.embassy_id):
        await interaction.followup.send(
            f"🏛️ **You are already a diplomat in the {embassy.country_name} Embassy.**\n\n"
            "No changes have been made to this request. If you meant to apply for a different Embassy, use **Want to join another Embassy** instead.",
            ephemeral=True,
        )
        return

    return await _original_handle_own_country(self, interaction, request)


async def _decide_guard(self, interaction: discord.Interaction, request_id: str, decision: Decision, route):
    """Applicants can never approve or decline their own Embassy request."""
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if request and int(request.get("discord_user_id", 0)) == int(interaction.user.id):
        action = "approve" if decision is Decision.APPROVED else "decline"
        await interaction.response.send_message(
            f"🔒 **You cannot {action} your own Embassy access request.**\n\n"
            "Another authorized diplomat or government reviewer must make the decision.",
            ephemeral=True,
        )
        return
    return await _original_decide(self, interaction, request_id, decision, route)


EmbassyFlow._handle_own_country = _handle_own_country_guard
EmbassyFlow.decide = _decide_guard
