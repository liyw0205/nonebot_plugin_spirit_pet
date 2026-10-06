from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql
from .test_loadout import stats


def supply(game, user="u1"):
    for level in game[0].content.forge_levels.values():
        for item_id in level.upgrade_items:
            sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, 1000) "
                "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=1000", (user, item_id))


def prepare(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000000")
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    supply(game)


def worn(game):
    return sql(game[1], "SELECT * FROM equipment ORDER BY pet_id, slot")


def stored(game):
    return sql(game[1], "SELECT * FROM unequipped_equipment WHERE quantity>0 ORDER BY enhancement")


@pytest.mark.parametrize("level", [0, 1, 10])
def test_equipment_view_shows_scaled_bonuses_next_cost_and_action(game, play, level):
    prepare(game, play)
    sql(game[1], "UPDATE equipment SET enhancement=?", (level,))
    reply = play("equipment")
    content = game[0].content
    forge = content.forge_levels[level]
    gear = content.equipment["wind_feather"]
    bonuses = {key: int(value * forge.bonus_multiplier) for key, value in gear.bonuses.model_dump().items()}
    assert f"青岚翎 +{level}" in reply.text()
    for key, label in (("hp", "气血"), ("attack", "攻击"), ("defense", "防御"), ("speed", "速度")):
        assert f"{label} +{bonuses[key]}" in reply.text()
    assert "护甲：未装备" in reply.text()
    assert "灵宠强化 护甲" not in reply.commands
    if forge.upgrade_stones is None:
        assert "已满级" in reply.text()
        assert "灵宠强化 灵器" not in reply.commands
    else:
        assert f"强化至 +{level + 1}：{forge.upgrade_stones} 灵石" in reply.text()
        for key, amount in forge.upgrade_items.items():
            assert f"{content.items[key].name} {amount}" in reply.text()
        assert "灵宠强化 灵器" in reply.commands


@pytest.mark.parametrize("argument", ["灵器", "青岚翎"])
def test_forge_charges_static_cost_and_updates_stats(game, play, argument):
    prepare(game, play)
    before_stats, before_player, before_items = stats(game), player(game[1]), items(game[1])
    cost = game[0].content.forge_levels[0]
    reply = play("enhance", argument)
    assert "青岚翎强化至 +1" in reply.text()
    assert worn(game)[0]["enhancement"] == 1
    assert player(game[1])["stones"] == before_player["stones"] - cost.upgrade_stones
    for key, amount in cost.upgrade_items.items():
        assert items(game[1])[key] == before_items[key] - amount
    assert stats(game).attack > before_stats.attack
    assert "青岚翎 +1" in play("equipment").text()


def test_cannot_forge_empty_slot_unknown_name_or_missing_material(game, play):
    prepare(game, play)
    before = worn(game), player(game[1]), items(game[1])
    for argument in ("护甲", "不存在", ""):
        with pytest.raises(GameError, match="没有装备"):
            play("enhance", argument)
    sql(game[1], "UPDATE inventory SET quantity=0")
    with pytest.raises(GameError, match="不足"):
        play("enhance", "灵器")
    assert worn(game) == before[0]
    assert player(game[1]) == before[1]


def test_insufficient_stones_or_late_material_failure_rolls_back(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE players SET stones=0")
    before = items(game[1]), worn(game)
    with pytest.raises(GameError, match="灵石不足"):
        play("enhance", "灵器")
    assert (items(game[1]), worn(game)) == before
    sql(game[1], "UPDATE players SET stones=10000")
    content = game[0].content
    levels = dict(content.forge_levels)
    levels[0] = levels[0].model_copy(update={"upgrade_items": {"spirit_food": 1, "bloodline_essence": 9999}})
    game[0].content = replace(content, forge_levels=levels)
    before = items(game[1]), worn(game), player(game[1])
    with pytest.raises(GameError, match="不足"):
        play("enhance", "灵器")
    assert (items(game[1]), worn(game), player(game[1])) == before


def test_forge_cap_does_not_consume_resources(game, play):
    prepare(game, play)
    top = max(game[0].content.forge_levels)
    sql(game[1], "UPDATE equipment SET enhancement=?", (top,))
    before = worn(game), player(game[1]), items(game[1])
    with pytest.raises(GameError, match="最高强化"):
        play("enhance", "灵器")
    assert (worn(game), player(game[1]), items(game[1])) == before


def test_unwear_and_rewear_preserves_enhancement_without_copying(game, play):
    prepare(game, play)
    play("enhance", "灵器")
    enhanced_stats = stats(game)
    play("unequip", "灵器", op="unwear-upgraded")
    play("unequip", "灵器", op="unwear-upgraded")
    assert not worn(game)
    assert stored(game)[0]["enhancement"] == 1
    assert stored(game)[0]["quantity"] == 1
    assert items(game[1])["wind_feather"] == 0
    play("equipment", "青岚翎")
    assert stats(game) == enhanced_stats
    assert worn(game)[0]["enhancement"] == 1
    assert not stored(game)


def test_swapping_different_and_same_items_preserves_each_level(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE pets SET species_id='sanlinglu'")
    play("enhance", "灵器")
    play("buy", "赤焰牙")
    play("equipment", "赤焰牙")
    assert worn(game)[0]["enhancement"] == 0
    assert stored(game)[0]["item_id"] == "wind_feather"
    assert stored(game)[0]["enhancement"] == 1
    play("equipment", "青岚翎")
    assert items(game[1])["fire_fang"] == 1
    sql(game[1], "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) "
        "VALUES ('u1', 'wind_feather', 2, 1)")
    play("equipment", "青岚翎")
    assert worn(game)[0]["enhancement"] == 2
    assert stored(game)[0]["enhancement"] == stored(game)[0]["quantity"] == 1
    with pytest.raises(GameError, match="已经装备"):
        play("equipment", "青岚翎")


def test_highest_owned_upgrade_selected_without_using_plain_copy(game, play):
    prepare(game, play)
    play("unequip", "灵器")
    for level in (1, 3, 2):
        sql(game[1], "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) "
            "VALUES ('u1', 'wind_feather', ?, 1)", (level,))
    play("equipment", "青岚翎")
    assert worn(game)[0]["enhancement"] == 3
    assert [row["enhancement"] for row in stored(game)] == [1, 2]
    assert items(game[1])["wind_feather"] == 1


def test_enhancement_is_owned_by_equipment_not_pet_or_player(game, play):
    prepare(game, play)
    play("enhance", "灵器")
    play("unequip", "灵器")
    play("summon")
    second = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    play("switch", str(second))
    play("equipment", "青岚翎")
    assert worn(game)[0]["pet_id"] == second
    assert worn(game)[0]["enhancement"] == 1
    play("adopt", "青鸾", user="u2")
    with pytest.raises(GameError, match="不足"):
        play("equipment", "青岚翎", user="u2")
    assert len(worn(game)) == 1


def test_forging_invalidates_team_readiness_and_redelivery_is_atomic(game, play):
    prepare(game, play)
    play("team_create")
    play("team_ready")
    before = player(game[1])["stones"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(
            lambda _: game[0].execute("u1", "enhance", "灵器", "same-forge", 1_800_000_000), range(8),
        ))
    assert all(reply == replies[0] for reply in replies)
    assert worn(game)[0]["enhancement"] == 1
    assert player(game[1])["stones"] == before - game[0].content.forge_levels[0].upgrade_stones
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


def test_concurrent_distinct_forges_cannot_overspend(game, play):
    prepare(game, play)
    cost = game[0].content.forge_levels[0].upgrade_stones
    sql(game[1], "UPDATE players SET stones=?", (cost,))

    def forge(index):
        try:
            game[0].execute("u1", "enhance", "灵器", f"forge-race-{index}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(forge, range(8))) == 1
    assert worn(game)[0]["enhancement"] == 1
    assert player(game[1])["stones"] == 0
