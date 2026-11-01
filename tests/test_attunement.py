"""Pet attunement: element override, skill/gear compatibility, weekly limit and gates."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.attunement_content import Attunements
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import attunement, loadout

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, pet, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def grant_items(game, item_id, amount, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def ready(game, play, *, stones=5000):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    grant_items(game, "bloodline_essence", 10)


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def table(game):
    return game[0].content.attunements


def option(game, element):
    return table(game).by_element[element]


def pet_row(game, name="青鸾"):
    return sql(game[1], "SELECT * FROM pets WHERE user_id='u1' AND name=?", (name,))[0]


def override_of(game, pet_id):
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?",
               (f"attune_{pet_id}_%",))
    rows = [row for row in rows if "_week_" not in row["quest_id"]]
    return rows[0]["quest_id"].rsplit("_", 1)[-1] if rows else None


def test_content_declares_eight_base_elements(game):
    content = game[0].content
    assert attunement.weekly_limit(ctx_of(game)) == 1
    elements = [row.element for row in table(game).options]
    assert len(elements) == 8 and len(set(elements)) == 8
    assert "ice" not in elements
    for row in table(game).options:
        assert content.elements[row.element].parent is None
        assert row.stones >= 1


def test_attunement_validation_rejects_derived_and_duplicate_targets():
    base = {"element": "fire", "stones": 100, "items": {}}
    assert Attunements.model_validate({"options": [base]}).by_element["fire"].stones == 100
    with pytest.raises(ValidationError):
        Attunements.model_validate({"options": []})
    with pytest.raises(ValidationError):
        Attunements.model_validate({"options": [{"element": "fire", "stones": 0, "items": {}}]})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("attunement", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_pets_options_and_costs(game, play):
    ready(game, play)
    page = play("attunement")
    assert "本命未改" in page.text()
    assert f"#{pet_row(game)['pet_id']}" in page.text()
    assert "灵石" in page.text()
    # the pet's own element is not offered
    offered = {link.command for link in page.inline_commands}
    species = game[0].content.species[pet_row(game)["species_id"]]
    elements = game[0].content.elements
    unavailable = {
        option.element for option in table(game).options
        if option.element in species.elements
    }
    assert len(offered) == len(table(game).options) - len(unavailable)
    for element in unavailable:
        assert not any(command.endswith(f" {elements[element].name}") for command in offered)


def test_attunement_rewrites_the_fighter_element(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    reply = play("attunement", f"{pet_id} 火", op="fire")
    assert reply.title == "易脉完成"
    assert override_of(game, pet_id) == "fire"
    fighter = loadout.combatant(ctx_of(game), "u1", pet_id=pet_id)
    assert fighter.elements == ("fire",)
    assert fighter.primary_element == "fire"


def test_attunement_charges_stones_and_items(game, play):
    ready(game, play, stones=2000)
    pet_id = pet_row(game)["pet_id"]
    cost = option(game, "fire")
    play("attunement", f"{pet_id} 火", op="cost")
    assert player(game[1])["stones"] == 2000 - cost.stones
    row = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='bloodline_essence'")[0]
    assert row["quantity"] == 10 - cost.items["bloodline_essence"]


def test_incompatible_skills_are_unequipped(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    content = game[0].content
    species = content.species[pet_row(game)["species_id"]]
    target = next(row.element for row in table(game).options if row.element not in species.elements)
    skill = next(
        row for row in content.skills.values()
        if row.requirements.elements and target not in row.requirements.elements
    )
    sql(game[1], "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, 1)",
        (pet_id, skill.id))
    reply = play("attunement", f"{pet_id} {content.elements[target].name}", op="skills")
    assert "自动卸下" in reply.text()
    row = sql(game[1], "SELECT equipped FROM learned_skills WHERE pet_id=? AND skill_id=?", (pet_id, skill.id))[0]
    assert row["equipped"] == 0


def test_worn_incompatible_gear_blocks_the_change(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    content = game[0].content
    species = content.species[pet_row(game)["species_id"]]
    from nonebot_plugin_spirit_pet.utils.elements import expand_elements

    wearable = expand_elements(species.elements, content.elements)
    target = next(row.element for row in table(game).options if row.element not in species.elements)
    gear, item = next(
        (content.equipment[item.equipment_id], item)
        for item in content.items.values()
        if item.equipment_id
        and set(content.equipment[item.equipment_id].requirements.elements) <= wearable
        and target not in content.equipment[item.equipment_id].requirements.elements
        and content.equipment[item.equipment_id].requirements.elements
    )
    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, 0)",
        (pet_id, gear.slot, item.id))
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="卸下不兼容的装备"):
        play("attunement", f"{pet_id} {content.elements[target].name}")
    assert override_of(game, pet_id) is None
    assert player(game[1])["stones"] == stones


def test_same_element_is_refused(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    species = game[0].content.species[pet_row(game)["species_id"]]
    current = game[0].content.elements[species.elements[0]].name
    with pytest.raises(GameError, match="已经是"):
        play("attunement", f"{pet_id} {current}")
    assert override_of(game, pet_id) is None


def test_weekly_limit_blocks_a_second_change(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("attunement", f"{pet_id} 火", op="w1")
    with pytest.raises(GameError, match="本周已易脉"):
        play("attunement", f"{pet_id} 金")
    assert override_of(game, pet_id) == "fire"


def test_the_limit_resets_next_week(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("attunement", f"{pet_id} 火", op="r1")
    later = NOW + WEEK
    reply = play("attunement", f"{pet_id} 金", op="r2", now=later)
    assert reply.title == "易脉完成"
    assert override_of(game, pet_id) == "metal"


def test_stone_shortage_writes_nothing(game, play):
    ready(game, play, stones=10)
    pet_id = pet_row(game)["pet_id"]
    with pytest.raises(GameError, match="灵石不足"):
        play("attunement", f"{pet_id} 火")
    assert override_of(game, pet_id) is None
    assert player(game[1])["stones"] == 10


def test_item_shortage_writes_nothing(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='bloodline_essence'")
    with pytest.raises(GameError, match="材料不足"):
        play("attunement", f"{pet_id} 火")
    assert override_of(game, pet_id) is None


def test_expedition_and_archived_pets_are_refused(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("attunement", f"{pet_id} 火")
    assert override_of(game, pet_id) is None


def test_unknown_pet_and_element_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="没有找到这只伙伴"):
        play("attunement", "9999 火")
    with pytest.raises(GameError, match="未找到"):
        play("attunement", f"{pet_row(game)['pet_id']} 不存在")
    with pytest.raises(GameError, match="格式"):
        play("attunement", "火")


def test_element_changes_the_damage_chart(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("attunement", f"{pet_id} 火", op="chart")
    from nonebot_plugin_spirit_pet.gameplay.combat import effectiveness

    definitions = game[0].content.elements
    assert effectiveness("fire", "metal", definitions) > effectiveness("water", "metal", definitions)


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "易脉：本命元素均未改" in play("objectives").text()
    play("attunement", f"{pet_row(game)['pet_id']} 火", op="obj")
    assert "易脉：1 只伙伴已改属" in play("objectives").text()
    assert "灵宠易脉" in play("help", "成长").text()
    assert handlers._parse("灵宠易脉") == ("attunement", "")
    assert handlers._parse("灵宠易脉 1 火") == ("attunement", "1 火")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    first = play("attunement", f"{pet_id} 火", op="replay")
    stones = player(game[1])["stones"]
    again = play("attunement", f"{pet_id} 火", op="replay")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones


def test_state_survives_a_restart(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("attunement", f"{pet_id} 火", op="persist")
    assert "已易脉为火" in play("attunement").text()
    assert loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).elements == ("fire",)


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("attunement")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
