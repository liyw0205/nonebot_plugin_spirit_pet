from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward


class ArcOption(Definition):
    """One exclusive choice inside a chapter; the reward is paid immediately."""

    id: Identifier
    label: Name
    text: str
    reward: Reward


class ArcChapter(Definition):
    order: Annotated[int, Field(ge=1, le=10)]
    title: Name
    text: str
    options: list[ArcOption] = Field(min_length=2, max_length=2)


class ArcFinale(Definition):
    text: str
    reward: Reward


class Arc(Definition):
    """A three-chapter story: sequential chapters, two choices each, one finale reward."""

    id: Identifier
    name: Name
    order: Annotated[int, Field(ge=1, le=30)]
    description: str
    requires: Identifier | None = None
    min_realm: Identifier
    chapters: list[ArcChapter] = Field(min_length=1, max_length=5)
    finale: ArcFinale

    @model_validator(mode="after")
    def _shape(self):
        orders = [chapter.order for chapter in self.chapters]
        if orders != list(range(1, len(self.chapters) + 1)):
            raise ValueError(f"arc {self.id} chapters must be contiguous from 1")
        for chapter in self.chapters:
            ids = [option.id for option in chapter.options]
            if len(ids) != len(set(ids)):
                raise ValueError(f"arc {self.id} chapter {chapter.order} has duplicate options")
        if self.requires is not None and self.requires == self.id:
            raise ValueError(f"arc {self.id} cannot require itself")
        return self

    @property
    def length(self) -> int:
        return len(self.chapters)
