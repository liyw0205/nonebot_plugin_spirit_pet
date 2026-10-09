import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.balance.lineup_report import evaluate_lineup, lineup_audit, lineup_markdown, run_lineup_report
from scripts.balance.lineup_scenarios import lineup_fixture, lineup_scenarios
from scripts.balance.scenarios import build_fighters, scenarios

from .support import sql


def test_lineup_matrix_pairs_all_dungeons_with_existing_legal_baselines(game):
    content = game[0].content
    matrix = lineup_scenarios(content)
    base = {(case.dungeon_id, case.profile, case.species) for case in scenarios(content)}
    assert len(matrix) == 4 * len(content.dungeons) == 64
    assert {case.realm for case in matrix} == set(range(len(content.realms)))
    assert {sum(map(len, case.rosters)) for case in matrix} == {1, 3, 5}
    for case in matrix:
        assert all(1 <= len(roster) <= 3 and len(set(roster)) == len(roster) for roster in case.rosters)
        if case.variant == "baseline":
            assert (case.dungeon_id, case.profile, tuple(species for roster in case.rosters for species in roster)) in base
        else:
            control = next(item for item in matrix if item.seed_group == case.seed_group and item.variant == "baseline")
            assert case.rosters[1:] == control.rosters[1:]
            assert case.rosters[0][0] == control.rosters[0][0]


def test_lineup_fixture_uses_production_roster_and_same_prepared_loadout_as_base(game):
    service, store = game
    case = next(case for case in lineup_scenarios(service.content)
                if case.profile == "prepared" and sum(map(len, case.rosters)) == 5)
    species = tuple(species for roster in case.rosters for species in roster)
    base = build_fighters(store, service.content, service.config, species, case.realm, case.profile)
    with lineup_fixture(store, service.content, service.config, case) as (conn, users, owned, units):
        assert len(users) == 3 and list(map(len, owned)) == [3, 1, 1]
        assert [unit.pet_id for unit in units] == [pet_id for roster in owned for pet_id in roster]
        assert [unit.stats for unit in units] == [unit.stats for unit in base]
        assert [[skill.id for skill in unit.skills] for unit in units] == [[skill.id for skill in unit.skills] for unit in base]
        assert conn.execute("SELECT COUNT(*) FROM active_pet_slots").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0] == 3
    for table in ("players", "pets", "active_pet_slots", "teams", "team_members", "equipment", "learned_skills"):
        assert not sql(store, f"SELECT * FROM {table}")


def test_lineup_report_replays_independently_and_rolls_back_all_settlements(game):
    service, store = game
    selected = [case for case in lineup_scenarios(service.content)
                if case.dungeon_id in {"forest", "temple"} and case.profile == "prepared"]
    first = run_lineup_report(store, service.content, service.config, 3, 712, selected)
    reversed_report = run_lineup_report(store, service.content, service.config, 3, 712, list(reversed(selected)))
    assert first["scenarios"] == list(reversed(reversed_report["scenarios"]))
    assert first["content_sha256"] == reversed_report["content_sha256"]
    changed = replace(service.content, rules=service.content.rules.model_copy(update={"starter_stones": 999}))
    assert run_lineup_report(store, changed, service.config, 1, 712, [])['content_sha256'] != first['content_sha256']
    for row in first["scenarios"]:
        assert row["wins"] + row["losses"] + row["draws"] == 3
        assert not any(row["settlement_violations"].values())
    for table in ("players", "pets", "inventory", "battle_records", "battle_participants", "quest_progress", "operations"):
        assert not sql(store, f"SELECT * FROM {table}")


def test_three_and_five_pet_yields_charge_each_pet_and_pay_each_member_once(game):
    service, store = game
    selected = [case for case in lineup_scenarios(service.content)
                if case.dungeon_id in {"forest", "temple"} and case.profile == "prepared"]
    report = run_lineup_report(store, service.content, service.config, 4, 20261007, selected)
    for row in report["scenarios"]:
        assert row["wins"] == 4
        energy = service.content.dungeons[row["dungeon"]].energy
        expected_interval = max(energy * service.config.spirit_pet_energy_interval,
                                service.config.spirit_pet_pve_cooldown)
        assert row["sustainable_interval_seconds"] == expected_interval
        for member in row["members"]:
            assert member["observed_energy_per_pet"] == [[energy, energy]] * len(member["roster"])
            assert member["total_member_energy_per_attempt"] == energy * len(member["roster"])
            assert member["reward_sets_per_win"] == member["exp_recipient_pet_slot"] == 1
            low, high = row["reward_per_member_win_range"]["stones"]
            assert low <= member["sampled_reward_per_attempt"]["stones"] <= high
            assert member["expected_reward_per_hour"]["stones"] == round((low + high) / 2 * 3600 / expected_interval, 3)
    for pair in report["comparisons"]:
        assert pair["baseline_reward_sets_per_win"] == pair["multi_reward_sets_per_win"] == pair["member_count"]
        assert pair["baseline_member_stones_per_hour"] == pair["multi_member_stones_per_hour"]
    slow = service.config.model_copy(update={"spirit_pet_pve_cooldown": 10000})
    row = evaluate_lineup(store, service.content, slow, selected[1], 1, 1)
    assert row["members"][0]["sustainable_attempts_per_hour"] == 0.36


def test_lineup_report_detects_real_settlement_regressions(game, monkeypatch):
    from scripts.balance import lineup_report

    service, store = game
    case = next(case for case in lineup_scenarios(service.content)
                if case.dungeon_id == "forest" and case.profile == "prepared" and case.variant == "multi")
    run = lineup_report.run_dungeon

    def broken(ctx, *args):
        result = run(ctx, *args)
        extra = ctx.repo.active_pets(ctx.user_id)[1]
        extra.energy += 1
        extra.exp += 1
        ctx.player().stones += 10000
        return result

    monkeypatch.setattr(lineup_report, "run_dungeon", broken)
    row = evaluate_lineup(store, service.content, service.config, case, 2, 1)
    assert row["settlement_violations"]["energy"] == 2
    assert row["settlement_violations"]["non_primary_exp"] == 2
    assert row["settlement_violations"]["member_reward"] == 2
    assert any("production settlement violation" in issue for issue in lineup_audit([row], service.content))


def test_lineup_complete_quick_matrix_passes_and_gate_detects_missing_or_unviable_cases(game):
    service, store = game
    report = run_lineup_report(store, service.content, service.config, 2, 20261007)
    assert report["issues"] == []
    assert len(report["comparisons"]) == 32 and report["battle_count"] == 128
    assert "Exp/Hour Range/Member" in lineup_markdown(report)
    rows = report["scenarios"][1:]
    assert any("missing lineup scenario" in issue for issue in lineup_audit(rows, service.content))
    row = next(row for row in rows if row["profile"] == "prepared" and row["variant"] == "multi")
    row["win_rate"] = 0.69
    row["max_rounds"] = 41
    issues = lineup_audit(rows, service.content)
    assert any("below 70%" in issue for issue in issues)
    assert any("combat boundary violation" in issue for issue in issues)


@pytest.mark.parametrize("runs", [0, -1, 10001, True, 1.5])
def test_lineup_report_rejects_invalid_samples(game, runs):
    service, store = game
    with pytest.raises(ValueError):
        run_lineup_report(store, service.content, service.config, runs, 1, [])


def test_lineup_cli_exports_portable_reports_without_touching_configured_player_db(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "player.db"
    database.write_bytes(b"a player database must never be opened")
    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "balance_lineups.py"), "--runs", "1", "--seed", "20261007",
         "--check", "--json", str(json_path), "--markdown", str(markdown_path)],
        cwd=tmp_path, env={**os.environ, "SPIRIT_PET_DB": str(database), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["scenario_count"] == report["battle_count"] == 64
    assert report["issues"] == [] and "seed=20261007" in result.stdout
    assert report["content_sha256"] in markdown_path.read_text(encoding="utf-8")
    assert b"\r" not in markdown_path.read_bytes()
    assert database.read_bytes() == b"a player database must never be opened"
