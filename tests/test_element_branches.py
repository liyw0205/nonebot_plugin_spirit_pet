from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.battle_content import Element, Requirement, Skill, Talent
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, effectiveness, fight
from nonebot_plugin_spirit_pet.gameplay.compatibility import check_requirements
from nonebot_plugin_spirit_pet.gameplay.talents import attack_modifiers
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.elements import element_ancestors, expand_elements

from .test_talents import StableRandom


def definitions():
    return {
        "water": Element(id="water", name="Water", strong_against=["fire"]),
        "ice": Element(id="ice", name="Ice", parent="water"),
        "fire": Element(id="fire", name="Fire", strong_against=["metal"]),
        "metal": Element(id="metal", name="Metal"),
        "wind": Element(id="wind", name="Wind"),
    }


def test_ancestors_include_self_and_parent_but_not_child_or_unrelated_element():
    elements = definitions()
    assert element_ancestors("ice", elements) == {"ice", "water"}
    assert element_ancestors("water", elements) == {"water"}
    assert expand_elements(("ice", "wind"), elements) == {"ice", "water", "wind"}


def test_ancestry_rejects_invalid_parent_and_cycles():
    elements = definitions()
    elements["water"] = elements["water"].model_copy(update={"parent": "ice"})
    with pytest.raises(ValueError, match="cyclic"):
        element_ancestors("ice", elements)
    with pytest.raises(ValueError, match="unknown"):
        element_ancestors("unknown", elements)


def test_branch_inherits_both_offensive_and_defensive_elemental_matchups():
    elements = definitions()
    assert effectiveness("water", "fire", elements) == 1.25
    assert effectiveness("ice", "fire", elements) == 1.25
    assert effectiveness("fire", "ice", elements) == 0.8
    assert effectiveness("ice", "wind", elements) == 1.0
    assert effectiveness(None, "fire", elements) == 1.0
    assert effectiveness("fire", None, elements) == 1.0


def test_ice_pet_can_use_water_but_water_pet_cannot_use_ice_and_composites_require_all(game, play):
    play("adopt", "青鸾")
    service, store = game
    ice = next(pet for pet in service.content.species.values() if "ice" in pet.elements)
    water = next(pet for pet in service.content.species.values() if "water" in pet.elements and "ice" not in pet.elements)
    realm = service.content.realms[0].id
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, "u1", 1_800_000_000, "element-test")
        pet = ctx.pet()
        pet.species_id = ice.id
        check_requirements(ctx, pet, Requirement(elements=["water"], min_realm=realm))
        missing = next(key for key in service.content.elements if key not in expand_elements(ice.elements, service.content.elements))
        with pytest.raises(GameError, match="同时具备"):
            check_requirements(ctx, pet, Requirement(elements=["water", missing], min_realm=realm))
        pet.species_id = water.id
        with pytest.raises(GameError, match="元素不兼容"):
            check_requirements(ctx, pet, Requirement(elements=["ice"], min_realm=realm))


def test_primary_element_controls_basic_attack_and_secondary_elements_do_not_cancel_weakness():
    elements = definitions()
    attacker = Fighter.create(
        "left", Stats(hp=100, attack=20, defense=0, speed=10), ("fire", "water"), primary_element="fire",
    )
    target = Fighter.create(
        "right", Stats(hp=100, attack=1000, defense=0, speed=1), ("water", "metal"), primary_element="water",
    )
    fight([attacker], [target], StableRandom(), elements)
    assert target.hp == 84


@pytest.mark.parametrize("skill_element, expected_hp", [("water", 75), (None, 80)])
def test_offensive_skill_uses_its_own_element_instead_of_pet_primary(skill_element, expected_hp):
    damage = Skill(
        id="skill", name="skill", description="skill", element=skill_element,
        requirements={"min_realm": "mortal"}, kind="damage", coefficient=1.0, book_item="book",
    )
    attacker = Fighter.create(
        "left", Stats(hp=100, attack=20, defense=0, speed=10), ("fire", "water"),
        (damage,), primary_element="fire",
    )
    target = Fighter.create(
        "right", Stats(hp=100, attack=1000, defense=0, speed=1), ("fire",), primary_element="fire",
    )
    fight([attacker], [target], StableRandom(), definitions())
    assert target.hp == expected_hp


def test_full_health_healing_fallback_retains_pet_primary_element():
    healing = Skill(
        id="heal", name="heal", description="heal", element="water",
        requirements={"min_realm": "mortal"}, kind="heal", coefficient=0.2, book_item="book",
    )
    attacker = Fighter.create(
        "left", Stats(hp=100, attack=20, defense=0, speed=10), ("fire", "water"),
        (healing,), primary_element="fire", pet_id=1,
    )
    target = Fighter.create(
        "right", Stats(hp=100, attack=1000, defense=0, speed=1), ("metal",), primary_element="metal",
    )
    result = fight([attacker], [target], StableRandom(), definitions())
    assert target.hp == 75
    assert result.skill_uses[0][1] == {}


def test_element_filtered_fury_accepts_branches_and_rejects_unrelated_attacks():
    talent = Talent(id="test", name="test", description="test", kind="fury", power=0.5, element="water")
    stats = Stats(hp=100, attack=20, defense=10, speed=10)
    attacker = Fighter.create("left", stats, talent=talent)
    target = Fighter.create("right", stats)
    assert attack_modifiers(attacker, target, "ice", definitions()) == (1.5, 10, "test")
    assert attack_modifiers(attacker, target, "fire", definitions()) == (1.0, 10, None)
    assert attack_modifiers(attacker, target, None, definitions()) == (1.0, 10, None)
