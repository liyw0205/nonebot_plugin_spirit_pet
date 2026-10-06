from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, NonNegative


class Category(Definition):
    id: Identifier
    name: Name
    description: str


class Element(Definition):
    id: Identifier
    name: Name
    strong_against: list[Identifier] = Field(default_factory=list)


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
