from rajdoot.embassy_layout import EmbassyLayoutPlanner


def test_planner_keeps_letter_groups_together() -> None:
    embassies = []
    for letter in ("A", "B", "C", "D"):
        for index in range(20):
            embassies.append(
                {
                    "id": f"{letter}-{index}",
                    "country_name": f"{letter}{index:02d}",
                    "channel_id": index + 1000,
                    "status": "active",
                }
            )

    plan = EmbassyLayoutPlanner.plan(embassies)
    assert len(plan) == 80
    assert max(entry.category_index for entry in plan) == 2

    first = [entry.country_name for entry in plan if entry.category_index == 1]
    second = [entry.country_name for entry in plan if entry.category_index == 2]
    assert first[-1].startswith("B")
    assert second[0].startswith("C")


def test_planner_ignores_archived_embassies() -> None:
    plan = EmbassyLayoutPlanner.plan(
        [
            {"id": "1", "country_name": "India", "channel_id": 1, "status": "active"},
            {"id": "2", "country_name": "Italy", "channel_id": 2, "status": "archived"},
        ]
    )
    assert [entry.country_name for entry in plan] == ["India"]


def test_category_name_uses_letter_range() -> None:
    plan = EmbassyLayoutPlanner.plan(
        [
            {"id": "1", "country_name": "India", "channel_id": 1, "status": "active"},
            {"id": "2", "country_name": "Italy", "channel_id": 2, "status": "active"},
        ]
    )
    assert EmbassyLayoutPlanner.category_name(1, plan) == "Embassy 1 (I-I)"
