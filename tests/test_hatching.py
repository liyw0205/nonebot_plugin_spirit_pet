from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql


def egg_for(game):
    return next(item for item in game[0].content.items.values() if item.kind == "pet_egg")


def grant_eggs(game, egg, count):
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, ?)", (egg.id, count))


def test_eggs_create_independent_pets_without_switching_active_pet(game, play):
    play("adopt", "青鸾")
    original = pet(game[1])
    owner = player(game[1])
    egg = egg_for(game)
    species = game[0].content.species[egg.species_id]
    grant_eggs(game, egg, 3)
    reply = play("use", f"{egg.name} 2", op="hatch")
    assert reply.title == "灵卵孵化"
    assert play("use", f"{egg.name} 2", op="hatch") == reply
    hatched = sql(game[1], "SELECT * FROM pets WHERE pet_id<>?", (original["pet_id"],))
    assert len(hatched) == 2
    assert len({row["pet_id"] for row in hatched}) == 2
    for row in hatched:
        assert row["species_id"] == species.id
        assert row["name"] == species.name
        assert (row["realm"], row["layer"], row["bloodline"], row["exp"]) == (0, 1, 0, 0)
        assert row["energy"] == 100
        assert row["affinity"] == species.initial_affinity
        assert row["energy_updated"] == 1_800_000_000
    assert items(game[1])[egg.id] == 1
    assert pet(game[1]) == original
    assert player(game[1]) == owner
    assert not sql(game[1], "SELECT * FROM learned_skills")
    assert not sql(game[1], "SELECT * FROM equipment")


def test_capacity_failure_does_not_consume_eggs(game, play):
    play("adopt")
    egg = egg_for(game)
    grant_eggs(game, egg, 2)
    game[0].config.spirit_pet_max_pets = 2
    with pytest.raises(GameError, match="容量不足"):
        play("use", f"{egg.id} 2")
    assert items(game[1])[egg.id] == 2
    assert len(sql(game[1], "SELECT * FROM pets")) == 1
    assert play("use", egg.id).title == "灵卵孵化"


def test_insufficient_eggs_does_not_create_partial_pets(game, play):
    play("adopt")
    egg = egg_for(game)
    grant_eggs(game, egg, 1)
    with pytest.raises(GameError):
        play("use", f"{egg.id} 2")
    assert items(game[1])[egg.id] == 1
    assert len(sql(game[1], "SELECT * FROM pets")) == 1


@pytest.mark.parametrize("amount", ["0", "-1", "1.5", "100"])
def test_invalid_hatching_amount_does_not_consume(game, play, amount):
    play("adopt")
    egg = egg_for(game)
    grant_eggs(game, egg, 1)
    with pytest.raises(GameError):
        play("use", f"{egg.id} {amount}")
    assert items(game[1])[egg.id] == 1


def test_hatching_redelivery_is_atomic_under_concurrency(game, play):
    play("adopt")
    egg = egg_for(game)
    grant_eggs(game, egg, 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: play("use", egg.id, op="same-egg"), range(8)))
    assert all(reply == replies[0] for reply in replies)
    assert items(game[1])[egg.id] == 0
    assert len(sql(game[1], "SELECT * FROM pets")) == 2


def test_pve_egg_drop_can_be_hatched(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    dungeon = next(dungeon for dungeon in content.dungeons.values() if not dungeon.team and any(
        content.items[item_id].kind == "pet_egg" and amount.maximum > 0
        for item_id, amount in dungeon.reward.items.items()
    ))
    sql(game[1], "UPDATE pets SET realm=6, layer=10, bloodline=4")
    game[0].rng.randint = lambda start, stop: stop
    assert play("challenge", dungeon.id).title == "秘境获胜"
    egg = next(content.items[item_id] for item_id in dungeon.reward.items
               if content.items[item_id].kind == "pet_egg")
    assert items(game[1])[egg.id] > 0
    assert play("use", egg.name).title == "灵卵孵化"
    assert sql(game[1], "SELECT * FROM pets WHERE species_id=?", (egg.species_id,))


def test_only_original_four_species_can_be_starters(game, play):
    for species in game[0].content.species.values():
        if not species.starter:
            with pytest.raises(GameError):
                play("adopt", species.name)
    assert not sql(game[1], "SELECT * FROM players")
