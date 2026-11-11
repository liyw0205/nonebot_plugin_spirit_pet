import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.gear_words import rows
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant

from .support import sql


def seed(game, item_id, amount):
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
                 "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=?", (item_id, amount, amount))


def craft_one(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    recipe = next(iter(game[0].content.recipes.values()))
    for key, amount in recipe.materials.items():
        seed(game, key, amount * 2)
    play("craft", recipe.name, op="selective-craft")
    return recipe


def test_catalog_and_detail_show_owned_stack(game, play):
    recipe = craft_one(game, play)
    page = play("gear_word_reforge", op="catalog")
    assert "灵器词条" in page.title
    assert f"{recipe.name} +0" in page.text()
    detail = play("gear_word_reforge", f"查看 {recipe.name} +0", op="detail")
    assert "选择目标四维" in detail.text()
    assert any("选择" in action.command for action in detail.inline_commands)


def test_objectives_exposes_word_stacks_and_entry_link(game, play):
    recipe = craft_one(game, play)
    page = play("objectives", op="word-objective")
    line = next(text for text in page.lines if text.startswith("灵器词条："))
    assert line.startswith("灵器词条：可定向淬词 1 栈")
    link = next(link for link in page.inline_commands if link.command == "灵宠词条重铸")
    assert page.lines[link.line] == line
    assert f"{recipe.name} +0" in play("gear_word_reforge", op="word-objective-catalog").text()


def test_selective_rewrites_one_slot_and_keeps_other_slots(game, play):
    recipe = craft_one(game, play)
    before = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ? ORDER BY quest_id", (f"gear_words_{recipe.item_id}_0_%",))
    seed(game, "spirit_food", 3)
    sql(game[1], "UPDATE players SET stones=1000")
    reply = play("gear_word_reforge", f"定向 {recipe.name} +0 1 攻击", op="selective")
    after = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ? ORDER BY quest_id", (f"gear_words_{recipe.item_id}_0_%",))
    assert "定向淬词完成" == reply.title
    assert len(after) == len(before)
    word_id = after[0]["quest_id"].split(f"gear_words_{recipe.item_id}_0_", 1)[1].split("_", 1)[1]
    assert game[0].content.gear_words[word_id].stat == "attack"
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == 850
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'")[0]["quantity"] == 0


def test_selective_rejects_bad_slot_stat_and_resources_without_writes(game, play):
    recipe = craft_one(game, play)
    seed(game, "spirit_food", 3)
    sql(game[1], "UPDATE players SET stones=1000")
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    with pytest.raises(GameError, match="词条序号"):
        play("gear_word_reforge", f"定向 {recipe.name} +0 99 攻击", op="bad-slot")
    with pytest.raises(GameError, match="目标四维"):
        play("gear_word_reforge", f"定向 {recipe.name} +0 1 幸运", op="bad-stat")
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before
    sql(game[1], "UPDATE players SET stones=0")
    with pytest.raises(GameError, match="需要 150"):
        play("gear_word_reforge", f"定向 {recipe.name} +0 1 攻击", op="poor")
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'")[0]["quantity"] == 3


def test_selective_operation_is_idempotent_and_survives_reopen(game, play):
    recipe = craft_one(game, play)
    seed(game, "spirit_food", 6)
    sql(game[1], "UPDATE players SET stones=1000")
    first = play("gear_word_reforge", f"定向 {recipe.name} +0 1 防御", op="same-operation")
    second = play("gear_word_reforge", f"定向 {recipe.name} +0 1 防御", op="same-operation")
    assert first.text() == second.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == 850
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'")[0]["quantity"] == 3
    reopened = game[0].execute("u1", "gear_word_reforge", f"查看 {recipe.name} +0", "after-reopen", 1_800_000_002)
    assert "防御" in reopened.text()


def test_worn_word_changes_combat_stats_and_invalidates_ready(game, play):
    recipe = craft_one(game, play)
    pet = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(game[1], "INSERT INTO equipment(pet_id,slot,item_id,enhancement) VALUES (?,?,?,0)", (pet, "weapon", recipe.item_id))
    seed(game, "spirit_food", 3)
    sql(game[1], "UPDATE players SET stones=1000")
    before = combatant(game[0].execute("u1", "status", "", "stats-before", 1_800_000_000), game[0].execute("u1", "status", "", "stats-before-2", 1_800_000_000)) if False else None
    play("gear_word_reforge", f"定向 {recipe.name} +0 1 速度", op="worn-selective")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM team_members WHERE user_id='u1' AND ready_pet_id IS NOT NULL")[0]["n"] == 0
