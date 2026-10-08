import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql


NOW = 1_800_000_000


def add_pet(store, *, name="玄狐副宠", species_id="xuanhu", exp=0):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, exp, energy_updated) VALUES ('u1', ?, ?, ?, ?)",
        (species_id, name, exp, NOW),
    )
    return sql(store, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]


def ready_active_pet(play, store, active_id):
    play("team_create", now=NOW)
    play("team_ready", now=NOW)
    assert sql(store, "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]


def test_numbered_breakthrough_advances_only_selected_pet(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1], exp=100)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    ready_active_pet(play, game[1], active_id)
    stones_before = player(game[1])["stones"]

    reply = play("breakthrough", str(target_id), now=NOW)

    assert reply.title == "小境界突破成功"
    active = sql(game[1], "SELECT exp, layer FROM pets WHERE pet_id=?", (active_id,))[0]
    target = sql(game[1], "SELECT exp, layer FROM pets WHERE pet_id=?", (target_id,))[0]
    assert active == {"exp": 0, "layer": 1}
    assert target == {"exp": 70, "layer": 2}
    assert player(game[1])["stones"] == stones_before - 10
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='breakthrough_once'") == [
        {"progress": 1},
    ]


def test_numbered_breakthrough_keeps_pill_argument_compatibility(game, play):
    play("adopt", "青鸾", now=NOW)
    target_id = add_pet(game[1], exp=1000)
    sql(game[1], "UPDATE pets SET layer=10 WHERE pet_id=?", (target_id,))
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','breakthrough_pill',1)")

    reply = play("breakthrough", f"{target_id} 破境丹", now=NOW)

    assert reply.title == "大境界破境成功"
    assert sql(game[1], "SELECT realm, layer FROM pets WHERE pet_id=?", (target_id,)) == [
        {"realm": 1, "layer": 1},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='breakthrough_pill'") == [
        {"quantity": 0},
    ]


def test_numbered_evolution_spends_selected_pet_exp_and_shared_resources(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1], exp=1000)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','bloodline_essence',3)")
    ready_active_pet(play, game[1], active_id)
    stones_before = player(game[1])["stones"]

    reply = play("evolve", str(target_id), now=NOW)

    assert reply.title == "血脉觉醒"
    assert sql(game[1], "SELECT bloodline, exp FROM pets WHERE pet_id=?", (active_id,))[0] == {
        "bloodline": 0, "exp": 0,
    }
    assert sql(game[1], "SELECT bloodline, exp FROM pets WHERE pet_id=?", (target_id,))[0] == {
        "bloodline": 1, "exp": 900,
    }
    assert player(game[1])["stones"] == stones_before - 200
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='bloodline_essence'") == [
        {"quantity": 0},
    ]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]


@pytest.mark.parametrize("action", ["breakthrough", "evolve"])
def test_numbered_progression_rejects_archived_pet(game, play, action):
    play("adopt", "青鸾", now=NOW)
    target_id = add_pet(game[1])
    play("pet_archive", str(target_id), now=NOW)

    with pytest.raises(GameError, match="已封存.*复原"):
        play(action, str(target_id), now=NOW)

    assert player(game[1])["last_train"] is None
    assert sql(game[1], "SELECT realm, layer, bloodline, exp FROM pets WHERE pet_id=?", (target_id,)) == [
        {"realm": 0, "layer": 1, "bloodline": 0, "exp": 0},
    ]
