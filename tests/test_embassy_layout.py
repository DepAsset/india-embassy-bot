import pytest

from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner


def test_planner_keeps_letter_groups_together() -> None:
    embassies = []
    channel_id = 1000
    for letter in ("A", "B", "C", "D"):
        for index in range(20):
            embassies.append(
                {
                    "id": f"{letter}-{index}",
                    "country_name": f"{letter}{index:02d}",
                    "channel_id": channel_id,
                    "status": "active",
                }
            )
            channel_id += 1

    plan = EmbassyLayoutPlanner.plan(embassies)
    assert len(plan.entries) == 80
    assert len(plan.categories) == 2

    first = plan.categories[0]
    second = plan.categories[1]
    assert first.name == "Embassy 1 (A-B)"
    assert second.name == "Embassy 2 (C-Z)"
    assert first.entries[-1].country_name.startswith("B")
    assert second.entries[0].country_name.startswith("C")


def test_two_category_layout_uses_m_to_z_for_final_category() -> None:
    names = [
        "Afghanistan",
        "Albania",
        "Algeria",
        "Argentina",
        "Australia",
        "Austria",
        "Belgium",
        "Brazil",
        "Canada",
        "Chile",
        "China",
        "Denmark",
        "Egypt",
        "France",
        "Germany",
        "Greece",
        "India",
        "Indonesia",
        "Iran",
        "Iraq",
        "Ireland",
        "Italy",
        "Japan",
        "Kenya",
        "Kuwait",
        "Laos",
        "Lebanon",
        "Malaysia",
        "Mexico",
        "Moldova",
        "Mongolia",
        "Morocco",
        "Myanmar",
        "Nepal",
        "Netherlands",
        "Nigeria",
        "Norway",
        "Pakistan",
        "Peru",
        "Poland",
        "Portugal",
        "Qatar",
        "Romania",
        "Russia",
        "Serbia",
        "Singapore",
        "Spain",
        "Sweden",
        "Switzerland",
        "Thailand",
        "Tunisia",
        "Turkiye",
        "Ukraine",
        "United Kingdom",
        "United States",
        "Uruguay",
        "Uzbekistan",
        "Venezuela",
        "Vietnam",
        "Yemen",
    ]
    embassies = [
        {
            "id": str(index),
            "country_name": name,
            "channel_id": 2000 + index,
            "status": "active",
        }
        for index, name in enumerate(names)
    ]

    plan = EmbassyLayoutPlanner.plan(embassies)

    assert plan.categories[0].name == "Embassy 1 (A-I)"
    assert plan.categories[-1].name == "Embassy 2 (J-Z)"


def test_planner_ignores_archived_embassies() -> None:
    plan = EmbassyLayoutPlanner.plan(
        [
            {"id": "1", "country_name": "India", "channel_id": 1, "status": "active"},
            {"id": "2", "country_name": "Italy", "channel_id": 2, "status": "archived"},
        ]
    )
    assert [entry.country_name for entry in plan.entries] == ["India"]
    assert plan.categories[0].name == "Embassy 1 (I-Z)"


def test_planner_rejects_a_letter_group_over_capacity() -> None:
    embassies = [
        {
            "id": str(index),
            "country_name": f"A{index:02d}",
            "channel_id": index + 1,
            "status": "active",
        }
        for index in range(51)
    ]
    with pytest.raises(ValueError, match="exceeds the category limit"):
        EmbassyLayoutPlanner.plan(embassies)


def test_channel_name_is_canonical_country_slug() -> None:
    assert EmbassyDiscordOrganizer.embassy_slug("United States") == "united-states"
    assert EmbassyDiscordOrganizer.embassy_slug("Côte d'Ivoire") == "c-te-d-ivoire"
