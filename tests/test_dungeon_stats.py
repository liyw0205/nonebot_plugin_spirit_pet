import json

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000  # 2027-01-15 Beijing
DAY = 86_400


def seed_battle(game, dungeon_id, *, user="u1", winner_side=0, played=NOW, operation=None):
    """Insert a finished pve battle in `dungeon_id` with `user` as a participant."""
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'pve', ?, 'seed', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"op-{dungeon_id}-{played}-{winner_side}-{user}", user, dungeon_id,
             winner_side, played, json.dumps({"teams": []})),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, user),
        )


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_catalog_aggregates_per_dungeon_and_orders_by_recent(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "forest", played=NOW, operation="c-win")                    # win
    seed_battle(game, "forest", winner_side=1, played=NOW + 1, operation="c-loss")  # loss
    seed_battle(game, "moon", played=NOW + 2, operation="c-moon")                 # win (most recent)
    page = play("dungeon_stats", now=NOW + 3)
    assert page.title == "秘境战绩 1/1"
    assert row(page, "月影谷") == "月影谷 · 出战 1 场 · 1 胜 0 负 0 平 · 最近获胜：2027-01-15 16:00"
    assert row(page, "青岚林") == "青岚林 · 出战 2 场 · 1 胜 1 负 0 平 · 最近获胜：2027-01-15 16:00"
    assert page.lines.index(row(page, "月影谷")) < page.lines.index(row(page, "青岚林"))
    assert "灵宠秘境首通" in page.commands
    assert [link.label for link in page.inline_commands] == ["查看战绩", "查看战绩"]


def test_detail_shows_summary_solo_link_and_recent_window(game, play):
    play("adopt", "青鸾", now=NOW)
    for index, winner in enumerate((0, 1, -1, 0, 0, 1)):
        seed_battle(game, "forest", winner_side=winner, played=NOW + index, operation=f"d-{index}")
    detail = play("dungeon_stats", "青岚林", now=NOW + 10)
    assert detail.title == "秘境战绩 · 青岚林"
    assert "出战 6 场 · 3 胜 2 负 1 平。" in detail.lines[0]
    assert "最近出战：2027-01-15 16:00" in detail.lines[1]
    assert "最近五场（新在前）：01-15 · 负、01-15 · 胜、01-15 · 胜、01-15 · 平、01-15 · 负" == detail.lines[2]
    assert "灵宠挑战 青岚林" in detail.commands  # forest is solo
    assert {link.command for link in detail.inline_commands} == {
        "灵宠秘境首通", "灵宠挑战 青岚林",
    }


def test_team_dungeon_detail_links_team_challenge(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "temple", played=NOW, operation="team-temple")
    detail = play("dungeon_stats", "上古灵殿", now=NOW + 1)
    assert "灵宠组队挑战 上古灵殿" in detail.commands
    assert {link.command for link in detail.inline_commands} == {
        "灵宠秘境首通", "灵宠组队挑战 上古灵殿",
    }


def test_single_dungeon_detail_links_solo_challenge(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "moon", played=NOW, operation="solo-moon")
    detail = play("dungeon_stats", "月影谷", now=NOW + 1)
    assert "灵宠挑战 月影谷" in detail.commands
    assert {link.command for link in detail.inline_commands} == {
        "灵宠秘境首通", "灵宠挑战 月影谷",
    }


def test_sweep_and_retired_keys_are_excluded(game, play):
    play("adopt", "青鸾", now=NOW)
    play("buy", "灵粮 3", now=NOW)
    sql(game[1], "UPDATE pets SET realm=0, energy=100")
    seed_battle(game, "removed_dungeon", played=NOW, operation="retired")
    page = play("dungeon_stats", now=NOW + 1)
    assert page.lines[0].startswith("还没有秘境出战记录") or "尚无" in page.lines[0]


def test_draw_only_history_shows_no_win(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "moon", winner_side=-1, played=NOW, operation="draw-only")
    page = play("dungeon_stats", now=NOW + 1)
    assert "0 胜 0 负 1 平 · 最近获胜：尚无获胜" in row(page, "月影谷")


def test_unregistered_and_empty_states(game, play):
    page = play("dungeon_stats", user="u9", now=NOW)
    assert page.title == "秘境战绩"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    play("adopt", "青鸾", now=NOW)
    empty = play("dungeon_stats", now=NOW + 1)
    assert "还没有秘境出战记录" in empty.text()
    with pytest.raises(GameError, match="还没有月影谷的出战记录"):
        play("dungeon_stats", "月影谷", now=NOW + 2)
    with pytest.raises(GameError, match="未找到该内容"):
        play("dungeon_stats", "不存在的秘境", now=NOW + 2)


def test_pagination_rejects_overflow(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="秘境战绩共 1 页"):
        play("dungeon_stats", "9", now=NOW)


def test_first_clear_page_links_stats_and_native_keyboard_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    first_clear = play("first_clear", now=NOW)
    assert "灵宠秘境战绩" in first_clear.commands
    seed_battle(game, "forest", played=NOW, operation="fc-link")
    page = play("dungeon_stats", now=NOW + 1)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_parse_routes_dungeon_stats():
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    assert handlers._parse("灵宠秘境战绩") == ("dungeon_stats", "")
    assert handlers._parse("灵宠秘境战绩 青岚林") == ("dungeon_stats", "青岚林")
    assert ("灵宠秘境战绩 秘境名", "灵宠秘境战绩 ", "按秘境回顾出战次数与胜负平；不填查看汇总列表。") in _HELP_SECTIONS["秘境与关卡"]
