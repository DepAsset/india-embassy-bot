from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import discord

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.verification import WarEraVerificationService
from rajdoot.warera import WarEraClient


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    status: str
    message: str
    profile: dict[str, Any] | None = None


class EmbassyRequestService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.verification = WarEraVerificationService(database, WarEraClient(settings))

    async def create_request(self, *, applicant_discord_id: int, embassy_id: str,
                             warera_user_id: str | None = None, profile_url: str | None = None) -> dict[str, Any]:
        return await self.database.create_embassy_request(
            applicant_discord_id=applicant_discord_id,
            embassy_id=embassy_id,
            warera_user_id=warera_user_id,
            profile_url=profile_url,
        )

    async def verify_warera_identity(self, *, request_id: str, warera_user_id: str) -> VerificationResult:
        result = await self.verification.verify(request_id, warera_user_id)
        return VerificationResult(result.verified, result.status, result.message, result.profile)

    async def record_event(self, *, request_id: str, event_type: str,
                           actor_discord_id: int | None = None, embassy_id: str | None = None,
                           details: dict[str, Any] | None = None) -> None:
        await self.database.add_request_event(
            request_id=request_id, event_type=event_type,
            actor_discord_id=actor_discord_id, embassy_id=embassy_id, details=details or {},
        )


class EmbassyRequestModal(discord.ui.Modal, title="Embassy Access Request"):
    warera_user_id = discord.ui.TextInput(
        label="WarEra User ID", placeholder="Enter your WarEra user ID", required=True, max_length=64,
    )
    profile_url = discord.ui.TextInput(
        label="WarEra Profile URL", placeholder="https://...", required=False, max_length=300,
    )

    def __init__(self, database: Database, embassy_id: str) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.embassy_id = embassy_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This request can only be created inside the embassy server.", ephemeral=True)
            return

        service = EmbassyRequestService(self.database)
        warera_id = str(self.warera_user_id.value).strip()
        try:
            request = await service.create_request(
                applicant_discord_id=interaction.user.id,
                embassy_id=self.embassy_id,
                warera_user_id=warera_id,
                profile_url=str(self.profile_url.value).strip() or None,
            )
            request_id = str(request["id"])
            await service.record_event(
                request_id=request_id, event_type="REQUEST_CREATED",
                actor_discord_id=interaction.user.id, embassy_id=self.embassy_id,
            )
            verification = await service.verify_warera_identity(request_id=request_id, warera_user_id=warera_id)
        except Exception as exc:
            if "uq_open_request_per_applicant_embassy" in str(exc):
                await interaction.response.send_message("You already have an active request for this embassy.", ephemeral=True)
                return
            raise

        if verification.ok:
            message = "✅ Request created and WarEra identity verified. Your request is now waiting for embassy approval."
        elif verification.status == "failed":
            message = "⚠️ Request created, but WarEra verification failed. Check your WarEra ID and try again later."
        else:
            message = "⏳ Request created. WarEra verification is still pending."
        await interaction.response.send_message(message, ephemeral=True)


class EmbassyRequestView(discord.ui.View):
    def __init__(self, database: Database, embassy_id: str) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.embassy_id = embassy_id

    @discord.ui.button(label="Request Embassy Access", emoji="🏛️", style=discord.ButtonStyle.primary)
    async def request_access(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EmbassyRequestModal(self.database, self.embassy_id))


def request_status_embed(request: dict[str, Any]) -> discord.Embed:
    status = str(request.get("request_status", "created")).replace("_", " ").title()
    verification = str(request.get("verification_status", "pending")).replace("_", " ").title()
    embed = discord.Embed(title="📨 Embassy Access Request", colour=discord.Colour.blurple())
    embed.add_field(name="Request", value=f"`{request['id']}`", inline=False)
    embed.add_field(name="Request Status", value=status, inline=True)
    embed.add_field(name="Verification", value=verification, inline=True)
    created = request.get("created_at")
    if isinstance(created, datetime):
        created = created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if created:
        embed.set_footer(text=f"Created {created}")
    return embed
