from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[int, Field(gt=0, le=1_000_000)]
NonNegative = Annotated[int, Field(ge=0, le=1_000_000)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Name = Annotated[str, Field(pattern=r"^[\u4e00-\u9fffA-Za-z0-9]{1,12}$")]
Rate = Annotated[float, Field(ge=0, le=1)]


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Stats(Definition):
    hp: Positive
    attack: Positive
    defense: NonNegative
    speed: Positive


class Species(Definition):
    id: Identifier
    name: Name
    description: str
    starter: bool = False
    stats: Stats
    category: Identifier
    elements: list[Identifier] = Field(min_length=1, max_length=4)
    primary_element: Identifier
    talent: Identifier
    initial_affinity: Annotated[int, Field(ge=0, le=100)] = 0
    training_bonus: Annotated[float, Field(ge=0, le=1)] = 0


class Effects(Definition):
    energy: NonNegative = 0
    exp: NonNegative = 0
    affinity: NonNegative = 0
    breakthrough_bonus: Rate = 0


class Item(Definition):
    id: Identifier
    name: Name
    description: str
    kind: Literal["consumable", "breakthrough", "material", "equipment", "skill_book", "pet_egg"]
    price: Positive | None = None
    effects: Effects = Effects()
    equipment_id: Identifier | None = None
    skill_id: Identifier | None = None
    species_id: Identifier | None = None

    @model_validator(mode="after")
    def check_effects(self):
        effects = self.effects
        recovery = effects.energy + effects.exp + effects.affinity
        if self.kind == "consumable" and (not recovery or effects.breakthrough_bonus):
            raise ValueError("consumable requires recovery effects only")
        if self.kind == "breakthrough" and (recovery or not effects.breakthrough_bonus):
            raise ValueError("breakthrough item requires a bonus only")
        if self.kind in {"material", "equipment", "skill_book", "pet_egg"} and (recovery or effects.breakthrough_bonus):
            raise ValueError("non-consumable item cannot have consumable effects")
        if (self.equipment_id is not None) != (self.kind == "equipment"):
            raise ValueError("only equipment items require equipment_id")
        if (self.skill_id is not None) != (self.kind == "skill_book"):
            raise ValueError("only skill books require skill_id")
        if (self.species_id is not None) != (self.kind == "pet_egg"):
            raise ValueError("only pet eggs require species_id")
        return self


class Cost(Definition):
    exp: NonNegative
    stones: NonNegative
    chance: Rate
    items: dict[Identifier, Positive] = Field(default_factory=dict)


class ResourceCost(Definition):
    stones: NonNegative
    items: dict[Identifier, Positive] = Field(default_factory=dict)


class Realm(Definition):
    id: Identifier
    name: Name
    multiplier: Annotated[float, Field(ge=1, le=1000)]
    advancement: Cost | None


class Layer(Definition):
    level: Annotated[int, Field(ge=1, le=10)]
    multiplier: Annotated[float, Field(ge=1, le=10)]
    advancement: Cost | None


class Bloodline(Definition):
    level: Annotated[int, Field(ge=0, le=10)]
    name: Name
    multiplier: Annotated[float, Field(ge=1, le=20)]
    evolution: Cost | None


class Range(Definition):
    minimum: NonNegative
    maximum: NonNegative

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class Reward(Definition):
    exp: Range
    stones: Range
    items: dict[Identifier, Range] = Field(default_factory=dict)


class EncounterOption(Definition):
    """One exclusive choice offered when an encounter is echoed."""

    id: Identifier
    label: Name
    text: str
    reward: Reward


class Encounter(Definition):
    id: Identifier
    name: Name
    text: str
    weight: Positive
    reward: Reward
    options: list[EncounterOption] = Field(default_factory=list)


class ExplorationRoute(Definition):
    id: Identifier
    name: Name
    description: str
    min_realm: Identifier
    encounters: list[Identifier] = Field(min_length=2, max_length=5)
    ambush_reward: Reward | None = None

    @model_validator(mode="after")
    def check_encounters(self):
        if len(set(self.encounters)) != len(self.encounters):
            raise ValueError("exploration route encounters must be unique")
        return self


class Enemy(Definition):
    id: Identifier
    name: Name
    stats: Stats
    elements: list[Identifier] = Field(min_length=1, max_length=4)
    primary_element: Identifier
    signature_skill: Identifier | None = None
    skill_every: Annotated[int, Field(ge=2, le=10)] | None = None

    @model_validator(mode="after")
    def check_signature_skill(self):
        if (self.signature_skill is None) != (self.skill_every is None):
            raise ValueError("enemy signature skill and interval must be configured together")
        return self


class Dungeon(Definition):
    id: Identifier
    name: Name
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    reward: Reward
    first_clear: Reward | None = None
    team: bool = False


class Quest(Definition):
    id: Identifier
    name: Name
    event: Literal[
        "sign", "train", "feed", "explore", "pve", "pvp", "breakthrough", "evolve", "bond", "expedition",
    ]
    target: Positive
    reward: Reward


class DrawEntry(Definition):
    species: Identifier
    weight: Positive


class Pool(Definition):
    id: Identifier
    name: Name
    stones: Positive
    entries: list[DrawEntry] = Field(min_length=1)
    guaranteed_batch_size: int | None = None
    guaranteed_species: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_batch_guarantee(self):
        if self.guaranteed_batch_size is not None and not 2 <= self.guaranteed_batch_size <= 10:
            raise ValueError("batch guarantee size must be between 2 and 10")
        if (self.guaranteed_batch_size is None) != (not self.guaranteed_species):
            raise ValueError("batch guarantee requires both a size and species")
        if len(set(self.guaranteed_species)) != len(self.guaranteed_species):
            raise ValueError("duplicate batch guarantee species")
        return self


class DailyFeatured(Definition):
    first: Reward
    third: Reward

    @model_validator(mode="after")
    def require_rewards(self):
        for name, reward in (("first", self.first), ("third", self.third)):
            if reward.stones.maximum == 0 and not reward.items:
                raise ValueError(f"daily featured {name} reward must not be empty")
        return self


class BreedingRule(Definition):
    affinity: Annotated[int, Field(ge=1, le=100)]
    energy: Positive
    cost: ResourceCost


class StageStarRule(Definition):
    """Rounds allowed per enemy for a stage clear rating.

    ``three`` is the full-star bar and ``two`` the two-star bar, both counted
    per enemy so a stage with more opponents gets proportionally more room.
    """

    three: Annotated[int, Field(gt=0, le=100)]
    two: Annotated[int, Field(gt=0, le=100)]

    @model_validator(mode="after")
    def ordered(self):
        if self.three >= self.two:
            raise ValueError("three-star bar must be stricter than the two-star bar")
        return self


class FarmWaterRule(Definition):
    seconds: Positive
    daily_limit: Annotated[int, Field(ge=1, le=10)]
    stones: NonNegative


class CuisineRule(Definition):
    daily_heat: Annotated[int, Field(ge=1, le=20)]
    max_level: Annotated[int, Field(ge=1, le=10)] = 5


class BanquetRule(Definition):
    """The weekly household banquet: one occasion per natural week."""

    min_level: Annotated[int, Field(ge=1, le=10)]
    stones: NonNegative
    spirit_food: Positive
    heat: Annotated[int, Field(ge=1, le=20)]
    energy: NonNegative
    exp: NonNegative
    affinity: NonNegative
    reward: Reward

    @model_validator(mode="after")
    def require_effect(self):
        if not (self.energy or self.exp or self.affinity):
            raise ValueError("a banquet must serve something")
        return self


class SupportRule(Definition):
    slots: Annotated[int, Field(ge=1, le=3)]
    rate: Annotated[float, Field(gt=0, le=0.5)]


class FarmRotationRule(Definition):
    """Bonus yield for changing the crop on a plot instead of repeating it."""

    rate_percent: Annotated[int, Field(ge=1, le=100)]


class ExpeditionLinesRule(Definition):
    """How many commissions one player may run at once, and what the second line costs."""

    count: Annotated[int, Field(ge=1, le=2)]
    unlock_cost: Annotated[int, Field(ge=1, le=1_000_000)]

    @model_validator(mode="after")
    def _sane(self):
        if self.count == 1 and self.unlock_cost:
            raise ValueError("a single expedition line cannot charge an unlock cost")
        return self


class PetReleaseRule(Definition):
    stones_base: Annotated[int, Field(ge=0, le=100_000)]
    stones_per_realm: Annotated[int, Field(ge=0, le=100_000)]
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sane(self):
        if self.stones_base + self.stones_per_realm == 0 and not self.items:
            raise ValueError("pet release must grant something")
        return self


class PairBondRule(Definition):
    stones: Annotated[int, Field(ge=0, le=100_000)]
    items: dict[Identifier, Positive] = Field(default_factory=dict)
    min_affinity: Annotated[int, Field(ge=0, le=1_000)]
    rates: dict[Annotated[str, Field(pattern="^(hp|attack|defense|speed)$")], Annotated[float, Field(gt=0, le=0.5)]]

    @model_validator(mode="after")
    def _sane(self):
        if not self.rates:
            raise ValueError("pair bond must grant at least one rate")
        if self.stones == 0 and not self.items:
            raise ValueError("pair bond must cost something")
        return self


class AttunementRule(Definition):
    weekly_limit: Annotated[int, Field(ge=1, le=7)]


class ResearchRule(Definition):
    energy: Positive
    food: Annotated[int, Field(ge=0, le=5)]
    gain: Annotated[int, Field(ge=1, le=100)]
    daily_limit: Annotated[int, Field(ge=1, le=20)]
    pet_daily_limit: Annotated[int, Field(ge=1, le=10)]

    @model_validator(mode="after")
    def _sane(self):
        if self.pet_daily_limit > self.daily_limit:
            raise ValueError("the per-pet study limit cannot exceed the daily limit")
        return self


class RaceRule(Definition):
    energy: Positive
    daily_limit: Annotated[int, Field(ge=1, le=20)]
    weights: dict[Literal["hp", "attack", "defense", "speed"], Annotated[float, Field(ge=0, le=1)]]

    @model_validator(mode="after")
    def _weights(self):
        required = {"hp", "attack", "defense", "speed"}
        if set(self.weights) != required:
            raise ValueError("race weights must cover hp, attack, defense and speed")
        if abs(sum(self.weights.values()) - 1) > 1e-9:
            raise ValueError("race weights must sum to 1")
        return self


class MoodRule(Definition):
    max: Annotated[int, Field(ge=1, le=5)]
    decay_days: Annotated[int, Field(ge=1, le=30)]
    soothe_items: Annotated[int, Field(ge=0, le=10)]
    rates: dict[str, Annotated[float, Field(ge=-0.3, le=0.3)]]

    @model_validator(mode="after")
    def _sane(self):
        if any(rate > 0 for rate in self.rates.values()):
            raise ValueError("care must be the baseline: no mood may grant a bonus")
        return self


class SpecializationRule(Definition):
    min_level: Annotated[int, Field(ge=1, le=5)]
    switch_stones: NonNegative


class AchievementPointsRule(Definition):
    per_claim: Annotated[int, Field(ge=1, le=100)]


class TransferRule(Definition):
    price_rate: Annotated[float, Field(gt=0, le=1)]
    min_stones: NonNegative
    bloodline_essence: Annotated[int, Field(ge=0, le=5)]


class TemperRule(Definition):
    max_layers: Annotated[int, Field(ge=1, le=20)]
    rate: Annotated[float, Field(gt=0, le=0.05)]
    stones_per_layer: NonNegative


class SocketCutRule(Definition):
    """Refining a socketed gem: every level adds a flat rate step to that slot."""

    max_level: Annotated[int, Field(ge=1, le=9)]
    rate_step: Annotated[float, Field(gt=0, lt=0.5)]
    gem_cost: Annotated[int, Field(ge=1, le=9)] = 1
    stones: list[NonNegative] = Field(min_length=1)

    @model_validator(mode="after")
    def levels_match(self):
        if len(self.stones) != self.max_level:
            raise ValueError("socket_cut stones must price every level")
        return self


class SectWeeklyTier(Definition):
    """One 师门周俸 rung: weekly contribution earned pays a fixed reward once."""

    tier: int = Field(ge=1, le=6)
    contribution: Positive
    reward: Reward


class SectRule(Definition):
    daily_contribution: Positive
    practice_energy: Positive
    practice_exp: Positive
    switch_stones: NonNegative
    mission_offers: int = Field(ge=1, le=4)
    weekly_tiers: list[SectWeeklyTier] = Field(min_length=1, max_length=6)


class DuelStance(Definition):
    """One way to spend a duel exchange: both damage multipliers move together."""

    name: Name
    dealt: Annotated[float, Field(ge=0.5, le=1.5)]
    taken: Annotated[float, Field(ge=0.5, le=1.5)]

    @model_validator(mode="after")
    def _tradeoff(self):
        if (self.dealt - 1) * (self.taken - 1) < 0:
            raise ValueError(f"duel stance {self.name} must move both multipliers the same way")
        return self


class DuelRule(Definition):
    """Exchange-based duels: one stance per message, health carried between them."""

    energy: Positive
    exchanges: Annotated[int, Field(ge=3, le=20)]
    stances: dict[Identifier, DuelStance]

    @model_validator(mode="after")
    def _sane(self):
        if self.energy > 100:
            raise ValueError("duel exchange energy exceeds a pet's pool")
        if len(self.stances) < 2:
            raise ValueError("a duel needs at least two stances")
        if len({stance.name for stance in self.stances.values()}) != len(self.stances):
            raise ValueError("duel stance names must be unique")
        dealt = [stance.dealt for stance in self.stances.values()]
        if not any(rate > 1 for rate in dealt) or not any(rate < 1 for rate in dealt):
            raise ValueError("duel stances must offer both an aggressive and a defensive choice")
        return self


class MerchantRule(Definition):
    """Daily merchant board: how many orders rotate in, and the all-clear bonus."""

    offers_per_day: Annotated[int, Field(ge=1, le=5)]
    all_clear_stones: NonNegative
    all_clear_rep: NonNegative

    @model_validator(mode="after")
    def _sane(self):
        if self.all_clear_stones + self.all_clear_rep == 0:
            raise ValueError("merchant all-clear bonus must grant stones or reputation")
        return self


class MailRule(Definition):
    """灵宠信箱: how long a mail stays claimable and what one may hold."""

    days: Annotated[int, Field(ge=1, le=30)]
    daily_limit: Annotated[int, Field(ge=1, le=10)]
    max_stones: Annotated[int, Field(ge=1, le=10_000)]
    max_items: Annotated[int, Field(ge=1, le=50)]
    inbox_capacity: Annotated[int, Field(ge=1, le=50)]
    kinds: list[Literal["material", "consumable"]] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def _sane(self):
        if len(set(self.kinds)) != len(self.kinds):
            raise ValueError("mail kinds must be unique")
        return self


class FriendRule(Definition):
    """灵宠好友: roster ceiling and how long a friend request stays actionable."""

    max_friends: Annotated[int, Field(ge=1, le=200)]
    request_hours: Annotated[int, Field(ge=1, le=72)]


class ShareRule(Definition):
    """灵宠分享: how many battle reports one may publish a day and how long a code lives."""

    daily_limit: Annotated[int, Field(ge=1, le=20)]
    code_days: Annotated[int, Field(ge=1, le=30)]
    list_page_size: Annotated[int, Field(ge=1, le=10)]


class DrillRule(Definition):
    """灵宠演武: how many zero-cost trial fights a player may run each day."""

    daily_attempts: Annotated[int, Field(ge=1, le=10)]


class BorrowRule(Definition):
    """灵宠借力: how much of a friend's lent companion reaches your active pet, and for how long."""

    rate: Annotated[float, Field(gt=0, le=0.25)]
    keep_days: Annotated[int, Field(ge=1, le=30)]


class SparRequestRule(Definition):
    """灵宠约战: how long an unanswered spar request stays actionable."""

    expires_hours: Annotated[int, Field(ge=1, le=72)]


class MentorLessonRule(Definition):
    """Daily mentoring: what the master pays and what the apprentice gains."""

    energy: Positive
    exp: Positive
    stones: NonNegative
    daily_limit: Annotated[int, Field(ge=1, le=10)]


class MentorRule(Definition):
    """灵宠师徒: how many apprentices one mentor keeps and what graduation pays."""

    max_apprentices: Annotated[int, Field(ge=1, le=5)]
    request_hours: Annotated[int, Field(ge=1, le=72)]
    graduate_realm: Identifier
    lesson: MentorLessonRule
    mentor_reward: Reward
    apprentice_reward: Reward


class Rules(Definition):
    starter_stones: NonNegative
    starter_items: dict[Identifier, Positive]
    daily_reward: Reward
    training_exp: Range
    training_energy: Positive
    explore_energy: Positive
    explore_ambush_chance: Annotated[float, Field(gt=0, lt=1)] = 0.2
    explore_ambush_energy: Positive = 10
    max_team_size: Annotated[int, Field(ge=2, le=5)]
    max_skill_slots: Annotated[int, Field(ge=1, le=4)]
    skill_proficiency_per_use: Positive = 5
    resonance_cost: ResourceCost
    breeding: BreedingRule
    daily_featured: DailyFeatured
    inheritance_cost: ResourceCost
    stage_star_rounds: StageStarRule
    recycle_percent: Annotated[int, Field(gt=0, lt=100)]
    farm_water: FarmWaterRule
    cuisine: CuisineRule
    banquet: BanquetRule
    sect: SectRule
    temper: TemperRule
    support: SupportRule
    socket_cut: SocketCutRule
    transfer: TransferRule
    achievement_points: AchievementPointsRule
    specialization: SpecializationRule
    mood: MoodRule
    race: RaceRule
    research: ResearchRule
    attunement: AttunementRule
    pair_bond: PairBondRule
    pet_release: PetReleaseRule
    farm_rotation: FarmRotationRule
    expedition_lines: ExpeditionLinesRule
    duel: DuelRule
    merchant: MerchantRule
    mail: MailRule
    friend: FriendRule
    share: ShareRule
    drill: DrillRule
    borrow: BorrowRule
    spar_request: SparRequestRule
    mentor: MentorRule
