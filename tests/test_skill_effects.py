import pytest

from nonebot_plugin_spirit_pet.domain.battle_content import Skill, Talent
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.gameplay import effects, talents
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, _act, fight

from .test_talents import StableRandom
from .support import sql


def fighter(name="unit", attack=20, speed=10, hp=100, skills=(), **kwargs):
    return Fighter.create(name, Stats(hp=hp, attack=attack, defense=0, speed=speed), skills=skills, **kwargs)


def active(kind, target="self", power=0.0, duration=0, skill_kind="utility", coefficient=0.0):
    return Skill(
        id="test", name="Test", description="Test", element=None,
        requirements={"min_realm": "qiling"}, kind=skill_kind, coefficient=coefficient,
        book_item="book_test", effects=[{"kind": kind, "target": target, "power": power, "duration": duration}],
    )


def apply(skill, caster, target=None, allies=None):
    target = target or caster
    planned = effects.plan(caster, skill, target, allies or [caster])
    return effects.apply(caster, skill, planned)


@pytest.mark.parametrize("caster_speed", [5, 20])
def test_repeated_fast_and_slow_control_always_allows_an_entire_action(caster_speed):
    freeze = active("stun", "enemy", duration=1, skill_kind="damage", coefficient=1.0)
    controller = fighter("controller", attack=1, speed=caster_speed, hp=10000, skills=(freeze,), pet_id=1)
    target = fighter("target", attack=1, speed=10, hp=10000)
    result = fight([controller], [target], StableRandom())
    assert result.rounds == 40
    assert target.turns == 40
    assert target.actions == 20
    assert result.skill_uses[0][1]["test"] == 40


def test_two_enemies_cannot_alternate_control_into_a_permanent_lock():
    freeze = active("stun", "enemy", duration=1, skill_kind="damage", coefficient=1.0)
    controllers = [fighter("fast", 1, 30, 10000, (freeze,)), fighter("slow", 1, 10, 10000, (freeze,))]
    target = fighter("target", attack=1, speed=20, hp=10000)
    fight(controllers, [target], StableRandom())
    assert target.turns == 40
    assert target.actions == 20


def test_controlled_actions_consume_temporary_effect_duration():
    unit = fighter()
    apply(active("ward", power=0.2, duration=1), unit)
    apply(active("empower", power=0.2, duration=1), unit)
    apply(active("weaken", "enemy", power=0.2, duration=1), fighter(), unit)
    apply(active("stun", "enemy", duration=1), fighter(), unit)
    unit.turns += 1
    assert effects.skip_action(unit)
    effects.finish_action(unit)
    assert unit.effects.ward is unit.effects.empower is unit.effects.weaken is None
    assert unit.effects.control_immunity == 1


def test_new_self_ward_lasts_its_full_following_actions_without_stacking():
    ward = active("ward", power=0.2, duration=2)
    unit = fighter()
    unit.turns = 1
    assert apply(ward, unit)
    assert not apply(ward, unit)
    assert unit.effects.ward.value == 20
    effects.finish_action(unit)
    assert unit.effects.ward.remaining == 2
    unit.turns += 1
    effects.finish_action(unit)
    assert unit.effects.ward.remaining == 1
    assert apply(ward, unit)
    assert unit.effects.ward.value == 20
    assert unit.effects.ward.remaining == 2
    unit.turns += 1
    effects.finish_action(unit)
    unit.turns += 1
    effects.finish_action(unit)
    assert unit.effects.ward is None


def test_ward_absorbs_before_innate_shield_and_refresh_does_not_add_capacity():
    unit = fighter()
    unit.shield = 10
    ward = active("ward", power=0.2, duration=2)
    apply(ward, unit)
    assert talents.receive_damage(unit, 15) == (0, 15)
    assert unit.effects.ward.value == 5
    assert unit.shield == 10
    apply(ward, unit)
    assert unit.effects.ward.value == 20
    assert talents.receive_damage(unit, 35) == (5, 30)
    assert unit.effects.ward is None
    assert unit.shield == 0


def test_skill_level_scales_ward_but_not_debuff_strength_or_duration():
    caster, target = fighter(skill_multipliers={"test": 2.0}), fighter()
    apply(active("ward", power=0.2, duration=2), caster)
    assert caster.effects.ward.value == 40
    apply(active("weaken", "enemy", power=0.25, duration=2), caster, target)
    assert target.effects.weaken.value == 0.25
    assert target.effects.weaken.remaining == 2


def test_weaken_and_empower_modify_direct_damage_and_counter_without_mutating_base_stats():
    unit = fighter(attack=100)
    apply(active("weaken", "enemy", power=0.4, duration=2), fighter(), unit)
    apply(active("empower", power=0.5, duration=2), unit)
    assert effects.attack(unit) == 90
    assert unit.stats.attack == 100
    unit.talent = Talent(id="counter", name="Counter", description="Counter", kind="counter", power=0.5)
    attacker = fighter()
    talents.after_hit(attacker, unit, 1)
    assert attacker.hp == 55


def test_same_type_refresh_preserves_stronger_effect_without_adding_percentages():
    caster, target = fighter(), fighter()
    apply(active("weaken", "enemy", power=0.4, duration=1), caster, target)
    apply(active("weaken", "enemy", power=0.2, duration=3), caster, target)
    assert target.effects.weaken.value == 0.4
    assert target.effects.weaken.remaining == 3
    assert effects.attack(target) == 12


def test_cleanse_clears_negative_effects_not_buffs_and_protects_one_following_action():
    healer, target = fighter(), fighter()
    target.poison_damage, target.poison_turns = 10, 3
    apply(active("ward", power=0.2, duration=2), target)
    apply(active("empower", power=0.2, duration=2), target)
    apply(active("weaken", "enemy", power=0.2, duration=2), healer, target)
    stun = active("stun", "enemy", duration=1)
    apply(stun, healer, target)
    apply(active("cleanse", "ally"), healer, target, [healer, target])
    assert target.poison_damage == target.poison_turns == 0
    assert target.effects.weaken is None and not target.effects.stunned
    assert target.effects.ward and target.effects.empower
    assert not apply(stun, healer, target)
    target.turns += 1
    assert not effects.skip_action(target)
    effects.finish_action(target)
    assert apply(stun, healer, target)


def test_dispel_removes_both_shields_and_attack_buff_but_not_negative_effects():
    caster, target = fighter(), fighter()
    target.shield = 10
    target.poison_damage, target.poison_turns = 5, 3
    apply(active("ward", power=0.2, duration=2), target)
    apply(active("empower", power=0.2, duration=2), target)
    apply(active("weaken", "enemy", power=0.2, duration=2), caster, target)
    apply(active("dispel", "enemy"), caster, target)
    assert target.shield == 0
    assert target.effects.ward is target.effects.empower is None
    assert target.effects.weaken and target.poison_turns == 3


def test_full_health_healing_can_cast_for_effective_ally_cleanse_and_uses_one_selected_target():
    cleansing = active("cleanse", "ally", skill_kind="heal", coefficient=0.1)
    caster = fighter("healer", skills=(cleansing,), pet_id=1)
    first, second = fighter("first"), fighter("second")
    first.poison_damage, first.poison_turns = 10, 3
    second.poison_damage, second.poison_turns = 10, 3
    second.effects.stunned = True
    _act(caster, [caster, first, second], [fighter("enemy")], StableRandom(), {}, [])
    assert caster.hp == caster.stats.hp
    assert caster.skill_uses == {"test": 1}
    assert first.poison_turns == 3
    assert second.poison_turns == 0 and not second.effects.stunned


def test_utility_enemy_is_selected_once_from_applicable_targets():
    dispel = active("dispel", "enemy")
    caster = fighter(skills=(dispel,))
    first, second = fighter("first"), fighter("second")
    second.shield = 25
    _act(caster, [caster], [first, second], StableRandom(), {}, [])
    assert second.shield == 0
    assert caster.skill_uses == {"test": 1}
    assert first.hp == second.hp == 100


def test_empty_healing_and_empty_utility_fall_back_without_mastery(game):
    for skill in (game[0].content.skills["pure_breath"], game[0].content.skills["spirit_dispel"]):
        caster = fighter(skills=(skill,), primary_element="earth")
        target = fighter(primary_element="water")
        _act(caster, [caster], [target], StableRandom(), game[0].content.elements, [])
        assert caster.skill_uses == {}
        assert target.hp == 75


def test_damage_effect_can_control_through_shields_but_not_evasion():
    freeze = active("stun", "enemy", duration=1, skill_kind="damage", coefficient=1.0)
    caster, target = fighter(skills=(freeze,)), fighter()
    target.shield = 100
    _act(caster, [caster], [target], StableRandom(), {}, [])
    assert target.hp == 100 and target.effects.stunned
    target = fighter(talent=Talent(id="evade", name="Evade", description="Evade", kind="evasion", power=1.0))
    _act(caster, [caster], [target], StableRandom(), {}, [])
    assert not target.effects.stunned and target.hp == 100
    assert caster.skill_uses == {"test": 2}


def test_controlled_caster_cannot_self_cleanse_and_gains_no_mastery():
    cleanse = active("cleanse", "self", skill_kind="heal", coefficient=0.2)
    caster = fighter(skills=(cleanse,), pet_id=1)
    caster.effects.stunned = True
    enemy = fighter(attack=1000, speed=1)
    result = fight([caster], [enemy], StableRandom())
    assert result.winner == 1
    assert result.skill_uses[0][1] == {}


def test_effect_runtime_state_is_local_to_the_fighter_and_encounter():
    first, second = fighter(), fighter()
    apply(active("ward", power=0.2, duration=2), first)
    assert first.effects.ward is not None
    assert second.effects.ward is None
    assert not second.effects.stunned


def test_ward_skill_runs_through_real_pve_and_awards_mastery_once(game, play):
    play("adopt", "白泽")
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "岩灵护障诀")
    play("learn", "岩灵护障")
    before = sql(game[1], "SELECT * FROM learned_skills")
    result = play("challenge", "青岚林", op="ward-pve")
    after = sql(game[1], "SELECT * FROM learned_skills")
    assert "临时护盾" in result.text()
    assert after != before
    assert play("challenge", "青岚林", op="ward-pve") == result
    assert sql(game[1], "SELECT * FROM learned_skills") == after
    assert not any("effects" in row or "stunned" in row for row in sql(game[1], "SELECT * FROM pets"))


def test_dispel_works_in_consented_pvp_and_only_real_dispel_is_counted(game, play):
    play("adopt", "青鸾")
    play("adopt", "白泽", user="u2")
    play("dao_name", "护盾道友", user="u2")
    sql(game[1], "UPDATE pets SET realm=1")
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    play("buy", "破障术诀")
    play("learn", "破障术")
    play("pvp", "护盾道友")
    result = play("accept", user="u2", op="dispel-pvp")
    assert "已驱散" in result.text()
    row = sql(game[1], "SELECT * FROM learned_skills WHERE skill_id='spirit_dispel'")[0]
    assert row["level"] == 1
    assert row["proficiency"] == game[0].content.rules.skill_proficiency_per_use
    assert play("accept", user="u2", op="dispel-pvp") == result
    assert sql(game[1], "SELECT * FROM learned_skills WHERE skill_id='spirit_dispel'")[0] == row
