import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import player_uid, sql

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)


def seed_spar(game, attacker, defender, *, winner_side=0, played=WEEK_START + 1, operation=None):
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'spar', '', '切磋结算', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"board-{attacker}-{defender}-{played}-{winner_side}",
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


def test_week_aggregates_wins_losses_draws(game, play):
    for user in ("u1", "u2", "u3"):
        account(game, play, user)
    seed_spar(game, "u1", "u2", winner_side=0, played=WEEK_START + 1, operation="w1")
    seed_spar(game, "u1", "u3", winner_side=-1, played=WEEK_START + 2, operation="d1")
    seed_spar(game, "u2", "u3", winner_side=0, played=WEEK_START + 3, operation="w2")
    page = play("spar_board", now=NOW)
    assert page.title == "灵宠切磋榜"
    assert row(page, f"UID {player_uid(game[1], 'u1')}") == (
        f"1. UID {player_uid(game[1], 'u1')} · 1 胜 0 负 1 平 · 2 场"
    )
    assert row(page, f"UID {player_uid(game[1], 'u2')}") == (
        f"2. UID {player_uid(game[1], 'u2')} · 1 胜 1 负 0 平 · 2 场"
    )
    assert row(page, f"UID {player_uid(game[1], 'u3')}") == (
        f"3. UID {player_uid(game[1], 'u3')} · 0 胜 1 负 1 平 · 2 场"
    )


def test_previous_week_is_excluded(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", played=WEEK_START - 1, operation="last-week")
    page = play("spar_board", now=NOW)
    assert "本周还没有切磋记录。" in page.text()
    assert "1. UID" not in page.text()


def test_top_ten_and_own_rank_outside(game, play):
    for index in range(1, 12):
        account(game, play, f"u{index}")
    for index in range(2, 12):
        seed_spar(game, "u1", f"u{index}", played=WEEK_START + index, operation=f"top-{index}")
    page = play("spar_board", user="u9", now=NOW)
    assert len(page.lines) == 1 + 10 + 1
    assert "你的名次：第 11 名（共 11 位参与者）。" in page.text()
    assert f"UID {player_uid(game[1], 'u9')}" not in page.text()


def test_empty_board_and_unregistered_are_read_only(game, play):
    page = play("spar_board", user="ghost", now=NOW)
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    account(game, play, "u1")
    empty = play("spar_board", now=NOW)
    assert "本周还没有切磋记录。" in empty.text()
    with pytest.raises(GameError, match="不接受参数"):
        play("spar_board", "1", now=NOW)


def test_board_is_read_only(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", played=WEEK_START + 1, operation="ro-board")
    before = state(game[1])
    play("spar_board", now=NOW)
    assert state(game[1]) == before


def test_help_parser_and_native_payload(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_spar(game, "u1", "u2", played=WEEK_START + 1, operation="native-board")
    assert _parse("灵宠切磋榜") == ("spar_board", "")
    assert "灵宠切磋榜" in play("help", "对战与赛季", now=NOW).text()
    page = play("spar_board", now=NOW)
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
