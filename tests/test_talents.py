from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.battle_content import Skill, Talent
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, fight
from nonebot_plugin_spirit_pet.gameplay import talents
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql


class StableRandom:
    def randint(self, start, stop):
        return 100 if (start, stop) == (90, 110) else start

    def random(self):
        return 0.5


def unit(kind=None, power=0.5, **kwargs):
    talent = Talent(id="test", name="test", description="test", kind=kind, power=power) if kind else None
    stats = Stats(hp=100, attack=20, defense=10, speed=10)
    return Fighter.create("test", stats, talent=talent, **kwargs)


def skill(kind="damage"):
    return Skill(
        id="test", name="test", description="test", element=None,
        requirements={"min_realm": "mortal"}, kind=kind,
        coefficient=1.2 if kind == "damage" else 0.2, book_item="book_test",
    )


@pytest.mark.parametrize("kind", ["fury", "first_strike", "execute"])
def test_damage_talents_modify_real_attack_power(kind):
    attacker, target = unit(kind), unit()
    target.hp = 40
    assert talents.attack_modifiers(attacker, target, None, {}) == (1.5, 10, "test")
    if kind == "first_strike":
        attacker.attacks = 1
        assert talents.attack_modifiers(attacker, target, None, {}) == (1.0, 10, None)
    if kind == "execute":
        target.hp = 41
        assert talents.attack_modifiers(attacker, target, None, {}) == (1.0, 10, None)


def test_pierce_reduces_only_target_defense():
    attacker, target = unit("pierce"), unit()
    assert talents.attack_modifiers(attacker, target, None, {}) == (1.0, 5, "test")
    assert target.stats.defense == 10


def test_shield_absorbs_damage_without_changing_maximum_health():
    defender = unit("shield")
    assert talents.initialize(defender)
    assert defender.shield == 50
    assert talents.receive_damage(defender, 70) == (20, 50)
    assert defender.hp == 80
    assert defender.stats.hp == 100
    assert talents.receive_damage(defender, 200) == (80, 0)
    assert defender.hp == 0


def test_lifesteal_uses_actual_health_damage_and_caps_healing():
    attacker, target = unit("lifesteal"), unit()
    attacker.hp = 90
    talents.after_hit(attacker, target, 6)
    assert attacker.hp == 93
    talents.after_hit(attacker, target, 100)
    assert attacker.hp == 100
    attacker.hp = 90
    assert not talents.after_hit(attacker, target, 0)
    assert attacker.hp == 90


def test_counter_is_non_recursive_and_requires_survival():
    attacker, target = unit("counter"), unit("counter")
    events = talents.after_hit(attacker, target, 10)
    assert len(events) == 1
    assert attacker.hp == 95
    assert target.hp == 100
    target.hp = 0
    assert not talents.after_hit(attacker, target, 10)
    assert attacker.hp == 95


def test_regeneration_caps_at_maximum_and_cannot_resurrect_poison_death():
    defender = unit("regeneration")
    defender.hp = 80
    assert talents.before_action(defender)
    assert defender.hp == 100
    assert not talents.before_action(defender)
    defender.hp = 5
    defender.poison_damage = 10
    defender.poison_turns = 3
    assert len(talents.before_action(defender)) == 1
    assert defender.hp == 0


def test_venom_refreshes_without_stacking_and_expires_after_three_actions():
    attacker, target = unit("venom", 0.1), unit()
    talents.after_hit(attacker, target, 5)
    talents.after_hit(attacker, target, 5)
    assert target.poison_damage == 10
    assert target.poison_turns == 3
    for _ in range(4):
        talents.before_action(target)
    assert target.hp == 70
    assert target.poison_turns == 0
    assert target.poison_damage == 0
    talents.after_hit(unit("venom", 0.03), target, 1)
    assert target.poison_damage == 3
    assert attacker.hp == 100


def test_evasion_only_affects_direct_attacks():
    defender = unit("evasion", 0.6)
    assert talents.evades(defender, StableRandom())
    defender.poison_damage = 10
    defender.poison_turns = 1
    talents.before_action(defender)
    assert defender.hp == 90
    assert not talents.evades(unit("evasion", 0.4), StableRandom())


def test_skill_level_multiplier_changes_damage_and_tracks_real_casts():
    outcomes = []
    for multiplier in (1.0, 2.0):
        attacker = unit(pet_id=7, skills=(skill(),), skill_multipliers={"test": multiplier})
        target = Fighter.create("target", Stats(hp=1000, attack=1000, defense=0, speed=1))
        result = fight([attacker], [target], StableRandom())
        assert result.skill_uses == ({7: {"test": 1}}, {})
        outcomes.append(target.hp)
    assert outcomes == [976, 952]


def test_skill_level_multiplier_changes_healing_and_does_not_exceed_max_hp():
    attacker = unit(pet_id=7, skills=(skill("heal"),), skill_multipliers={"test": 2.0})
    attacker.hp = 20
    target = Fighter.create("target", Stats(hp=1000, attack=1000, defense=0, speed=1))
    result = fight([attacker], [target], StableRandom())
    assert any("恢复 40" in line for line in result.lines)
    assert result.skill_uses == ({7: {"test": 1}}, {})


def test_full_health_healing_falls_back_to_basic_attack_without_mastery():
    attacker = unit(pet_id=7, skills=(skill("heal"),))
    target = Fighter.create("target", Stats(hp=1, attack=1, defense=0, speed=1))
    result = fight([attacker], [target], StableRandom())
    assert result.winner == 0
    assert result.skill_uses == ({7: {}}, {})
    assert not any("施展" in line for line in result.lines)


def test_evaded_skill_is_still_cast_but_never_counts_a_counter_as_a_skill():
    attacker = unit(pet_id=7, skills=(skill(),))
    target = unit("evasion", 1.0, pet_id=8)
    result = fight([attacker], [target], StableRandom())
    assert result.skill_uses[0][7]["test"] > 0
    assert result.skill_uses[1][8] == {}
    assert target.hp == 100


def test_counters_can_end_combat_without_extra_turns():
    attacker = Fighter.create("left", Stats(hp=1, attack=1, defense=0, speed=10))
    target = unit("counter")
    result = fight([attacker], [target], StableRandom())
    assert result.winner == 1
    assert result.rounds == 1
    assert any("反击" in line for line in result.lines)


def test_talent_combat_remains_bounded_and_logs_remain_short():
    left, right = unit("regeneration"), unit("regeneration")
    result = fight([left], [right], StableRandom())
    assert result.winner == -1
    assert result.rounds == 40
    assert len(result.lines) <= 8


def test_loadout_connects_persistent_levels_equipment_and_species_talent(game, play):
    play("adopt", "青鸾")
    service, store = game

    def current():
        with closing(store.connect()) as conn:
            ctx = Context(Repository(conn), service.content, service.config, service.rng, "u1", 1_800_000_000, "talent-test")
            return combatant(ctx)

    baseline = current()
    sql(store, "UPDATE players SET stones=10000")
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    play("buy", "风刃术诀")
    play("learn", "风刃术")
    plain = current()
    sql(store, "UPDATE equipment SET enhancement=1")
    sql(store, "UPDATE learned_skills SET level=2")
    upgraded = current()
    item = service.content.items["wind_feather"]
    gear = service.content.equipment[item.equipment_id]
    multiplier = service.content.forge_levels[1].bonus_multiplier
    for key, bonus in gear.bonuses.model_dump().items():
        assert getattr(upgraded.stats, key) == getattr(baseline.stats, key) + int(bonus * multiplier)
    assert upgraded.stats.attack > plain.stats.attack
    assert plain.skill_multipliers["wind_slash"] == service.content.skill_levels[1].power_multiplier
    assert upgraded.skill_multipliers["wind_slash"] == service.content.skill_levels[2].power_multiplier
    assert upgraded.primary_element == service.content.species["qingluan"].primary_element
    assert upgraded.talent == service.content.talents[service.content.species["qingluan"].talent]
    assert upgraded.pet_id == baseline.pet_id
