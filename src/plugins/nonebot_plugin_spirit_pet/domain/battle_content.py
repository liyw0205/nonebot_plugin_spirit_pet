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


class Skill(Definition):
    id: Identifier
    name: Name
    description: str
    element: Identifier | None
    requirements: Requirement
    kind: Literal["damage", "heal"]
    coefficient: Annotated[float, Field(gt=0, le=3)]
    book_item: Identifier


class DaoNames(Definition):
    prefixes: list[Annotated[str, Field(pattern=r"^[\u4e00-\u9fff]{1,4}$")]] = Field(min_length=2)
    suffixes: list[Annotated[str, Field(pattern=r"^[\u4e00-\u9fff]{1,4}$")]] = Field(min_length=2)
