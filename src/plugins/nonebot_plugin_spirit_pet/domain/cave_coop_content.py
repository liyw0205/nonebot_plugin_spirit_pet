from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, ResourceCost, Reward


class CaveCoopProject(Definition):
    id: Identifier
    name: Name
    facility: Identifier
    min_level: Annotated[int, Field(ge=1, le=9)]
    owner_cost: ResourceCost
    helper_items: dict[Identifier, Positive]
    owner_reward: Reward
    helper_reward: Reward
    hours: Annotated[int, Field(ge=1, le=168)] = 72

    @model_validator(mode="after")
    def fixed_account_rewards(self):
        if not self.helper_items:
            raise ValueError("cave co-op requires contribution materials")
        for reward in (self.owner_reward, self.helper_reward):
            if reward.exp.maximum:
                raise ValueError("cave co-op rewards cannot grant pet experience")
            if reward.stones.minimum != reward.stones.maximum or any(
                bounds.minimum != bounds.maximum for bounds in reward.items.values()
            ):
                raise ValueError("cave co-op rewards must be fixed")
        return self


class CaveCoopSnapshot(Definition):
    snapshot_version: Literal[1]
    status: Literal["pending", "ready", "finished", "rejected", "cancelled", "expired", "invalidated"]
    stage: Literal["pending", "ready", "finished", "rejected", "cancelled", "expired", "invalidated"]
    event: Literal["start", "accept", "complete", "reject", "cancel", "expire", "invalidate"]
    project_id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    project_name: Name
    project: CaveCoopProject
    owner_id: Annotated[str, Field(min_length=1)]
    helper_id: Annotated[str, Field(min_length=1)]
    facility: Identifier
    facility_level: Annotated[int, Field(ge=1, le=9)]
    owner_cost_paid: ResourceCost
    helper_items: dict[Identifier, Positive]
    started_at: Annotated[int, Field(ge=0)]
    expires_at: Annotated[int, Field(ge=0)]
    updated_at: Annotated[int, Field(ge=0)]
    contributor_id: Annotated[str, Field(min_length=1)] | None = None
    finished_at: Annotated[int, Field(ge=0)] | None = None
    final_reward: dict[str, object] | None = None
    refunds: dict[str, list[str]] | None = None

    @model_validator(mode="after")
    def validate_transition_snapshot(self):
        if self.owner_id == self.helper_id:
            raise ValueError("cave co-op participants must differ")
        if self.project.facility != self.facility or self.project.name != self.project_name:
            raise ValueError("cave co-op project identity does not match its snapshot")
        if self.project.owner_cost != self.owner_cost_paid or self.project.helper_items != self.helper_items:
            raise ValueError("cave co-op cost snapshot does not match its frozen project")
        if self.expires_at <= self.started_at or self.updated_at < self.started_at:
            raise ValueError("cave co-op snapshot timestamps are not ordered")
        expected = {
            "start": "pending",
            "accept": "ready",
            "complete": "finished",
            "reject": "rejected",
            "cancel": "cancelled",
            "expire": "expired",
            "invalidate": "invalidated",
        }
        if self.stage != self.status or expected[self.event] != self.status:
            raise ValueError("cave co-op snapshot status does not match its event")
        if self.status == "ready" and (self.contributor_id != self.helper_id):
            raise ValueError("ready cave co-op snapshot must identify its contributor")
        if self.status == "finished" and (self.finished_at is None or self.final_reward is None):
            raise ValueError("finished cave co-op snapshot must include its settlement")
        return self
