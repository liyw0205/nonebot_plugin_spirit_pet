from typing import Annotated, Literal

from pydantic import Field, model_validator

from .battle_content import Element, Skill, Talent
from .content import Definition, Identifier, Reward, Stats

INVITE_SECONDS = 24 * 3600
RecordId = Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
Timestamp = Annotated[int, Field(ge=0)]


class RelayFighter(Definition):
    name: str = Field(min_length=1, max_length=160)
    stats: Stats
    elements: list[Identifier] = Field(max_length=4)
    skills: list[Skill] = Field(max_length=20)
    primary_element: Identifier | None
    pet_id: RecordId | None
    talent: Talent | None
    skill_multipliers: dict[Identifier, Annotated[float, Field(gt=0, le=20)]]
    resonance_name: str | None
    skill_interval: Annotated[int, Field(ge=1)]
    affinity: Annotated[int, Field(ge=0, le=100)] | None
    equipment_sets: list[str]
    dealt: Annotated[float, Field(ge=0.25, le=2.5)]
    taken: Annotated[float, Field(ge=0.25, le=2.5)]
    study_branch: Literal["guard", "assault"] | None
    study_level: Annotated[int, Field(ge=0, le=3)]

    @model_validator(mode="after")
    def check_fighter(self):
        if (self.study_branch is None) != (self.study_level == 0):
            raise ValueError("invalid frozen study branch")
        skills = {skill.id for skill in self.skills}
        if len(skills) != len(self.skills) or set(self.skill_multipliers) - skills:
            raise ValueError("invalid frozen skills")
        return self


class RelayLeg(Definition):
    user_id: str
    pet_id: RecordId
    winner: Literal[-1, 0, 1]
    rounds: Annotated[int, Field(ge=1, le=40)]
    report_id: RecordId
    energy: Annotated[int, Field(gt=0, le=100)]
    last_pve_before: int | None
    played_at: Timestamp
    mastery: list[str]


class FriendRelaySnapshot(Definition):
    kind: Literal["friend_relay"] = "friend_relay"
    version: Literal[1] = 1
    run_id: RecordId
    owner_id: str = Field(min_length=1)
    helper_id: str = Field(min_length=1)
    owner_pet_id: RecordId
    owner_pet_name: str = Field(min_length=1, max_length=80)
    helper_pet_id: RecordId | None = None
    helper_pet_name: str | None = None
    dungeon_id: Identifier
    dungeon_name: str
    min_realm: Annotated[int, Field(ge=0, le=20)]
    realm_name: str
    energy: Annotated[int, Field(gt=0, le=100)]
    cooldown: Annotated[int, Field(gt=0)]
    max_rounds: Literal[40] = 40
    mastery_per_use: Annotated[int, Field(ge=0, le=1_000_000)]
    reward: Reward
    reward_names: dict[Identifier, str]
    enemies: list[RelayFighter] = Field(min_length=1, max_length=10)
    elements: dict[Identifier, Element] = Field(min_length=1)
    fighters: list[RelayFighter] = Field(default_factory=list, max_length=2)
    captures: list[dict] = Field(default_factory=list, max_length=2)
    status: Literal["pending", "first", "second", "completed", "defeated", "rejected", "cancelled", "expired"]
    started_at: Timestamp
    expires_at: Timestamp
    updated_at: Timestamp
    accepted_at: Timestamp | None = None
    week: Timestamp | None = None
    finished_at: Timestamp | None = None
    outcomes: list[RelayLeg] = Field(default_factory=list, max_length=2)
    settlement: dict[str, list[str]] | None = None

    @model_validator(mode="after")
    def check_run(self):
        if self.owner_id == self.helper_id or self.owner_pet_id == self.helper_pet_id:
            raise ValueError("relay participants must differ")
        if self.expires_at != self.started_at + INVITE_SECONDS or self.updated_at < self.started_at:
            raise ValueError("invalid relay timestamps")
        if set(self.reward_names) != set(self.reward.items):
            raise ValueError("reward names must cover items")
        if any(enemy.pet_id is not None for enemy in self.enemies):
            raise ValueError("relay enemies cannot be player pets")
        for key, element in self.elements.items():
            references = set(element.strong_against) | ({element.parent} if element.parent else set())
            if key != element.id or references - set(self.elements):
                raise ValueError("invalid frozen element rules")
        for fighter in [*self.enemies, *self.fighters]:
            referenced = set(fighter.elements) | ({fighter.primary_element} if fighter.primary_element else set())
            referenced.update(skill.element for skill in fighter.skills if skill.element)
            if fighter.talent and fighter.talent.element:
                referenced.add(fighter.talent.element)
            if referenced - set(self.elements):
                raise ValueError("missing frozen element")
        accepted = self.accepted_at is not None
        if accepted:
            if not self.started_at <= self.accepted_at < self.expires_at or self.accepted_at > self.updated_at:
                raise ValueError("invalid acceptance timestamp")
            if self.week is None or not self.week <= self.accepted_at < self.week + 7 * 86400:
                raise ValueError("invalid reserved week")
            if self.helper_pet_id is None or not self.helper_pet_name or len(self.fighters) != 2 or len(self.captures) != 2:
                raise ValueError("accepted relay must freeze two pets")
            for index, pet_id in enumerate((self.owner_pet_id, self.helper_pet_id)):
                if self.fighters[index].pet_id != pet_id:
                    raise ValueError("frozen fighter differs from selected pet")
                teams = self.captures[index].get("teams")
                if not isinstance(teams, list) or len(teams) != 2 or any(not isinstance(team, dict) for team in teams):
                    raise ValueError("invalid frozen battle capture")
                for side, (team, fighters) in enumerate(zip(teams, ([self.fighters[index]], self.enemies))):
                    members = team.get("members")
                    if team.get("side") != side or not isinstance(members, list) or len(members) != len(fighters):
                        raise ValueError("frozen capture differs from combat teams")
                    if any(not isinstance(member, dict) or member.get("stats") != fighter.stats.model_dump()
                           for member, fighter in zip(members, fighters)):
                        raise ValueError("frozen capture differs from combat stats")
        elif self.fighters or self.captures or self.helper_pet_id is not None or self.helper_pet_name is not None or self.week is not None or self.outcomes:
            raise ValueError("unaccepted relay cannot have frozen participants or results")
        if self.status in {"first", "second", "completed", "defeated"} and not accepted:
            raise ValueError("relay must be accepted before combat")
        if self.status in {"pending", "rejected", "expired"} and accepted:
            raise ValueError("invalid invitation status")
        expected_count = {"pending": 0, "first": 0, "second": 1, "completed": 2, "rejected": 0, "expired": 0}
        if self.status in expected_count and len(self.outcomes) != expected_count[self.status]:
            raise ValueError("relay results do not match stage")
        if self.status == "defeated" and (not self.outcomes or self.outcomes[-1].winner == 0):
            raise ValueError("defeated relay requires a lost or drawn battle")
        if self.status == "cancelled" and len(self.outcomes) > 1:
            raise ValueError("completed relay cannot be cancelled")
        previous = self.accepted_at or self.started_at
        for index, leg in enumerate(self.outcomes):
            if (leg.user_id, leg.pet_id) != ((self.owner_id, self.owner_pet_id), (self.helper_id, self.helper_pet_id))[index]:
                raise ValueError("relay order or pet differs")
            if leg.energy != self.energy or not previous <= leg.played_at <= self.updated_at:
                raise ValueError("invalid relay bill")
            if index < len(self.outcomes) - 1 and leg.winner != 0:
                raise ValueError("a failed leg cannot be followed by another")
            previous = leg.played_at
        if self.status in {"second", "completed", "cancelled"} and any(leg.winner != 0 for leg in self.outcomes):
            raise ValueError("invalid winning relay results")
        terminal = self.status not in {"pending", "first", "second"}
        if terminal != (self.finished_at is not None) or (terminal and self.finished_at != self.updated_at):
            raise ValueError("terminal relay must record completion time")
        if self.status == "completed":
            if set(self.settlement or ()) != {self.owner_id, self.helper_id}:
                raise ValueError("completed relay must settle both players")
        elif self.settlement is not None:
            raise ValueError("unfinished relay cannot settle rewards")
        if self.status in {"pending", "rejected"} and self.updated_at >= self.expires_at:
            raise ValueError("invitation has expired")
        if self.status == "expired" and self.updated_at < self.expires_at:
            raise ValueError("invitation expired too early")
        return self
