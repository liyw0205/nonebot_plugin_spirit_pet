import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, sql


def add_pet(store, species_id="qingluan", name="青鸾副宠", *, realm=0, energy=100):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, realm, energy, energy_updated) "
        "VALUES ('u1', ?, ?, ?, ?, 1800000000)",
        (species_id, name, realm, energy),
    )
    return sql(store, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]


def test_same_species_co_training_advances_both_once_and_shares_cooldown(game, play):
    play("adopt", "青鸾")
    partner_id = add_pet(game[1], realm=2)

    reply = play("co_train", str(partner_id), op="co-train")
    assert reply.title == "同族合修"
    assert "只计一次每日修炼任务" in reply.text()
    pets = sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id")
    active, partner = pets
    assert active["exp"] > 0
    assert partner["exp"] == active["exp"] * 3
    assert (active["energy"], partner["energy"]) == (85, 85)
    assert player_last_train(game[1]) == 1_800_000_000
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='train_once'") == [
        {"progress": 1},
    ]

    assert play("co_train", str(partner_id), op="co-train") == reply
    with pytest.raises(GameError, match="调息"):
        play("train", now=1_800_000_001)
    assert [row["energy"] for row in sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")] == [85, 85]


def test_co_training_requires_a_different_same_species_pet(game, play):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    other_species_id = add_pet(game[1], "xuanhu", "玄狐")
    before = sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id")

    with pytest.raises(GameError, match="另一只同族"):
        play("co_train", str(active_id))
    with pytest.raises(GameError, match="同一种族"):
        play("co_train", str(other_species_id))
    assert sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id") == before


def test_co_training_rejects_archived_or_tired_partner_without_cost(game, play):
    play("adopt", "青鸾")
    partner_id = add_pet(game[1])
    play("pet_archive", str(partner_id))
    before = pet(game[1])
    with pytest.raises(GameError, match="已封存"):
        play("co_train", str(partner_id))
    assert pet(game[1]) == before

    play("pet_restore", str(partner_id))
    sql(game[1], "UPDATE pets SET energy=0, energy_updated=1800000000 WHERE pet_id=?", (partner_id,))
    before = sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id")
    with pytest.raises(GameError, match="精力不足"):
        play("co_train", str(partner_id))
    assert sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id") == before


def test_roster_surfaces_co_training_only_when_both_pets_can_act(game, play):
    play("adopt", "青鸾")
    partner_id = add_pet(game[1])

    roster = play("pet_list")
    assert f"灵宠合修 {partner_id}" in roster.commands
    assert f"青鸾副宠（编号 {partner_id}）" in roster.text()

    play("train")
    assert f"灵宠合修 {partner_id}" not in play("pet_list").commands

    sql(game[1], "UPDATE players SET last_train=NULL WHERE user_id='u1'")
    sql(game[1], "UPDATE pets SET energy=0, energy_updated=1800000000 WHERE pet_id=?", (partner_id,))
    assert f"灵宠合修 {partner_id}" not in play("pet_list").commands


def test_roster_hides_co_training_for_partner_on_expedition(game, play):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    partner_id = add_pet(game[1])
    play("switch", str(partner_id))
    play("expedition_start", "采灵药")
    play("switch", str(active_id))

    assert f"灵宠合修 {partner_id}" not in play("pet_list").commands
    before = sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id")
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("co_train", str(partner_id))
    assert sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id") == before


def player_last_train(store):
    return sql(store, "SELECT last_train FROM players WHERE user_id='u1'")[0]["last_train"]
