import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.domain.battle_content import Skill, SkillEffect

from .support import sql


@pytest.mark.parametrize("data", [
    {"kind": "stun", "target": "enemy", "duration": 2},
    {"kind": "stun", "target": "enemy", "duration": 1, "power": 0.1},
    {"kind": "stun", "target": "self", "duration": 1},
    {"kind": "weaken", "target": "ally", "duration": 1, "power": 0.2},
    {"kind": "weaken", "target": "enemy", "duration": 0, "power": 0.2},
    {"kind": "ward", "target": "self", "duration": 4, "power": 0.2},
    {"kind": "empower", "target": "self", "duration": 2, "power": 0.0},
    {"kind": "cleanse", "target": "enemy"},
    {"kind": "cleanse", "target": "self", "duration": 1},
    {"kind": "dispel", "target": "enemy", "power": 0.1},
    {"kind": "dispel", "target": "ally"},
    {"kind": "ward", "target": "self", "duration": 1, "power": 0.2, "expires_at": 1},
])
def test_effect_definitions_reject_invalid_target_duration_power_and_runtime_state(data):
    with pytest.raises(ValidationError):
        SkillEffect.model_validate(data)


@pytest.mark.parametrize("kind,coefficient,effects", [
    ("damage", 0.0, []),
    ("heal", 0.0, []),
    ("utility", 0.0, []),
    ("utility", 1.0, [{"kind": "cleanse", "target": "self"}]),
    ("damage", 1.0, [{"kind": "cleanse", "target": "self"}]),
    ("heal", 0.2, [{"kind": "dispel", "target": "enemy"}]),
    ("utility", 0.0, [{"kind": "cleanse", "target": "self"}, {"kind": "dispel", "target": "enemy"}]),
    ("utility", 0.0, [{"kind": "cleanse", "target": "self"}] * 2),
])
def test_skill_effect_contract_rejects_ambiguous_or_empty_skills(kind, coefficient, effects):
    with pytest.raises(ValidationError):
        Skill(
            id="test", name="Test", description="Test", element=None,
            requirements={"min_realm": "qiling"}, kind=kind, coefficient=coefficient,
            book_item="book_test", effects=effects,
        )


@pytest.mark.parametrize("skill_id,species_id", [
    ("ice_seal", "hanying"), ("poison_sapping", "duman"), ("earthen_ward", "baize"),
    ("pure_breath", "qingluan"), ("spirit_dispel", "qingluan"), ("battle_chant", "qingluan"),
])
def test_every_new_effect_skill_has_a_buyable_book_and_can_be_learned(game, play, skill_id, species_id):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    sql(game[1], "UPDATE pets SET realm=1, species_id=?", (species_id,))
    skill = game[0].content.skills[skill_id]
    book = game[0].content.items[skill.book_item]
    assert skill.effects and book.price is not None
    play("buy", book.name)
    play("learn", skill.name)
    assert sql(game[1], "SELECT * FROM learned_skills WHERE skill_id=?", (skill_id,))
