import re

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import pet_outing
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400


def snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(store, "SELECT * FROM pets ORDER BY pet_id"),
        sql(
            store,
            "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
            " ORDER BY user_id, quest_id",
        ),
    )


class GreatRandom:
    def randint(self, start, stop):
        return stop if (start, stop) == (1, 100) else start

    def random(self):
        return 0.0


def test_route_catalog_is_read_only_and_previews_all_destinations(game, play):
    play("adopt", "青鸾", now=NOW)
    conn = game[1].connect()
    conn.execute("UPDATE pets SET energy=1, energy_updated=?", (NOW - 3600,))
    conn.commit()
    conn.close()
    before = snapshot(game[1])

    page = play("pet_outing", "路线", now=NOW)

    assert page.title == "灵宠出游择景"
    assert len(page.inline_commands) == 8
    assert {link.command for link in page.inline_commands} == {
        f"灵宠出游 1 {name}"
        for name in ("溪畔", "山脊", "灵木林", "集市口", "旧观遗址", "望云坡", "浅山洞", "灵草甸")
    }
    assert sum(map(int, re.findall(r"精彩/寻常/平平 (\d+)%/(\d+)%/(\d+)%", page.text())[0])) == 100
    assert "攻击" in page.text() and "速度" in page.text()
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=1")[0]["energy"] == 1


def test_selected_scene_drives_real_check_reward_and_recent_route(game, play):
    play("adopt", "青鸾", now=NOW)
    game[0].rng = GreatRandom()
    before_stones = player(game[1])["stones"]

    reply = play("pet_outing", "1 浅山洞", now=NOW, op="route-cave")

    assert "浅山洞" in reply.text()
    assert "精彩" in reply.text()
    assert player(game[1])["stones"] == before_stones + 42  # Cave minimum 28, plus 50%.
    assert items(game[1])["spirit_food"] == 4
    route = sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' "
        "AND quest_id='outing_trip_1_cave'",
    )
    assert route == [{"progress": NOW * 4 + 3, "claimed": 0}]
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id='outing_trip_1_brook'") == []

    board = play("pet_outing_board", now=NOW + 1)
    assert "最近 浅山洞/精彩" in board.text()
    assert any(link.command == "灵宠出游 路线 1" for link in board.inline_commands)


def test_route_name_on_active_pet_and_explicit_pet_choice(game, play):
    play("adopt", "青鸾", now=NOW)
    play("summon", now=NOW, op="route-summon")
    game[0].rng = GreatRandom()

    first = play("pet_outing", "山脊", now=NOW, op="route-active")
    second = play("pet_outing", "2 灵木林", now=NOW + 1, op="route-other")

    assert "山脊" in first.text()
    assert "灵木林" in second.text()
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'outing_trip_%'") == [
        {"quest_id": "outing_trip_1_ridge"},
        {"quest_id": "outing_trip_2_grove"},
    ]


def test_unknown_route_and_wrong_owner_leave_state_unchanged(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "青鸾", user="u2", now=NOW)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="没有这个出游地点"):
        play("pet_outing", "不存在的景点", now=NOW, op="route-invalid")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("pet_outing", "999 山脊", now=NOW, op="route-owner")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("pet_outing", "2 山脊", now=NOW, op="route-other-owner")
    assert snapshot(game[1]) == before


def test_legacy_day_marker_prevents_clock_rollback_without_fabricating_route(game, play):
    play("adopt", "青鸾", now=NOW)
    recorded_day = beijing_day(NOW + DAY)
    conn = game[1].connect()
    conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
        " VALUES ('u1', ?, 1, 0)",
        (f"outing_day_{recorded_day}_1",),
    )
    conn.commit()
    conn.close()
    before = snapshot(game[1])

    page = play("pet_outing", "路线 1", now=NOW)
    assert "系统日期早于最近出游日" in page.text()
    assert page.inline_commands == ()
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'outing_trip_%'") == []

    with pytest.raises(GameError, match="系统日期早于最近出游日"):
        play("pet_outing", "山脊", now=NOW, op="route-clock-back")


def test_clock_rollback_refuses_after_new_route_and_keeps_snapshot(game, play):
    play("adopt", "青鸾", now=NOW)
    play("pet_outing", "山脊", now=NOW + DAY, op="route-later-day")
    before = snapshot(game[1])

    with pytest.raises(GameError, match="系统日期早于最近出游日"):
        play("pet_outing", "浅山洞", now=NOW, op="route-backward")

    assert snapshot(game[1]) == before


def test_failed_late_settlement_rolls_back_all_outing_state(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    game[0].rng = GreatRandom()
    before = snapshot(game[1])

    def fail_after_settlement(*args):
        raise RuntimeError("injected route-ledger failure")

    monkeypatch.setattr(pet_outing, "_record_trip", fail_after_settlement)
    with pytest.raises(RuntimeError, match="injected route-ledger failure"):
        play("pet_outing", "山脊", now=NOW, op="route-rollback")

    assert snapshot(game[1]) == before


def test_operation_replay_pays_and_records_only_once(game, play):
    play("adopt", "青鸾", now=NOW)
    game[0].rng = GreatRandom()
    first = play("pet_outing", "灵木林", now=NOW, op="route-replay")
    after_first = snapshot(game[1])

    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    replay = restarted.execute("u1", "pet_outing", "灵木林", "route-replay", NOW + DAY)

    assert replay == first
    assert snapshot(game[1]) == after_first
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id LIKE 'outing_trip_%'")[0]["n"] == 1


def test_route_records_are_bounded_and_latest_result_is_visible(game, play):
    play("adopt", "青鸾", now=NOW)
    locations = ("溪畔", "山脊", "灵木林", "集市口", "旧观遗址", "望云坡", "浅山洞", "灵草甸")
    for index in range(10):
        play(
            "pet_outing", locations[index % len(locations)],
            now=NOW + index * DAY, op=f"route-bounded-{index}",
        )

    rows = sql(
        game[1],
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id='u1' "
        "AND quest_id GLOB 'outing_trip_1_*'",
    )
    assert rows[0]["n"] == len(locations)
    latest = play("pet_outing_board", now=NOW + 9 * DAY + 1)
    assert "最近 山脊/平平" in latest.text()
    assert beijing_day(NOW + 9 * DAY) in latest.text()


def test_pet_id_prefixes_do_not_match_longer_numeric_ids(game, play):
    play("adopt", "青鸾", now=NOW)
    conn = game[1].connect()
    conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES "
        "('u1', 'outing_sight_10_brook', 1, 0), "
        "('u1', 'outing_trip_10_meadow', ?, 0)",
        (NOW * 4 + 3,),
    )
    conn.commit()
    conn.close()

    board = play("pet_outing_board", now=NOW)

    assert "见闻 0/8" in board.text()
    assert "最近 灵草甸" not in board.text()


def test_route_commands_are_documented_parseable_and_native_safe(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("pet_outing", "路线", now=NOW)
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠出游 路线") == ("pet_outing", "路线")
    assert handlers._parse("灵宠出游 路线 1") == ("pet_outing", "路线 1")
    assert handlers._parse("灵宠出游 1 山脊") == ("pet_outing", "1 山脊")
    native, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}
    assert native and len(page.inline_commands) == 8
    help_page = play("help", "血脉与道具", now=NOW)
    assert any(line.startswith("灵宠出游 路线：") for line in help_page.lines)
    assert any(line.startswith("灵宠出游 地点：") for line in help_page.lines)
