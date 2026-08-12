from enum import StrEnum


class RequestState(StrEnum):
    SUBMITTED = "submitted"
    PROFILE_RESOLVED = "profile_resolved"
    OTP_PENDING = "otp_pending"
    OTP_LOCKED = "otp_locked"
    VERIFIED = "verified"
    EMBASSY_SELECTION = "embassy_selection"
    DIPLOMAT_REVIEW = "diplomat_review"
    GOVERNMENT_REVIEW = "government_review"
    PREAPPROVED = "preapproved"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    DECLINED = "declined"
    RECOVERY_PENDING = "recovery_pending"
    STALE = "stale"
    CLOSED = "closed"


class AssignmentStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class EmbassyStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class PreapprovalStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AssignmentType(StrEnum):
    AMBASSADOR = "ambassador"
    FOREIGN_DIPLOMAT = "foreign_diplomat"
    APPLICANT = "applicant"
    SPECIAL_OFFICIAL = "special_official"
    GOVERNMENT_APPROVAL = "government_approval"
    PREAPPROVAL = "preapproval"
    ADMIN_OVERRIDE = "admin_override"
