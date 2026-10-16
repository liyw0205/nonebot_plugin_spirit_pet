import sqlite3

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, sql


def account(game, play, species="shiou"):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    sql(game[1], "UPDATE pets SET species_id=? WHERE user_id='u1'", (species,))


def seed_stone_guard(game, play):
    account(game, play)
    play("buy", "灵心铃")
    play("equipment", "灵心铃")
    sql(game[1], "INSERT INTO unequipped_equipment VALUES ('u1', 'earth_shell', 2, 1)")
    sql(game[1], "INSERT INTO unequipped_equipment VALUES ('u1', 'stone_core', 3, 1)")


def test_command_and_set_detail_expose_actionable_parts_without_creating_player(game, play):
    assert COMMANDS["灵宠套装穿戴"] == "equipment_set_equip"
    assert handlers._parse("灵宠套装穿戴 1 山岳镇魂") == ("equipment_set_equip", "1 山岳镇魂")

    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET species_id='shiou' WHERE user_id='u1'")
    detail = play("equipment_sets", "山岳镇魂")
    assert any("玄岩甲 · 背包缺少" in line for line in detail.lines)
    assert any("山心石 · 背包缺少" in line for line in detail.lines)
    assert any(link.command == "灵宠装备图鉴 玄岩甲" for link in detail.inline_commands)
    assert any(link.command == "灵宠商店 山心石" for link in detail.inline_commands)
    assert not any(link.command.startswith("灵宠套装穿戴") for link in detail.inline_commands)

    unregistered = play("equipment_sets", "木灵缚甲", user="u9")
    assert "尚未结契" in unregistered.text()
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='u9'") == []


def test_one_step_wear_preserves_upgrades_returns_replaced_gear_and_claims_reward(game, play):
    seed_stone_guard(game, play)
    before_bell = items(game[1]).get("spirit_bell", 0)
    target = pet(game[1])["pet_id"]
    detail = play("equipment_sets", "山岳镇魂")
    assert detail.lines[-3] == "装配状态：可由青鸾一键穿戴。"
    assert any(link.command == f"灵宠套装穿戴 {target} 山岳镇魂" for link in detail.inline_commands)

    result = play("equipment_set_equip", f"{target} 山岳镇魂", op="wear-stone-guard")
    assert result.title == "套装穿戴"
    assert "护甲：玄岩甲 +2" in result.lines
    assert "饰品：山心石 +3" in result.lines
    assert sql(game[1], "SELECT slot, item_id, enhancement FROM equipment WHERE pet_id=? ORDER BY slot",
               (pet(game[1])["pet_id"],)) == [
        {"slot": "armor", "item_id": "earth_shell", "enhancement": 2},
        {"slot": "charm", "item_id": "stone_core", "enhancement": 3},
    ]
    assert items(game[1]).get("spirit_bell", 0) == before_bell + 1
    assert sql(
        game[1],
        "SELECT * FROM unequipped_equipment WHERE item_id IN ('earth_shell', 'stone_core') AND quantity>0",
    ) == []
    assert play("equipment_set_equip", f"{target} 山岳镇魂", op="wear-stone-guard") == result

    ready = play("equipment_sets", "山岳镇魂")
    assert "套装加成：气血 +30 防御 +6。" in ready.lines
    assert any(link.command == "灵宠套装领奖 山岳镇魂" for link in ready.inline_commands)
    assert play("equipment_set_claim", "山岳镇魂").title == "套装完成奖励"

    with pytest.raises(GameError, match="已经穿齐"):
        play("equipment_set_equip", f"{target} 山岳镇魂")


def test_stale_ready_link_rechecks_inventory_without_partial_wear(game, play):
    account(game, play)
    play("buy", "玄岩甲")
    play("buy", "山心石")
    detail = play("equipment_sets", "山岳镇魂")
    stale = next(link for link in detail.inline_commands if link.command.startswith("灵宠套装穿戴 "))
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='stone_core'")
    before = items(game[1])
    action, argument = handlers._parse(stale.command)

    with pytest.raises(GameError, match="背包缺少山心石"):
        play(action, argument)

    assert sql(game[1], "SELECT * FROM equipment WHERE pet_id=?", (pet(game[1])["pet_id"],)) == []
    assert items(game[1]) == before


def test_incompatible_or_expedition_busy_pet_cannot_wear_set(game, play):
    account(game, play, species="qingluan")
    play("buy", "玄岩甲")
    play("buy", "山心石")
    detail = play("equipment_sets", "山岳镇魂")
    assert "不适配" in detail.text()
    assert not any(link.command.startswith("灵宠套装穿戴") for link in detail.inline_commands)
    with pytest.raises(GameError, match="不兼容"):
        play("equipment_set_equip", f"{pet(game[1])['pet_id']} 山岳镇魂")
    assert items(game[1]).get("earth_shell", 0) == 1
    assert items(game[1]).get("stone_core", 0) == 1

    sql(game[1], "UPDATE pets SET species_id='shiou' WHERE user_id='u1'")
    play("expedition_start", "采灵药")
    detail = play("equipment_sets", "山岳镇魂")
    assert "仍在行程中，暂不能穿戴" in detail.text()
    with pytest.raises(GameError, match="仍有未结行程|正在外出派遣"):
        play("equipment_set_equip", f"{pet(game[1])['pet_id']} 山岳镇魂")
    assert items(game[1]).get("earth_shell", 0) == 1


def test_late_equipment_write_failure_rolls_back_all_set_swaps_and_allows_retry(game, play):
    seed_stone_guard(game, play)
    target = pet(game[1])["pet_id"]
    before_items = items(game[1])
    before_equipment = sql(game[1], "SELECT * FROM equipment ORDER BY pet_id, slot")
    sql(game[1],
        "CREATE TRIGGER reject_set_armor BEFORE INSERT ON equipment WHEN NEW.slot='armor' "
        "BEGIN SELECT RAISE(ABORT, 'injected set equip failure'); END")

    with pytest.raises(sqlite3.IntegrityError, match="injected set equip failure"):
        play("equipment_set_equip", f"{target} 山岳镇魂", op="rollback-set-equip")

    assert items(game[1]) == before_items
    assert sql(game[1], "SELECT * FROM equipment ORDER BY pet_id, slot") == before_equipment
    assert sql(game[1], "SELECT * FROM unequipped_equipment WHERE item_id IN ('earth_shell', 'stone_core')") == [
        {"user_id": "u1", "item_id": "earth_shell", "enhancement": 2, "quantity": 1},
        {"user_id": "u1", "item_id": "stone_core", "enhancement": 3, "quantity": 1},
    ]

    sql(game[1], "DROP TRIGGER reject_set_armor")
    retry = play("equipment_set_equip", f"{target} 山岳镇魂", op="rollback-set-equip")
    assert retry.title == "套装穿戴"


def test_old_detail_link_cannot_apply_to_a_new_active_pet(game, play):
    account(game, play)
    play("buy", "玄岩甲")
    play("buy", "山心石")
    old_pet_id = pet(game[1])["pet_id"]
    detail = play("equipment_sets", "山岳镇魂")
    stale = next(link for link in detail.inline_commands if link.command.startswith("灵宠套装穿戴 "))

    play("summon", "1")
    new_pet_id = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    play("switch", str(new_pet_id))
    before = items(game[1])
    action, argument = handlers._parse(stale.command)

    with pytest.raises(GameError, match="当前出战伙伴已变化"):
        play(action, argument)

    assert old_pet_id != new_pet_id
    assert items(game[1]) == before
    assert sql(game[1], "SELECT * FROM equipment") == []
