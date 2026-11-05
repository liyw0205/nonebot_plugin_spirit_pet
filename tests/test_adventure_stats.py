import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000  # 2027-01-15 16:00 Beijing
DAY = 86_400


def seed_ambush(game, route_id, *, user="u1", winner_side=0, played=NOW, operation=None):
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'pve', ?, 'seed', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"ambush-{route_id}-{played}-{winner_side}-{user}", user,
             f"ambush_{route_id}", winner_side, played, json.dumps({"teams": []})),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, user),
        )
        conn.commit()


def row(page, text):
    return next(line for line in page.lines if text in line)


def route(game, route_id):
    return game[0].content.exploration_routes[route_id]


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_catalog_aggregates_per_route_and_orders_by_recent(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_ambush(game, "spirit_spring", played=NOW, operation="a-win")
    seed_ambush(game, "spirit_spring", winner_side=1, played=NOW + 1, operation="a-loss")
    seed_ambush(game, "starfall_valley", played=NOW + 2, operation="a-star")
    page = play("adventure_stats", now=NOW + 3)
    assert page.title == "历练战绩 1/1"
    spring = route(game, "spirit_spring")
    star = route(game, "starfall_valley")
    assert row(page, spring.name) == (
        f"{spring.name} · 伏击 2 场 · 1 胜 1 负 0 平 · 最近伏击：2027-01-15 16:00"
    )
    assert row(page, star.name) == (
        f"{star.name} · 伏击 1 场 · 1 胜 0 负 0 平 · 最近伏击：2027-01-15 16:00"
    )
    assert page.lines.index(row(page, star.name)) < page.lines.index(row(page, spring.name))
    assert "灵宠历练" in page.commands
    assert "灵宠战报" in page.commands
    assert [link.label for link in page.inline_commands] == ["查看战绩", "查看战绩"]


def test_detail_shows_summary_recent_window_and_retry_link(game, play):
    play("adopt", "青鸾", now=NOW)
    for index, winner in enumerate((0, 1, -1, 0, 0, 1)):
        seed_ambush(game, "spirit_spring", winner_side=winner, played=NOW + index,
                    operation=f"detail-{index}")
    spring = route(game, "spirit_spring")
    detail = play("adventure_stats", spring.name, now=NOW + 10)
    assert detail.title == f"历练战绩 · {spring.name}"
    assert "伏击 6 场 · 3 胜 2 负 1 平。" in detail.lines[0]
    assert "伏击概率：20%" in detail.lines[1]
    assert "最近五场（新在前）：01-15 · 负、01-15 · 胜、01-15 · 胜、01-15 · 平、01-15 · 负" == detail.lines[2]
    assert "灵宠历练" in detail.commands
    assert detail.inline_commands[0].command == f"灵宠历练 {spring.name}"


def test_draw_only_and_no_win_text(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_ambush(game, "spirit_spring", winner_side=-1, played=NOW, operation="draw")
    page = play("adventure_stats", now=NOW + 1)
    assert "0 胜 0 负 1 平" in row(page, route(game, "spirit_spring").name)


def test_dungeon_and_unknown_ambush_keys_are_excluded(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_ambush(game, "forest", played=NOW, operation="not-a-route")
    seed_ambush(game, "removed_route", played=NOW + 1, operation="retired")
    page = play("adventure_stats", now=NOW + 2)
    assert "还没有历练伏击记录" in page.text()
    assert page.title == "历练战绩 1/1"


def test_only_the_current_player_is_counted(game, play):
    play("adopt", "青鸾", user="u2", now=NOW)
    seed_ambush(game, "spirit_spring", user="u2", played=NOW, operation="other-user")
    play("adopt", "青鸾", now=NOW)
    page = play("adventure_stats", now=NOW + 1)
    assert "还没有历练伏击记录" in page.text()
    with pytest.raises(GameError, match="还没有.*的伏击记录"):
        play("adventure_stats", route(game, "spirit_spring").name, now=NOW + 2)


def test_unregistered_is_read_only_and_does_not_create_a_player(game, play):
    page = play("adventure_stats", user="ghost", now=NOW)
    assert page.title == "历练战绩"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    with pytest.raises(GameError, match="尚未结契"):
        play("adventure_stats", route(game, "spirit_spring").name, user="ghost", now=NOW)


def test_pagination_orders_and_rejects_overflow(game, play):
    play("adopt", "青鸾", now=NOW)
    routes = list(game[0].content.exploration_routes.values())[:6]
    for index, entry in enumerate(routes):
        seed_ambush(game, entry.id, played=NOW + index, operation=f"page-{entry.id}")
    first = play("adventure_stats", now=NOW + 10)
    assert first.title == "历练战绩 1/2"
    assert len(first.lines) == 5
    second = play("adventure_stats", "2", now=NOW + 10)
    assert second.title == "历练战绩 2/2"
    assert len(second.lines) == 1
    with pytest.raises(GameError, match="共 2 页"):
        play("adventure_stats", "3", now=NOW + 10)


def test_invalid_route_and_non_numeric_page_rejection(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="未找到该内容"):
        play("adventure_stats", "不存在的路线", now=NOW)
    seed_ambush(game, "spirit_spring", played=NOW, operation="bad-page")
    with pytest.raises(GameError, match="共 1 页"):
        play("adventure_stats", "9", now=NOW + 1)


def test_help_parser_and_native_payload(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_ambush(game, "spirit_spring", played=NOW, operation="native")
    assert _parse("灵宠历练战绩") == ("adventure_stats", "")
    assert _parse("灵宠历练战绩 灵泉修行") == ("adventure_stats", "灵泉修行")
    guide = play("help", "秘境与关卡", now=NOW)
    assert "灵宠历练战绩 路线名" in guide.text()
    page = play("adventure_stats", now=NOW + 1)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons <= set(page.commands)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}


def test_pages_are_read_only(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_ambush(game, "spirit_spring", played=NOW, operation="readonly")
    before = state(game[1])
    play("adventure_stats", now=NOW + 1)
    play("adventure_stats", route(game, "spirit_spring").name, now=NOW + 2)
    assert state(game[1]) == before
