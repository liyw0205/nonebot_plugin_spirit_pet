import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql
from .test_arena_matching import NOW, register
from .test_battles import setup_team

SPECIES = ("qingluan", "xuanhu", "baize")


def roster(game, play, user="u1"):
    """Give one player three distinct-species pets at full energy and return the ids."""
    sql(game[1], "UPDATE players SET stones=stones+10000 WHERE user_id=?", (user,))
    play("summon", "2", user=user)
    rows = sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))
    for row, species_id in zip(rows, SPECIES):
        sql(game[1], "UPDATE pets SET species_id=?, energy=100 WHERE pet_id=?", (species_id, row["pet_id"]))
    return [row["pet_id"] for row in rows]


def test_three_pet_solo_dungeon_grants_one_reward_set(game, play):
    play("adopt", "青鸾")
    pet_ids = roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    stones_before, items_before = player(game[1])["stones"], items(game[1])

    result = play("challenge", "青岚林", op="lineup-pve")

    assert result.title == "秘境获胜"
    # 固定随机源取区间下限：每位成员一场只结算一份掉落，与出战宠物数量无关。
    assert player(game[1])["stones"] - stones_before == 40
    assert items(game[1]).get("forge_ore", 0) - items_before.get("forge_ore", 0) == 1
    assert items(game[1]).get("bloodline_essence", 0) - items_before.get("bloodline_essence", 0) == 1
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='u1' ORDER BY pet_id") == [
        {"energy": 80}, {"energy": 80}, {"energy": 80},
    ]


def test_three_pet_leader_gets_one_reward_set_in_team_dungeon(game, play):
    setup_team(game, play)
    pet_ids = roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    before = {user: (player(game[1], user)["stones"], items(game[1], user)) for user in ("u1", "u2")}
    play("team_ready")
    play("team_ready", user="u2")

    result = play("team_challenge", op="lineup-team")

    assert result.title == "秘境获胜"
    for user in ("u1", "u2"):
        stones, owned = before[user]
        assert player(game[1], user)["stones"] - stones == 90
        assert items(game[1], user).get("bloodline_essence", 0) - owned.get("bloodline_essence", 0) == 1


def test_ranked_pvp_rejects_lineup_spanning_realms(game, play):
    register(game, play)
    pet_ids = roster(game, play, user="private-0")
    sql(game[1], "UPDATE pets SET realm=1, energy=100 WHERE user_id='private-0'")
    sql(game[1], "UPDATE pets SET realm=2 WHERE pet_id=?", (pet_ids[-1],))
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids), user="private-0")

    with pytest.raises(GameError, match="同一大境界"):
        play("pvp", "道友01", user="private-0", now=NOW)
    with pytest.raises(GameError, match="同一大境界"):
        play("match", user="private-0", now=NOW)
    assert not sql(game[1], "SELECT * FROM pvp_results")


def test_mixed_realm_defender_is_rejected_and_hidden_from_matching(game, play):
    register(game, play)
    pet_ids = roster(game, play, user="private-1")
    sql(game[1], "UPDATE pets SET realm=1 WHERE user_id='private-1'")
    sql(game[1], "UPDATE pets SET realm=2 WHERE pet_id=?", (pet_ids[-1],))
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids), user="private-1")

    match = play("match", user="private-0", now=NOW)
    assert "灵宠论剑 道友01" not in match.commands
    assert "灵宠论剑 道友02" in match.commands
    with pytest.raises(GameError, match="不同大境界"):
        play("pvp", "道友01", user="private-0", now=NOW)
    assert not sql(game[1], "SELECT * FROM pvp_results")
