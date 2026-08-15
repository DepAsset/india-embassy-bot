from __future__ import annotations

from types import SimpleNamespace

from rajdoot.embassy_approval import EmbassyApprovalService


def test_indian_citizen_role_classifies_as_ambassador(monkeypatch) -> None:
    monkeypatch.setattr("rajdoot.embassy_approval.settings.indian_citizen_role_id", 123)
    member = SimpleNamespace(roles=[SimpleNamespace(id=123)])

    assert EmbassyApprovalService.assignment_type(member) == "indian_ambassador"


def test_other_member_classifies_as_foreign_diplomat(monkeypatch) -> None:
    monkeypatch.setattr("rajdoot.embassy_approval.settings.indian_citizen_role_id", 123)
    member = SimpleNamespace(roles=[SimpleNamespace(id=456, name="Embassy Access")])

    assert EmbassyApprovalService.assignment_type(member) == "foreign_diplomat"


def test_name_based_citizen_fallback(monkeypatch) -> None:
    monkeypatch.setattr("rajdoot.embassy_approval.settings.indian_citizen_role_id", None)
    member = SimpleNamespace(roles=[SimpleNamespace(id=456, name="Indian Citizen")])

    assert EmbassyApprovalService.assignment_type(member) == "indian_ambassador"
