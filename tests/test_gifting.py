import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
U1_UID = 10000
U2_UID = 10001


def make_friends_via_arena(game):
    """One arena row between u1 and u2 satisfies the friendship check."""
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side, "
            "rounds, played_at, reply, snapshot, battle_log) "
            "VALUES ('seed-friend', 'u1', 'pvp', '', 'seed', 0, 3, 1, '{}', '{}', '[]')",
        )
        conn.executemany(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?, ?, ?, 'participant')",
            [(cursor.lastrowid, "u1", 0), (cursor.lastrowid, "u2", 1)],
        )


def adopt_both(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")


def gift_log(game, day="*"):
    return sql(game[1], f"SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'gift_log_{day}'")


def test_gift_stones_moves_balance_between_players(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET stones=0 WHERE user_id='u2'")
    reply = play("gift", f"{U2_UID} 灵石 200", op="gift-1")
    assert "已向 UID 10001 赠送灵石 200" in reply.text()
    assert player(game[1], "u1")["stones"] == 800
    assert player(game[1], "u2")["stones"] == 200


def test_gift_material_moves_items(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',5)")
    play("gift", f"{U2_UID} 锻灵矿 2", op="gift-mat")
    assert items(game[1], "u1")["forge_ore"] == 3
    assert items(game[1], "u2")["forge_ore"] == 2


def test_gift_requires_friendship(game, play):
    adopt_both(game, play)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    with pytest.raises(GameError, match="只能向"):
        play("gift", f"{U2_UID} 灵石 100", op="gift-stranger")


def test_gift_rejects_self_and_unknown_uid(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    with pytest.raises(GameError, match="其他玩家"):
        play("gift", f"{U1_UID} 灵石 100", op="gift-self")
    with pytest.raises(GameError, match="其他玩家"):
        play("gift", "99999 灵石 100", op="gift-unknown")


def test_daily_gift_cap_three(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    for index in range(3):
        play("gift", f"{U2_UID} 灵石 100", now=NOW + index, op=f"cap-{index}")
    with pytest.raises(GameError, match="已达 3 次"):
        play("gift", f"{U2_UID} 灵石 100", now=NOW + 3, op="cap-4")


def test_stone_gift_cap_per_operation(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    with pytest.raises(GameError, match="最多 2000"):
        play("gift", f"{U2_UID} 灵石 2001", op="cap-stones")


def test_unequipable_kinds_rejected(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    with pytest.raises(GameError, match="只能赠送"):
        play("gift", f"{U2_UID} 青岚翎 1", op="gift-gear")


def add_second_pet(game, user="u1"):
    """Insert an idle second pet and make it the active one."""
    sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) "
                 "VALUES (?, 'jiaolong', '蛟龙', 1800000000)", (user,))
    sql(game[1], "UPDATE players SET active_pet_id=(SELECT MAX(pet_id) FROM pets WHERE user_id=?) WHERE user_id=?",
        (user, user))


def test_foster_marks_and_return_restores(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    add_second_pet(game)  # pet 2 becomes active; pet 1 idle
    reply = play("foster", f"{U2_UID} 1", op="foster-1")
    assert "已寄养" in reply.text()
    foster_rows = sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='foster_1'")
    assert foster_rows and foster_rows[0]["claimed"] == 1
    back = play("foster_return", "1", user="u2", op="return-1")
    assert "已归还" in back.text()
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='foster_1'") == []


def test_foster_requires_ownership_and_idle(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    with pytest.raises(GameError, match="没有属于你"):
        play("foster", f"{U2_UID} 2", op="foster-other")


def test_foster_feed_consumes_caretaker_food(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    add_second_pet(game)
    play("foster", f"{U2_UID} 1", op="foster-feed-setup")
    sql(game[1], "UPDATE pets SET energy=40 WHERE pet_id=1")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u2','spirit_food',2) "
                 "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity")
    before = items(game[1], "u2")["spirit_food"]
    reply = play("foster_feed", "1", user="u2", op="foster-feed")
    assert "灵粮 -1" in reply.text() or "精力" in reply.text()
    assert items(game[1], "u2")["spirit_food"] == before - 1


def test_foster_feed_rejected_for_non_caretaker(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    add_second_pet(game)
    play("foster", f"{U2_UID} 1", op="foster-feed-setup-2")
    sql(game[1], "UPDATE pets SET energy=40 WHERE pet_id=1")
    play("adopt", "白泽", user="u3")
    with pytest.raises(GameError, match="只有代管方"):
        play("foster_feed", "1", user="u3", op="foster-feed-other")


def test_gift_rejects_malformed_arguments(game, play):
    adopt_both(game, play)
    make_friends_via_arena(game)
    with pytest.raises(GameError, match="格式"):
        play("gift", f"{U2_UID} 灵石", op="gift-malformed")
    with pytest.raises(GameError, match="格式"):
        play("foster", str(U2_UID), op="foster-malformed")
