from __future__ import annotations

from rajdoot.embassy_workflow import country, otp
from rajdoot.warera import detect_government_position


def test_detects_mofa_from_warera_infos() -> None:
    assert detect_government_position({"infos": {"minOfForeignAffairsOf": "country-1"}}) == "Minister of Foreign Affairs"


def test_detects_president_from_named_field() -> None:
    assert detect_government_position({"governmentPosition": "President"}) == "President"


def test_country_handles_nested_country_object() -> None:
    assert country({"country": {"id": "7", "name": "Italy"}}) == ("7", "Italy")


def test_country_handles_warera_object_id_and_name() -> None:
    assert country({"country": {"_id": "6813b6d546e731854c7ac862", "name": "India"}}) == ("6813b6d546e731854c7ac862", "India")


def test_otp_is_six_alphanumeric_characters() -> None:
    value = otp()
    assert len(value) == 6 and value.isalnum() and value.upper() == value
