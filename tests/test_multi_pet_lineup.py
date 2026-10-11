import json

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql


def test_three_pet_lineup_enters_pve_and_each_pet_pays_energy(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", "2")
    pets = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id")
    species = ("qingluan", "xuanhu", "baize")
    for row, species_id in zip(pets, species):
        sql(game[1], "UPDATE pets SET species_id=?, energy=100 WHERE pet_id=?", (species_id, row["pet_id"]))

    lineup = " ".join(str(row["pet_id"]) for row in pets)
    result = play("lineup", lineup)
    assert "最多出战三只" in result.text()
    assert sql(game[1], "SELECT slot, pet_id FROM active_pet_slots ORDER BY slot") == [
        {"slot": index, "pet_id": row["pet_id"]} for index, row in enumerate(pets, 1)
    ]

    battle = play("challenge", "青岚林", op="three-pet-pve")
    assert battle.title == "秘境获胜"
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='u1' ORDER BY pet_id") == [
        {"energy": 80}, {"energy": 80}, {"energy": 80},
    ]
    record = sql(game[1], "SELECT snapshot FROM battle_records WHERE operation_id='three-pet-pve'")[0]
    snapshot = json.loads(record["snapshot"])
    assert len(snapshot["teams"][0]["members"]) == 3


def test_lineup_rejects_duplicate_species_and_pet_rename_is_unknown(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", "1")
    pets = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id")
    with pytest.raises(GameError, match="重复宠物种类"):
        play("lineup", " ".join(str(row["pet_id"]) for row in pets))
    with pytest.raises(GameError, match="未知指令"):
        play("rename", "新名字")
