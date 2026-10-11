import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR


@pytest.fixture
def expedition_dir(tmp_path):
    directory = tmp_path / "content"
    shutil.copytree(DATA_DIR, directory)
    return directory


def edit(directory, change):
    path = directory / "expeditions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_default_expeditions_have_distinct_materials_and_progressive_gates():
    content = Catalog.load()
    expected = (
        ("herb_gathering", "采灵药", 0, 25, "spirit_food"),
        ("ore_survey", "寻锻矿", 1, 30, "forge_ore"),
        ("essence_search", "探血髓", 2, 40, "bloodline_essence"),
    )
    assert {entry[0] for entry in expected} <= set(content.expeditions)
    for identifier, name, realm, energy, material in expected:
        expedition = content.expeditions[identifier]
        assert expedition.name == name
        assert expedition.min_realm == content.realms[realm].id
        assert expedition.energy == energy
        assert set(expedition.reward.items) == {material}
        assert expedition.reward.items[material].minimum >= 1
        assert 0 < expedition.reward.exp.maximum <= 50
        assert 0 < expedition.reward.stones.maximum <= 40
        assert set(expedition.model_dump()) == {"id", "name", "description", "min_realm", "energy", "reward"}


def test_high_realm_expeditions_offer_distinct_existing_item_uses():
    content = Catalog.load()
    expected = (
        ("jindan_alchemy", "赤霞炼丹", "jindan", 50, "breakthrough_pill"),
        ("yuanying_stargazing", "归墟观星", "yuanying", 60, "book_storm_dive"),
        ("huashen_nether_egg", "幽庭觅卵", "huashen", 70, "egg_molian"),
        ("dujie_heaven_relic", "天门寻器", "dujie", 80, "stone_core"),
    )
    assert set(content.expeditions) == {
        "herb_gathering", "ore_survey", "essence_search",
        *(entry[0] for entry in expected),
    }
    uses = []
    for identifier, name, realm, energy, item in expected:
        expedition = content.expeditions[identifier]
        assert (expedition.name, expedition.min_realm, expedition.energy) == (name, realm, energy)
        assert set(expedition.reward.items) == {item}
        assert expedition.reward.items[item].minimum == 0
        assert expedition.reward.items[item].maximum == 1
        assert expedition.reward.exp.minimum < expedition.reward.exp.maximum
        assert expedition.reward.stones.minimum < expedition.reward.stones.maximum
        uses.append(content.items[item].kind)
    assert uses == ["breakthrough", "skill_book", "pet_egg", "equipment"]


def test_unknown_expedition_realm_is_rejected(expedition_dir):
    edit(expedition_dir, lambda rows: rows[0].update(min_realm="unknown"))
    with pytest.raises(ValueError, match="unknown expedition realm"):
        Catalog.load(expedition_dir)


def test_unknown_expedition_reward_item_is_rejected(expedition_dir):
    edit(expedition_dir, lambda rows: rows[0]["reward"]["items"].update({
        "unknown": {"minimum": 1, "maximum": 1},
    }))
    with pytest.raises(ValueError, match="unknown reward items"):
        Catalog.load(expedition_dir)


@pytest.mark.parametrize("change", [
    lambda rows: rows.clear(),
    lambda rows: rows.append({**rows[0], "name": "异名委托"}),
    lambda rows: rows.append({**rows[0], "id": "different_id"}),
])
def test_empty_duplicate_id_and_duplicate_name_are_rejected(expedition_dir, change):
    edit(expedition_dir, change)
    with pytest.raises(ValueError, match="empty or duplicate"):
        Catalog.load(expedition_dir)


@pytest.mark.parametrize("field", [
    "started_at", "finishes_at", "claimed_at", "created_at", "expires_at", "cooldown",
    "duration", "duration_seconds", "owner_id", "pet_id", "state", "reward_snapshot",
])
def test_expedition_definitions_reject_runtime_and_time_fields(expedition_dir, field):
    edit(expedition_dir, lambda rows: rows[0].update({field: 1}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(expedition_dir)


@pytest.mark.parametrize("energy", [0, -1, 101, "25", 25.5, True, None])
def test_expedition_energy_is_strictly_within_pet_capacity(expedition_dir, energy):
    edit(expedition_dir, lambda rows: rows[0].update(energy=energy))
    with pytest.raises(ValidationError, match="energy"):
        Catalog.load(expedition_dir)


@pytest.mark.parametrize("change", [
    lambda reward: reward["exp"].update(minimum=-1),
    lambda reward: reward["exp"].update(minimum=30, maximum=20),
    lambda reward: reward["stones"].update(maximum="10"),
    lambda reward: reward["stones"].update(maximum=1_000_001),
    lambda reward: reward["items"]["spirit_food"].update(maximum=-1),
    lambda reward: reward["items"]["spirit_food"].update(maximum=False),
    lambda reward: reward["items"]["spirit_food"].update(claimed_at=1),
    lambda reward: reward.update(settled_at=1),
])
def test_expedition_rewards_are_strict_bounded_definitions(expedition_dir, change):
    edit(expedition_dir, lambda rows: change(rows[0]["reward"]))
    with pytest.raises(ValidationError):
        Catalog.load(expedition_dir)


@pytest.mark.parametrize("field", ["id", "name", "description", "min_realm", "energy", "reward"])
def test_expedition_requires_complete_definition(expedition_dir, field):
    edit(expedition_dir, lambda rows: rows[0].pop(field))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(expedition_dir)
