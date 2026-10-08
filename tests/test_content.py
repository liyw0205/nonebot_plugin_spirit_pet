import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.utils.randomness import weighted_choice


@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit(directory, filename, change):
    path = directory / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_default_content_is_complete():
    content = Catalog.load()
    assert len(content.species) >= 20
    assert {key for key, species in content.species.items() if species.starter} == {
        "qingluan", "xuanhu", "baize", "jiaolong",
    }
    assert set(content.layers) == set(range(1, 11))
    assert len(content.realms) == 7
    assert len(content.bloodlines) == 5
    assert content.rules.max_team_size == 3


@pytest.mark.parametrize("filename", [
    "pets.json", "items.json", "realms.json", "layers.json", "bloodlines.json",
    "adventures.json", "exploration_routes.json", "quests.json", "pools.json", "enemies.json", "dungeons.json",
    "equipment.json", "equipment_sets.json", "skills.json", "elements.json", "categories.json",
])
@pytest.mark.parametrize("field", ["created_at", "cooldown", "last_login", "timestamp"])
def test_static_data_rejects_runtime_fields(content_dir, filename, field):
    edit(content_dir, filename, lambda data: data[0].update({field: 1800000000}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(content_dir)


def test_nested_runtime_state_and_rules_extra_fields_rejected(content_dir):
    edit(content_dir, "items.json", lambda data: data[0]["effects"].update({"finish_at": 1}))
    with pytest.raises(ValidationError):
        Catalog.load(content_dir)


def test_unknown_reward_item_fails_early(content_dir):
    edit(content_dir, "quests.json", lambda data: data[0]["reward"]["items"].update({
        "ghost_item": {"minimum": 1, "maximum": 2},
    }))
    with pytest.raises(ValueError, match="unknown reward items"):
        Catalog.load(content_dir)


def test_exploration_encounter_requires_a_display_name(content_dir):
    edit(content_dir, "adventures.json", lambda data: data[0].pop("name"))
    with pytest.raises(ValidationError, match="name"):
        Catalog.load(content_dir)


def test_missing_layer_duplicate_id_and_bad_range(content_dir):
    edit(content_dir, "layers.json", lambda data: data.pop())
    with pytest.raises(ValueError, match="1 through 10"):
        Catalog.load(content_dir)


def test_duplicate_species(content_dir):
    edit(content_dir, "pets.json", lambda data: data.append(data[0]))
    with pytest.raises(ValueError, match="duplicate"):
        Catalog.load(content_dir)


def test_duplicate_json_object_keys_are_not_silently_overwritten(content_dir):
    path = content_dir / "rules.json"
    path.write_text('{"starter_stones":100,"starter_stones":0}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        Catalog.load(content_dir)


def test_bad_reward_range_and_unreferenced_enemy(content_dir):
    edit(content_dir, "quests.json", lambda data: data[0]["reward"].update({
        "exp": {"minimum": 20, "maximum": 10},
    }))
    with pytest.raises(ValidationError, match="minimum"):
        Catalog.load(content_dir)


def test_unknown_species_and_enemy_cross_reference(content_dir):
    edit(content_dir, "pools.json", lambda data: data[0]["entries"][0].update({"species": "unknown"}))
    with pytest.raises(ValueError, match="unknown summon"):
        Catalog.load(content_dir)


def test_unknown_dungeon_enemy(content_dir):
    edit(content_dir, "dungeons.json", lambda data: data[0].update({"enemies": ["unknown"]}))
    with pytest.raises(ValueError, match="unknown dungeon enemies"):
        Catalog.load(content_dir)


def test_exploration_routes_reject_unknown_and_duplicate_encounters(content_dir):
    edit(content_dir, "exploration_routes.json", lambda data: data[0]["encounters"].__setitem__(0, "unknown"))
    with pytest.raises(ValueError, match="unknown exploration route encounters"):
        Catalog.load(content_dir)

    shutil.copytree(DATA_DIR, content_dir, dirs_exist_ok=True)
    edit(content_dir, "exploration_routes.json", lambda data: data[1]["encounters"].append("spring"))
    with pytest.raises(ValueError, match="exactly one route"):
        Catalog.load(content_dir)


def test_exploration_route_rejects_unknown_realm(content_dir):
    edit(content_dir, "exploration_routes.json", lambda data: data[0].update({"min_realm": "unknown"}))
    with pytest.raises(ValueError, match="unknown exploration route realm"):
        Catalog.load(content_dir)


def test_every_realm_requires_an_exploration_route(content_dir):
    edit(content_dir, "exploration_routes.json", lambda data: data[-1].update({"min_realm": "huashen"}))
    with pytest.raises(ValueError, match="missing exploration routes for realms"):
        Catalog.load(content_dir)


def test_content_rejects_implicit_numeric_coercion(content_dir):
    edit(content_dir, "pets.json", lambda data: data[0].update({"initial_affinity": "12"}))
    with pytest.raises(ValidationError):
        Catalog.load(content_dir)


@pytest.mark.parametrize("filename,change", [
    ("pets.json", lambda data: data[0].update({"category": "unknown"})),
    ("pets.json", lambda data: data[0].update({"elements": ["unknown"]})),
    ("skills.json", lambda data: data[0].update({"element": "water"})),
    ("skills.json", lambda data: data[0].update({"book_item": "spirit_food"})),
    ("skills.json", lambda data: data[0]["requirements"].update({"elements": ["fire", "water"]})),
    ("equipment.json", lambda data: data[0]["requirements"].update({"categories": ["unknown"]})),
    ("items.json", lambda data: data[0].update({"skill_id": "fireball"})),
])
def test_invalid_battle_content_rejected_at_startup(content_dir, filename, change):
    edit(content_dir, filename, change)
    with pytest.raises(ValueError):
        Catalog.load(content_dir)


@pytest.mark.parametrize("change,error", [
    (lambda rows: rows[0].update({"items": ["wind_feather", "frost_beak"]}), "distinct slots"),
    (lambda rows: rows[0].update({"items": ["unknown", "spirit_bell"]}), "unknown equipment set items"),
])
def test_equipment_sets_are_validated(content_dir, change, error):
    edit(content_dir, "equipment_sets.json", change)
    with pytest.raises(ValueError, match=error):
        Catalog.load(content_dir)


@pytest.mark.parametrize("change,error", [
    (lambda enemy: enemy.update(signature_skill="unknown", skill_every=3), "unknown enemy signature skill"),
    (lambda enemy: enemy.update(signature_skill="fireball"), "configured together"),
    (lambda enemy: enemy.update(signature_skill="ice_lance", skill_every=3), "incompatible with enemy elements"),
    (lambda enemy: enemy.update(signature_skill="thunder_roar", skill_every=3), "incompatible with enemy elements"),
])
def test_enemy_signature_skill_content_is_validated(content_dir, change, error):
    edit(content_dir, "enemies.json", lambda rows: change(rows[0]))
    with pytest.raises((ValueError, ValidationError), match=error):
        Catalog.load(content_dir)


def test_weighted_selection_boundary_and_invalid_weights():
    class Random:
        def random(self):
            return 0.5

    assert weighted_choice(Random(), ["a", "b"], [1, 1]) == "b"
    with pytest.raises(ValueError):
        weighted_choice(Random(), ["a"], [0])
    with pytest.raises(ValueError):
        weighted_choice(Random(), ["a"], [-1])
