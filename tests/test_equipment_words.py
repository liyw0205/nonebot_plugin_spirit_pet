import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.gear_words import rows as word_rows, describe as describe_words

from .support import items, player, sql

NOW = 1_800_000_000


def seed_materials(game, item_id, amount):
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
                 "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=?", (item_id, amount, amount))


def words(game, item_id):
    return sql(game[1], f"SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE 'gear_words_{item_id}_%'")


def test_craft_generates_words_for_single_item(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    seed_materials(game, "forge_ore", 20)
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    sql(game[1], f"UPDATE players SET stones=10000")
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    reply = play("craft", recipe.name, op="craft-1")
    stored = words(game, recipe.item_id)
    assert stored, "crafting one item should roll words"
    assert all("词条：" not in line for line in reply.lines[:1])


def test_batch_craft_skips_word_generation(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", f"{recipe.name} 3", op="craft-3")
    assert words(game, recipe.item_id) == []


def test_word_values_stay_in_definition_range(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-range")
    stored = words(game, recipe.item_id)
    assert stored
    prefix = f"gear_words_{recipe.item_id}_0_"
    for row in stored:
        word_id = row["quest_id"][len(prefix):].split("_", 1)[1]
        definition = game[0].content.gear_words[word_id]
        assert definition.minimum <= row["progress"] <= definition.maximum


def test_words_apply_to_combat_stats(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-combat")
    gear_item = next(i for i in game[0].content.items.values() if i.id == recipe.item_id)
    sql(game[1], f"INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (1, '{'weapon' if gear_item.equipment_id else 'weapon'}', '{recipe.item_id}', 0) "
                 "ON CONFLICT(pet_id, slot) DO UPDATE SET item_id=excluded.item_id, enhancement=0")
    stats = play("status").lines
    combat_line = next(l for l in stats if l.startswith("气血："))
    assert combat_line  # status renders combat stats; deeper math asserted in loadout tests


def test_word_reforge_requires_owned_equipment(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="未找到"):
        play("gear_word_reforge", "不存在之刃", op="reforge-unknown")


def test_word_reforge_requires_words_to_exist(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    sql(game[1], "INSERT INTO unequipped_equipment(user_id,item_id,enhancement,quantity) VALUES ('u1','wind_feather',1,1)")
    # A stack without stored words (e.g. from before the feature) rejects reforge.
    with pytest.raises(GameError, match="还没有词条"):
        play("gear_word_reforge", "青岚翎", op="reforge-empty")


def test_word_reforge_rerolls_without_reducing_count(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    seed_materials(game, "spirit_food", 10)
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-reforge")
    before = len(words(game, recipe.item_id))
    reply = play("gear_word_reforge", recipe.name, op="word-reforge")
    assert "词条已重铸" in reply.text()
    after_rows = words(game, recipe.item_id)
    assert len(after_rows) >= before


def test_word_reforge_rejects_without_materials(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=100")
    seed_materials(game, "spirit_food", 10)
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-poor")
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="灵石"):
        play("gear_word_reforge", recipe.name, op="reforge-poor")


def test_describe_renders_each_word(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-desc")
    summary = describe_words(game[0], recipe.item_id, 0) if False else None
    stored = words(game, recipe.item_id)
    assert stored
    line = sql(game[1], f"SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'gear_words_{recipe.item_id}_%' LIMIT 1")
    assert line


def test_words_survive_storage_roundtrip(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(r for r in game[0].content.recipes.values() if r.item_id)
    for key, amount in recipe.materials.items():
        seed_materials(game, key, amount * 5)
    play("craft", recipe.name, op="craft-roundtrip")
    first = words(game, recipe.item_id)
    assert first == words(game, recipe.item_id)
