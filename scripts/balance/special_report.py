import hashlib
from copy import deepcopy
from random import Random

from pydantic import TypeAdapter

from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.gameplay.combat import effectiveness, fight

from .effect_observer import observe_effects
from .special_scenarios import build_special, special_scenarios


def _units(units, opponents, content):
    return [{
        "name": unit.name, "stats": unit.stats.model_dump(), "primary_element": unit.primary_element,
        "elements": list(unit.elements), "talent": unit.talent.id if unit.talent else None,
        "basic_matchups": [effectiveness(unit.primary_element, target.primary_element, content.elements)
                           for target in opponents],
        "skills": [{"id": skill.id, "kind": skill.kind, "element": skill.element,
                    "power_multiplier": unit.skill_multipliers[skill.id],
                    "damage_matchups": [effectiveness(skill.element, target.primary_element, content.elements)
                                        for target in opponents] if skill.kind == "damage" else None}
                   for skill in unit.skills],
    } for unit in units]


def evaluate_special(store, content, config, scenario, runs: int, seed: int) -> dict:
    templates = build_special(store, content, config, scenario)
    digest = hashlib.sha256(scenario.seed_group.encode("utf-8")).digest()
    derived_seed = seed ^ int.from_bytes(digest[:8], "big")
    wins = draws = total_rounds = max_rounds = casts = 0
    remaining = [0.0, 0.0]
    invalid_states = 0
    with observe_effects() as actual:
        for trial in range(runs):
            left, right = deepcopy(templates)
            battle = fight(left, right, Random(derived_seed + trial), content.elements)
            wins += battle.winner == 0
            draws += battle.winner == -1
            total_rounds += battle.rounds
            max_rounds = max(max_rounds, battle.rounds)
            if scenario.category == "effect":
                casts += battle.skill_uses[0].get(left[0].pet_id, {}).get(scenario.subject, 0)
            for side, team in enumerate((left, right)):
                remaining[side] += sum(unit.hp for unit in team) / sum(unit.stats.hp for unit in team)
                invalid_states += sum(not 0 <= unit.hp <= unit.stats.hp or unit.shield < 0 for unit in team)
    activations = {kind: count for (skill_id, kind), count in actual.items() if skill_id == scenario.subject}
    return {
        "id": scenario.id, "category": scenario.category, "subject": scenario.subject,
        "variant": scenario.variant, "realm": content.realms[scenario.realm].id,
        "seed_group": scenario.seed_group, "party": list(scenario.party),
        "dungeon": scenario.dungeon_id, "opponents": list(scenario.opponents),
        "initial_venom": scenario.initial_venom,
        "trials": runs, "wins": wins, "draws": draws, "losses": runs - wins - draws,
        "win_rate": round(wins / runs, 4), "mean_rounds": round(total_rounds / runs, 3), "max_rounds": max_rounds,
        "mean_left_hp_ratio": round(remaining[0] / runs, 4), "mean_right_hp_ratio": round(remaining[1] / runs, 4),
        "tracked_skill_casts": casts, "effect_activations": activations,
        "actual_effect_activations": sum(activations.values()), "invalid_states": invalid_states,
        "left_units": _units(templates[0], templates[1], content),
        "right_units": _units(templates[1], templates[0], content),
    }


def coverage(rows, content):
    controls = {(row["category"], row["subject"]): row for row in rows if row["variant"] == "control"}
    changed_lineages = set()
    triggered = set()
    issues = []
    for row in rows:
        if row["max_rounds"] > 40 or row["invalid_states"]:
            issues.append(f"combat boundary violation: {row['id']}")
        if row["variant"] != "selected":
            continue
        control = controls.get((row["category"], row["subject"]))
        if control is None:
            issues.append(f"missing paired control: {row['id']}")
            continue
        if row["category"] == "lineage":
            if row["left_units"][0]["stats"] != control["left_units"][0]["stats"]:
                changed_lineages.add(row["subject"])
        elif row["tracked_skill_casts"]:
            triggered.update((row["subject"], kind) for kind, count in row["effect_activations"].items() if count)
    expected = {(skill.id, effect.kind) for skill in content.skills.values() for effect in skill.effects}
    missing_lineages = sorted(set(content.lineages) - changed_lineages)
    missing_effects = sorted(expected - triggered)
    issues.extend(f"lineage not exercised with a real stat change: {key}" for key in missing_lineages)
    issues.extend(f"skill effect never actually triggered: {skill}/{kind}" for skill, kind in missing_effects)
    return {
        "lineages_expected": len(content.lineages), "lineages_exercised": len(changed_lineages),
        "effects_expected": len(expected), "effects_triggered": len(expected & triggered),
        "missing_lineages": missing_lineages, "missing_effects": [list(pair) for pair in missing_effects],
    }, issues


def run_special_report(store, content, config, runs: int, seed: int, selected=None):
    if type(runs) is not int or not 1 <= runs <= 10000 or type(seed) is not int:
        raise ValueError("runs must be an integer from 1 to 10000; seed must be an integer")
    selected = special_scenarios(content) if selected is None else selected
    rows = [evaluate_special(store, content, config, scenario, runs, seed) for scenario in selected]
    covered, issues = coverage(rows, content)
    return {
        "seed": seed, "runs_per_scenario": runs,
        "content_sha256": hashlib.sha256(TypeAdapter(Catalog).dump_json(content)).hexdigest(),
        "scenario_count": len(rows), "battle_count": len(rows) * runs,
        "coverage": covered, "issues": issues, "scenarios": rows,
        "scope": {
            "lineage": "Each lineage paired with its unselected control, same species/realm/minimum bloodline/gear/skills; "
                       "production loadout versus a real solo dungeon. Costs are assumed already paid.",
            "effect": "Six controlled synthetic matchups at each skill's minimum realm; one selected skill versus basic "
                      "attacks, compatible production gear and talents. Healing fixture starts after a one-HP venom hit.",
            "instrumentation": "Scoped single-process observer counts returned effect events only when the relevant "
                               "target state also changes; casts alone do not prove effect coverage.",
            "not_covered": ["all PvP species and loadout combinations", "cross-tier matchups", "all branch pairings",
                            "every effect at every skill level", "economy and acquisition time", "long-run live-player meta"],
        },
    }
