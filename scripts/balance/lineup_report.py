import hashlib
import json
from random import Random

from pydantic import TypeAdapter

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.gameplay.adventure import run_dungeon
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .lineup_scenarios import SIMULATION_NOW, lineup_fixture, lineup_scenarios

PREPARED_MULTI_WIN_RATE_FLOOR = 0.7


def _bounds(reward):
    return {"exp": (reward.exp.minimum, reward.exp.maximum),
            "stones": (reward.stones.minimum, reward.stones.maximum),
            **{f"item:{key}": (value.minimum, value.maximum) for key, value in reward.items.items()}}


def evaluate_lineup(store, content, config, scenario, runs: int, seed: int) -> dict:
    dungeon = content.dungeons[scenario.dungeon_id]
    bounds = _bounds(dungeon.reward)
    digest = hashlib.sha256(scenario.seed_group.encode("utf-8")).digest()
    derived_seed = seed ^ int.from_bytes(digest[:8], "big")
    wins = draws = total_rounds = max_rounds = 0
    violations = {key: 0 for key in ("energy", "non_primary_exp", "member_reward", "quest_progress", "snapshot")}
    sustainable_interval = max(config.spirit_pet_pve_cooldown, dungeon.energy * config.spirit_pet_energy_interval)
    attempts_per_hour = 3600 / sustainable_interval
    with lineup_fixture(store, content, config, scenario) as (conn, users, pet_ids, units):
        totals = [{key: 0 for key in bounds} for _ in users]
        observed = [{key: [None, None] for key in bounds} for _ in users]
        energy_ranges = [[[None, None] for _ in owned] for owned in pet_ids]
        for trial in range(runs):
            conn.execute("SAVEPOINT lineup_trial")
            try:
                # Each trial gets a fresh identity map, since SQLite rollback cannot undo cached Python objects.
                repo = Repository(conn)
                ctx = Context(repo, content, config, Random(derived_seed + trial), users[0], SIMULATION_NOW,
                              "lineup-trial")
                run_dungeon(ctx, dungeon, users, users[0] if len(users) > 1 else None)
                record = conn.execute("SELECT winner_side, rounds, snapshot FROM battle_records "
                                      "WHERE operation_id='lineup-trial'").fetchone()
                winner, rounds = record["winner_side"], record["rounds"]
                wins += winner == 0
                draws += winner == -1
                total_rounds += rounds
                max_rounds = max(max_rounds, rounds)
                snapshot = json.loads(record["snapshot"])
                participants = conn.execute("SELECT COUNT(*) FROM battle_participants").fetchone()[0]
                violations["snapshot"] += (len(snapshot["teams"][0]["members"]) != len(units)
                                            or participants != len(users))
                for member, (user, owned) in enumerate(zip(users, pet_ids)):
                    pets = [repo.pet(pet_id) for pet_id in owned]
                    for slot, pet in enumerate(pets):
                        spent = 100 - pet.energy
                        low, high = energy_ranges[member][slot]
                        energy_ranges[member][slot] = [spent if low is None else min(low, spent),
                                                      spent if high is None else max(high, spent)]
                        violations["energy"] += spent != dungeon.energy
                        violations["non_primary_exp"] += slot > 0 and pet.exp != 0
                    inventory = repo.inventory(user)
                    resources = {"exp": pets[0].exp, "stones": repo.player(user).stones,
                                 **{f"item:{key}": inventory.get(key, 0) for key in dungeon.reward.items}}
                    for key, quantity in resources.items():
                        minimum, maximum = bounds[key] if winner == 0 else (0, 0)
                        violations["member_reward"] += not minimum <= quantity <= maximum
                        totals[member][key] += quantity
                        if winner == 0:
                            low, high = observed[member][key]
                            observed[member][key] = [quantity if low is None else min(low, quantity),
                                                     quantity if high is None else max(high, quantity)]
                    for quest in content.quests.values():
                        if quest.event == "pve":
                            row = conn.execute("SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
                                               (user, quest.id)).fetchone()
                            violations["quest_progress"] += (row[0] if row else 0) != int(winner == 0)
            finally:
                conn.execute("ROLLBACK TO lineup_trial")
                conn.execute("RELEASE lineup_trial")
        win_rate = wins / runs
        members = []
        for index, roster in enumerate(scenario.rosters):
            members.append({
                "member_slot": index + 1, "roster": list(roster), "exp_recipient_pet_slot": 1,
                "reward_sets_per_win": 1, "energy_per_pet_per_attempt": dungeon.energy,
                "observed_energy_per_pet": energy_ranges[index],
                "total_member_energy_per_attempt": dungeon.energy * len(roster),
                "sustainable_attempts_per_hour": round(attempts_per_hour, 4),
                "sampled_reward_per_attempt": {key: round(value / runs, 3) for key, value in totals[index].items()},
                "sampled_reward_per_hour": {key: round(value / runs * attempts_per_hour, 3)
                                            for key, value in totals[index].items()},
                "observed_reward_per_win_range": observed[index],
                "expected_reward_per_hour": {
                    key: round((low + high) / 2 * win_rate * attempts_per_hour, 3)
                    for key, (low, high) in bounds.items()},
                "expected_reward_per_hour_range": {
                    key: [round(low * win_rate * attempts_per_hour, 3),
                          round(high * win_rate * attempts_per_hour, 3)] for key, (low, high) in bounds.items()},
            })
        unit_details = [{"species": species, "stats": unit.stats.model_dump(),
                         "skills": [skill.id for skill in unit.skills]}
                        for species, unit in zip((key for roster in scenario.rosters for key in roster), units)]
    return {
        "id": scenario.id, "seed_group": scenario.seed_group, "derived_seed": derived_seed,
        "dungeon": dungeon.id, "realm": content.realms[scenario.realm].id,
        "profile": scenario.profile, "variant": scenario.variant,
        "member_count": len(scenario.rosters), "pet_count": sum(map(len, scenario.rosters)),
        "rosters": [list(roster) for roster in scenario.rosters],
        "trials": runs, "wins": wins, "draws": draws, "losses": runs - wins - draws,
        "win_rate": round(win_rate, 4), "mean_rounds": round(total_rounds / runs, 3), "max_rounds": max_rounds,
        "reward_sets_per_party_win": len(scenario.rosters), "reward_per_member_win_range": bounds,
        "total_party_energy_per_attempt": dungeon.energy * sum(map(len, scenario.rosters)),
        "sustainable_interval_seconds": sustainable_interval, "members": members,
        "settlement_violations": violations, "units": unit_details,
    }


def lineup_audit(rows, content) -> list[str]:
    issues = []
    expected = {scenario.id for scenario in lineup_scenarios(content)}
    actual = [row["id"] for row in rows]
    issues.extend(f"missing lineup scenario: {key}" for key in sorted(expected - set(actual)))
    issues.extend(f"unexpected lineup scenario: {key}" for key in sorted(set(actual) - expected))
    if len(set(actual)) != len(actual):
        issues.append("duplicate lineup scenarios")
    for row in rows:
        dungeon = content.dungeons[row["dungeon"]]
        expected_members = 3 if dungeon.team else 1
        expected_pets = (5 if dungeon.team else 3) if row["variant"] == "multi" else expected_members
        if row["member_count"] != expected_members or row["pet_count"] != expected_pets:
            issues.append(f"invalid member/pet coverage: {row['id']}")
        if row["max_rounds"] > 40 or row["wins"] + row["draws"] + row["losses"] != row["trials"]:
            issues.append(f"combat boundary violation: {row['id']}")
        if any(row["settlement_violations"].values()):
            issues.append(f"production settlement violation: {row['id']}")
        if row["profile"] == "prepared" and row["variant"] == "multi":
            if row["win_rate"] < PREPARED_MULTI_WIN_RATE_FLOOR:
                issues.append(f"prepared multi win rate below 70%: {row['id']}")
    return issues


def lineup_comparisons(rows) -> list[dict]:
    controls = {row["seed_group"]: row for row in rows if row["variant"] == "baseline"}
    result = []
    for row in rows:
        control = controls.get(row["seed_group"])
        if row["variant"] != "multi" or control is None:
            continue
        result.append({
            "seed_group": row["seed_group"], "baseline": control["id"], "multi": row["id"],
            "baseline_pet_count": control["pet_count"], "multi_pet_count": row["pet_count"],
            "member_count": row["member_count"],
            "baseline_win_rate": control["win_rate"], "multi_win_rate": row["win_rate"],
            "win_rate_delta": round(row["win_rate"] - control["win_rate"], 4),
            "baseline_mean_rounds": control["mean_rounds"], "multi_mean_rounds": row["mean_rounds"],
            "baseline_reward_sets_per_win": control["reward_sets_per_party_win"],
            "multi_reward_sets_per_win": row["reward_sets_per_party_win"],
            "baseline_member_stones_per_hour": control["members"][0]["expected_reward_per_hour"]["stones"],
            "multi_member_stones_per_hour": row["members"][0]["expected_reward_per_hour"]["stones"],
        })
    return result


def run_lineup_report(store, content, config, runs: int, seed: int, selected=None) -> dict:
    if type(runs) is not int or not 1 <= runs <= 10000 or type(seed) is not int:
        raise ValueError("runs must be an integer from 1 to 10000; seed must be an integer")
    rows = [evaluate_lineup(store, content, config, scenario, runs, seed)
            for scenario in (lineup_scenarios(content) if selected is None else selected)]
    return {
        "seed": seed, "runs_per_scenario": runs,
        "content_sha256": hashlib.sha256(TypeAdapter(Catalog).dump_json(content)).hexdigest(),
        "scenario_count": len(rows), "battle_count": len(rows) * runs,
        "parameters": {"pve_cooldown_seconds": config.spirit_pet_pve_cooldown,
                       "energy_recovery_seconds": config.spirit_pet_energy_interval,
                       "starting_energy_per_pet": 100},
        "profiles": {
            "entry": "First layer, mortal bloodline, species initial affinity, no equipment or learned skills.",
            "prepared": "Fifth layer, bloodline floor(realm/2), affinity 30, compatible three-slot equipment at +realm, "
                        "one damage and one healing skill at level 1+floor(realm/2); no selected lineage or resonance.",
        },
        "scope": {
            "matrix": "Every solo/team dungeon at its minimum realm, entry/prepared profiles, paired baseline/multi rosters. "
                      "The first three starter species in catalog order form the fixed trio.",
            "baseline": "Solo: first starter alone. Team: three members with one starter each, an existing legal baseline.",
            "multi": "Solo: one member with the fixed trio. Team: leader with the trio, two teammates with one pet each.",
            "profiles": "Same entry/prepared growth, equipment and skill selection as the base balance matrix; "
                        "no lineage or resonance. Each independent trial resets to the initial loadout and full energy.",
            "execution": "Production run_dungeon, roster/loadout and fight execute in SQLite savepoints; all simulation "
                         "players, rewards, mastery, quests and reports roll back. No player database is used by the CLI.",
            "not_covered": ["all species/lineage/resonance/loadout combinations", "PvP balance", "stage first-clear rewards",
                            "acquisition time", "consumable or spare-pet rotations", "long-run live-player meta"],
        },
        "economy_basis": "Each participating pet pays energy independently; their natural recovery runs in parallel. "
                         "Sustainable attempts/hour = 3600 / max(shared PVE cooldown, per-pet energy * recovery interval). "
                         "Each member receives one reward set per win; only their first pet receives exp. "
                         "Sampled yields come from actual production settlements, including zero rewards on losses/draws. "
                         "Expected ranges multiply static reward bounds by sampled win rate and attempts/hour; they are "
                         "quantity bounds, not confidence intervals. No daily/achievement rewards, potions, initial energy "
                         "or item resale valuations are counted.",
        "gates": {"prepared_multi_win_rate_floor": PREPARED_MULTI_WIN_RATE_FLOOR, "maximum_rounds": 40,
                  "require_complete_matrix": True, "require_valid_production_settlement": True},
        "issues": lineup_audit(rows, content), "comparisons": lineup_comparisons(rows), "scenarios": rows,
    }


def lineup_markdown(report) -> str:
    lines = ["# Multi-Pet Lineup Balance Report", "",
             f"Seed: `{report['seed']}`; content SHA-256: `{report['content_sha256']}`.", "",
             f"{report['scenario_count']} scenarios, {report['battle_count']} battles, "
             f"{report['runs_per_scenario']} trials per scenario; {len(report['issues'])} gate issues.", "",
             report["scope"]["matrix"], "", report["scope"]["profiles"], "",
             "Entry: " + report["profiles"]["entry"], "",
             "Prepared: " + report["profiles"]["prepared"], "", report["economy_basis"], "",
             "| Scenario | Members/Pets | W/L/D | Mean/Max Rounds | Energy/Pet | Exp/Hour Range/Member | Stones/Hour Range/Member |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["scenarios"]:
        member = row["members"][0]
        exp = member["expected_reward_per_hour_range"]["exp"]
        stones = member["expected_reward_per_hour_range"]["stones"]
        lines.append(f"| {row['id']} | {row['member_count']}/{row['pet_count']} | "
                     f"{row['wins']}/{row['losses']}/{row['draws']} | {row['mean_rounds']}/{row['max_rounds']} | "
                     f"{member['energy_per_pet_per_attempt']} | {exp[0]}-{exp[1]} | {stones[0]}-{stones[1]} |")
    lines.extend(("", "## Paired Comparisons", "",
                  "| Pair | Pets | Baseline/Multi Win Rate | Baseline/Multi Mean Rounds | Reward Sets/Win | Member Stones/Hour |",
                  "| --- | --- | --- | --- | --- | --- |"))
    for row in report["comparisons"]:
        lines.append(f"| {row['seed_group']} | {row['baseline_pet_count']}/{row['multi_pet_count']} | "
                     f"{row['baseline_win_rate']}/{row['multi_win_rate']} | "
                     f"{row['baseline_mean_rounds']}/{row['multi_mean_rounds']} | "
                     f"{row['baseline_reward_sets_per_win']}/{row['multi_reward_sets_per_win']} | "
                     f"{row['baseline_member_stones_per_hour']}/{row['multi_member_stones_per_hour']} |")
    lines.extend(("", "## Coverage Limits", ""))
    lines.extend(f"- {item}" for item in report["scope"]["not_covered"])
    lines.extend(("", "## Gate Issues", ""))
    lines.extend(f"- {issue}" for issue in report["issues"])
    if not report["issues"]:
        lines.append("None.")
    return "\n".join(lines) + "\n"
