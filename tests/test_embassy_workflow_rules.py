from __future__ import annotations

from rajdoot.embassy_workflow import country, otp
from rajdoot.warera import detect_government_position


def test_detects_mofa_from_warera_infos() -> None:
    profile = {"infos": {"minOfForeignAffairsOf": "country-1"}}
    assert detect_government_position(profile) == "Minister of Foreign Affairs"


def test_detects_president_from_named_field() -> None:
    profile = {"governmentPosition": "President"}
    assert detect_government_position(profile) == "President"


def test_country_handles_nested_country_object() -> None:
    profile = {"country": {"id": "7", "name": "Italy"}}
    assert country(profile) == ("7", "Italy")


def test_country_handles_country_id_with_resolved_name() -> None:
    profile = {"country": {"id": "6813b6d546e731854c7ac862", "name": "India"}}
    assert country(profile) == ("6813b6d546e731854c7ac862", "India")


def test_otp_is_six_alphanumeric_characters() -> None:
    value = otp()
    assert len(value) == 6
    assert value.isalnum()
    assert value.upper() == value
