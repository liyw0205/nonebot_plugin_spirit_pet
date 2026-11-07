"""Daily roadside encounters: one cost/benefit choice per player per day."""

from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward


class DailyCost(Definition):
    """What an option takes before it pays out; at least one part is non-zero."""

    stones: Annotated[int, Field(ge=0, le=100_000)] = 0
    items: dict[Identifier, Annotated[int, Field(gt=0, le=999)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_cost(self):
        if self.stones == 0 and not self.items:
            raise ValueError("daily encounter option must cost something")
        return self


class DailyOption(Definition):
    id: Identifier
    label: Name
    text: str
    cost: DailyCost
    reward: Reward
    # An id in `daily_followups.json`: picking this option schedules that
    # encounter for the next Beijing day. None keeps the ordinary one-day story.
    next: Identifier | None = None

    @model_validator(mode="after")
    def require_reward(self):
        reward = self.reward
        if reward.exp.maximum <= 0 and reward.stones.maximum <= 0 and not reward.items:
            raise ValueError("daily encounter option must reward something")
        return self


class DailyEncounter(Definition):
    id: Identifier
    name: Name
    description: str
    options: list[DailyOption] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def unique_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("daily encounter option ids must be unique")
        return self


class DailyFollowup(DailyEncounter):
    """An encounter unlocked by a prior day's choice, not by the day rotation.

    ``trigger`` names the ordinary ``daily_encounters`` entry whose option points
    here, so the catalog can prove every follow-up is reachable from content.
    Follow-up options may themselves carry ``next`` for a short chain, but the
    shipped four stay one-shot to keep the loop bounded.
    """

    trigger: Identifier
