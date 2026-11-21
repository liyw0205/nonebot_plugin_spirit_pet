from pydantic import Field

from .content import Definition, Identifier, Name, Positive, Reward


class SectBossMilestone(Definition):
    tier: int = Field(ge=1, le=6)
    total_damage: Positive
    member_damage: Positive
    reward: Reward


class SectBossPersonalTier(Definition):
    tier: int = Field(ge=1, le=6)
    damage: Positive
    reward: Reward


class SectBoss(Definition):
    id: Identifier
    sect: Identifier
    name: Name
    description: str = Field(min_length=1, max_length=160)
    enemy: Identifier
    max_hp: Positive
    energy: Positive
    daily_attempts: int = Field(ge=1, le=3)
    milestones: list[SectBossMilestone] = Field(min_length=3, max_length=6)
    personal_tiers: list[SectBossPersonalTier] = Field(min_length=3, max_length=6)
