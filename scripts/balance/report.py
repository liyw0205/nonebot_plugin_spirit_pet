import hashlib
from copy import deepcopy
from random import Random

from pydantic import TypeAdapter

from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, fight
from nonebot_plugin_spirit_pet.storage.database import Store

from .scenarios import Scenario, build_fighters, scenarios


def evaluate(store: Store, content: Catalog, config: Config, scenario: Scenario, runs: int, seed: int) -> dict:
    dungeon = content.dungeons[scenario.dungeon_id]
    blueprints = build_fighters(store, content, config, scenario.species, scenario.realm, scenario.profile)
    enemies = [Fighter.create(enemy.name, enemy.stats, enemy.elements, primary_element=enemy.primary_element)
               for enemy in (content.enemies[key] for key in dungeon.enemies)]
    wins = draws = total_rounds = max_rounds = 0
    identity = hashlib.sha256(scenario.id.encode("utf-8")).digest()
    scenario_seed = seed ^ int.from_bytes(identity[:8], "big")
    for trial in range(runs):
        battle = fight(deepcopy(blueprints), deepcopy(enemies), Random(scenario_seed + trial), content.elements)
        wins += battle.winner == 0
        draws += battle.winner == -1
        total_rounds += battle.rounds
        max_rounds = max(max_rounds, battle.rounds)
    win_rate = wins / runs
    # Sustainable yield excludes consumables, initial energy, quests and purchased resources.
    sustainable_interval = max(config.spirit_pet_pve_cooldown, dungeon.energy * config.spirit_pet_energy_interval)
    exp = (dungeon.reward.exp.minimum + dungeon.reward.exp.maximum) / 2 * win_rate
    stones = (dungeon.reward.stones.minimum + dungeon.reward.stones.maximum) / 2 * win_rate
    return {
        "id": scenario.id, "dungeon": dungeon.id, "realm": content.realms[scenario.realm].id,
        "profile": scenario.profile, "party": list(scenario.species), "party_size": len(scenario.species),
        "trials": runs, "wins": wins, "draws": draws, "losses": runs - wins - draws,
        "win_rate": round(win_rate, 4), "mean_rounds": round(total_rounds / runs, 3), "max_rounds": max_rounds,
        "energy_per_player": dungeon.energy,
        "expected_exp_per_attempt": round(exp, 3), "expected_stones_per_attempt": round(stones, 3),
        "sustainable_attempts_per_hour": round(3600 / sustainable_interval, 4),
        "expected_exp_per_hour": round(exp * 3600 / sustainable_interval, 3),
        "expected_stones_per_hour": round(stones * 3600 / sustainable_interval, 3),
        "units": [{"species": species, "stats": unit.stats.model_dump(),
                   "skills": [skill.id for skill in unit.skills]} for species, unit in zip(scenario.species, blueprints)],
    }


def audit(rows: list[dict], content: Catalog) -> list[str]:
    issues = []
    for realm in content.realms:
        for size in (1, 2, 3):
            relevant = [row for row in rows if row["realm"] == realm.id and row["party_size"] == size]
            if not relevant:
                issues.append(f"missing realm/party coverage: {realm.id}/{size}")
    for row in rows:
        if row["max_rounds"] > 40:
            issues.append(f"round bound exceeded: {row['id']}")
        if row["profile"] == "prepared" and row["wins"] == 0:
            issues.append(f"prepared party never won in sampled trials: {row['id']}")
    return issues


def run_report(store: Store, content: Catalog, config: Config, runs: int, seed: int,
               selected: list[Scenario] | None = None) -> dict:
    if type(runs) is not int or not 1 <= runs <= 10000 or type(seed) is not int:
        raise ValueError("runs must be an integer from 1 to 10000; seed must be an integer")
    rows = [evaluate(store, content, config, scenario, runs, seed)
            for scenario in (scenarios(content) if selected is None else selected)]
    digest = hashlib.sha256(TypeAdapter(Catalog).dump_json(content))
    return {
        "seed": seed, "runs_per_scenario": runs, "content_sha256": digest.hexdigest(),
        "parameters": {"pve_cooldown_seconds": config.spirit_pet_pve_cooldown,
                       "energy_recovery_seconds": config.spirit_pet_energy_interval},
        "profiles": {
            "entry": "First layer, mortal bloodline, initial affinity, no gear or learned skills.",
            "prepared": "Fifth layer, bloodline floor(realm/2), affinity 30, compatible three-slot gear at +realm, "
                        "one damage and one healing skill at 1+floor(realm/2); no selected lineage.",
        },
        "economy_basis": "Per-player sustainable PVE only; shared cooldown and natural energy recovery; "
                         "no potions, starting energy, daily rewards or item resale valuations.",
        "scenario_count": len(rows), "battle_count": len(rows) * runs,
        "issues": audit(rows, content), "scenarios": rows,
    }
