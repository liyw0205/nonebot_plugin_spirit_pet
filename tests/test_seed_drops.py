import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000


def force_seed_drop(game):
    """The seed roll is randint(1,100) <= percent; force a hit without breaking
    battle target/damage rolls that use other ranges."""
    original = game[0].rng.randint
    game[0].rng.randint = lambda start, stop: (
        start if start == 1 and stop == 100 else original(start, stop)
    )


def test_ambush_victory_drops_route_seed(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_seed_drop(game)
    # Ambush roll also uses randint; both hit, so ambush fires and seed drops.
    play("explore", "灵泉修行", now=NOW + 1, op="seed-ambush")
    assert items(game[1]).get("seed_spirit_rice", 0) == 1


def test_dungeon_victory_drops_realm_seed(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_seed_drop(game)
    # All randint returns start=1: minimum damage both sides. Boost via bloodline
    # and realm so the seeded pet outlasts wood_guard (240 hp vs low enemy damage).
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")
    play("challenge", "青岚林", now=NOW + 1, op="seed-dungeon")
    assert items(game[1]).get("seed_spirit_rice", 0) == 1


def test_sweep_drops_realm_seed(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100, bloodline=4, layer=10")
    force_seed_drop(game)
    play("challenge", "青岚林", now=NOW + 1, op="sweep-seed-clear")
    before = items(game[1]).get("seed_spirit_rice", 0)
    sql(game[1], "UPDATE pets SET energy=100")
    play("sweep", "青岚林", now=NOW + 1 + 900, op="sweep-seed")
    assert items(game[1]).get("seed_spirit_rice", 0) == before + 1


def test_expedition_claim_snapshot_includes_seed(game, play):
    play("adopt", "青鸾", now=NOW)
    force_seed_drop(game)
    play("expedition_start", "采灵药", now=NOW, op="seed-exp")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    snapshot = sql(game[1], "SELECT reward_snapshot FROM expeditions")[0]["reward_snapshot"]
    assert "seed_" in snapshot
    result = play("expedition_claim", str(job_id), now=NOW + 3600, op="seed-exp-claim")
    assert "灵稻种 +1" in result.text()
    assert items(game[1]).get("seed_spirit_rice", 0) == 1


def test_seed_drop_miss_leaves_inventory_untouched(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    # Force the seed roll to miss (randint returns stop=100 > 25).
    game[0].rng.randint = lambda start, stop: stop
    game[0].rng.random = lambda: 0.99  # skip ambush, pick encounter
    play("explore", "灵泉修行", now=NOW + 1, op="seed-miss")
    assert items(game[1]).get("seed_spirit_rice", 0) == 0


def test_seeds_are_materials_and_recyclable(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "灵稻种 1", now=NOW, op="seed-buy")
    assert items(game[1])["seed_spirit_rice"] == 1
    before = player(game[1])["stones"]
    play("recycle", "灵稻种 1", now=NOW + 1, op="seed-recycle")
    # 40 * 40% = 16 stones back.
    assert player(game[1])["stones"] == before + 16
    assert items(game[1]).get("seed_spirit_rice", 0) == 0


def test_shop_lists_seeds(game, play):
    listing = play("shop", "灵稻种", now=NOW)
    assert "售价：40 灵石" in listing.text()
    detail = play("shop", "蕴灵穗种", now=NOW)
    assert "售价：150 灵石" in detail.text()


def test_bag_groups_seeds_under_materials(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "灵稻种 2", now=NOW, op="bag-seed")
    bag = play("bag", now=NOW + 1)
    assert "灵稻种：2" in bag.text()


def test_seed_planting_closes_the_loop(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="loop-open")
    play("buy", "灵稻种 1", now=NOW, op="loop-buy")
    play("farm_plant", "1 灵稻种", now=NOW + 1, op="loop-plant")
    result = play("farm_harvest", "1", now=NOW + 1 + 1800, op="loop-harvest")
    assert "灵粮 +3" in result.text()
