import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player_uid, sql

NOW = 1_800_000_000


def seed_spar(game, attacker, defender, *, winner_side=0, played=NOW, operation=None):
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'spar', '', '切磋结算', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"spar-{attacker}-{defender}-{played}-{winner_side}",
             attacker, winner_side, played, json.dumps({"teams": []})),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, attacker),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 1, 'participant')", (cursor.lastrowid, defender),
        )
        conn.commit()


def account(game, play, user):
    play("adopt", "青鸾", user=user, now=NOW)


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_list_groups_by_opponent_and_orders_by_recent(game, play):
    for user in ("u1", "u2", "u3"):
        account(game, play, user)
    seed_spar(game, "u1", "u2", played=NOW, operation="w1")
    seed_spar(game, "u1", "u2", winner_side=1, played=NOW + 1, operation="l1")
    seed_spar(game, "u1", "u3", played=NOW + 2, operation="w2")
    page = play("spar_stats", now=NOW + 3)
    assert page.title == "切磋战绩 1/1"
    assert row(page, f"UID {player_uid(game[1], 'u3')}") == (
        f"UID {player_uid(game[1], 'u3')} · 切磋 1 场 · 1 胜 0 负 0 平 · 最近切磋：2027-01-15 16:00"
    )
    assert row(page, f"UID {player_uid(game[1], 'u2')}") == (
        f"UID {player_uid(game[1], 'u2')} · 切磋 2 场 · 1 胜 1 负 0 平 · 最近切磋：2027-01-15 16:00"
    )
    assert page.lines.index(row(page, f"UID {player_uid(game[1], 'u3')}")) < page.lines.index(
        row(page, f"UID {player_uid(game[1], 'u2')}")
    )


def test_detail_recent_five_and_retry_link(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    for index, winner in enumerate((0, 1, -1, 0, 0, 1)):
        seed_spar(game, "u1", "u2", winner_side=winner, played=NOW + index,
                  operation=f"d-{index}")
    uid = player_uid(game[1], "u2")
    detail = play("spar_stats", str(uid), now=NOW + 10)
    assert detail.title == f"切磋战绩 · UID {uid}"
    assert "切磋 6 场 · 3 胜 2 负 1 平。" in detail.lines[0]
    assert "最近五场（新在前）：01-15 · 负、01-15 · 胜、01-15 · 胜、01-15 · 平、01-15 · 负" == detail.lines[2]
    assert detail.inline_commands[0].command == f"灵宠切磋 {uid}"


def test_both_sides_see_the_same_battle_with_opposite_results(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", winner_side=0, played=NOW, operation="sym-win")
    first = play("spar_stats", now=NOW + 1)
    second = play("spar_stats", user="u2", now=NOW + 1)
    assert "1 胜 0 负" in row(first, f"UID {player_uid(game[1], 'u2')}")
    assert "0 胜 1 负" in row(second, f"UID {player_uid(game[1], 'u1')}")


def test_draw_and_only_own_battles_count(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    account(game, play, "u3")
    seed_spar(game, "u2", "u3", winner_side=0, played=NOW, operation="other")
    seed_spar(game, "u1", "u2", winner_side=-1, played=NOW + 1, operation="draw")
    page = play("spar_stats", now=NOW + 2)
    assert len(page.lines) == 1
    assert "0 胜 0 负 1 平" in page.lines[0]


def test_pagination_and_overflow(game, play):
    account(game, play, "u1")
    for index in range(2, 8):
        account(game, play, f"u{index}")
        seed_spar(game, "u1", f"u{index}", played=NOW + index, operation=f"page-{index}")
    first = play("spar_stats", now=NOW + 10)
    assert first.title == "切磋战绩 1/2"
    assert len(first.lines) == 5
    second = play("spar_stats", "分页 2", now=NOW + 10)
    assert second.title == "切磋战绩 2/2"
    assert len(second.lines) == 1
    with pytest.raises(GameError, match="共 2 页"):
        play("spar_stats", "分页 3", now=NOW + 10)


def test_empty_unregistered_and_unknown_uid(game, play):
    empty = play("spar_stats", user="ghost", now=NOW)
    assert "尚未结契" in empty.text()
    assert empty.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    account(game, play, "u1")
    assert "还没有切磋记录" in play("spar_stats", now=NOW + 1).text()
    with pytest.raises(GameError, match="未找到该修士"):
        play("spar_stats", "10000", now=NOW + 2)
    with pytest.raises(GameError, match="格式"):
        play("spar_stats", "abc", now=NOW + 2)
    with pytest.raises(GameError, match="格式"):
        play("spar_stats", "分页 x", now=NOW + 2)


def test_help_parser_and_native_payload(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", played=NOW, operation="native")
    assert _parse("灵宠切磋战绩") == ("spar_stats", "")
    assert _parse("灵宠切磋战绩 10001") == ("spar_stats", "10001")
    guide = play("help", "对战与赛季", now=NOW)
    assert "灵宠切磋战绩 UID" in guide.text()
    page = play("spar_stats", now=NOW + 1)
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
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", played=NOW, operation="readonly")
    before = state(game[1])
    play("spar_stats", now=NOW + 1)
    play("spar_stats", str(player_uid(game[1], "u2")), now=NOW + 2)
    assert state(game[1]) == before
