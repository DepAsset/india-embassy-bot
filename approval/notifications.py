from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalNotification:
    title: str
    body: str
    mention_user_ids: tuple[int, ...] = ()
    dm_user_id: int | None = None
    thread_message: str | None = None


def approval_result_notification(
    applicant_id: int,
    embassy_name: str,
    approved: bool,
    reason: str | None = None,
) -> ApprovalNotification:
    if approved:
        return ApprovalNotification(
            title="Embassy Access Approved",
            body=f"Your access to the {embassy_name} Embassy has been approved.",
            dm_user_id=applicant_id,
            thread_message="Embassy access approved. Your access is now being provisioned.",
        )
    reason_text = f" Reason: {reason}" if reason else ""
    return ApprovalNotification(
        title="Embassy Access Declined",
        body=f"Your request for the {embassy_name} Embassy was declined.{reason_text}",
        dm_user_id=applicant_id,
        thread_message="Embassy access request declined.",
    )
