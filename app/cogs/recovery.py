from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from core.audit import AuditLogger
from core.state import RequestState


GOVERNMENT_ROLE_IDS = {settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id}


def authorized(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(role.id in GOVERNMENT_ROLE_IDS for role in member.roles)


class RecoveryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.database
        self.audit = AuditLogger(bot.database)

    @app_commands.command(name="embassy-recovery", description="Review Embassy requests requiring manual recovery after repeated OTP lockouts.")
    async def recovery(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not authorized(interaction.user):
            await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
            return
        docs = await self.db.collection("requests").find({"state": RequestState.RECOVERY_PENDING.value}).sort("updated_at", -1).limit(20).to_list(length=20)
        if not docs:
            await interaction.response.send_message("No requests are awaiting manual recovery.", ephemeral=True)
            return
        text = "\n".join(f"`{d['request_id']}` • Discord <@{d['discord_user_id']}> • WarEra `{d.get('warera_user_id','?')}` • {d.get('verified_country_name','?')}" for d in docs)
        await interaction.response.send_message(text[:4000], ephemeral=True)

    @app_commands.command(name="embassy-recover", description="Move a repeated OTP-lockout request into government review.")
    @app_commands.describe(request_id="Embassy request ID", approve="Approve the manual recovery")
    async def recover(self, interaction: discord.Interaction, request_id: str, approve: bool) -> None:
        if not isinstance(interaction.user, discord.Member) or not authorized(interaction.user):
            await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
            return
        requests = self.db.collection("requests")
        request = await requests.find_one({"request_id": request_id, "state": RequestState.RECOVERY_PENDING.value})
        if not request:
            await interaction.response.send_message("That request is not awaiting manual recovery.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        if approve:
            await requests.update_one({"request_id": request_id, "state": RequestState.RECOVERY_PENDING.value}, {"$set": {"state": RequestState.GOVERNMENT_REVIEW.value, "recovery_approved_by": interaction.user.id, "recovery_approved_at": now, "updated_at": now}})
            action = "RECOVERY_MOVED_TO_GOVERNMENT_REVIEW"
            message = "Recovery approved. The request is now in Government Review."
        else:
            await requests.update_one({"request_id": request_id, "state": RequestState.RECOVERY_PENDING.value}, {"$set": {"state": RequestState.DECLINED.value, "active": False, "recovery_declined_by": interaction.user.id, "recovery_declined_at": now, "updated_at": now}})
            action = "RECOVERY_DECLINED"
            message = "Recovery declined and the request has been closed."
        await self.audit.log(action=action, actor_id=interaction.user.id, request_id=request_id, target_id=str(request.get("discord_user_id")), warera_id=str(request.get("warera_user_id") or ""), new_state=(RequestState.GOVERNMENT_REVIEW.value if approve else RequestState.DECLINED.value))
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecoveryCog(bot))
