"""Battle formation: per-slot trade-offs, base-stat-only scaling, gates and persistence."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.formation_content import Formation, Formations
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import formation, loadout
from nonebot_plugin_spirit_pet.gameplay.combat import pet_stats
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def ready(game, play):
    play("adopt", "青鸾")


def pet_row(game, name="青鸾"):
    return sql(game[1], "SELECT * FROM pets WHERE user_id='u1' AND name=?", (name,))[0]


def position_row(game, pet_id):
    rows = sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?",
        (f"formation_{pet_id}_%",),
    )
    return rows[0]["quest_id"].rsplit("_", 1)[-1] if rows else None


def test_content_declares_three_trade_off_positions(game):
    content = game[0].content
    ids = [entry.id for entry in content.formations.positions]
    assert ids == ["vanguard", "center", "rear"]
    for entry in content.formations.positions:
        assert max(entry.rates.values()) > 1
        assert min(entry.rates.values()) < 1
        assert set(entry.rates) == {"hp", "attack", "defense", "speed"}


def test_formation_validation_rejects_pure_gains_and_pure_costs():
    good = {"hp": 1.1, "attack": 0.9, "defense": 1.0, "speed": 1.0}
    assert Formation.model_validate({"id": "x", "name": "试", "description": "d", "rates": good}).id == "x"
    with pytest.raises(ValidationError, match="raise at least one"):
        Formation.model_validate(
            {"id": "x", "name": "试", "description": "d",
             "rates": {"hp": 0.9, "attack": 0.9, "defense": 0.9, "speed": 0.9}}
        )
    with pytest.raises(ValidationError, match="cost at least one"):
        Formation.model_validate(
            {"id": "x", "name": "试", "description": "d",
             "rates": {"hp": 1.2, "attack": 1.2, "defense": 1.2, "speed": 1.2}}
        )
    with pytest.raises(ValidationError):
        Formation.model_validate({"id": "x", "name": "试", "description": "d", "rates": {"hp": 3}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("formation", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_the_roster_and_every_position(game, play):
    ready(game, play)
    page = play("formation")
    assert "未布阵" in page.text()
    assert "前锋" in page.text() and "后援" in page.text()
    assert "阵位只作用于基础四维" in page.text()
    assert len(page.inline_commands) == 3  # one roster pet, three positions


def test_a_position_applies_to_base_stats_only(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    baseline = loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).stats
    play("formation", f"{pet_id} 前锋", op="front")
    vanguard = loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).stats
    rates = game[0].content.formations.by_id["vanguard"].rates
    for stat, rate in rates.items():
        assert getattr(vanguard, stat) == int(getattr(baseline, stat) * rate + 0.5)


def test_flat_bonuses_keep_their_documented_values(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    content = game[0].content
    from nonebot_plugin_spirit_pet.utils.elements import expand_elements

    species = content.species[pet_row(game)["species_id"]]
    wearable = expand_elements(species.elements, content.elements)
    item = next(
        entry for entry in content.items.values()
        if entry.equipment_id
        and content.equipment[entry.equipment_id].slot == "weapon"
        and set(content.equipment[entry.equipment_id].requirements.elements) <= wearable
        and (
            not content.equipment[entry.equipment_id].requirements.categories
            or species.category in content.equipment[entry.equipment_id].requirements.categories
        )
    )
    weapon = content.equipment[item.equipment_id]
    base = pet_stats_from(game, pet_id)
    rate = content.formations.by_id["vanguard"].rates["attack"]
    expected = int(base.attack * rate + 0.5) + weapon.bonuses.attack

    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, 'weapon', ?, 0)",
        (pet_id, item.id))
    play("formation", f"{pet_id} 前锋", op="flat")

    assert loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).stats.attack == expected


def pet_stats_from(game, pet_id):
    return pet_stats(Repository(game[1].connect()).pet(pet_id), game[0].content)


def test_assigning_replaces_the_previous_position(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("formation", f"{pet_id} 前锋", op="p1")
    assert position_row(game, pet_id) == "vanguard"
    play("formation", f"{pet_id} 后援", op="p2")
    assert position_row(game, pet_id) == "rear"
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE ?", (f"formation_{pet_id}_%",))
    assert len(rows) == 1


def test_reassigning_the_same_position_is_refused(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("formation", f"{pet_id} 前锋", op="same-1")
    with pytest.raises(GameError, match="已经在"):
        play("formation", f"{pet_id} 前锋")


def test_an_unassigned_pet_keeps_the_old_baseline(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    before = loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).stats
    assert formation.rates_of(ctx_of(game), pet_id) == {}
    assert loadout.combatant(ctx_of(game), "u1", pet_id=pet_id).stats == before


def test_pets_outside_the_roster_cannot_be_assigned(game, play):
    ready(game, play)
    play("summon", "1", op="extra")
    rows = sql(game[1], "SELECT pet_id, name FROM pets WHERE user_id='u1' ORDER BY pet_id")
    roster = {pet_row(game)["pet_id"]}
    outsider = next(row["pet_id"] for row in rows if row["pet_id"] not in roster)
    with pytest.raises(GameError, match="出战阵容"):
        play("formation", f"{outsider} 中军")
    assert position_row(game, outsider) is None


def test_archived_and_unknown_pets_are_refused(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    with pytest.raises(GameError, match="没有找到这只伙伴"):
        play("formation", "9999 前锋")
    with pytest.raises(GameError, match="没有这个阵位"):
        play("formation", f"{pet_id} 侧翼")
    with pytest.raises(GameError, match="格式"):
        play("formation", "前锋")


def test_an_archived_pet_is_refused(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet_id,))
    with pytest.raises(GameError, match="封存"):
        play("formation", f"{pet_id} 前锋")
    assert position_row(game, pet_id) is None


def test_objective_help_and_parse(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    assert "阵位：出战阵容尚未布阵" in play("objectives").text()
    play("formation", f"{pet_id} 中军", op="obj")
    assert "阵位：已布阵 1/1" in play("objectives").text()
    assert "灵宠阵位" in play("help", "成长").text()
    assert handlers._parse("灵宠阵位") == ("formation", "")
    assert handlers._parse("灵宠阵位 1 前锋") == ("formation", "1 前锋")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    first = play("formation", f"{pet_id} 前锋", op="replay")
    again = play("formation", f"{pet_id} 前锋", op="replay")
    assert again.text() == first.text()
    assert position_row(game, pet_id) == "vanguard"


def test_state_survives_a_restart(game, play):
    ready(game, play)
    pet_id = pet_row(game)["pet_id"]
    play("formation", f"{pet_id} 后援", op="persist")
    lines = play("formation").text().splitlines()
    assert any("后援" in line and pet_row(game)["name"] in line for line in lines)
    assert formation.position_of(ctx_of(game), pet_id) == "rear"


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("formation")
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
