from __future__ import annotations

"""Final wiring for the Embassy request state machine."""

import discord

from access.models import AccessSource
from app.cogs.embassy_flow import EmbassyFlow, OtherEmbassySelectView
from core.state import RequestState


_ORIGINAL_PROCESS_CHOICE = EmbassyFlow.process_choice
_ORIGINAL_PROCESS_OTHER = EmbassyFlow.process_other_embassy


async def _process_choice(self: EmbassyFlow, interaction: discord.Interaction, request_id: str, choice: str) -> None:
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if not request:
        await interaction.response.send_message("This Embassy request is no longer active.", ephemeral=True)
        return
    if request.get("discord_user_id") != interaction.user.id:
        await interaction.response.send_message("Only the applicant can choose the Embassy for this request.", ephemeral=True)
        return
    if request.get("state") != RequestState.VERIFIED.value:
        await interaction.response.send_message("This request is not ready for Embassy selection.", ephemeral=True)
        return

    flags = request.get("official_flags") or {}
    is_special_official = bool(flags.get("president") or flags.get("vice_president") or flags.get("eam_or_mofa"))

    if choice == "own" and is_special_official:
        await interaction.response.defer()
        country_id = str(request.get("verified_country_id") or "").strip()
        country_name = str(request.get("verified_country_name") or "").strip()
        embassy = await self.registry.get_by_country(country_id) if country_id else None
        if embassy is None:
            embassy = await self.registry.get_by_country(country_name)
        if embassy is None or not embassy.active:
            embassy = await self._create_embassy(interaction.guild, country_id or country_name, country_name, interaction.user.id)
        await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.SPECIAL_OFFICIAL)
        await self._finalize_direct(interaction, request, embassy, "Special official status grants automatic Embassy access.")
        return

    if choice == "other" and is_special_official:
        await interaction.response.defer(ephemeral=True)
        embassies = await self.registry.get_active()
        embassies = [
            e for e in embassies
            if e.country_key.lower() != str(request.get("verified_country_id") or "").lower()
            and e.country_name.lower() != str(request.get("verified_country_name") or "").lower()
        ]
        if not embassies:
            await interaction.followup.send("There are currently no other active Embassies to request. Please contact EAM/Admin.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=e.country_name[:100], value=e.embassy_id, description=f"Request access to the {e.country_name} Embassy")
            for e in embassies[:25]
        ]
        await interaction.followup.send(
            "Select the Embassy you want to join. Your official status qualifies you for automatic access.",
            ephemeral=True,
            view=OtherEmbassySelectView(self.bot, request_id, options),
        )
        return

    await _ORIGINAL_PROCESS_CHOICE(self, interaction, request_id, choice)


async def _process_other_embassy(self: EmbassyFlow, interaction: discord.Interaction, request_id: str, embassy_id: str) -> None:
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if not request or request.get("discord_user_id") != interaction.user.id:
        await interaction.response.send_message("This request is no longer available.", ephemeral=True)
        return

    embassy = await self.registry.get_by_id(embassy_id)
    if not embassy or not embassy.active:
        await interaction.response.send_message("That Embassy is no longer active. Please restart the Embassy selection.", ephemeral=True)
        return

    flags = request.get("official_flags") or {}
    is_special_official = bool(flags.get("president") or flags.get("vice_president") or flags.get("eam_or_mofa"))
    if is_special_official:
        await interaction.response.defer()
        await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.SPECIAL_OFFICIAL)
        await self._finalize_direct(interaction, request, embassy, "Special official status grants automatic Embassy access.")
        return

    await _ORIGINAL_PROCESS_OTHER(self, interaction, request_id, embassy_id)


EmbassyFlow.process_choice = _process_choice
EmbassyFlow.process_other_embassy = _process_other_embassy
