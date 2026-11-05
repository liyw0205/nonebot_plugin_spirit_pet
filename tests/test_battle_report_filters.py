import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000

KINDS = {"论剑": "pvp", "切磋": "spar", "秘境": "pve", "关卡": "pve_stage"}


def seed_battle(game, kind, *, user="u1", played=NOW, title="seed", operation=None):
    snapshot = json.dumps({
        "teams": [
            {"side": 0, "members": [{"pet_name": "青鸾"}]},
            {"side": 1, "members": [{"pet_name": "木灵"}]},
        ],
    })
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, ?, '', ?, 0, 3, ?, '{}', ?, '[]')",
            (operation or f"filter-{kind}-{user}-{played}-{title}", user, kind, title,
             played, snapshot),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, user),
        )
        conn.commit()
        return cursor.lastrowid


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW)


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_each_kind_only_lists_that_kind(game, play):
    account(game, play)
    for name, kind in KINDS.items():
        seed_battle(game, kind, title=f"{name}测试", operation=f"kind-{kind}")
    for name in KINDS:
        page = play("battle_reports", name, now=NOW + 10)
        assert page.title == f"灵宠战报 · {name} 1/1"
        assert len(page.lines) == 1
        assert name in page.lines[0]
        assert all(other not in page.lines[0] for other in KINDS if other != name)


def test_filter_pagination_uses_filtered_total_and_prefix(game, play):
    account(game, play)
    for index in range(6):
        seed_battle(game, "spar", played=NOW + index, operation=f"spar-{index}")
    first = play("battle_reports", "切磋", now=NOW + 10)
    assert first.title == "灵宠战报 · 切磋 1/2"
    assert len(first.lines) == 5
    second = play("battle_reports", "切磋 2", now=NOW + 10)
    assert second.title == "灵宠战报 · 切磋 2/2"
    assert len(second.lines) == 1
    assert "灵宠战报 切磋 分页 1" in second.commands
    same = play("battle_reports", "切磋 分页 2", now=NOW + 10)
    assert same.title == second.title
    assert "灵宠战报 切磋 分页 2" in first.commands


def test_unfiltered_history_keeps_old_contract(game, play):
    account(game, play)
    for index in range(6):
        seed_battle(game, "spar", played=NOW + index, operation=f"all-{index}")
    first = play("battle_reports", now=NOW + 10)
    second = play("battle_reports", "分页 2", now=NOW + 10)
    assert first.title == "灵宠战报 1/2"
    assert second.title == "灵宠战报 2/2"
    assert "灵宠战报 分页 2" in first.commands


def test_empty_filter_unknown_kind_and_bad_page(game, play):
    account(game, play)
    empty = play("battle_reports", "论剑", now=NOW + 1)
    assert empty.title == "灵宠战报 · 论剑 1/1"
    assert empty.lines == ("尚无论剑战报。",)
    with pytest.raises(GameError, match="格式"):
        play("battle_reports", "传说", now=NOW + 1)
    seed_battle(game, "spar", played=NOW, operation="one-spar")
    with pytest.raises(GameError, match="战报共 1 页"):
        play("battle_reports", "切磋 9", now=NOW + 2)
    with pytest.raises(GameError, match="格式"):
        play("battle_reports", "切磋 分页 x", now=NOW + 2)


def test_filter_is_per_player(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_battle(game, "pvp", user="u2", operation="u2-pvp")
    assert play("battle_reports", "论剑", now=NOW + 1).lines == ("尚无论剑战报。",)
    assert len(play("battle_reports", "论剑", user="u2", now=NOW + 1).lines) == 1


def test_detail_still_works_from_filtered_list(game, play):
    account(game, play)
    battle_id = seed_battle(game, "spar", title="切磋详情", operation="detail-spar")
    page = play("battle_reports", "切磋", now=NOW + 1)
    assert page.inline_commands[0].command == f"灵宠战报 查看 {battle_id}"
    detail = play("battle_reports", f"查看 {battle_id}", now=NOW + 2)
    assert detail.title.startswith(f"战报 #{battle_id} ")
    assert "切磋" in detail.lines[0]


def test_filters_are_read_only(game, play):
    account(game, play)
    for index, kind in enumerate(KINDS.values()):
        seed_battle(game, kind, played=NOW + index, operation=f"ro-{kind}")
    before = state(game[1])
    for name in KINDS:
        play("battle_reports", name, now=NOW + 10)
    play("battle_reports", "切磋 1", now=NOW + 10)
    assert state(game[1]) == before


def test_help_parser_and_native_payload(game, play):
    account(game, play)
    seed_battle(game, "spar", operation="native-filter")
    assert _parse("灵宠战报 切磋") == ("battle_reports", "切磋")
    assert _parse("灵宠战报 切磋 2") == ("battle_reports", "切磋 2")
    guide = play("help", "对战与赛季", now=NOW)
    assert "灵宠战报 论剑/切磋/秘境/关卡" in guide.text()
    page = play("battle_reports", "切磋", now=NOW + 1)
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
