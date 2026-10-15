from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

SeasonMissionMetric = Literal[
    "season_matches", "season_wins", "season_pve", "season_discoveries", "season_claims",
]


class SeasonMission(Definition):
    """One objective of the current arena season.

    Every metric is scoped to the season window returned by
    ``utils.time.season_bounds`` and derived from records that already carry a
    timestamp, so no schema change is needed; the claim marker lives in the
    existing ``quest_progress`` table and stores the season start.
    """

    id: Identifier
    name: Name
    description: str
    metric: SeasonMissionMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: Reward
