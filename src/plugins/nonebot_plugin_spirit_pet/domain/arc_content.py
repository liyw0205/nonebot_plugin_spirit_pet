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
    """Default finale plus optional per-path endings keyed by the recorded picks."""

    text: str
    reward: Reward
    paths: list["ArcEnding"] = Field(default_factory=list, max_length=16)


class ArcEnding(Definition):
    """One authored ending; ``choices`` is the 1-based option index per chapter."""

    choices: list[Annotated[int, Field(ge=1, le=2)]]
    text: str


ArcFinale.model_rebuild()


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
        seen = set()
        for ending in self.finale.paths:
            if len(ending.choices) != len(self.chapters):
                raise ValueError(f"arc {self.id} ending must choose one option per chapter")
            key = tuple(ending.choices)
            if key in seen:
                raise ValueError(f"arc {self.id} has duplicate ending {key}")
            seen.add(key)
        return self

    @property
    def length(self) -> int:
        return len(self.chapters)
