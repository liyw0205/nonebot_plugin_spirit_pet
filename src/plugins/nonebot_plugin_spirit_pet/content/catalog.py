import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, TypeAdapter
from ..domain.battle_content import (
    Category, DaoNames, Element, Equipment, ForgeLevel, Skill, SkillLevel, Talent,
)
from .validation import validate_battle_content
from .crafting_validation import validate_crafting_content
from .lineage_validation import validate_lineages
from ..domain.crafting_content import Recipe
from ..domain.lineage_content import Lineage

from ..domain.content import (
    Bloodline, Dungeon, Encounter, Enemy, Item, Layer, Pool, Quest, Realm, Rules, Species,
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
    enemies: dict[str, Enemy]
    dungeons: dict[str, Dungeon]
    quests: dict[str, Quest]
    pools: dict[str, Pool]
    rules: Rules
    categories: dict[str, Category]
    elements: dict[str, Element]
    equipment: dict[str, Equipment]
    skills: dict[str, Skill]
    talents: dict[str, Talent]
    skill_levels: dict[int, SkillLevel]
    forge_levels: dict[int, ForgeLevel]
    recipes: dict[str, Recipe]
    lineages: dict[str, Lineage]
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
            enemies=_index(directory / "enemies.json", Enemy),
            dungeons=_index(directory / "dungeons.json", Dungeon),
            quests=_index(directory / "quests.json", Quest),
            pools=_index(directory / "pools.json", Pool),
            rules=Rules.model_validate(_read(directory / "rules.json")),
            categories=_index(directory / "categories.json", Category),
            elements=_index(directory / "elements.json", Element),
            equipment=_index(directory / "equipment.json", Equipment),
            skills=_index(directory / "skills.json", Skill),
            talents=_index(directory / "talents.json", Talent),
            skill_levels=_index(directory / "skill_levels.json", SkillLevel, "level"),
            forge_levels=_index(directory / "forge_levels.json", ForgeLevel, "level"),
            recipes=_index(directory / "recipes.json", Recipe),
            lineages=_index(directory / "lineages.json", Lineage),
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
        for reward in (
            self.rules.daily_reward, *(q.reward for q in self.quests.values()),
            *(e.reward for e in self.encounters.values()), *(d.reward for d in self.dungeons.values()),
        ):
            self._require(reward.items, self.items, "reward items")
        realm_ids = {realm.id for realm in self.realms}
        for dungeon in self.dungeons.values():
            self._require([dungeon.min_realm], realm_ids, "dungeon realm")
            self._require(dungeon.enemies, self.enemies, "dungeon enemies")
            if dungeon.energy > 100:
                raise ValueError("dungeon energy exceeds capacity")
        for energy in (self.rules.training_energy, self.rules.explore_energy, self.rules.pvp_energy):
            if energy > 100:
                raise ValueError("action energy exceeds capacity")
        for pool in self.pools.values():
            ids = [entry.species for entry in pool.entries]
            self._require(ids, self.species, "summon pool")
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate species in summon pool")
        if "standard" not in self.pools or "spirit_food" not in self.items:
            raise ValueError("standard pool and spirit_food are required")
        if self.items["spirit_food"].kind != "consumable":
            raise ValueError("spirit_food must be a consumable")
        self._validate_progression()
        validate_battle_content(self)
        validate_crafting_content(self)
        validate_lineages(self)

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

    @staticmethod
    def _require(keys, targets, label):
        missing = set(keys) - set(targets)
        if missing:
            raise ValueError(f"unknown {label}: {sorted(missing)}")
