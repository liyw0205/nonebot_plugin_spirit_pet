from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.crafting_validation import validate_crafting_content
from nonebot_plugin_spirit_pet.domain.crafting_content import Recipe, salvage_yield
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql


def prepare(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000000")
    for key in ("forge_ore", "bloodline_essence"):
        sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, 1000) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=1000", (key,))


def stored(game, item_id="wind_feather", enhancement=0, user="u1"):
    if enhancement:
        rows = sql(game[1], "SELECT quantity FROM unequipped_equipment "
                   "WHERE user_id=? AND item_id=? AND enhancement=?", (user, item_id, enhancement))
    else:
        rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user, item_id))
    return rows[0]["quantity"] if rows else 0


def content_with_recipe(content, **changes):
    recipes = dict(content.recipes)
    recipes["wind_feather"] = recipes["wind_feather"].model_copy(update=changes)
    return replace(content, recipes=recipes)


def test_all_equipment_has_a_resource_losing_recipe(game):
    content = game[0].content
    assert len(content.recipes) == len(content.equipment) == 14
    assert {recipe.item_id for recipe in content.recipes.values()} == {
        item.id for item in content.items.values() if item.kind == "equipment"
    }
    for recipe in content.recipes.values():
        assert recipe.stones > 0
        assert 0 <= recipe.enhancement_refund_percent <= 50
        invested = dict(recipe.materials)
        for level in content.forge_levels:
            if level:
                for key, amount in content.forge_levels[level - 1].upgrade_items.items():
                    invested[key] = invested.get(key, 0) + amount
            returned = salvage_yield(recipe, content.forge_levels, level)
            assert all(amount <= invested.get(key, 0) for key, amount in returned.items())
            assert any(returned.get(key, 0) < amount for key, amount in invested.items())


def test_workshop_pages_detail_and_refund_preview_are_read_only(game, play):
    prepare(game, play)
    before = player(game[1]), items(game[1])
    first = play("recipe_catalog")
    assert first.title == "百工灵谱 1/3"
    assert len(first.lines) == 5
    assert "灵宠工坊 2" in first.commands
    last = play("recipe_catalog", "3")
    assert len(last.lines) == 4
    assert "灵宠工坊 2" in last.commands
    assert "灵宠工坊 4" not in last.commands
    detail = play("recipe_catalog", "青岚翎 +3")
    assert "打造一件 +0：40 灵石、锻灵矿 2" in detail.text()
    assert "分解一件 +3：锻灵矿 4" in detail.text()
    assert "50%" in detail.text() and "+10" in detail.text()
    assert "灵宠分解 青岚翎 +3" in detail.commands
    assert (player(game[1]), items(game[1])) == before
    with pytest.raises(GameError, match="共 3 页"):
        play("recipe_catalog", "4")
    with pytest.raises(GameError, match="等级"):
        play("recipe_catalog", "青岚翎 +11")


def test_batch_crafting_and_salvage_spend_resources_and_never_refund_stones(game, play):
    prepare(game, play)
    before = player(game[1]), items(game[1])
    recipe = game[0].content.recipes["wind_feather"]
    crafted = play("craft", "青岚翎 3", op="craft-batch")
    assert play("craft", "青岚翎 3", op="craft-batch") == crafted
    assert stored(game) == 3
    assert player(game[1])["stones"] == before[0]["stones"] - recipe.stones * 3
    after_craft = player(game[1])["stones"]
    recycled = play("salvage", "青岚翎 2", op="salvage-batch")
    assert play("salvage", "青岚翎 2", op="salvage-batch") == recycled
    assert stored(game) == 1
    assert player(game[1])["stones"] == after_craft
    assert stored(game, "forge_ore") == before[1]["forge_ore"] - recipe.materials["forge_ore"] * 3 + 2
    assert "不返还灵石" in recycled.text()


def test_full_material_loop_craft_equip_forge_unequip_salvage(game, play):
    prepare(game, play)
    play("craft", "青岚翎")
    play("equipment", "青岚翎")
    for _ in range(3):
        play("enhance", "灵器")
    with pytest.raises(GameError, match="已穿戴"):
        play("salvage", "青岚翎 +3")
    play("unequip", "灵器")
    before = player(game[1]), items(game[1])
    play("salvage", "青岚翎 +3")
    assert stored(game, enhancement=3) == 0
    assert player(game[1]) == before[0]
    assert stored(game, "forge_ore") == before[1]["forge_ore"] + 4


def test_default_salvage_does_not_touch_upgraded_or_equipped_pieces(game, play):
    prepare(game, play)
    play("craft", "青岚翎 2")
    play("equipment", "青岚翎")
    play("enhance", "灵器")
    play("unequip", "灵器")
    assert stored(game) == stored(game, enhancement=1) == 1
    play("salvage", "青岚翎")
    assert stored(game) == 0 and stored(game, enhancement=1) == 1
    before = items(game[1])
    with pytest.raises(GameError, match="显式"):
        play("salvage", "青岚翎")
    assert items(game[1]) == before
    play("equipment", "青岚翎")
    worn = sql(game[1], "SELECT * FROM equipment")
    with pytest.raises(GameError, match="已穿戴"):
        play("salvage", "青岚翎 +1")
    assert sql(game[1], "SELECT * FROM equipment") == worn


def test_batch_salvage_rounds_per_piece_and_preserves_other_grades(game, play):
    prepare(game, play)
    for level in (1, 3):
        sql(game[1], "INSERT INTO unequipped_equipment VALUES ('u1', 'wind_feather', ?, 3)", (level,))
    before = stored(game, "forge_ore")
    play("salvage", "青岚翎 +1 2")
    assert stored(game, "forge_ore") == before + 2
    assert stored(game, enhancement=1) == 1
    assert stored(game, enhancement=3) == 3
    play("salvage", "青岚翎 +3 2")
    assert stored(game, "forge_ore") == before + 2 + 8
    assert stored(game, enhancement=3) == 1


def test_max_level_refund_is_capped_at_static_cumulative_materials(game, play):
    prepare(game, play)
    content = game[0].content
    maximum = max(content.forge_levels)
    recipe = content.recipes["wind_feather"]
    assert salvage_yield(recipe, content.forge_levels, maximum) == {"forge_ore": 28}
    for invalid in (-1, maximum + 1, True):
        with pytest.raises(ValueError, match="unsupported"):
            salvage_yield(recipe, content.forge_levels, invalid)
    before = items(game[1])
    with pytest.raises(GameError, match="等级"):
        play("salvage", "青岚翎 +11")
    assert items(game[1]) == before


def test_crafting_late_material_failure_and_no_stones_roll_back(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='bloodline_essence'")
    before = player(game[1]), items(game[1])
    with pytest.raises(GameError, match="不足"):
        play("craft", "龙鳞甲")
    assert (player(game[1]), items(game[1])) == before
    assert stored(game, "dragon_scale") == 0
    sql(game[1], "UPDATE players SET stones=0")
    with pytest.raises(GameError, match="灵石不足"):
        play("craft", "青岚翎")
    assert items(game[1]) == before[1]


@pytest.mark.parametrize("action,argument", [
    ("craft", "青岚翎 0"), ("craft", "青岚翎 100"), ("craft", "青岚翎 -1"),
    ("craft", "青岚翎 1 2"), ("salvage", "青岚翎 +1 0"), ("salvage", "青岚翎 100"),
    ("salvage", "青岚翎 2 +1"), ("salvage", "青岚翎 +1 1 1"),
    ("salvage", "青岚翎 +-1"), ("salvage", "青岚翎 +999"),
    ("recipe_catalog", "青岚翎 +1 1"), ("recipe_catalog", "青岚翎 1"),
    ("craft", "灵粮"), ("salvage", "锻灵矿"), ("salvage", ""),
])
def test_invalid_crafting_input_never_changes_state(game, play, action, argument):
    prepare(game, play)
    before = player(game[1]), items(game[1])
    with pytest.raises(GameError):
        play(action, argument)
    assert (player(game[1]), items(game[1])) == before


def test_quantity_upper_bound_is_usable(game, play):
    prepare(game, play)
    play("craft", "青岚翎 99")
    assert stored(game) == 99
    play("salvage", "青岚翎 +0 99")
    assert stored(game) == 0


def test_salvage_never_uses_another_players_inventory(game, play):
    prepare(game, play)
    play("craft", "青岚翎")
    play("adopt", "青鸾", user="u2")
    with pytest.raises(GameError, match="不足"):
        play("salvage", "青岚翎", user="u2")
    assert stored(game) == 1
    assert stored(game, user="u2") == 0


def test_concurrent_crafting_and_salvage_cannot_copy_materials(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE inventory SET quantity=2 WHERE item_id='forge_ore'")

    def run(action, index):
        try:
            game[0].execute("u1", action, "青岚翎", f"{action}-{index}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda index: run("craft", index), range(8))) == 1
    assert stored(game) == 1 and stored(game, "forge_ore") == 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda index: run("salvage", index), range(8))) == 1
    assert stored(game) == 0 and stored(game, "forge_ore") == 1


@pytest.mark.parametrize("field", ["created_at", "cooldown", "last_login", "finish_at"])
def test_recipe_rejects_runtime_fields(game, field):
    data = game[0].content.recipes["wind_feather"].model_dump()
    data[field] = 123
    with pytest.raises(ValidationError, match="Extra inputs"):
        Recipe.model_validate(data)


@pytest.mark.parametrize("changes", [
    {"stones": 0}, {"materials": {}}, {"salvage_materials": {}},
    {"enhancement_refund_percent": 51}, {"enhancement_refund_percent": -1},
    {"enhancement_refund_percent": "50"}, {"materials": {"forge_ore": 0}},
])
def test_recipe_values_are_strictly_validated(game, changes):
    data = game[0].content.recipes["wind_feather"].model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


@pytest.mark.parametrize("changes,match", [
    ({"materials": {"unknown": 2}}, "unknown crafting"),
    ({"materials": {"spirit_food": 2}}, "must be materials"),
    ({"salvage_materials": {"forge_ore": 2}}, "strictly fewer"),
    ({"salvage_materials": {"forge_ore": 3}}, "strictly fewer"),
    ({"salvage_materials": {"bloodline_essence": 1}}, "strictly fewer"),
    ({"name": "错误装备"}, "names must match"),
])
def test_invalid_crafting_links_or_material_profits_rejected(game, changes, match):
    with pytest.raises(ValueError, match=match):
        validate_crafting_content(content_with_recipe(game[0].content, **changes))


def test_missing_duplicate_and_unreachable_recipes_fail_validation(game):
    content = game[0].content
    recipes = dict(content.recipes)
    recipes.pop("fire_fang")
    with pytest.raises(ValueError, match="exactly once"):
        validate_crafting_content(replace(content, recipes=recipes))
    with pytest.raises(ValueError, match="exactly once"):
        validate_crafting_content(content_with_recipe(content, item_id="fire_fang"))
    definitions = dict(content.items)
    definitions["isolated"] = definitions["forge_ore"].model_copy(update={
        "id": "isolated", "name": "隔绝矿", "price": None,
    })
    unavailable = content_with_recipe(replace(content, items=definitions), materials={"forge_ore": 2, "isolated": 1})
    with pytest.raises(ValueError, match="acquisition source"):
        validate_crafting_content(unavailable)


def test_shop_salvage_arbitrage_rejected_even_if_recipe_itself_loses_materials(game):
    content = game[0].content
    definitions = dict(content.items)
    definitions["wind_feather"] = definitions["wind_feather"].model_copy(update={"price": 1})
    with pytest.raises(ValueError, match="cheaper materials"):
        validate_crafting_content(replace(content, items=definitions))
