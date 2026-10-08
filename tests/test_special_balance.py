from copy import deepcopy

import pytest

from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import effects
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter
from scripts.balance.effect_observer import observe_effects
from scripts.balance.report import evaluate
from scripts.balance.scenarios import build_fighters, scenarios
from scripts.balance.special_report import coverage, evaluate_special, run_special_report
from scripts.balance.special_scenarios import build_special, special_scenarios

from .support import sql


def test_special_matrix_preserves_basic_matrix_and_covers_every_new_definition(game):
    content = game[0].content
    matrix = special_scenarios(content)
    assert len(scenarios(content)) == 626
    assert len(matrix) == 124
    assert len({case.id for case in matrix}) == len(matrix)
    assert {case.subject for case in matrix if case.category == "lineage"} == set(content.lineages)
    assert {case.subject for case in matrix if case.category == "effect"} == {
        skill.id for skill in content.skills.values() if skill.effects
    }
    assert {case.subject for case in matrix if case.category == "skill"} == {"spirit_wave"}


def test_every_effect_is_cast_and_really_changes_state_in_actual_battle(game):
    service, store = game
    report = run_special_report(store, service.content, service.config, 2, 20261007)
    assert report["issues"] == []
    assert report["coverage"]["lineages_exercised"] == 54
    assert report["coverage"]["effects_triggered"] == 7
    assert all(row["max_rounds"] <= 40 for row in report["scenarios"])
    for row in report["scenarios"]:
        assert row["wins"] + row["draws"] + row["losses"] == 2
        if row["category"] == "effect" and row["variant"] == "selected":
            assert row["tracked_skill_casts"] > 0
            assert row["actual_effect_activations"] > 0
    for table in ("players", "pets", "equipment", "learned_skills"):
        assert not sql(store, f"SELECT * FROM {table}")


def test_special_results_replay_independently_of_scenario_order(game):
    service, store = game
    selected = special_scenarios(service.content)[-4:]
    first = run_special_report(store, service.content, service.config, 3, 918, selected)
    second = run_special_report(store, service.content, service.config, 3, 918, list(reversed(selected)))
    assert first["scenarios"] == list(reversed(second["scenarios"]))
    assert first["content_sha256"] == second["content_sha256"]


def test_special_observer_does_not_modify_basic_simulation_results(game):
    service, store = game
    case = scenarios(service.content)[0]
    original = effects.apply
    before = evaluate(store, service.content, service.config, case, 3, 8)
    selected = [scenario for scenario in special_scenarios(service.content) if scenario.category == "effect"]
    run_special_report(store, service.content, service.config, 1, 8, selected)
    assert effects.apply is original
    assert evaluate(store, service.content, service.config, case, 3, 8) == before


def test_observer_restores_production_function_after_exception():
    original = effects.apply
    with pytest.raises(RuntimeError, match="simulation failed"):
        with observe_effects():
            assert effects.apply is not original
            raise RuntimeError("simulation failed")
    assert effects.apply is original


def test_observer_ignores_planned_effects_that_are_no_longer_effective(game):
    skill = game[0].content.skills["ice_seal"]
    stats = Stats(hp=100, attack=10, defense=0, speed=10)
    caster, target = Fighter.create("caster", stats), Fighter.create("target", stats)
    planned = ((skill.effects[0], target),)
    target.effects.control_immunity = 1
    with observe_effects() as observed:
        assert effects.apply(caster, skill, planned) == ()
        assert observed == {}
        target.effects.control_immunity = 0
        assert effects.apply(caster, skill, planned)
        assert observed == {("ice_seal", "stun"): 1}
        assert effects.apply(caster, skill, planned) == ()
        assert observed == {("ice_seal", "stun"): 1}


def test_report_shows_real_primary_and_skill_element_matchups(game):
    service, store = game
    case = next(case for case in special_scenarios(service.content)
                if case.subject == "ice_seal" and case.variant == "selected")
    row = evaluate_special(store, service.content, service.config, case, 2, 1)
    actor = row["left_units"][0]
    assert actor["primary_element"] == "ice"
    assert actor["basic_matchups"] == [1.25]
    assert actor["skills"][0]["element"] == "ice"
    assert actor["skills"][0]["damage_matchups"] == [1.25]


def test_area_skill_special_fixture_uses_selected_skill_and_multiple_targets(game):
    service, store = game
    case = next(case for case in special_scenarios(service.content)
                if case.subject == "spirit_wave" and case.variant == "selected")
    row = evaluate_special(store, service.content, service.config, case, 3, 17)
    control = evaluate_special(
        store,
        service.content,
        service.config,
        next(case for case in special_scenarios(service.content)
             if case.subject == "spirit_wave" and case.variant == "control"),
        3,
        17,
    )
    assert row["tracked_skill_casts"] > 0
    assert control["tracked_skill_casts"] == 0
    assert len(row["right_units"]) == 2
    assert row["invalid_states"] == 0


@pytest.mark.parametrize("species,realm,message", [("hanying", 0, "境界"), ("xuanhu", 1, "元素")])
def test_explicit_special_skills_must_pass_production_requirements(game, species, realm, message):
    service, store = game
    with pytest.raises(GameError, match=message):
        build_fighters(store, service.content, service.config, (species,), realm, "prepared",
                       skill_ids=(("ice_seal",),))
    assert not sql(store, "SELECT * FROM players")


def test_lineage_fixture_respects_species_and_minimum_bloodline(game):
    service, store = game
    case = next(case for case in special_scenarios(service.content) if case.category == "lineage")
    left, right = build_special(store, service.content, service.config, case)
    assert left and right
    with pytest.raises(GameError, match="分支数据无效"):
        build_fighters(store, service.content, service.config, case.party, case.realm, "prepared",
                       lineage_ids=(case.subject,), bloodlines=(0,))
    assert not sql(store, "SELECT * FROM pets")


def test_coverage_does_not_accept_casts_without_real_triggers(game):
    service, store = game
    report = run_special_report(store, service.content, service.config, 1, 20261007)
    rows = deepcopy(report["scenarios"])
    affected = next(row for row in rows if row["subject"] == "ice_seal" and row["variant"] == "selected")
    assert affected["tracked_skill_casts"] > 0
    affected["effect_activations"] = {}
    covered, issues = coverage(rows, service.content)
    assert covered["missing_effects"] == [["ice_seal", "stun"]]
    assert any("never actually triggered" in issue for issue in issues)
    affected["max_rounds"] = 41
    assert any("boundary violation" in issue for issue in coverage(rows, service.content)[1])


@pytest.mark.parametrize("runs", [0, -1, 10001, True, 1.5])
def test_special_report_rejects_invalid_trial_counts(game, runs):
    service, store = game
    with pytest.raises(ValueError):
        run_special_report(store, service.content, service.config, runs, 1, [])
