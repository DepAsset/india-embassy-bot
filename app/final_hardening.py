from __future__ import annotations

"""Final production hardening layer.

This module is intentionally loaded last so approval/access invariants are the
same no matter which legacy compatibility layer was imported earlier.
"""

from datetime import datetime, timezone

import discord

from access.models import AccessSource
from approval.workflow import ApprovalWorkflow, Decision, Route
from app.cogs.embassy_flow import EmbassyFlow, EmbassyApprovalView
from app.config import settings
from core.state import RequestState


_REVIEW_STATES = {
    RequestState.DIPLOMAT_REVIEW.value,
    RequestState.GOVERNMENT_REVIEW.value,
    RequestState.PREAPPROVED.value,
    RequestState.AUTO_APPROVED.value,
}


async def _safe_decide_workflow(self: ApprovalWorkflow, request_id: str, actor_id: int, decision: Decision, route: Route, reason: str | None = None) -> bool:
    current = await self.requests.find_one({
        "request_id": request_id,
        "active": True,
        "state": {"$in": list(_REVIEW_STATES)},
    })
    if not current:
        return False

    now = datetime.now(timezone.utc)
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
            return False
        raise

    new_state = RequestState.APPROVED.value if decision is Decision.APPROVED else RequestState.DECLINED.value
    result = await self.requests.update_one(
        {"request_id": request_id, "state": current["state"], "active": True},
        {"$set": {
            "state": new_state,
            "decision": decision.value,
            "decision_actor_id": actor_id,
            "decision_reason": reason,
            "updated_at": now,
            "active": False,
        }},
    )
    if result.modified_count != 1:
        await self.decisions.delete_one({"request_id": request_id, "actor_id": actor_id, "decided_at": now})
        return False

    await self.audit.log(
        action=f"REQUEST_{decision.value}",
        actor_id=actor_id,
        request_id=request_id,
        embassy_id=str(current.get("requested_embassy_id") or ""),
        warera_id=str(current.get("warera_user_id") or ""),
        old_state=current.get("state"),
        new_state=new_state,
        reason=reason,
        metadata={"route": route.value},
    )
    return True


async def _rollback_decision(self: ApprovalWorkflow, request_id: str, actor_id: int) -> None:
    request = await self.requests.find_one({"request_id": request_id, "decision_actor_id": actor_id, "active": False})
    if not request:
        return
    previous_state = RequestState.GOVERNMENT_REVIEW.value if request.get("approval_route") == Route.GOVERNMENT_REVIEW.value else RequestState.DIPLOMAT_REVIEW.value
    await self.requests.update_one(
        {"request_id": request_id, "decision_actor_id": actor_id, "active": False},
        {"$set": {
            "state": previous_state,
            "active": True,
            "decision": None,
            "decision_actor_id": None,
            "decision_reason": None,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    await self.decisions.delete_one({"request_id": request_id, "actor_id": actor_id})


ApprovalWorkflow.decide = _safe_decide_workflow
ApprovalWorkflow.rollback_decision = _rollback_decision


async def _safe_embassy_decide(self: EmbassyFlow, interaction: discord.Interaction, request_id: str, decision: Decision, route: Route) -> None:
    request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
    if not request:
        await interaction.response.send_message("This request has already been decided or closed.", ephemeral=True)
        return

    applicant_id = int(request.get("discord_user_id") or 0)
    if applicant_id == interaction.user.id:
        await interaction.response.send_message("🔒 You cannot approve or decline your own Embassy access request.", ephemeral=True)
        return

    if route is Route.FOREIGN_DIPLOMAT:
        if not await self.access.has_access(interaction.user.id, str(request.get("requested_embassy_id") or "")):
            await interaction.response.send_message("Only an active diplomat of this Embassy can decide this request.", ephemeral=True)
            return
    elif route is Route.GOVERNMENT_REVIEW:
        if not isinstance(interaction.user, discord.Member) or not (
            interaction.user.guild_permissions.administrator
            or any(role.id == settings.role_eam_id for role in interaction.user.roles)
        ):
            await interaction.response.send_message("Only EAM or an Administrator can decide this request.", ephemeral=True)
            return

    embassy = await self.registry.get_by_id(str(request.get("requested_embassy_id") or ""))
    if embassy is None:
        await interaction.response.send_message("The requested Embassy record could not be found.", ephemeral=True)
        return

    await interaction.response.defer()
    workflow = ApprovalWorkflow(self.db)
    approved = decision is Decision.APPROVED

    if not await workflow.decide(request_id, interaction.user.id, decision, route):
        await interaction.followup.send("This request was already handled by another reviewer.", ephemeral=True)
        return

    if approved:
        try:
            await self._grant_access(
                interaction.guild,
                applicant_id,
                embassy,
                AccessSource.DIPLOMAT_APPROVAL if route is Route.FOREIGN_DIPLOMAT else AccessSource.GOVERNMENT_OVERRIDE,
            )
        except Exception:
            await workflow.rollback_decision(request_id, interaction.user.id)
            await self.audit.log(
                action="ACCESS_GRANT_FAILED_AFTER_APPROVAL_CLAIM",
                actor_id=interaction.user.id,
                request_id=request_id,
                embassy_id=embassy.embassy_id,
            )
            await interaction.followup.send("Discord access could not be granted. The approval was rolled back and the request remains open.", ephemeral=True)
            return

        await self._log_channel(
            f"✅ **Embassy Access Approved**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{applicant_id}>\n**Approved By:** {interaction.user.mention}"
        )
        await self._close_request_thread(
            interaction.guild,
            request,
            f"Your Embassy access request has been **approved**.\n\n**Embassy:** {embassy.country_name}\n**Approved by:** {interaction.user.mention}\n\nYour access has been granted. Welcome, diplomat. 🇮🇳",
        )
    else:
        await self._log_channel(
            f"❌ **Embassy Access Declined**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{applicant_id}>\n**Declined By:** {interaction.user.mention}"
        )
        await self._close_request_thread(
            interaction.guild,
            request,
            f"Your Embassy access request has been **declined**.\n\n**Embassy:** {embassy.country_name}\n**Decision by:** {interaction.user.mention}\n\nNo Embassy access has been granted.",
        )

    try:
        if interaction.message:
            await interaction.message.edit(view=EmbassyApprovalView.disabled_view())
    except discord.HTTPException:
        pass


EmbassyFlow.decide = _safe_embassy_decide
