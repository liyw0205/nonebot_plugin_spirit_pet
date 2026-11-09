from typing import Literal

from pydantic import model_validator

from .content import Definition, Identifier, Name, Range

OutingStat = Literal["attack", "defense", "speed"]


class OutingScene(Definition):
    """One place a companion can wander to, with its own attribute check.

    The scene only carries static content: the payout range, an optional item
    the pet may bring back, and the 见闻 label recorded the first time that pet
    returns from here with a decent result. Player state stays in
    ``quest_progress``.
    """

    id: Identifier
    name: Name
    text: str
    stat: OutingStat
    stones: Range
    item: Identifier | None = None
    sight: Name

    @model_validator(mode="after")
    def named_placeholder(self):
        if "{name}" not in self.text:
            raise ValueError(f"outing scene {self.id} text needs a {{name}} placeholder")
        return self
