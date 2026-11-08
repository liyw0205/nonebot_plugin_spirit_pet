"""Cave expansion: two new facilities, 繁荣 tiers and the daily offering record."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def facility(game, facility_id):
    return game[0].content.cave[facility_id]


def set_levels(game, mapping, user="u1"):
    for facility_id, level in mapping.items():
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (user, f"cave_{facility_id}_level", level),
        )


def offering_rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? "
        "AND quest_id LIKE 'cave_offering_%' ORDER BY quest_id",
        (user,),
    )


def test_content_defines_five_facilities_and_five_offering_tiers(game):
    content = game[0].content
    assert sorted(content.cave) == ["alchemy", "herb_garden", "pen", "spirit_field", "spring"]
    assert content.cave["herb_garden"].item == "seed_blood_herb"
    assert content.cave["spirit_field"].item == "seed_spirit_rice"
    for entry in content.cave.values():
        assert entry.max_level == 5 and len(entry.upgrades) == 4
    assert sorted(content.cave_offerings) == [1, 2, 3, 4, 5]
    for tier, reward in content.cave_offerings.items():
        assert reward.stones or reward.items
        assert all(item_id in content.items for item_id in reward.items)
    stones = [content.cave_offerings[tier].stones for tier in sorted(content.cave_offerings)]
    assert stones == sorted(stones) and stones[0] == 40


def test_page_shows_prosperity_tier_and_offering_state(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("cave", now=NOW)
    assert "洞府总览：5/25 级 · 繁荣 5/25（1 档）" in page.text()
    assert "每日供奉：今日可供奉（1 档：灵石 40）。" in page.text()
    commands = {f"/{link.command}" for link in page.inline_commands}
    assert "/灵宠洞府 供奉" in commands and "/灵宠洞府 记录" in commands


def test_daily_offering_pays_once_per_day_and_tracks_the_counter(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000")
    result = play("cave", "供奉", now=NOW, op="offer-one")
    assert "洞府繁荣 5/25（1 档）" in result.text()
    assert player(game[1])["stones"] == 1040
    assert offering_rows(game) == [{"quest_id": f"cave_offering_2027-01-15", "progress": 1}]
    assert sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_cave_offerings'",
    ) == [{"progress": 1}]
    assert "累计供奉 1 次" in result.text()

    with pytest.raises(GameError, match="今日已经供奉过"):
        play("cave", "供奉", now=NOW + 60, op="offer-twice")
    assert player(game[1])["stones"] == 1040
    assert len(offering_rows(game)) == 1

    page = play("cave", now=NOW + 61)
    assert "今日已供奉" in page.text()
    assert "/灵宠洞府 供奉" not in {f"/{link.command}" for link in page.inline_commands}

    play("cave", "供奉", now=NOW + DAY, op="offer-next-day")
    assert player(game[1])["stones"] == 1080
    assert sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_cave_offerings'",
    ) == [{"progress": 2}]


def test_offering_follows_the_prosperity_tier(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000")
    set_levels(game, {"spring": 5, "pen": 5})  # 5 + 5 + 1 + 1 + 1 = 13 prosperity
    page = play("cave", now=NOW)
    assert "繁荣 13/25（2 档）" in page.text()
    assert "今日可供奉（2 档：灵石 80 · 灵粮 1）" in page.text()
    play("cave", "供奉", now=NOW + 1, op="offer-tier-two")
    assert player(game[1])["stones"] == 1080
    assert items(game[1])["spirit_food"] == 4  # starter 3 + 1
    assert offering_rows(game)[0]["progress"] == 2


def test_offering_record_groups_by_week_and_paginates(game, play):
    play("adopt", "青鸾", now=NOW)
    # Two days in one week, plus six other weeks: seven weeks -> two pages.
    for day, tier in (
        ("2026-08-31", 1), ("2026-09-07", 1), ("2026-09-14", 2), ("2026-09-21", 3),
        ("2026-09-28", 4), ("2026-10-05", 3), ("2026-10-06", 4), ("2026-10-12", 5),
    ):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 1)",
            (f"cave_offering_{day}", tier),
        )
    first = play("cave", "记录", now=NOW)
    assert "洞府供奉记录（第 1/2 页，每页 6 周）：" in first.text()
    assert "2026-10-12 起 · 供奉 1 天 · 最高 5 档" in first.text()
    assert "2026-10-05 起 · 供奉 2 天 · 最高 4 档" in first.text()
    assert "2026-08-31" not in first.text()
    second = play("cave", "记录 2", now=NOW)
    assert "2026-08-31 起 · 供奉 1 天 · 最高 1 档" in second.text()
    with pytest.raises(GameError, match="共 2 页"):
        play("cave", "记录 3", now=NOW, op="record-three")

    empty = play("cave", "记录", user="ghost", now=NOW)
    assert "尚未结契" in empty.text() or "还没有供奉记录" in empty.text()


def test_objectives_help_and_native_contract(game, play):
    play("adopt", "青鸾", now=NOW)
    objectives = play("objectives", now=NOW)
    assert "洞府：繁荣 5/25（1 档） · 今日可供奉 · 剩余 5 次设施行动" in objectives.text()
    page = play("cave", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not (buttons & linked)

    play("cave", "供奉", now=NOW + 1, op="objective-offer")
    after = play("objectives", now=NOW + 2)
    assert "今日已供奉" in after.text()
    guide = play("help", "成长", now=NOW)
    assert "灵宠洞府 供奉" in guide.text() and "灵宠洞府 记录" in guide.text()
    assert handlers._parse("灵宠洞府 供奉") == ("cave", "供奉")
    assert handlers._parse("灵宠洞府 记录 2") == ("cave", "记录 2")
