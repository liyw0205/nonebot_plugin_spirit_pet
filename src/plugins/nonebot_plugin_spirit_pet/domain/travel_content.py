from pydantic import Field

from .content import Definition, Identifier, Name, NonNegative, Positive, Reward


class TravelChoice(Definition):
    id: Identifier
    label: Name
    text: str = Field(min_length=1)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)
    reward: Reward


class TravelScene(Definition):
    id: Identifier
    name: Name
    text: str = Field(min_length=1)
    options: list[TravelChoice] = Field(min_length=2, max_length=3)
