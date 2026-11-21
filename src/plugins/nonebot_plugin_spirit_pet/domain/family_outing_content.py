from string import Formatter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

Story = Annotated[str, Field(min_length=4, max_length=240)]


def validate_story(text: str) -> None:
    if not text.strip():
        raise ValueError("family outing story must not be blank")
    try:
        for _, field, spec, conversion in Formatter().parse(text):
            if field is not None and (field not in {"parent", "child"} or spec or conversion):
                raise ValueError("family outing story has an invalid placeholder")
        text.format(parent="亲本", child="后代")
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError("family outing story has an invalid placeholder") from error


class FamilyOutingChoice(Definition):
    id: Identifier
    name: Name
    parent_energy: Annotated[int, Field(ge=1, le=8)]
    child_energy: Annotated[int, Field(ge=1, le=8)]
    food: Annotated[int, Field(ge=0, le=2)]
    rapport: Annotated[int, Field(ge=1, le=3)]


class FamilyOutingStage(Definition):
    name: Name
    text: Story
    outcomes: dict[Identifier, Story] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_stories(self):
        for text in (self.text, *self.outcomes.values()):
            validate_story(text)
        return self


class FamilyOutingRoute(Definition):
    id: Identifier
    name: Name
    scene: Identifier
    stages: list[FamilyOutingStage] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_stage_names(self):
        if len({stage.name for stage in self.stages}) != 3:
            raise ValueError("family outing stages must have unique names")
        return self


class FamilyOutingTier(Definition):
    name: Name
    rapport: Annotated[int, Field(ge=0, le=9)]
    bond_exp: Annotated[int, Field(ge=1, le=16)]


class FamilyOutingRules(Definition):
    weekly_starts: Literal[2] = 2
    duration: Literal[86400] = 86400


class FamilyOutingCatalog(Definition):
    rules: FamilyOutingRules
    food_item: Literal["spirit_food"]
    choices: list[FamilyOutingChoice] = Field(min_length=3, max_length=3)
    tiers: list[FamilyOutingTier] = Field(min_length=3, max_length=3)
    routes: list[FamilyOutingRoute] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def check_routes_and_rewards(self):
        if {choice.id for choice in self.choices} != {"guide", "explore", "rest"}:
            raise ValueError("family outing choices must be guide, explore and rest")
        if len({choice.name for choice in self.choices}) != len(self.choices):
            raise ValueError("family outing choices must have unique names")
        if not any(choice.food == 0 for choice in self.choices):
            raise ValueError("family outings need a choice without food")
        for field in ("id", "name", "scene"):
            if len({getattr(route, field) for route in self.routes}) != len(self.routes):
                raise ValueError(f"family outing routes must have unique {field}")
        if not {"brook", "grove", "ridge"}.issubset(route.scene for route in self.routes):
            raise ValueError("family outings must cover brook, grove and ridge")
        for route in self.routes:
            if any(set(stage.outcomes) != {choice.id for choice in self.choices} for stage in route.stages):
                raise ValueError("family outing stages must cover every choice")
        if self.tiers[0].rapport != 0 or len({tier.name for tier in self.tiers}) != len(self.tiers):
            raise ValueError("family outing rewards need a zero tier and unique names")
        if any(left.rapport >= right.rapport or left.bond_exp >= right.bond_exp
               for left, right in zip(self.tiers, self.tiers[1:])):
            raise ValueError("family outing reward thresholds and experience must strictly increase")
        totals = {0}
        for _ in range(3):
            totals = {total + choice.rapport for total in totals for choice in self.choices}
        for index, tier in enumerate(self.tiers):
            upper = self.tiers[index + 1].rapport if index + 1 < len(self.tiers) else 10
            if not any(tier.rapport <= total < upper for total in totals):
                raise ValueError("family outing reward tier is unreachable")
        return self
