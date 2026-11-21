from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Rate

Rarity = Literal["common", "uncommon", "rare"]


class WildCaptureEntry(Definition):
    species: Identifier
    enemy: Identifier
    rarity: Rarity
    weight: Annotated[int, Field(gt=0, le=100_000)]
    enemy_scale: Annotated[float, Field(ge=0.25, le=2.0)] = 1.0


class WildCaptureRoute(Definition):
    route: Identifier
    entries: list[WildCaptureEntry] = Field(min_length=3, max_length=12)


class WildCaptureRules(Definition):
    capture_item: Identifier
    daily_encounters: Annotated[int, Field(ge=1, le=5)]
    capture_attempts: Annotated[int, Field(ge=1, le=5)]
    capture_window_seconds: Annotated[int, Field(ge=300, le=86_400)]
    rare_pity: Annotated[int, Field(ge=2, le=20)]
    same_species_limit: Annotated[int, Field(ge=1, le=10)]
    capture_rates: dict[Rarity, Rate]
    routes: list[WildCaptureRoute] = Field(min_length=1)
