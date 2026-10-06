import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.utils.elements import expand_elements


@pytest.fixture
def catalog_dir(tmp_path):
    directory = tmp_path / "content"
    shutil.copytree(DATA_DIR, directory)
    return directory


def edit(directory, filename, change):
    path = directory / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_starters_and_obtainable_diverse_pet_roster():
    content = Catalog.load()
    assert {pet.id for pet in content.species.values() if pet.starter} == {
        "qingluan", "xuanhu", "baize", "jiaolong",
    }
    assert len(content.species) >= 20
    assert {entry.species for entry in content.pools["standard"].entries} == set(content.species)
    assert content.pools["standard"].entries[0].species == "qingluan"
    assert len({pet.talent for pet in content.species.values()}) == len(content.species)
    for element in ("fire", "water", "wood", "metal", "earth", "ice", "poison"):
        pets = [pet for pet in content.species.values() if pet.primary_element == element]
        assert len(pets) >= 2
        assert len({pet.category for pet in pets}) >= 2
        assert len({content.talents[pet.talent].kind for pet in pets}) >= 2
        assert len({tuple(pet.stats.model_dump().values()) for pet in pets}) == len(pets)


@pytest.mark.parametrize("species,starter", [("qingluan", False), ("bifang", True)])
def test_starter_roster_cannot_silently_change(catalog_dir, species, starter):
    edit(catalog_dir, "pets.json", lambda rows: next(
        row for row in rows if row["id"] == species
    ).update(starter=starter))
    with pytest.raises(ValueError, match="starter species must be exactly"):
        Catalog.load(catalog_dir)


def test_explicit_primary_element_and_parent_inheritance():
    content = Catalog.load()
    for actor in (*content.species.values(), *content.enemies.values()):
        assert actor.primary_element in actor.elements
    assert content.elements["ice"].parent == "water"
    for element in ("metal", "wood", "water", "fire", "earth", "wind", "thunder", "poison"):
        assert content.elements[element].parent is None
    assert expand_elements(["ice"], content.elements) == {"ice", "water"}
    assert expand_elements(["water"], content.elements) == {"water"}


@pytest.mark.parametrize("filename", ["pets.json", "enemies.json"])
def test_primary_element_cannot_be_implicit_or_outside_elements(catalog_dir, filename):
    edit(catalog_dir, filename, lambda rows: rows[0].pop("primary_element"))
    with pytest.raises(ValidationError, match="primary_element"):
        Catalog.load(catalog_dir)
    edit(catalog_dir, filename, lambda rows: rows[0].update(primary_element="ice"))
    with pytest.raises(ValueError, match="primary element must belong"):
        Catalog.load(catalog_dir)


@pytest.mark.parametrize("parent", ["unknown", "ice"])
def test_unknown_or_cyclic_parent_is_rejected(catalog_dir, parent):
    edit(catalog_dir, "elements.json", lambda rows: next(
        row for row in rows if row["id"] == "water"
    ).update(parent=parent))
    with pytest.raises(ValueError, match="parent|cycle|cyclic"):
        Catalog.load(catalog_dir)


def test_parent_skill_and_equipment_remain_reachable_for_ice_only_species(catalog_dir):
    edit(catalog_dir, "pets.json", lambda rows: rows.__setitem__(slice(None), [
        {**row, "elements": ["ice"], "primary_element": "ice", "talent": "snow_mirage"}
        if row["id"] == "hanying" else row
        for row in rows
    ]))
    edit(catalog_dir, "equipment.json", lambda rows: next(
        row for row in rows if row["id"] == "frost_beak"
    )["requirements"].update(elements=["water"]))
    edit(catalog_dir, "skills.json", lambda rows: next(
        row for row in rows if row["id"] == "frost_cocoon"
    ).update(element="water", requirements={
        "elements": ["water"], "categories": ["insect"], "min_realm": "qiling",
    }))
    assert Catalog.load(catalog_dir).skills["frost_cocoon"].element == "water"


def test_unreachable_species_is_rejected(catalog_dir):
    edit(catalog_dir, "pets.json", lambda rows: rows.append({
        **rows[0], "id": "unreachable", "name": "无缘灵宠", "starter": False,
    }))
    with pytest.raises(ValueError, match="no acquisition route"):
        Catalog.load(catalog_dir)


def test_unused_summon_pool_does_not_establish_acquisition(catalog_dir):
    edit(catalog_dir, "pools.json", lambda rows: rows[0].update(entries=[
        entry for entry in rows[0]["entries"] if entry["species"] != "bifang"
    ]))
    edit(catalog_dir, "pools.json", lambda rows: rows.append({
        "id": "unopened", "name": "未启灵池", "stones": 100,
        "entries": [{"species": "bifang", "weight": 1}],
    }))
    with pytest.raises(ValueError, match="no acquisition route"):
        Catalog.load(catalog_dir)


def test_egg_drop_is_an_independent_acquisition_route(catalog_dir):
    edit(catalog_dir, "pools.json", lambda rows: rows[0].update(entries=[
        entry for entry in rows[0]["entries"] if entry["species"] != "tengling"
    ]))
    assert Catalog.load(catalog_dir).items["egg_tengling"].species_id == "tengling"
    edit(catalog_dir, "dungeons.json", lambda rows: next(
        row for row in rows if row["id"] == "forest"
    )["reward"]["items"].pop("egg_tengling"))
    with pytest.raises(ValueError, match="no acquisition route"):
        Catalog.load(catalog_dir)


def test_zero_quantity_egg_drop_does_not_establish_acquisition(catalog_dir):
    edit(catalog_dir, "pools.json", lambda rows: rows[0].update(entries=[
        entry for entry in rows[0]["entries"] if entry["species"] != "tengling"
    ]))
    edit(catalog_dir, "dungeons.json", lambda rows: next(
        row for row in rows if row["id"] == "forest"
    )["reward"]["items"]["egg_tengling"].update(minimum=0, maximum=0))
    with pytest.raises(ValueError, match="no acquisition route"):
        Catalog.load(catalog_dir)


@pytest.mark.parametrize("change", [
    lambda item: item.update(species_id="unknown"),
    lambda item: item.update(effects={"energy": 10}),
    lambda item: item.update(kind="material"),
    lambda item: item.pop("species_id"),
])
def test_egg_type_and_target_are_validated(catalog_dir, change):
    edit(catalog_dir, "items.json", lambda rows: change(next(
        row for row in rows if row["id"] == "egg_tengling"
    )))
    with pytest.raises(ValueError):
        Catalog.load(catalog_dir)


@pytest.mark.parametrize("filename,change,error", [
    ("pets.json", lambda rows: rows[0].update(talent="unknown"), "pet talent"),
    ("pets.json", lambda rows: rows[0].update(talent="blazing_plume"), "elemental talent"),
    ("talents.json", lambda rows: rows[0].update(kind="unsupported"), "kind"),
    ("talents.json", lambda rows: rows[0].update(power=0), "power"),
    ("talents.json", lambda rows: rows[0].update(power=1.01), "power"),
    ("talents.json", lambda rows: rows[0].update(element="unknown"), "talent element"),
    ("talents.json", lambda rows: rows[0].update(kind="shield"), "only fury"),
])
def test_talent_contracts_fail_early(catalog_dir, filename, change, error):
    edit(catalog_dir, filename, change)
    with pytest.raises(ValueError, match=error):
        Catalog.load(catalog_dir)


def test_progression_tables_have_caps_and_usable_material_sources():
    content = Catalog.load()
    assert list(content.skill_levels) == list(range(1, 6))
    assert content.skill_levels[5].required_proficiency is None
    assert list(content.forge_levels) == list(range(11))
    assert content.forge_levels[10].upgrade_stones is None
    assert content.forge_levels[10].upgrade_items == {}
    assert content.forge_levels[1].bonus_multiplier >= 1.2
    assert content.items["forge_ore"].kind == "material"
    assert any("forge_ore" in dungeon.reward.items for dungeon in content.dungeons.values())
    assert any("forge_ore" in quest.reward.items for quest in content.quests.values())
    eggs = {item.id for item in content.items.values() if item.kind == "pet_egg"}
    drops = {item for dungeon in content.dungeons.values() for item in dungeon.reward.items}
    assert len(eggs) >= 3
    assert eggs <= drops
    assert all(content.items[egg].price is None for egg in eggs)


@pytest.mark.parametrize("filename,change,error", [
    ("skill_levels.json", lambda rows: rows.pop(1), "contiguous"),
    ("skill_levels.json", lambda rows: rows[0].update(required_proficiency=None), "final skill"),
    ("skill_levels.json", lambda rows: rows[-1].update(required_proficiency=100), "final skill"),
    ("skill_levels.json", lambda rows: rows[1].update(power_multiplier=1.0), "strictly increase"),
    ("forge_levels.json", lambda rows: rows.pop(), "0 through 10"),
    ("forge_levels.json", lambda rows: rows[0].update(upgrade_stones=None), "final forge"),
    ("forge_levels.json", lambda rows: rows[-1].update(upgrade_items={"forge_ore": 1}), "final forge"),
    ("forge_levels.json", lambda rows: rows[0].update(upgrade_items={"unknown": 1}), "forge cost"),
    ("forge_levels.json", lambda rows: rows[0].update(upgrade_items={"spirit_food": 1}), "materials"),
    ("forge_levels.json", lambda rows: rows[0].update(bonus_multiplier=1.1), "equal 1"),
])
def test_progression_references_and_boundaries(catalog_dir, filename, change, error):
    edit(catalog_dir, filename, change)
    with pytest.raises(ValueError, match=error):
        Catalog.load(catalog_dir)


@pytest.mark.parametrize("filename", ["talents.json", "skill_levels.json", "forge_levels.json"])
@pytest.mark.parametrize("field", ["created_at", "cooldown", "last_login", "proficiency", "owner_id"])
def test_new_static_tables_reject_runtime_state(catalog_dir, filename, field):
    edit(catalog_dir, filename, lambda rows: rows[0].update({field: 1}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(catalog_dir)
