from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

CourseTile = Literal["fruit", "meadow", "low", "high"]
TILE_COST = {"fruit": 1, "meadow": -2, "low": 1, "high": 2}
BASE_STAMINA = 4
MAX_STAMINA = 6


class PlayCourse(Definition):
    id: Identifier
    name: Name
    description: str = Field(min_length=1)
    rows: list[list[CourseTile]] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def playable(self):
        if any(len(row) != 3 for row in self.rows):
            raise ValueError("each play course segment needs three lanes")
        if not self.description.strip():
            raise ValueError("play course needs a description")
        if {tile for row in self.rows for tile in row} != set(TILE_COST):
            raise ValueError("play course needs fruit, meadow and both hurdles")
        # A bounded reachability check, using the weakest starting partner.
        states = {(1, BASE_STAMINA, 0)}
        for row in self.rows:
            states = {
                (lane, min(MAX_STAMINA, stamina - TILE_COST[tile]), fruit + (tile == "fruit"))
                for previous, stamina, fruit in states
                for lane, tile in enumerate(row)
                if abs(lane - previous) <= 1 and stamina >= TILE_COST[tile]
            }
        if not any(fruit >= 2 for _, _, fruit in states):
            raise ValueError("play course needs a reachable great finish at base stamina")
        return self
