"""灵宠寄养 board: both directions of an open foster, plus today's gifts."""

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000
U1_UID = 10000
U2_UID = 10001


def make_friends_via_arena(game):
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side,"
            " rounds, played_at, reply, snapshot, battle_log)"
            " VALUES ('seed-friend', 'u1', 'pvp', '', 'seed', 0, 3, 1, '{}', '{}', '[]')"
        )
        conn.executemany(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, ?, 'participant')",
            [(cursor.lastrowid, "u1", 0), (cursor.lastrowid, "u2", 1)],
        )


def setup(game, play):
    play("adopt", "青鸾", user="u1", now=NOW)
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES ('u1', 'baize', '白泽', ?)",
        (NOW,),
    )
    play("adopt", "玄狐", user="u2", now=NOW)
    make_friends_via_arena(game)


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT user_id, pet_id, name, archived FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id"),
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY item_id"),
    )


def test_the_owner_sees_who_holds_the_pet(game, play):
    setup(game, play)
    play("foster", f"{U2_UID} 2", user="u1", now=NOW)
    reply = play("foster", user="u1", now=NOW)
    assert "寄养中 1 只" in reply.text()
    line = next(text for text in reply.lines if "寄养中：" in text)
    assert "白泽" in line and f"代管人 UID {U2_UID}" in line
    index = reply.lines.index(line)
    assert any(link.line == index and link.command == "灵宠归还 2" for link in reply.inline_commands)


def test_the_caretaker_sees_the_owner_and_can_feed(game, play):
    setup(game, play)
    play("foster", f"{U2_UID} 2", user="u1", now=NOW)
    reply = play("foster", user="u2", now=NOW)
    assert "代管中 1 只" in reply.text()
    line = next(text for text in reply.lines if "代管中：" in text)
    assert "白泽" in line and f"主人 UID {U1_UID}" in line
    index = reply.lines.index(line)
    commands = {link.command for link in reply.inline_commands if link.line == index}
    assert commands == {"灵宠寄养喂食 2", "灵宠归还 2"}


def test_an_empty_board_says_so(game, play):
    play("adopt", "青鸾", user="u1", now=NOW)
    reply = play("foster", user="u1", now=NOW)
    assert "当前没有寄养往来" in reply.text()
    assert "代管中 0 只" in reply.text() and "寄养中 0 只" in reply.text()


def test_the_board_is_read_only(game, play):
    setup(game, play)
    play("foster", f"{U2_UID} 2", user="u1", now=NOW)
    before = snapshot(game)
    play("foster", user="u1", now=NOW)
    play("foster", user="u2", now=NOW)
    assert snapshot(game) == before


def test_an_unregistered_player_gets_a_preview(game, play):
    reply = play("foster", user="u9", now=NOW)
    assert "尚未结契" in reply.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='u9'") == []


def test_a_single_argument_still_refuses_with_the_format(game, play):
    setup(game, play)
    with pytest.raises(GameError, match="格式：灵宠寄养"):
        play("foster", "10001", user="u1", now=NOW)


def test_the_board_counts_today_gifts(game, play):
    setup(game, play)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'forge_ore', 5)")
    play("gift", f"{U2_UID} 灵石 100", user="u1", op="gift-1", now=NOW)
    play("gift", f"{U2_UID} 锻灵矿 2", user="u1", op="gift-2", now=NOW)
    reply = play("foster", user="u1", now=NOW)
    assert "今日赠礼 2/3" in reply.text()


def test_board_links_parse_and_buttons_stay_within_four(game, play):
    setup(game, play)
    play("foster", f"{U2_UID} 2", user="u1", now=NOW)
    reply = play("foster", user="u2", now=NOW)
    assert reply.inline_commands
    for link in reply.inline_commands:
        assert handlers._parse(link.command) is not None, link.command
        assert 0 <= link.line < len(reply.lines)
    pairs = _action_items(reply)
    assert len(pairs) <= 4
    buttons = {command for _, command in pairs}
    links = {link.command for link in reply.inline_commands}
    assert buttons & links == set()
    assert buttons <= set(reply.commands)


def test_returning_clears_the_board(game, play):
    setup(game, play)
    play("foster", f"{U2_UID} 2", user="u1", now=NOW)
    play("foster_return", "2", user="u1", now=NOW)
    reply = play("foster", user="u1", now=NOW)
    assert "当前没有寄养往来" in reply.text()
