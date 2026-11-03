"""灵宠配装: saving a pet's worn gear and re-equipping it in one command."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import equipment, gear_presets

from .support import pet, player, sql

NOW = 1_800_000_000
DAY = 86400


def give_gear(game, item_id, quantity=1, enhancement=0, user="u1"):
    if enhancement:
        sql(
            game[1],
            "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(user_id, item_id, enhancement)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, enhancement, quantity),
        )
        return
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, quantity),
    )


def starter(game, name="青鸾"):
    return next(entry for entry in game[0].content.species.values() if entry.name == name)


def gear_by_slot(game):
    """{slot: [item, ...]} for the equipment a fresh 青鸾 can actually wear."""
    species = starter(game)
    realms = [realm.id for realm in game[0].content.realms]
    out: dict[str, list] = {}
    for item in game[0].content.items.values():
        if item.kind != "equipment":
            continue
        gear = game[0].content.equipment[item.equipment_id]
        need = gear.requirements
        if any(element not in species.elements for element in need.elements):
            continue
        if need.categories and species.category not in need.categories:
            continue
        if realms.index(need.min_realm) > 0:
            continue
        out.setdefault(gear.slot, []).append(item)
    return {slot: sorted(items, key=lambda entry: entry.id) for slot, items in out.items()}


def bag(game, item_id, user="u1"):
    row = sql(
        game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user, item_id),
    )
    return int(row[0]["quantity"]) if row else 0


def preset_rows(game, user="u1"):
    return sorted(
        row["quest_id"] for row in sql(
            game[1],
            "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE 'gear%'",
            (user,),
        )
    )


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, item_id, enhancement, quantity FROM unequipped_equipment"
                     " ORDER BY user_id, item_id, enhancement"),
        sql(game[1], "SELECT pet_id, slot, item_id, enhancement FROM equipment ORDER BY pet_id, slot"),
        sql(game[1], "SELECT quest_id FROM quest_progress ORDER BY user_id, quest_id"),
    )


def wear(game, play, item, op="wear"):
    return play("equipment", item.name, op=op)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview(game, play):
    page = play("gear_preset", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert preset_rows(game, "ghost") == []


def test_the_page_lists_three_presets_for_the_active_pet(game, play):
    play("adopt", "青鸾")
    page = play("gear_preset")
    assert "1 套：空" in page.text()
    assert "2 套：空" in page.text()
    assert "3 套：空" in page.text()


# ---------------------------------------------------------------- save

def test_saving_records_the_worn_gear_in_keyed_rows(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    rows = preset_rows(game)
    assert rows == [f"gear1_1_weapon_0_{weapon.id}"]
    assert f"灵器 {weapon.name}" in play("gear_preset").text()


def test_saving_nothing_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="没有穿戴灵物"):
        play("gear_preset", "保存 1")
    assert preset_rows(game) == []


def test_saving_again_overwrites_the_same_slot_row(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id, enhancement=2)
    play("equipment", weapon.name)
    play("gear_preset", "保存 1")
    assert preset_rows(game) == [f"gear1_1_weapon_2_{weapon.id}"]
    # Re-save while wearing the same item at its enhanced level: the slot row is replaced,
    # not duplicated, and the enhancement is part of what a preset remembers.
    play("gear_preset", "保存 1")
    assert preset_rows(game) == [f"gear1_1_weapon_2_{weapon.id}"]


def test_an_out_of_range_preset_number_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="配装只有 3 套"):
        play("gear_preset", "保存 4")
    with pytest.raises(GameError, match="配装序号必须是"):
        play("gear_preset", "保存 一")


def test_saving_for_a_pet_you_do_not_own_is_refused(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    other = pet(game[1], "u2")["pet_id"]
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("gear_preset", f"保存 {other} 1")


# ---------------------------------------------------------------- apply

def test_applying_restores_the_saved_gear_from_the_bag(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    assert bag(game, weapon.id) == 1
    reply = play("gear_preset", "应用 1")
    assert "已换第 1 套" in reply.text()
    assert bag(game, weapon.id) == 0
    assert sql(game[1], "SELECT item_id FROM equipment")[0]["item_id"] == weapon.id


def test_applying_swaps_the_current_gear_back_into_the_bag(game, play):
    """Applying replaces the pieces it covers and returns them to the bag."""
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    # Put a *different* weapon in the same slot directly: the fresh 青鸾 can only wear one
    # weapon from content, but the swap path must still return whatever was there.
    intruder = next(
        item.id for item in sorted(game[0].content.items.values(), key=lambda entry: entry.id)
        if item.kind == "equipment"
        and game[0].content.equipment[item.equipment_id].slot == "weapon"
        and item.id != weapon.id
    )
    sql(
        game[1],
        "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, 'weapon', ?, 0)",
        (pet(game[1])["pet_id"], intruder),
    )
    play("gear_preset", "应用 1")
    equipped = {
        row["slot"]: row["item_id"] for row in sql(game[1], "SELECT slot, item_id FROM equipment")
    }
    assert equipped == {"weapon": weapon.id}
    assert bag(game, weapon.id) == 0
    assert bag(game, intruder) == 1, "the replaced piece must return to the bag"


def test_applying_never_duplicates_gear(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    play("gear_preset", "应用 1")
    total = bag(game, weapon.id) + sql(
        game[1], "SELECT COUNT(*) AS n FROM equipment WHERE item_id=?", (weapon.id,),
    )[0]["n"]
    assert total == 1


def test_applying_a_preset_while_already_wearing_it_is_refused(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    with pytest.raises(GameError, match="已经是第 1 套"):
        play("gear_preset", "应用 1")


def test_applying_an_empty_preset_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="还没有保存"):
        play("gear_preset", "应用 2")


def test_applying_when_the_gear_is_gone_writes_nothing(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    sql(game[1], "DELETE FROM inventory WHERE item_id=?", (weapon.id,))
    before = snapshot(game)
    with pytest.raises(GameError, match="已不在背包中"):
        play("gear_preset", "应用 1")
    assert snapshot(game) == before


def test_an_enhanced_piece_is_restored_at_its_own_level(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id, enhancement=3)
    play("equipment", weapon.name)
    assert sql(game[1], "SELECT enhancement FROM equipment")[0]["enhancement"] == 3
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    play("gear_preset", "应用 1")
    row = sql(game[1], "SELECT enhancement FROM equipment")[0]
    assert row["enhancement"] == 3
    assert sql(
        game[1], "SELECT quantity FROM unequipped_equipment WHERE enhancement=3 AND quantity>0",
    ) == []


def test_a_pet_on_an_expedition_cannot_be_re_geared(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    pet_id = pet(game[1])["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'gear-op', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW, NOW + 600),
    )
    before = snapshot(game)
    with pytest.raises(GameError, match="正在外出派遣"):
        play("gear_preset", "应用 1")
    assert snapshot(game) == before


# ---------------------------------------------------------------- clear

def test_clearing_removes_the_rows_but_not_the_gear(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("gear_preset", "清除 1")
    assert preset_rows(game) == []
    assert sql(game[1], "SELECT item_id FROM equipment")[0]["item_id"] == weapon.id


def test_clearing_an_empty_preset_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="是空的"):
        play("gear_preset", "清除 2")


# ---------------------------------------------------------------- surfaces

def test_presets_survive_a_restart(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    play("unequip", "灵器")
    from nonebot_plugin_spirit_pet.storage.database import Store

    Store(game[1].path).initialize()
    play("gear_preset", "应用 1")
    assert sql(game[1], "SELECT item_id FROM equipment")[0]["item_id"] == weapon.id


def test_the_page_links_can_be_parsed_back(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    page = play("gear_preset")
    labels = {link.label for link in page.inline_commands}
    assert {"应用", "覆盖", "清除", "保存"} <= labels
    for link in page.inline_commands:
        assert link.line < len(page.lines)
        assert _parse(link.command) is not None


def test_help_and_parser_cover_the_command(game, play):
    play("adopt", "青鸾")
    assert _parse("灵宠配装") == ("gear_preset", "")
    assert _parse("灵宠配装 保存 1") == ("gear_preset", "保存 1")
    assert _parse("灵宠配装 应用 3") == ("gear_preset", "应用 3")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["灵物与灵术"]}
    assert "灵宠配装" in rows
    assert "灵宠配装 应用 序号" in rows


def test_the_objectives_page_does_not_grow_a_line(game, play):
    play("adopt", "青鸾")
    assert all(not line.startswith("配装") for line in play("objectives").lines)
    assert gear_presets.objective_line(None, "u1") == ""


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    play("adopt", "青鸾")
    weapon = gear_by_slot(game)["weapon"][0]
    give_gear(game, weapon.id)
    wear(game, play, weapon)
    play("gear_preset", "保存 1")
    page = play("gear_preset")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_parsing_a_foreign_key_returns_nothing():
    assert gear_presets._parse("gear1_1_weapon_0_wind_feather") == (
        1, 1, "weapon", 0, "wind_feather",
    )
    assert gear_presets._parse("gearx_1_weapon_0_item") is None
    assert gear_presets._parse("gear1_1_hat_0_item") is None
