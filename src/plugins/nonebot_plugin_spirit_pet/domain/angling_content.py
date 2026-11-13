from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier

MOVES = {"收线": (2, 2), "稳竿": (1, 0), "放线": (-1, -3)}
INITIAL_TENSION = 4
LINE_LIMIT = 10


def forecast(progress: int, tension: int, pull: int, move: str) -> tuple[int, int]:
    gain, strain = MOVES[move]
    return max(0, progress + gain), tension + strain + pull


class AnglingCourse(Definition):
    id: Identifier
    description: str = Field(min_length=1)
    goal: Annotated[int, Field(ge=5, le=9)]
    pulls: list[Annotated[int, Field(ge=-3, le=3)]] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def playable(self):
        if not self.description.strip() or not any(n > 0 for n in self.pulls) or not any(n < 0 for n in self.pulls):
            raise ValueError("angling needs a description and changing currents")
        states = {(0, INITIAL_TENSION)}
        for pull in self.pulls:
            states = {forecast(p, t, pull, move) for p, t in states for move in MOVES
                      if 0 < forecast(p, t, pull, move)[1] < LINE_LIMIT}
        if not any(p >= self.goal for p, _ in states):
            raise ValueError("angling course has no winning route")
        return self
