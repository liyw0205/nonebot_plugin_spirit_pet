import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import pet_stats
from nonebot_plugin_spirit_pet.domain.state import Pet

from .support import items, pet, player, sql


def rich(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=100000")
    sql(game[1], "UPDATE pets SET exp=100000")


def test_all_ten_layers_and_major_transition(game, play):
    rich(game, play)
    for level in range(2, 11):
        assert play("breakthrough").title == "小境界突破成功"
        assert pet(game[1])["layer"] == level
        assert pet(game[1])["realm"] == 0
    reply = play("breakthrough")
    assert reply.title == "大境界破境成功"
    assert (pet(game[1])["realm"], pet(game[1])["layer"]) == (1, 1)
    assert "凝气 1层" in play("status").text()


def test_minor_cost_scales_with_major_realm(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET realm=2, layer=1, exp=90")
    before = player(game[1])["stones"]
    play("breakthrough")
    assert pet(game[1])["exp"] == 0
    assert player(game[1])["stones"] == before - 30


def test_major_failure_and_assisting_pill(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET layer=10, exp=100")
    game[0].rng.random = lambda: 0.95
    before = player(game[1])["stones"]
    assert play("breakthrough").title == "破境未成"
    assert pet(game[1])["exp"] == 75
    assert pet(game[1])["layer"] == 10
    assert player(game[1])["stones"] == before - 50
    play("buy", "破境丹")
    sql(game[1], "UPDATE pets SET exp=100")
    assert play("breakthrough", "破境丹").title == "大境界破境成功"
    assert items(game[1])["breakthrough_pill"] == 0


def test_pill_not_spent_on_small_breakthrough_or_insufficient_exp(game, play):
    rich(game, play)
    play("buy", "破境丹")
    with pytest.raises(GameError, match="无需"):
        play("breakthrough", "破境丹")
    sql(game[1], "UPDATE pets SET exp=0, layer=10")
    with pytest.raises(GameError):
        play("breakthrough", "破境丹")
    assert items(game[1])["breakthrough_pill"] == 1


def test_max_realm_can_still_advance_to_tenth_layer(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET realm=6, layer=9")
    play("breakthrough")
    assert pet(game[1])["layer"] == 10
    with pytest.raises(GameError, match="最高境界"):
        play("breakthrough")


def test_bloodline_consumes_material_and_increases_stats_idempotently(game, play):
    rich(game, play)
    play("buy", "血脉精华 3")
    before = pet_stats(Pet(**pet(game[1])), game[0].content)
    reply = play("evolve", op="evolution")
    assert play("evolve", op="evolution") == reply
    after = pet_stats(Pet(**pet(game[1])), game[0].content)
    assert after.attack > before.attack
    assert pet(game[1])["bloodline"] == 1
    assert items(game[1])["bloodline_essence"] == 0
    assert pet(game[1])["exp"] == 99900


def test_missing_evolution_material_rolls_back_all_resources(game, play):
    rich(game, play)
    initial = player(game[1]), pet(game[1]), items(game[1])
    with pytest.raises(GameError):
        play("evolve")
    assert (player(game[1]), pet(game[1]), items(game[1])) == initial


def test_highest_bloodline_refuses_without_spending(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET bloodline=4")
    before = player(game[1]), pet(game[1])
    with pytest.raises(GameError, match="最高血脉"):
        play("evolve")
    assert (player(game[1]), pet(game[1])) == before


def test_daily_quests_claim_once_and_reset_without_clock_rewind(game, play):
    play("adopt", now=1000)
    play("train", now=1000)
    first = play("claim", "吐纳一周天", now=1000, op="claim")
    assert play("claim", "吐纳一周天", now=1000, op="claim") == first
    assert player(game[1])["stones"] == 150
    with pytest.raises(GameError, match="已领取"):
        play("claim", "吐纳一周天", now=1001)
    play("quests", now=1000 + 86400)
    with pytest.raises(GameError, match="尚未完成"):
        play("claim", "吐纳一周天", now=1000 + 86400)
    next_day = player(game[1])["quest_day"]
    play("quests", now=1000)
    assert player(game[1])["quest_day"] == next_day
