from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from approval.workflow import ApprovalWorkflow, Decision, Route
from app.cogs.complete import CompleteEmbassyCog
from app.cogs.embassy_flow import EmbassyFlow, EmbassyApprovalView
from app.cogs.embassy_requests import CompanyVerificationView
from app.cogs.recovery import RecoveryCog
from app.config import settings
from app.embassy_patches import CuratedSurpriseView, _DisabledSurpriseView
from core.state import RequestState
from embassy.registry import EmbassyRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company verification UI cleanup
# ---------------------------------------------------------------------------
_original_company_init = CompanyVerificationView.__init__


def _extract_otp(message: discord.Message) -> str | None:
    for embed in message.embeds:
        description = embed.description or ""
        match = re.search(r"```(?:[A-Za-z0-9_-]+)?\s*([A-Z0-9]{4,32})\s*```", description)
        if match:
            return match.group(1).strip()
    return None


def _company_init(self: CompanyVerificationView, service):
    _original_company_init(self, service)

    # The older user-fixes compatibility layer added a second Copy OTP button.
    # Keep exactly one and enforce the requested two-row layout.
    seen_copy = False
    for item in list(self.children):
        if not isinstance(item, discord.ui.Button):
            continue
        if item.custom_id == "embassy:copy-otp":
            if seen_copy:
                self.remove_item(item)
                continue
            seen_copy = True
        if item.custom_id == "embassy:open-companies":
            item.row = 0
        elif item.custom_id == "embassy:copy-otp":
            item.row = 0
        elif item.custom_id == "embassy:verify-company":
            item.row = 1

    # Make the built-in fallback parser correct as well. The persisted
    # plaintext OTP used by the compatibility patch remains the preferred
    # source when available.
    self._otp_from_message = staticmethod(_extract_otp)


CompanyVerificationView.__init__ = _company_init


# ---------------------------------------------------------------------------
# Approval correctness and race protection
# ---------------------------------------------------------------------------
_original_decide = EmbassyFlow.decide


async def _decide_guarded(self: EmbassyFlow, interaction, request_id, decision, route):
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if request and int(request.get("discord_user_id", 0)) == interaction.user.id:
        await interaction.response.send_message(
            "🔒 You cannot approve or decline your own Embassy access request.",
            ephemeral=True,
        )
        return
    return await _original_decide(self, interaction, request_id, decision, route)


EmbassyFlow.decide = _decide_guarded


async def _workflow_decide_safe(self: ApprovalWorkflow, request_id, actor_id, decision, route, reason=None):
    # Check the state before writing the unique decision document. This closes
    # the stale-button race where an old button could create a decision record
    # after another reviewer had already completed the request.
    current = await self.requests.find_one({
        "request_id": request_id,
        "active": True,
        "state": {
            "$in": [
                RequestState.DIPLOMAT_REVIEW.value,
                RequestState.GOVERNMENT_REVIEW.value,
                RequestState.PREAPPROVED.value,
                RequestState.AUTO_APPROVED.value,
            ]
        },
    })
    if not current:
        return False

    now = datetime.now(timezone.utc)
    result = await self.requests.update_one(
        {"request_id": request_id, "state": current["state"], "active": True},
        {"$set": {
            "state": RequestState.APPROVED.value if decision is Decision.APPROVED else RequestState.DECLINED.value,
            "decision": decision.value,
            "decision_actor_id": actor_id,
            "decision_reason": reason,
            "updated_at": now,
            "active": False,
        }},
    )
    if result.modified_count != 1:
        return False

    try:
        await self.decisions.insert_one({
            "request_id": request_id,
            "actor_id": actor_id,
            "decision": decision.value,
            "route": route.value,
            "reason": reason,
            "decided_at": now,
        })
    except Exception as exc:
        if exc.__class__.__name__ == "DuplicateKeyError":
            await self.requests.update_one(
                {
                    "request_id": request_id,
                    "decision_actor_id": actor_id,
                    "decision": decision.value,
                    "active": False,
                },
                {"$set": {
                    "state": current["state"],
                    "active": True,
                    "decision": None,
                    "decision_actor_id": None,
                    "decision_reason": None,
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
            return False
        raise

    await self.audit.log(
        action=f"REQUEST_{decision.value}",
        actor_id=actor_id,
        request_id=request_id,
        embassy_id=str(current.get("requested_embassy_id") or ""),
        warera_id=str(current.get("warera_user_id") or ""),
        old_state=current.get("state"),
        new_state=RequestState.APPROVED.value if decision is Decision.APPROVED else RequestState.DECLINED.value,
        reason=reason,
        metadata={"route": route.value},
    )
    return True


ApprovalWorkflow.decide = _workflow_decide_safe


# ---------------------------------------------------------------------------
# Recovery is connected back into the same Government Review workflow.
# ---------------------------------------------------------------------------
async def _notify_recovery_government(bot: commands.Bot, request: dict) -> None:
    embassy = await EmbassyRegistry(bot.database).get_by_id(str(request.get("requested_embassy_id") or ""))
    channel = bot.get_channel(settings.channel_embassy_management_id)
    if not embassy or not isinstance(channel, discord.TextChannel):
        return

    role = channel.guild.get_role(settings.role_eam_id)
    content = role.mention if role else "🏛️ Embassy Management"
    embed = discord.Embed(title="🔐 Embassy Recovery Review", color=discord.Color.orange())
    embed.add_field(name="Applicant", value=f"<@{request['discord_user_id']}>", inline=True)
    embed.add_field(name="WarEra", value=str(request.get("warera_user_id") or "Unknown"), inline=True)
    embed.add_field(name="Embassy", value=embassy.country_name, inline=True)
    embed.add_field(name="Reason", value="Repeated OTP lockouts require manual Government Review.", inline=False)

    message = await channel.send(
        content=content,
        embed=embed,
        view=EmbassyApprovalView(bot, str(request["request_id"]), Route.GOVERNMENT_REVIEW.value),
        allowed_mentions=discord.AllowedMentions(roles=True),
    )
    await bot.database.collection("requests").update_one(
        {"request_id": request["request_id"], "state": RequestState.GOVERNMENT_REVIEW.value},
        {"$set": {"approval_message_id": message.id, "approval_route": Route.GOVERNMENT_REVIEW.value}},
    )


async def _recover_wired(self: RecoveryCog, interaction, request_id: str, approve: bool):
    if not isinstance(interaction.user, discord.Member) or not (
        interaction.user.guild_permissions.administrator
        or any(r.id in {
            settings.role_president_id,
            settings.role_vice_president_id,
            settings.role_nsa_id,
            settings.role_minister_id,
        } for r in interaction.user.roles)
    ):
        await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
        return

    requests = self.db.collection("requests")
    request = await requests.find_one({
        "request_id": request_id,
        "state": RequestState.RECOVERY_PENDING.value,
        "active": True,
    })
    if not request:
        await interaction.response.send_message("That request is not awaiting manual recovery.", ephemeral=True)
        return

    now = datetime.now(timezone.utc)
    if not approve:
        result = await requests.update_one(
            {"request_id": request_id, "state": RequestState.RECOVERY_PENDING.value, "active": True},
            {"$set": {
                "state": RequestState.DECLINED.value,
                "active": False,
                "recovery_declined_by": interaction.user.id,
                "recovery_declined_at": now,
                "updated_at": now,
            }},
        )
        if result.modified_count:
            await self.audit.log(
                action="RECOVERY_DECLINED",
                actor_id=interaction.user.id,
                request_id=request_id,
                target_id=str(request.get("discord_user_id")),
                warera_id=str(request.get("warera_user_id") or ""),
                new_state=RequestState.DECLINED.value,
            )
        await interaction.response.send_message("Recovery declined and the request has been closed.", ephemeral=True)
        return

    result = await requests.update_one(
        {"request_id": request_id, "state": RequestState.RECOVERY_PENDING.value, "active": True},
        {"$set": {
            "state": RequestState.GOVERNMENT_REVIEW.value,
            "status": "PENDING_APPROVAL",
            "approval_route": Route.GOVERNMENT_REVIEW.value,
            "recovery_approved_by": interaction.user.id,
            "recovery_approved_at": now,
            "updated_at": now,
        }},
    )
    if result.modified_count != 1:
        await interaction.response.send_message("That recovery request was already handled.", ephemeral=True)
        return

    await self.audit.log(
        action="RECOVERY_MOVED_TO_GOVERNMENT_REVIEW",
        actor_id=interaction.user.id,
        request_id=request_id,
        target_id=str(request.get("discord_user_id")),
        warera_id=str(request.get("warera_user_id") or ""),
        new_state=RequestState.GOVERNMENT_REVIEW.value,
    )
    await _notify_recovery_government(self.bot, request)
    await interaction.response.send_message(
        "Recovery approved. The request is now in Government Review and EAM/Admin has been notified.",
        ephemeral=True,
    )


RecoveryCog.recover = _recover_wired


# ---------------------------------------------------------------------------
# Durable access reconciliation
# ---------------------------------------------------------------------------
async def _reconcile_all(self: CompleteEmbassyCog):
    guild = self.bot.get_guild(settings.discord_guild_id)
    if guild is None:
        return

    cursor = self.bot.database.collection("embassy_assignments").find(
        {"active": True}, {"discord_user_id": 1}
    ).limit(500)
    user_ids = {
        int(doc["discord_user_id"])
        async for doc in cursor
        if doc.get("discord_user_id") is not None
    }
    for user_id in user_ids:
        try:
            await self.projector.reconcile_member(guild, user_id)
        except (discord.HTTPException, discord.NotFound):
            logger.warning("Could not reconcile Embassy access for Discord user %s", user_id)
        except Exception:
            logger.exception("Unexpected access reconciliation failure for Discord user %s", user_id)


@tasks.loop(minutes=15)
async def _real_reconcile(self: CompleteEmbassyCog):
    await _reconcile_all(self)


@_real_reconcile.before_loop
async def _before_reconcile(self: CompleteEmbassyCog):
    await self.bot.wait_until_ready()


# CompleteEmbassyCog.__init__ already calls self.reconcile.start(), so replacing
# the Loop before the cog is instantiated turns the placeholder into the real
# reconciliation task without adding a second scheduler.
CompleteEmbassyCog.reconcile = _real_reconcile


# ---------------------------------------------------------------------------
# Persistent welcome-message surprise restoration
# ---------------------------------------------------------------------------
async def restore_surprise_views(bot: commands.Bot) -> None:
    bot.add_view(_DisabledSurpriseView())
    docs = bot.database.collection("embassy_surprises").find({"used": False}).limit(500)
    async for doc in docs:
        token = str(doc.get("token") or "")
        recipient_id = doc.get("recipient_id")
        if not token or recipient_id is None:
            continue
        bot.add_view(CuratedSurpriseView(bot, token, int(recipient_id)))
