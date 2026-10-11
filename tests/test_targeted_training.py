import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql


NOW = 1_800_000_000


def add_pet(store, *, user_id="u1", species_id="xuanhu", name="玄狐副宠", energy=100):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, energy, energy_updated) VALUES (?, ?, ?, ?, ?)",
        (user_id, species_id, name, energy, NOW),
    )
    return sql(store, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user_id,))[0]["pet_id"]


def test_numbered_training_targets_roster_pet_and_shares_daily_progress(game, play):
    play("adopt", "青鸾", now=NOW)
    target_id = add_pet(game[1])

    reply = play("train", str(target_id), now=NOW)

    assert reply.title == "吐纳修炼"
    assert f"编号 {target_id}" in reply.text()
    pets = sql(game[1], "SELECT pet_id, exp, energy FROM pets ORDER BY pet_id")
    assert pets[0]["exp"] == 0
    assert pets[0]["energy"] == 100
    assert pets[1]["exp"] > 0
    assert pets[1]["energy"] == 85
    assert player(game[1])["last_train"] == NOW
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='train_once'") == [
        {"progress": 1},
    ]

    with pytest.raises(GameError, match="调息"):
        play("train", now=NOW + 1)
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='train_once'") == [
        {"progress": 1},
    ]


def test_training_non_active_pet_keeps_active_team_readiness(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1])
    play("team_create", now=NOW)
    play("team_ready", now=NOW)

    play("train", str(target_id), now=NOW)

    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]


@pytest.mark.parametrize("pet_id", ["abc", "0", "9223372036854775808", "１２"])
def test_numbered_training_rejects_invalid_or_unowned_ids(game, play, pet_id):
    play("adopt", "青鸾", now=NOW)
    before = pet(game[1]), player(game[1])

    with pytest.raises(GameError, match="有效编号"):
        play("train", pet_id, now=NOW)
    assert (pet(game[1]), player(game[1])) == before


def test_numbered_training_rejects_other_players_archived_and_tired_pets(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    foreign_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
    archived_id = add_pet(game[1], name="封存玄狐")
    tired_id = add_pet(game[1], name="疲惫玄狐", energy=0)
    play("pet_archive", str(archived_id), now=NOW)

    with pytest.raises(GameError, match="没有属于你的在册灵宠"):
        play("train", str(foreign_id), now=NOW)
    with pytest.raises(GameError, match="已封存.*复原"):
        play("train", str(archived_id), now=NOW)
    with pytest.raises(GameError, match="精力不足"):
        play("train", str(tired_id), now=NOW)
    assert player(game[1])["last_train"] is None
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id IN (?, ?)", (archived_id, tired_id)) == [
        {"exp": 0}, {"exp": 0},
    ]


def test_numbered_training_rejects_pet_on_expedition(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1])
    play("switch", str(target_id), now=NOW)
    play("expedition_start", "采灵药", now=NOW)
    play("switch", str(active_id), now=NOW)

    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("train", str(target_id), now=NOW)
    assert player(game[1])["last_train"] is None
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (target_id,)) == [{"exp": 0}]
