import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import pet, player, sql


NOW = 1_800_000_000


def add_pet(store, *, name="玄狐副宠", energy=50):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, energy, energy_updated) "
        "VALUES ('u1', 'xuanhu', ?, ?, ?)",
        (name, energy, NOW),
    )
    return sql(store, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]


def create_ready_team(play, store):
    active_id = pet(store)["pet_id"]
    play("team_create", now=NOW)
    play("team_ready", now=NOW)
    assert sql(store, "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]
    return active_id


def test_numbered_feed_only_changes_selected_pet_and_keeps_team_ready(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])

    reply = play("feed", str(target_id), now=NOW)

    assert "灵粮 -1，精力 +20，修为 +10，亲密 +5" in reply.text()
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (active_id,)) == [
        {"energy": 100, "exp": 0, "affinity": 0},
    ]
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"energy": 70, "exp": 10, "affinity": 5},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'") == [
        {"quantity": 2},
    ]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]


def test_numbered_bond_uses_player_daily_limit_and_preserves_active_readiness(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])

    reply = play("bond", str(target_id), now=NOW)

    assert "亲密 +2（2/100）" in reply.text()
    assert pet(game[1])["affinity"] == 0
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"affinity": 2},
    ]
    assert player(game[1])["last_bond_day"] == beijing_day(NOW)
    assert player(game[1])["current_bond_streak"] == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_once'") == [
        {"progress": 1},
    ]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond", now=NOW)


def test_numbered_bond_rejects_target_on_expedition_without_using_daily_interaction(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1])
    play("switch", str(target_id), now=NOW)
    play("expedition_start", "采灵药", now=NOW)
    play("switch", str(active_id), now=NOW)

    with pytest.raises(GameError, match="当前不能行动"):
        play("bond", str(target_id), now=NOW)
    assert player(game[1])["last_bond_day"] == ""
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"affinity": 0},
    ]
