from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[int, Field(gt=0, le=1_000_000)]
NonNegative = Annotated[int, Field(ge=0, le=1_000_000)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Name = Annotated[str, Field(pattern=r"^[\u4e00-\u9fffA-Za-z0-9]{1,12}$")]
Rate = Annotated[float, Field(ge=0, le=1)]


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Stats(Definition):
    hp: Positive
    attack: Positive
    defense: NonNegative
    speed: Positive


class Species(Definition):
    id: Identifier
    name: Name
    description: str
    starter: bool = False
    stats: Stats
    category: Identifier
    elements: list[Identifier] = Field(min_length=1, max_length=4)
    initial_affinity: Annotated[int, Field(ge=0, le=100)] = 0
    training_bonus: Annotated[float, Field(ge=0, le=1)] = 0


class Effects(Definition):
    energy: NonNegative = 0
    exp: NonNegative = 0
    affinity: NonNegative = 0
    breakthrough_bonus: Rate = 0


class Item(Definition):
    id: Identifier
    name: Name
    description: str
    kind: Literal["consumable", "breakthrough", "material", "equipment", "skill_book"]
    price: Positive | None = None
    effects: Effects = Effects()
    equipment_id: Identifier | None = None
    skill_id: Identifier | None = None

    @model_validator(mode="after")
    def check_effects(self):
        effects = self.effects
        recovery = effects.energy + effects.exp + effects.affinity
        if self.kind == "consumable" and (not recovery or effects.breakthrough_bonus):
            raise ValueError("consumable requires recovery effects only")
        if self.kind == "breakthrough" and (recovery or not effects.breakthrough_bonus):
            raise ValueError("breakthrough item requires a bonus only")
        if self.kind in {"material", "equipment", "skill_book"} and (recovery or effects.breakthrough_bonus):
            raise ValueError("non-consumable item cannot have consumable effects")
        if (self.equipment_id is not None) != (self.kind == "equipment"):
            raise ValueError("only equipment items require equipment_id")
        if (self.skill_id is not None) != (self.kind == "skill_book"):
            raise ValueError("only skill books require skill_id")
        return self


class Cost(Definition):
    exp: NonNegative
    stones: NonNegative
    chance: Rate
    items: dict[Identifier, Positive] = Field(default_factory=dict)


class Realm(Definition):
    id: Identifier
    name: Name
    multiplier: Annotated[float, Field(ge=1, le=1000)]
    advancement: Cost | None


class Layer(Definition):
    level: Annotated[int, Field(ge=1, le=10)]
    multiplier: Annotated[float, Field(ge=1, le=10)]
    advancement: Cost | None


class Bloodline(Definition):
    level: Annotated[int, Field(ge=0, le=10)]
    name: Name
    multiplier: Annotated[float, Field(ge=1, le=20)]
    evolution: Cost | None


class Range(Definition):
    minimum: NonNegative
    maximum: NonNegative

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class Reward(Definition):
    exp: Range
    stones: Range
    items: dict[Identifier, Range] = Field(default_factory=dict)


class Encounter(Definition):
    id: Identifier
    text: str
    weight: Positive
    reward: Reward


class Enemy(Definition):
    id: Identifier
    name: Name
    stats: Stats
    elements: list[Identifier] = Field(min_length=1, max_length=4)


class Dungeon(Definition):
    id: Identifier
    name: Name
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    reward: Reward
    team: bool = False


class Quest(Definition):
    id: Identifier
    name: Name
    event: Literal["train", "feed", "explore", "pve", "evolve"]
    target: Positive
    reward: Reward


class DrawEntry(Definition):
    species: Identifier
    weight: Positive


class Pool(Definition):
    id: Identifier
    name: Name
    stones: Positive
    entries: list[DrawEntry] = Field(min_length=1)


class Rules(Definition):
    starter_stones: NonNegative
    starter_items: dict[Identifier, Positive]
    daily_reward: Reward
    training_exp: Range
    training_energy: Positive
    explore_energy: Positive
    pvp_energy: Positive
    pvp_rating_delta: Positive
    max_team_size: Annotated[int, Field(ge=2, le=5)]
    max_skill_slots: Annotated[int, Field(ge=1, le=4)]
