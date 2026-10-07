import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.domain.arena_content import ArenaRules


@pytest.fixture
def arena_dir(tmp_path):
    directory = tmp_path / "content"
    shutil.copytree(DATA_DIR, directory)
    return directory


def edit(directory, change):
    path = directory / "arena.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_default_arena_rules_and_rewards_are_explicit():
    content = Catalog.load()
    rules = content.arena
    assert rules.model_dump(exclude={"tiers"}) == {
        "initial_rating": 1000,
        "min_realm": "ningqi",
        "max_rating_gap": 200,
        "daily_matches": 5,
        "pair_daily_matches": 1,
        "pair_season_matches": 3,
        "reward_matches": 10,
        "reward_opponents": 4,
        "rating_delta": 20,
        "energy": 20,
    }
    assert [tier.model_dump() for tier in rules.tiers] == [
        {
            "id": "qingyun", "name": "青云", "minimum_rating": 0,
            "stones": 300, "items": {"forge_ore": 3},
        },
        {
            "id": "lingxiao", "name": "凌霄", "minimum_rating": 1050,
            "stones": 600, "items": {"forge_ore": 6, "bloodline_essence": 2},
        },
        {
            "id": "tianque", "name": "天阙", "minimum_rating": 1150,
            "stones": 1000, "items": {"forge_ore": 10, "bloodline_essence": 4},
        },
    ]
    assert "pvp_energy" not in content.rules.model_dump()
    assert "pvp_rating_delta" not in content.rules.model_dump()
    assert ArenaRules.model_validate_json(rules.model_dump_json()) == rules


@pytest.mark.parametrize("field", [
    "initial_rating", "min_realm", "max_rating_gap", "daily_matches",
    "pair_daily_matches", "pair_season_matches", "reward_matches",
    "reward_opponents", "rating_delta", "energy", "tiers",
])
def test_all_arena_rule_fields_are_required(arena_dir, field):
    edit(arena_dir, lambda data: data.pop(field))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("field", ["id", "name", "minimum_rating", "stones", "items"])
def test_all_arena_tier_fields_are_required(arena_dir, field):
    edit(arena_dir, lambda data: data["tiers"][0].pop(field))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("field", [
    "initial_rating", "max_rating_gap", "daily_matches", "pair_daily_matches",
    "pair_season_matches", "reward_matches", "reward_opponents", "rating_delta", "energy",
])
@pytest.mark.parametrize("value", ["1", 1.0, True, None])
def test_arena_numbers_reject_implicit_coercion(arena_dir, field, value):
    edit(arena_dir, lambda data: data.update({field: value}))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("field,value", [
    ("initial_rating", -1), ("initial_rating", 1_000_001),
    ("max_rating_gap", 0), ("max_rating_gap", 10_001),
    ("daily_matches", 0), ("daily_matches", 101),
    ("pair_daily_matches", 0), ("pair_daily_matches", 101),
    ("pair_season_matches", 0), ("pair_season_matches", 10_001),
    ("reward_matches", 0), ("reward_matches", 10_001),
    ("reward_opponents", 0), ("reward_opponents", 1_001),
    ("rating_delta", 0), ("rating_delta", 10_001),
    ("energy", 0), ("energy", 101),
])
def test_arena_numbers_are_bounded(arena_dir, field, value):
    edit(arena_dir, lambda data: data.update({field: value}))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("change,message", [
    ({"pair_daily_matches": 6, "pair_season_matches": 6}, "daily matches"),
    ({"pair_daily_matches": 4, "pair_season_matches": 3}, "pair season matches"),
    ({"reward_opponents": 11}, "reward opponents"),
    ({"reward_matches": 141}, "shortest season capacity"),
])
def test_incoherent_or_unreachable_arena_quotas_are_rejected(arena_dir, change, message):
    edit(arena_dir, lambda data: data.update(change))
    with pytest.raises(ValidationError, match=message):
        Catalog.load(arena_dir)


def test_reward_opponents_is_a_minimum_not_a_limit(arena_dir):
    edit(arena_dir, lambda data: data.update(pair_season_matches=2))
    rules = Catalog.load(arena_dir).arena
    assert rules.reward_matches > rules.reward_opponents * rules.pair_season_matches


def test_shortest_season_capacity_boundary_is_reachable(arena_dir):
    edit(arena_dir, lambda data: data.update(reward_matches=140, reward_opponents=140))
    rules = Catalog.load(arena_dir).arena
    assert rules.reward_matches == rules.daily_matches * 28


@pytest.mark.parametrize("field", [
    "created_at", "started_at", "ends_at", "claimed_at", "expires_at", "cooldown",
    "duration", "duration_seconds", "season_id", "owner_id", "pet_id", "rating",
    "matches", "opponents", "state", "exp",
])
@pytest.mark.parametrize("nested", [False, True])
def test_arena_rejects_time_player_state_and_experience(arena_dir, field, nested):
    def change(data):
        target = data["tiers"][0] if nested else data
        target[field] = 1

    edit(arena_dir, change)
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("change,message", [
    (lambda data: data.update(tiers=[]), "tiers"),
    (lambda data: data["tiers"][0].update(minimum_rating=1), "begin at zero"),
    (lambda data: data["tiers"][1].update(id="qingyun"), "duplicate arena tier id"),
    (lambda data: data["tiers"][1].update(name="青云"), "duplicate arena tier name"),
    (lambda data: data["tiers"][1].update(minimum_rating=0), "strictly increase"),
    (lambda data: data["tiers"].reverse(), "begin at zero"),
    (lambda data: data["tiers"][2].update(minimum_rating=1000), "strictly increase"),
    (lambda data: data["tiers"][0].update(stones=0, items={}), "must not be empty"),
    (lambda data: data["tiers"][1].update(stones=299), "must not decrease"),
    (lambda data: data["tiers"][1]["items"].update(forge_ore=2), "must not decrease"),
    (lambda data: data["tiers"][1]["items"].pop("forge_ore"), "must not decrease"),
    (lambda data: data["tiers"][2]["items"].pop("bloodline_essence"), "must not decrease"),
])
def test_invalid_or_regressive_arena_tiers_are_rejected(arena_dir, change, message):
    edit(arena_dir, change)
    with pytest.raises(ValidationError, match=message):
        Catalog.load(arena_dir)


@pytest.mark.parametrize("field,value", [
    ("minimum_rating", -1), ("minimum_rating", 1_000_001),
    ("minimum_rating", "0"), ("minimum_rating", False),
    ("stones", -1), ("stones", 1_000_001), ("stones", "300"), ("stones", True),
    ("items", {"forge_ore": 0}), ("items", {"forge_ore": 1_000_001}),
    ("items", {"forge_ore": "3"}), ("items", {"forge_ore": True}),
    ("items", {"bad-id": 3}), ("id", "Bad-ID"), ("name", ""),
])
def test_arena_tier_fields_are_strict_and_bounded(arena_dir, field, value):
    edit(arena_dir, lambda data: data["tiers"][0].update({field: value}))
    with pytest.raises(ValidationError, match=field):
        Catalog.load(arena_dir)


def test_equal_rewards_and_one_currency_are_allowed(arena_dir):
    def change(data):
        for tier in data["tiers"]:
            tier.update(stones=0, items={"forge_ore": 3})

    edit(arena_dir, change)
    assert all(tier.stones == 0 for tier in Catalog.load(arena_dir).arena.tiers)

    def stones_only(data):
        for tier in data["tiers"]:
            tier.update(stones=100, items={})

    edit(arena_dir, stones_only)
    assert all(not tier.items for tier in Catalog.load(arena_dir).arena.tiers)


def test_arena_realm_reference_is_required(arena_dir):
    edit(arena_dir, lambda data: data.update(min_realm="unknown"))
    with pytest.raises(ValueError, match="unknown arena realm"):
        Catalog.load(arena_dir)


def test_arena_reward_item_reference_is_required(arena_dir):
    edit(arena_dir, lambda data: data["tiers"][-1]["items"].update(unknown=1))
    with pytest.raises(ValueError, match="unknown arena tier reward items"):
        Catalog.load(arena_dir)


def test_arena_root_must_be_an_object(arena_dir):
    path = arena_dir / "arena.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValidationError):
        Catalog.load(arena_dir)


def test_arena_duplicate_json_keys_are_rejected(arena_dir):
    path = arena_dir / "arena.json"
    path.write_text('{"energy":20,"energy":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        Catalog.load(arena_dir)


def test_arena_rules_and_tiers_are_frozen():
    rules = Catalog.load().arena
    with pytest.raises(ValidationError, match="frozen"):
        rules.energy = 1
    with pytest.raises(ValidationError, match="frozen"):
        rules.tiers[0].stones = 1


@pytest.mark.parametrize("field", ["pvp_energy", "pvp_rating_delta"])
def test_obsolete_shared_rules_are_rejected(arena_dir, field):
    path = arena_dir / "rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = 20
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(arena_dir)
