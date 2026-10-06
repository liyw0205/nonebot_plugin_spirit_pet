from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from scripts.balance.report import audit, evaluate, run_report
from scripts.balance.scenarios import Scenario, build_fighters, scenarios

from .support import sql


def test_all_realms_have_solo_and_team_content(game):
    content = game[0].content
    matrix = scenarios(content)
    covered = {(scenario.realm, len(scenario.species)) for scenario in matrix}
    assert covered == {(realm, size) for realm in range(len(content.realms)) for size in (1, 2, 3)}
    for dungeon in content.dungeons.values():
        assert any(scenario.dungeon_id == dungeon.id for scenario in matrix)


def test_simulation_uses_production_loadout_without_changing_database(game):
    service, store = game
    units = build_fighters(store, service.content, service.config, ("qingluan", "xuanhu"), 2, "prepared")
    assert len(units) == 2 and all(unit.skills and unit.talent and unit.primary_element for unit in units)
    assert units[0].primary_element == "wind"
    assert not sql(store, "SELECT * FROM players")
    assert not sql(store, "SELECT * FROM pets")
    assert not sql(store, "SELECT * FROM equipment")
    assert not sql(store, "SELECT * FROM learned_skills")


def test_results_replay_exactly_and_do_not_depend_on_scenario_order(game):
    service, store = game
    selected = scenarios(service.content)[:2]
    first = run_report(store, service.content, service.config, 8, 812, selected)
    second = run_report(store, service.content, service.config, 8, 812, list(reversed(selected)))
    assert first["scenarios"] == list(reversed(second["scenarios"]))
    assert first["content_sha256"] == second["content_sha256"]
    modified = replace(service.content, rules=service.content.rules.model_copy(update={"starter_stones": 999}))
    different = run_report(store, modified, service.config, 1, 812, selected)
    assert different["content_sha256"] != first["content_sha256"]


def test_unit_time_yield_accounts_for_energy_not_just_cooldown(game):
    service, store = game
    scenario = Scenario("yield", "forest", 0, "prepared", ("qingluan",))
    result = evaluate(store, service.content, service.config, scenario, 5, 1)
    assert result["wins"] == 5
    assert result["sustainable_attempts_per_hour"] == 0.6
    assert result["expected_stones_per_attempt"] == 60
    assert result["expected_stones_per_hour"] == 36
    config = service.config.model_copy(update={"spirit_pet_pve_cooldown": 10000})
    slowed = evaluate(store, service.content, config, scenario, 5, 1)
    assert slowed["sustainable_attempts_per_hour"] == 0.36


def test_prepared_parties_have_a_viable_path_at_every_realm(game):
    service, store = game
    selected = [scenario for scenario in scenarios(service.content) if scenario.profile == "prepared"]
    rows = [evaluate(store, service.content, service.config, scenario, 10, 20261007) for scenario in selected]
    assert audit(rows, service.content) == []
    assert all(row["wins"] + row["losses"] + row["draws"] == 10 for row in rows)


def test_audit_reports_absent_tiers_and_unwinnable_prepared_scenarios(game):
    service, store = game
    scenario = Scenario("losing", "forest", 0, "prepared", ("qingluan",))
    row = evaluate(store, service.content, service.config, scenario, 1, 1)
    row["wins"] = 0
    row["max_rounds"] = 41
    issues = audit([row], service.content)
    assert any("missing realm/party coverage" in issue for issue in issues)
    assert any("never won" in issue for issue in issues)
    assert any("round bound" in issue for issue in issues)


@pytest.mark.parametrize("runs", [0, -1, 10001, True, 1.5])
def test_simulation_rejects_invalid_sample_counts(game, runs):
    service, store = game
    with pytest.raises(ValueError):
        run_report(store, service.content, service.config, runs, 1, [])


def test_dungeon_pages_and_details_expose_actual_content(game, play):
    content = game[0].content
    pages = (len(content.dungeons) + 4) // 5
    lines = []
    for page in range(1, pages + 1):
        reply = play("dungeons", str(page))
        assert len(reply.lines) <= 5
        lines.extend(reply.lines)
    assert len(lines) == len(content.dungeons)
    for dungeon in content.dungeons.values():
        detail = play("dungeons", dungeon.name)
        for enemy_id in dungeon.enemies:
            enemy = content.enemies[enemy_id]
            assert content.elements[enemy.primary_element].name in detail.text()
            assert str(enemy.stats.hp) in detail.text()
        for item_id in dungeon.reward.items:
            assert content.items[item_id].name in detail.text()
    with pytest.raises(GameError):
        play("dungeons", str(pages + 1))
