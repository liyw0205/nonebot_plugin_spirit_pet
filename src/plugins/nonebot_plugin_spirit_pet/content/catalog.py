import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, TypeAdapter
from ..domain.achievement_content import Achievement
from ..domain.arena_content import ArenaRules
from ..domain.battle_content import (
    Category, DaoNames, Element, Equipment, EquipmentSet, ForgeLevel, Skill, SkillLevel, Talent,
)
from .validation import validate_battle_content
from .crafting_validation import validate_crafting_content
from .lineage_validation import validate_lineages
from ..domain.crafting_content import Recipe
from ..domain.expedition_content import Expedition
from ..domain.stage_content import Stage
from ..domain.lineage_content import Lineage
from ..domain.resonance_content import Resonance

from ..domain.content import (
    Bloodline, Dungeon, Encounter, Enemy, ExplorationRoute, Item, Layer, Pool, Quest, Realm, Rules, Species,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)


def _index(path: Path, model: type[BaseModel], key: str = "id"):
    entries = TypeAdapter(list[model]).validate_python(_read(path))
    result = {getattr(entry, key): entry for entry in entries}
    names = [entry.name for entry in entries if hasattr(entry, "name")]
    if not entries or len(result) != len(entries) or len(set(names)) != len(names):
        raise ValueError(f"empty or duplicate content in {path.name}")
    return result


@dataclass(frozen=True)
class Catalog:
    species: dict[str, Species]
    realms: tuple[Realm, ...]
    layers: dict[int, Layer]
    bloodlines: dict[int, Bloodline]
    items: dict[str, Item]
    encounters: dict[str, Encounter]
    exploration_routes: dict[str, ExplorationRoute]
    enemies: dict[str, Enemy]
    dungeons: dict[str, Dungeon]
    quests: dict[str, Quest]
    pools: dict[str, Pool]
    rules: Rules
    arena: ArenaRules
    categories: dict[str, Category]
    elements: dict[str, Element]
    equipment: dict[str, Equipment]
    equipment_sets: dict[str, EquipmentSet]
    skills: dict[str, Skill]
    talents: dict[str, Talent]
    skill_levels: dict[int, SkillLevel]
    forge_levels: dict[int, ForgeLevel]
    recipes: dict[str, Recipe]
    lineages: dict[str, Lineage]
    expeditions: dict[str, Expedition]
    stages: dict[str, Stage]
    achievements: dict[str, Achievement]
    resonances: dict[str, Resonance]
    dao_names: DaoNames

    @classmethod
    def load(cls, directory: Path = DATA_DIR) -> "Catalog":
        catalog = cls(
            species=_index(directory / "pets.json", Species),
            realms=tuple(_index(directory / "realms.json", Realm).values()),
            layers=_index(directory / "layers.json", Layer, "level"),
            bloodlines=_index(directory / "bloodlines.json", Bloodline, "level"),
            items=_index(directory / "items.json", Item),
            encounters=_index(directory / "adventures.json", Encounter),
            exploration_routes=_index(directory / "exploration_routes.json", ExplorationRoute),
            enemies=_index(directory / "enemies.json", Enemy),
            dungeons=_index(directory / "dungeons.json", Dungeon),
            quests=_index(directory / "quests.json", Quest),
            pools=_index(directory / "pools.json", Pool),
            rules=Rules.model_validate(_read(directory / "rules.json")),
            arena=ArenaRules.model_validate(_read(directory / "arena.json")),
            categories=_index(directory / "categories.json", Category),
            elements=_index(directory / "elements.json", Element),
            equipment=_index(directory / "equipment.json", Equipment),
            equipment_sets=_index(directory / "equipment_sets.json", EquipmentSet),
            skills=_index(directory / "skills.json", Skill),
            talents=_index(directory / "talents.json", Talent),
            skill_levels=_index(directory / "skill_levels.json", SkillLevel, "level"),
            forge_levels=_index(directory / "forge_levels.json", ForgeLevel, "level"),
            recipes=_index(directory / "recipes.json", Recipe),
            lineages=_index(directory / "lineages.json", Lineage),
            expeditions=_index(directory / "expeditions.json", Expedition),
            stages=_index(directory / "stages.json", Stage),
            achievements=_index(directory / "achievements.json", Achievement),
            resonances=_index(directory / "resonances.json", Resonance),
            dao_names=DaoNames.model_validate(_read(directory / "dao_names.json")),
        )
        catalog.validate()
        return catalog

    def validate(self):
        if set(self.layers) != set(range(1, 11)):
            raise ValueError("layers must be exactly 1 through 10")
        if set(self.bloodlines) != set(range(len(self.bloodlines))):
            raise ValueError("bloodline levels must start at 0 and be contiguous")
        if {species.id for species in self.species.values() if species.starter} != {
            "qingluan", "xuanhu", "baize", "jiaolong",
        }:
            raise ValueError("starter species must be exactly qingluan, xuanhu, baize and jiaolong")
        for stages in (self.realms, tuple(self.layers[i] for i in range(1, 11))):
            if stages[-1].advancement is not None or any(s.advancement is None for s in stages[:-1]):
                raise ValueError("only the final stage must have null advancement")
        bloodlines = [self.bloodlines[i] for i in range(len(self.bloodlines))]
        if bloodlines[-1].evolution is not None or any(b.evolution is None for b in bloodlines[:-1]):
            raise ValueError("only the final bloodline must have null evolution")
        for cost in (
            *(r.advancement for r in self.realms),
            *(layer.advancement for layer in self.layers.values()),
            *(b.evolution for b in self.bloodlines.values()),
        ):
            if cost:
                self._require(cost.items, self.items, "cost items")
        self._require(self.rules.starter_items, self.items, "starter items")
        self._require(self.rules.resonance_cost.items, self.items, "resonance cost items")
        if any(self.items[key].kind != "material" for key in self.rules.resonance_cost.items):
            raise ValueError("resonance costs must be materials")
        for reward in (
            self.rules.daily_reward, *(q.reward for q in self.quests.values()),
            *(e.reward for e in self.encounters.values()), *(d.reward for d in self.dungeons.values()),
            *(expedition.reward for expedition in self.expeditions.values()),
        ):
            self._require(reward.items, self.items, "reward items")
        route_encounters = [
            encounter_id
            for route in self.exploration_routes.values()
            for encounter_id in route.encounters
        ]
        self._require(route_encounters, self.encounters, "exploration route encounters")
        if set(route_encounters) != set(self.encounters) or len(route_encounters) != len(set(route_encounters)):
            raise ValueError("each exploration encounter must belong to exactly one route")
        realm_ids = {realm.id for realm in self.realms}
        for route in self.exploration_routes.values():
            self._require([route.min_realm], realm_ids, "exploration route realm")
        missing_route_realms = realm_ids - {
            route.min_realm for route in self.exploration_routes.values()
        }
        if missing_route_realms:
            raise ValueError(
                f"missing exploration routes for realms: {sorted(missing_route_realms)}"
            )
        self._require([self.arena.min_realm], realm_ids, "arena realm")
        self._validate_equipment_sets()
        for tier in self.arena.tiers:
            self._require(tier.items, self.items, "arena tier reward items")
        for expedition in self.expeditions.values():
            self._require([expedition.min_realm], realm_ids, "expedition realm")
        for dungeon in self.dungeons.values():
            self._require([dungeon.min_realm], realm_ids, "dungeon realm")
            self._require(dungeon.enemies, self.enemies, "dungeon enemies")
            if dungeon.energy > 100:
                raise ValueError("dungeon energy exceeds capacity")
        self._validate_stages(realm_ids)
        for energy in (self.rules.training_energy, self.rules.explore_energy):
            if energy > 100:
                raise ValueError("action energy exceeds capacity")
        for pool in self.pools.values():
            ids = [entry.species for entry in pool.entries]
            self._require(ids, self.species, "summon pool")
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate species in summon pool")
            self._require(pool.guaranteed_species, self.species, "summon guarantee")
            if not set(pool.guaranteed_species).issubset(ids):
                raise ValueError("batch guarantee species must belong to the same pool")
            if pool.guaranteed_species and set(pool.guaranteed_species) == set(ids):
                raise ValueError("batch guarantee must be narrower than its summon pool")
        if "standard" not in self.pools or "spirit_food" not in self.items:
            raise ValueError("standard pool and spirit_food are required")
        if self.pools["standard"].guaranteed_batch_size is None:
            raise ValueError("standard pool requires a batch summon guarantee")
        if self.items["spirit_food"].kind != "consumable":
            raise ValueError("spirit_food must be a consumable")
        self._validate_progression()
        validate_battle_content(self)
        self._validate_resonances()
        validate_crafting_content(self)
        validate_lineages(self)
        self._validate_achievements()

    def _validate_progression(self):
        if set(self.skill_levels) != set(range(1, len(self.skill_levels) + 1)):
            raise ValueError("skill levels must start at 1 and be contiguous")
        if set(self.forge_levels) != set(range(11)):
            raise ValueError("forge levels must be exactly 0 through 10")
        skill_levels = [self.skill_levels[i] for i in sorted(self.skill_levels)]
        forge_levels = [self.forge_levels[i] for i in sorted(self.forge_levels)]
        if skill_levels[-1].required_proficiency is not None or any(
            level.required_proficiency is None for level in skill_levels[:-1]
        ):
            raise ValueError("only the final skill level must have null required_proficiency")
        if forge_levels[-1].upgrade_stones is not None or any(
            level.upgrade_stones is None for level in forge_levels[:-1]
        ):
            raise ValueError("only the final forge level must have null upgrade_stones")
        if forge_levels[-1].upgrade_items:
            raise ValueError("final forge level cannot require upgrade items")
        for level in forge_levels:
            self._require(level.upgrade_items, self.items, "forge cost items")
            if any(self.items[item].kind != "material" for item in level.upgrade_items):
                raise ValueError("forge cost items must be materials")
        for stages, multiplier in (
            (skill_levels, "power_multiplier"), (forge_levels, "bonus_multiplier"),
        ):
            if getattr(stages[0], multiplier) != 1:
                raise ValueError("initial progression multiplier must equal 1")
            if any(
                getattr(current, multiplier) <= getattr(previous, multiplier)
                for previous, current in zip(stages, stages[1:])
            ):
                raise ValueError("progression multipliers must strictly increase")

    def _validate_equipment_sets(self):
        assigned: dict[str, str] = {}
        for equipment_set in self.equipment_sets.values():
            if len(set(equipment_set.items)) != len(equipment_set.items):
                raise ValueError("equipment set items must be unique")
            self._require(equipment_set.items, self.equipment, "equipment set items")
            slots = [self.equipment[item_id].slot for item_id in equipment_set.items]
            if len(set(slots)) != len(slots):
                raise ValueError("equipment set items must use distinct slots")
            if not any(equipment_set.bonuses.model_dump().values()):
                raise ValueError("equipment set must provide a bonus")
            for item_id in equipment_set.items:
                previous = assigned.setdefault(item_id, equipment_set.id)
                if previous != equipment_set.id:
                    raise ValueError("equipment cannot belong to multiple sets")

    def _validate_stages(self, realm_ids):
        if not self.stages:
            raise ValueError("stages must not be empty")
        ordered = sorted(self.stages.values(), key=lambda stage: stage.order)
        if [stage.order for stage in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("stage orders must be contiguous starting at 1")
        self._require([stage.min_realm for stage in ordered], realm_ids, "stage realm")
        for stage in ordered:
            self._require(stage.enemies, self.enemies, "stage enemies")
            self._require(stage.reward.items, self.items, "stage reward items")
            if stage.previous_id is not None:
                self._require([stage.previous_id], self.stages, "stage prerequisite")
            if stage.energy > 100:
                raise ValueError("stage energy exceeds capacity")
        for index, stage in enumerate(ordered):
            expected = ordered[index - 1].id if index else None
            if stage.previous_id != expected:
                raise ValueError("stage previous_id must form the ordered chain")

    def _validate_achievements(self):
        required = {
            "species_collected", "duplicate_species", "pets_owned", "max_realm", "max_layer", "max_bloodline",
            "stage_clears", "pvp_wins", "pve_wins", "team_pve_wins", "lineage_branches", "skills_learned",
            "max_skill_level", "skill_level_sum", "expedition_claims", "max_affinity",
            "best_bond_streak", "adventures_discovered",
        }
        present = {achievement.metric for achievement in self.achievements.values()}
        if not required.issubset(present):
            raise ValueError(f"missing achievement metrics: {sorted(required - present)}")
        pairs = [(entry.metric, entry.target) for entry in self.achievements.values()]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate achievement metric target")
        maxima = {
            "species_collected": len(self.species),
            "duplicate_species": len(self.species),
            "max_realm": len(self.realms),
            "max_layer": len(self.realms) * 10,
            "max_bloodline": max(self.bloodlines),
            "stage_clears": len(self.stages),
            "lineage_branches": len(self.lineages),
            "skills_learned": len(self.skills),
            "max_skill_level": len(self.skill_levels),
            "skill_level_sum": len(self.skills) * len(self.skill_levels),
            "max_affinity": 100,
            "adventures_discovered": len(self.encounters),
        }
        targets = {}
        for entry in self.achievements.values():
            targets.setdefault(entry.metric, set()).add(entry.target)
        final_milestones = {
            "species_collected", "max_realm", "max_layer", "max_bloodline",
            "stage_clears", "max_skill_level", "max_affinity", "adventures_discovered",
        }
        for metric in final_milestones:
            if maxima[metric] not in targets.get(metric, set()):
                raise ValueError(f"missing final achievement milestone for {metric}")
        expected_layers = set(range(10, maxima["max_layer"] + 1, 10))
        if not expected_layers.issubset(targets.get("max_layer", set())):
            raise ValueError("missing realm layer achievement milestone")
        if not {50, 100}.issubset(targets.get("max_affinity", set())):
            raise ValueError("missing affinity achievement milestone")
        if not {7, 30}.issubset(targets.get("best_bond_streak", set())):
            raise ValueError("missing bond streak achievement milestone")
        if not {1, 10, 30}.issubset(targets.get("team_pve_wins", set())):
            raise ValueError("missing team PVE achievement milestone")
        if not {5, 10}.issubset(targets.get("adventures_discovered", set())):
            raise ValueError("missing adventure discovery achievement milestone")
        for entry in self.achievements.values():
            self._require(entry.reward.items, self.items, "achievement reward items")
            maximum = maxima.get(entry.metric)
            if maximum is not None and entry.target > maximum:
                raise ValueError(f"achievement target exceeds available {entry.metric}")

    def _validate_resonances(self):
        covered = set()
        pairs = set()
        for resonance in self.resonances.values():
            self._require(resonance.required_species, self.species, "resonance species")
            pair = frozenset(resonance.required_species)
            if pair in pairs:
                raise ValueError("duplicate resonance species pair")
            pairs.add(pair)
            covered.update(pair)
        if covered != set(self.species):
            raise ValueError("every species must appear in at least one resonance")

    @staticmethod
    def _require(keys, targets, label):
        missing = set(keys) - set(targets)
        if missing:
            raise ValueError(f"unknown {label}: {sorted(missing)}")
