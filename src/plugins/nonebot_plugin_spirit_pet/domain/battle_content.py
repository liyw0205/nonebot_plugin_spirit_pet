from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class Category(Definition):
    id: Identifier
    name: Name
    description: str


class Element(Definition):
    id: Identifier
    name: Name
    parent: Identifier | None = None
    strong_against: list[Identifier] = Field(default_factory=list)


class Talent(Definition):
    id: Identifier
    name: Name
    description: str
    kind: Literal[
        "fury", "first_strike", "lifesteal", "counter", "shield",
        "regeneration", "execute", "evasion", "venom", "pierce",
    ]
    power: Annotated[float, Field(gt=0, le=1)]
    element: Identifier | None = None

    @model_validator(mode="after")
    def check_element(self):
        if self.element is not None and self.kind != "fury":
            raise ValueError("only fury talents may require an element")
        return self


class SkillLevel(Definition):
    level: Positive
    required_proficiency: Positive | None
    power_multiplier: Annotated[float, Field(ge=1, le=10)]


class ForgeLevel(Definition):
    level: Annotated[int, Field(ge=0, le=10)]
    bonus_multiplier: Annotated[float, Field(ge=1, le=10)]
    upgrade_stones: Positive | None
    upgrade_items: dict[Identifier, Positive] = Field(default_factory=dict)


class Bonuses(Definition):
    hp: NonNegative = 0
    attack: NonNegative = 0
    defense: NonNegative = 0
    speed: NonNegative = 0


class Requirement(Definition):
    elements: list[Identifier] = Field(default_factory=list)
    categories: list[Identifier] = Field(default_factory=list)
    min_realm: Identifier


class Equipment(Definition):
    id: Identifier
    name: Name
    slot: Literal["weapon", "armor", "charm"]
    requirements: Requirement
    bonuses: Bonuses


class SkillEffect(Definition):
    kind: Literal["stun", "weaken", "ward", "empower", "cleanse", "dispel"]
    target: Literal["self", "ally", "enemy"]
    power: Annotated[float, Field(ge=0, le=0.8)] = 0
    duration: Annotated[int, Field(ge=0, le=3)] = 0

    @model_validator(mode="after")
    def check_effect(self):
        hostile = self.kind in {"stun", "weaken", "dispel"}
        if hostile != (self.target == "enemy"):
            raise ValueError("effect target does not match its beneficial or hostile kind")
        if self.kind == "stun":
            if self.power or self.duration != 1:
                raise ValueError("stun must skip exactly one action without a power value")
        elif self.kind in {"cleanse", "dispel"}:
            if self.power or self.duration:
                raise ValueError("instant removal effects cannot have power or duration")
        elif self.power <= 0 or self.duration <= 0:
            raise ValueError("temporary effects require positive power and action duration")
        return self


class Skill(Definition):
    id: Identifier
    name: Name
    description: str
    element: Identifier | None
    requirements: Requirement
    kind: Literal["damage", "heal", "utility"]
    coefficient: Annotated[float, Field(ge=0, le=3)]
    book_item: Identifier
    effects: list[SkillEffect] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def check_skill(self):
        if self.kind == "utility":
            if self.coefficient or not self.effects:
                raise ValueError("utility skills require effects and a zero coefficient")
        elif self.coefficient <= 0:
            raise ValueError("damage and healing skills require a positive coefficient")
        keys = [(effect.kind, effect.target) for effect in self.effects]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate skill effects")
        hostile = {effect.target == "enemy" for effect in self.effects}
        if len(hostile) > 1:
            raise ValueError("one skill cannot mix beneficial and hostile effects")
        if self.kind == "damage" and False in hostile:
            raise ValueError("damage skills may only carry hostile effects")
        if self.kind == "heal" and True in hostile:
            raise ValueError("healing skills may only carry beneficial effects")
        return self


class DaoNames(Definition):
    prefixes: list[Annotated[str, Field(pattern=r"^[\u4e00-\u9fff]{1,4}$")]] = Field(min_length=2)
    suffixes: list[Annotated[str, Field(pattern=r"^[\u4e00-\u9fff]{1,4}$")]] = Field(min_length=2)
