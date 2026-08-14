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
    special = bool(flags.get("president") or flags.get("vice_president") or flags.get("eam_or_mofa"))
    country_id = str(request.get("verified_country_id") or "").strip()
    country_name = str(request.get("verified_country_name") or "").strip()

    if choice == "own":
        embassy = await self.registry.get_by_country(country_id) if country_id else None
        if embassy is None:
            embassy = await self.registry.get_by_country(country_name)

        if embassy and embassy.active and await self.access.has_access(interaction.user.id, embassy.embassy_id):
            await interaction.response.send_message(
                f"You are already a diplomat in the **{embassy.country_name} Embassy**.\n\n"
                "Nothing has been changed. If you meant to apply for a different Embassy, use **Want to join another Embassy**.",
                ephemeral=True,
            )
            return

        if special:
            await interaction.response.defer()
            if embassy is None:
                embassy = await self._create_embassy(interaction.guild, country_id or country_name, country_name, interaction.user.id)
            elif not embassy.active:
                await self.registry.restore(embassy.embassy_id)
                embassy = await self.registry.get_by_id(embassy.embassy_id)
            if embassy is None:
                await interaction.followup.send("I could not prepare your Embassy record. Please contact EAM/Admin.", ephemeral=True)
                return
            await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.SPECIAL_OFFICIAL)
            await self._finalize_direct(interaction, request, embassy, "President / Vice President / EAM status grants automatic access.")
            return

        await interaction.response.defer()
        if embassy is None:
            embassy = await self._create_embassy(interaction.guild, country_id or country_name, country_name, interaction.user.id)
            await self._set_review(request, embassy, __import__("approval.workflow", fromlist=["Route"]).Route.GOVERNMENT_REVIEW, reason="Embassy was created for the first applicant and requires Government activation.")
            await self._notify_government(interaction.guild, request, embassy, revival=False)
            await interaction.followup.send(
                f"The **{country_name} Embassy** has been created. EAM/Admin has been notified to activate and approve the first diplomatic access.",
                ephemeral=True,
            )
            return

        if not embassy.active:
            await self.registry.restore(embassy.embassy_id)
            embassy = await self.registry.get_by_id(embassy.embassy_id)
            if embassy is None:
                await interaction.followup.send("The Embassy could not be restored. Please contact EAM/Admin.", ephemeral=True)
                return

        active = await self.access.active_for_embassy(embassy.embassy_id)
        if not active:
            await self._set_review(request, embassy, __import__("approval.workflow", fromlist=["Route"]).Route.GOVERNMENT_REVIEW, reason="Embassy exists but has no active diplomats.")
            await self._notify_government(interaction.guild, request, embassy, revival=True)
            await interaction.followup.send(
                f"The **{embassy.country_name} Embassy** exists but currently has no active diplomats. EAM/Admin has been notified to review the Embassy revival.",
                ephemeral=True,
            )
            return

        preapproval = await self.approvals.find_preapproval(embassy.embassy_id, str(request.get("warera_user_id") or ""))
        if preapproval:
            await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.PRE_APPROVAL)
            await self._finalize_direct(interaction, request, embassy, "Valid Embassy pre-approval was found.", action="REQUEST_AUTO_APPROVED")
            await self.approvals.consume_preapproval(str(preapproval["preapproval_id"]))
            return

        from approval.workflow import Route
        await self._set_review(request, embassy, Route.FOREIGN_DIPLOMAT, reason="Awaiting approval from an active diplomat.")
        await self._notify_diplomats(interaction.guild, request, embassy)
        await interaction.followup.send(
            f"Your request has been sent to the active diplomats of the **{embassy.country_name} Embassy**. You will be notified once a decision is made.",
            ephemeral=True,
        )
        return

    if choice == "other":
        await interaction.response.defer(ephemeral=True)
        embassies = await self.registry.get_active()
        embassies = [
            e for e in embassies
            if e.country_key.lower() != country_id.lower()
            and e.country_name.lower() != country_name.lower()
        ]
        if not embassies:
            await interaction.followup.send("There are currently no other active Embassies to request.", ephemeral=True)
            return
        options = [
            discord.SelectOption(
                label=e.country_name[:100],
                value=e.embassy_id,
                description=f"Request access to the {e.country_name} Embassy",
            )
            for e in embassies[:25]
        ]
        await interaction.followup.send(
            "Select the Embassy you want to join. Requests outside your WarEra country go to EAM/Admin for approval.",
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
        await interaction.response.send_message("That Embassy is no longer active.", ephemeral=True)
        return
    if await self.access.has_access(interaction.user.id, embassy_id):
        await interaction.response.send_message(
            f"You already have active access to the **{embassy.country_name} Embassy**.",
            ephemeral=True,
        )
        return

    from approval.workflow import Route
    await interaction.response.defer()
    await self._set_review(request, embassy, Route.GOVERNMENT_REVIEW, reason="Applicant requested an Embassy outside their WarEra country.")
    await self._notify_government(interaction.guild, request, embassy, revival=False)
    await interaction.followup.send(
        f"Your request for the **{embassy.country_name} Embassy** has been sent to EAM/Admin for approval.",
        ephemeral=True,
    )


EmbassyFlow.process_choice = _process_choice
EmbassyFlow.process_other_embassy = _process_other_embassy
