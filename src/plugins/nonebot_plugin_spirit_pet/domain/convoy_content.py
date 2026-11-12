from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class ConvoyRoad(Definition):
    name: Name
    damage: Annotated[int, Field(ge=1, le=80)]
    enemies: Annotated[list[Identifier], Field(max_length=2)]
    items: dict[Identifier, Annotated[int, Field(strict=True, ge=1, le=3)]]


class ConvoyStop(Definition):
    name: Name
    roads: Annotated[list[ConvoyRoad], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def choices(self):
        safe, risky = self.roads
        if safe.enemies or not risky.enemies or safe.items or not risky.items:
            raise ValueError("convoy stop needs a safe detour and a rewarded battle road")
        if safe.damage <= risky.damage or safe.name == risky.name:
            raise ValueError("convoy roads need distinct risk and damage")
        return self


class ConvoyRoute(Definition):
    id: Identifier
    name: Name
    description: str
    stops: Annotated[list[ConvoyStop], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def distinct_stops(self):
        if len({stop.name for stop in self.stops}) != len(self.stops):
            raise ValueError("convoy stop names must be unique")
        if sum(stop.roads[0].damage for stop in self.stops) >= 100:
            raise ValueError("convoy must have a survivable safe route")
        return self
