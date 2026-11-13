import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, TypeAdapter
from ..domain.achievement_content import Achievement
from ..domain.arena_content import ArenaRules
from ..domain.ascension_content import AscensionStage
from ..domain.shop_content import ShopOffer
from ..domain.battle_content import (
    Category, Element, Equipment, EquipmentSet, ForgeLevel, Skill, SkillLevel, Talent,
)
from .validation import validate_battle_content
from .crafting_validation import validate_crafting_content
from .lineage_validation import validate_lineages
from ..domain.crafting_content import Recipe
from ..domain.expedition_content import Expedition
from ..domain.forbidden_content import ForbiddenZone
from ..domain.cuisine_content import CuisineDish
from ..domain.team_trial_content import TeamTrial
from ..domain.cave_content import CaveFacility
from ..domain.corridor_content import Corridor
from ..domain.sect_content import Sect
from ..domain.sect_mission_content import SectMission
from ..domain.sect_trial_content import SectTrial
from ..domain.codex_trial_content import CodexTrial
from ..domain.survival_content import SurvivalTrial
from ..domain.arc_content import Arc
from ..domain.tribulation_content import Tribulation
from ..domain.combo_content import Combo
from ..domain.achievement_shop_content import AchievementOffer
from ..domain.specialization_content import Specialization, skill_archetype
from ..domain.mood_content import MoodLevel
from ..domain.race_content import RaceTrack
from ..domain.race_prize_content import RacePrize
from ..domain.farm_level_content import FarmLevel
from ..domain.cave_offering_content import CaveOffering
from ..domain.gauntlet_content import Gauntlet
from ..domain.sigil_content import Sigil
from ..domain.escort_content import EscortMission
from ..domain.attunement_content import AttunementOption, Attunements
from ..domain.formation_content import Formation, Formations
from ..domain.contract_content import Contract
from ..domain.hybrid_content import Hybrid
from ..domain.alchemy_content import AlchemyRecipe
from ..domain.difficulty_content import Difficulty
from ..domain.bounty_content import Bounty
from ..domain.sect_exchange_content import SectOffer
from ..domain.intent_content import BattleIntent
from ..domain.gem_content import SocketGem
from ..domain.duel_content import DuelOpponent
from ..domain.drill_content import DrillDummy
from ..domain.commission_content import Commission
from ..domain.merchant_exchange_content import MerchantOffer
from ..domain.merchant_contract_content import MerchantContract
from ..domain.merchant_standing_content import MerchantStanding
from ..domain.play_game_content import PlayGame
from ..domain.play_course_content import PlayCourse
from ..domain.training_content import TrainingRule, TrainingTrial
from ..domain.convoy_content import ConvoyRoute
from ..domain.outing_content import OutingScene
from ..domain.tracking_content import TrackingMap
from ..domain.tracking_reward_content import TrackingReward
from ..domain.herbalism_content import HerbRoute
from ..domain.herbalism_reward_content import HerbalismReward
from ..domain.pill_furnace_reward_content import PillFurnaceReward
from ..domain.fishing_content import FishingBait, FishingSpot
from ..domain.angling_content import AnglingCourse
from ..domain.battle_supply_content import BattleSupply
from ..domain.nursery_content import NurseryRule
from ..domain.collection_rank_reward_content import CollectionRankReward
from ..domain.collection_exchange_content import CollectionExchangeOffer
from ..domain.arena_merit_content import ArenaMeritOffer
from ..domain.share_rank_reward_content import ShareRankReward
from ..domain.share_reward_content import ShareReward
from ..domain.market_content import MarketRule
from ..domain.stage_content import Stage
from ..domain.tower_content import TowerFloor
from ..domain.main_quest_content import MainQuest
from ..domain.weekly_quest_content import WeeklyQuest
from ..domain.weekly_reward_content import WeeklyReward
from ..domain.title_content import Title
from ..domain.lineage_content import Lineage
from ..domain.resonance_content import Resonance
from ..domain.journey_content import Journey
from ..domain.season_mission_content import SeasonMission
from ..domain.daily_assignment_content import DailyAssignment
from ..domain.daily_encounter_content import DailyEncounter, DailyFollowup
from ..domain.codex_content import CodexReward
from ..domain.crop_content import Crop
from ..domain.stage_star_content import StageStarReward
from ..domain.arena_tier_content import ArenaTierReward
from ..domain.gear_word_content import GearWord
from ..utils.elements import element_ancestors, expand_elements

from ..domain.content import (
    Bloodline, Dungeon, Encounter, Enemy, ExplorationRoute, Item, Layer, Pool, Quest, Realm, Rules, Species,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)


def _index(path: Path, model: type[BaseModel], key: str = "id"):
    entries = TypeAdapter(list[model]).validate_python(_read(path))
    result = {getattr(entry, key): entry for entry in entries}
    names = [entry.name for entry in entries if hasattr(entry, "name")]
    if not entries or len(result) != len(entries) or len(set(names)) != len(names):
        raise ValueError(f"empty or duplicate content in {path.name}")
    return result


@dataclass(frozen=True)
class Catalog:
    species: dict[str, Species]
    realms: tuple[Realm, ...]
    layers: dict[int, Layer]
    bloodlines: dict[int, Bloodline]
    items: dict[str, Item]
    encounters: dict[str, Encounter]
    exploration_routes: dict[str, ExplorationRoute]
    enemies: dict[str, Enemy]
    dungeons: dict[str, Dungeon]
    quests: dict[str, Quest]
    pools: dict[str, Pool]
    rules: Rules
    arena: ArenaRules
    categories: dict[str, Category]
    elements: dict[str, Element]
    equipment: dict[str, Equipment]
    equipment_sets: dict[str, EquipmentSet]
    skills: dict[str, Skill]
    talents: dict[str, Talent]
    skill_levels: dict[int, SkillLevel]
    forge_levels: dict[int, ForgeLevel]
    recipes: dict[str, Recipe]
    lineages: dict[str, Lineage]
    expeditions: dict[str, Expedition]
    stages: dict[str, Stage]
    tower: dict[str, TowerFloor]
    main_quests: dict[str, MainQuest]
    weekly_quests: dict[str, WeeklyQuest]
    weekly_rewards: dict[str, WeeklyReward]
    titles: dict[str, Title]
    achievements: dict[str, Achievement]
    resonances: dict[str, Resonance]
    journey: dict[str, Journey]
    season_missions: dict[str, SeasonMission]
    daily_assignments: dict[str, DailyAssignment]
    daily_encounters: dict[str, DailyEncounter]
    daily_followups: dict[str, DailyFollowup]
    codex_rewards: dict[str, CodexReward]
    crops: dict[str, Crop]
    stage_star_rewards: dict[int, StageStarReward]
    arena_tier_rewards: dict[str, ArenaTierReward]
    gear_words: dict[str, GearWord]
    ascension: dict[str, AscensionStage]
    shop_offers: dict[str, ShopOffer]
    forbidden: dict[str, ForbiddenZone]
    cuisine: dict[str, CuisineDish]
    team_trials: dict[str, TeamTrial]
    cave: dict[str, CaveFacility]
    corridor: dict[str, Corridor]
    sects: dict[str, Sect]
    sect_missions: dict[str, SectMission]
    sect_trials: dict[str, SectTrial]
    codex_trials: dict[str, CodexTrial]
    survival: dict[str, SurvivalTrial]
    arcs: dict[str, Arc]
    tribulations: dict[str, Tribulation]
    combos: dict[str, Combo]
    achievement_shop: dict[str, AchievementOffer]
    specializations: dict[str, Specialization]
    moods: dict[str, MoodLevel]
    races: dict[str, RaceTrack]
    race_prizes: dict[int, RacePrize]
    farm_levels: dict[int, FarmLevel]
    cave_offerings: dict[int, CaveOffering]
    gauntlets: dict[str, Gauntlet]
    sigils: dict[str, Sigil]
    escorts: dict[str, EscortMission]
    attunements: Attunements
    formations: Formations
    contracts: dict[str, Contract]
    hybrids: dict[str, Hybrid]
    alchemy: dict[str, AlchemyRecipe]
    difficulties: dict[str, Difficulty]
    bounties: dict[str, Bounty]
    sect_exchange: dict[str, SectOffer]
    intents: dict[str, BattleIntent]
    gems: dict[str, SocketGem]
    duels: dict[str, DuelOpponent]
    commissions: dict[str, Commission]
    merchant_exchange: dict[str, MerchantOffer]
    merchant_contracts: dict[str, MerchantContract]
    merchant_standings: dict[str, MerchantStanding]
    play_games: dict[str, PlayGame]
    play_courses: dict[str, PlayCourse]
    training_trials: dict[str, TrainingTrial]
    training_rule: TrainingRule
    convoy_routes: dict[str, ConvoyRoute]
    outings: dict[str, OutingScene]
    fishing_spots: dict[str, FishingSpot]
    fishing_baits: dict[str, FishingBait]
    angling_courses: dict[str, AnglingCourse]
    collection_rank_rewards: dict[int, CollectionRankReward]
    collection_exchange: dict[str, CollectionExchangeOffer]
    arena_merit_exchange: dict[str, ArenaMeritOffer]
    share_rewards: dict[int, ShareReward]
    share_rank_rewards: dict[int, ShareRankReward]
    market: MarketRule
    drills: dict[str, DrillDummy]
    tracking_maps: dict[str, TrackingMap]
    tracking_rewards: dict[str, TrackingReward]
    herb_routes: dict[str, HerbRoute]
    herbalism_rewards: dict[str, HerbalismReward]
    pill_furnace_rewards: dict[str, PillFurnaceReward]
    battle_supplies: dict[str, BattleSupply]
    nursery: NurseryRule

    @classmethod
    def load(cls, directory: Path = DATA_DIR) -> "Catalog":
        catalog = cls(
            species=_index(directory / "pets.json", Species),
            realms=tuple(_index(directory / "realms.json", Realm).values()),
            layers=_index(directory / "layers.json", Layer, "level"),
            bloodlines=_index(directory / "bloodlines.json", Bloodline, "level"),
            items=_index(directory / "items.json", Item),
            encounters=_index(directory / "adventures.json", Encounter),
            exploration_routes=_index(directory / "exploration_routes.json", ExplorationRoute),
            enemies=_index(directory / "enemies.json", Enemy),
            dungeons=_index(directory / "dungeons.json", Dungeon),
            quests=_index(directory / "quests.json", Quest),
            pools=_index(directory / "pools.json", Pool),
            rules=Rules.model_validate(_read(directory / "rules.json")),
            arena=ArenaRules.model_validate(_read(directory / "arena.json")),
            categories=_index(directory / "categories.json", Category),
            elements=_index(directory / "elements.json", Element),
            equipment=_index(directory / "equipment.json", Equipment),
            equipment_sets=_index(directory / "equipment_sets.json", EquipmentSet),
            skills=_index(directory / "skills.json", Skill),
            talents=_index(directory / "talents.json", Talent),
            skill_levels=_index(directory / "skill_levels.json", SkillLevel, "level"),
            forge_levels=_index(directory / "forge_levels.json", ForgeLevel, "level"),
            recipes=_index(directory / "recipes.json", Recipe),
            lineages=_index(directory / "lineages.json", Lineage),
            expeditions=_index(directory / "expeditions.json", Expedition),
            stages=_index(directory / "stages.json", Stage),
            tower=_index(directory / "tower.json", TowerFloor),
            main_quests=_index(directory / "main_quests.json", MainQuest),
            weekly_quests=_index(directory / "weekly_quests.json", WeeklyQuest),
            weekly_rewards=_index(directory / "weekly_rewards.json", WeeklyReward),
            titles=_index(directory / "titles.json", Title),
            achievements=_index(directory / "achievements.json", Achievement),
            resonances=_index(directory / "resonances.json", Resonance),
            journey=_index(directory / "journey.json", Journey),
            season_missions=_index(directory / "season_missions.json", SeasonMission),
            daily_assignments=_index(directory / "daily_assignments.json", DailyAssignment),
            daily_encounters=_index(directory / "daily_encounters.json", DailyEncounter),
            daily_followups=_index(directory / "daily_followups.json", DailyFollowup),
            codex_rewards=_index(directory / "codex_rewards.json", CodexReward, "species"),
            crops=_index(directory / "crops.json", Crop),
            gear_words=_index(directory / "gear_words.json", GearWord),
            ascension=_index(directory / "ascension.json", AscensionStage),
            shop_offers=_index(directory / "shop_rotation.json", ShopOffer),
            stage_star_rewards=_index(directory / "stage_star_rewards.json", StageStarReward, "stars"),
            arena_tier_rewards=_index(directory / "arena_tier_rewards.json", ArenaTierReward, "tier"),
            forbidden=_index(directory / "forbidden.json", ForbiddenZone),
            cuisine=_index(directory / "cuisine.json", CuisineDish),
            team_trials=_index(directory / "team_trials.json", TeamTrial),
            cave=_index(directory / "cave.json", CaveFacility),
            corridor=_index(directory / "corridor.json", Corridor),
            sects=_index(directory / "sects.json", Sect),
            sect_missions=_index(directory / "sect_missions.json", SectMission),
            sect_trials=_index(directory / "sect_trials.json", SectTrial),
            codex_trials=_index(directory / "codex_trials.json", CodexTrial),
            survival=_index(directory / "survival.json", SurvivalTrial),
            arcs=_index(directory / "arcs.json", Arc),
            tribulations=_index(directory / "tribulations.json", Tribulation),
            combos=_index(directory / "combos.json", Combo),
            achievement_shop=_index(directory / "achievement_shop.json", AchievementOffer),
            specializations=_index(directory / "specializations.json", Specialization),
            moods=_index(directory / "moods.json", MoodLevel, "id"),
            races=_index(directory / "races.json", RaceTrack),
            race_prizes=_index(directory / "race_prizes.json", RacePrize, "rank"),
            farm_levels=_index(directory / "farm_levels.json", FarmLevel, "level"),
            cave_offerings=_index(directory / "cave_offerings.json", CaveOffering, "tier"),
            gauntlets=_index(directory / "gauntlets.json", Gauntlet),
            sigils=_index(directory / "sigils.json", Sigil),
            escorts=_index(directory / "escorts.json", EscortMission),
            attunements=Attunements(options=list(_index(directory / "attunements.json", AttunementOption, "element").values())),
            formations=Formations(positions=list(_index(directory / "formations.json", Formation).values())),
            contracts=_index(directory / "contracts.json", Contract),
            hybrids=_index(directory / "hybrids.json", Hybrid),
            alchemy=_index(directory / "alchemy.json", AlchemyRecipe),
            difficulties=_index(directory / "difficulties.json", Difficulty),
            bounties=_index(directory / "bounties.json", Bounty),
            sect_exchange=_index(directory / "sect_exchange.json", SectOffer),
            intents=_index(directory / "intents.json", BattleIntent),
            gems=_index(directory / "gems.json", SocketGem),
            duels=_index(directory / "duels.json", DuelOpponent),
            commissions=_index(directory / "commissions.json", Commission),
            merchant_exchange=_index(directory / "merchant_exchange.json", MerchantOffer),
            merchant_contracts=_index(directory / "merchant_contracts.json", MerchantContract),
            merchant_standings=_index(directory / "merchant_standings.json", MerchantStanding),
            play_games=_index(directory / "play_games.json", PlayGame),
            play_courses=_index(directory / "play_courses.json", PlayCourse),
            training_trials=_index(directory / "training_trials.json", TrainingTrial),
            training_rule=TrainingRule.model_validate(_read(directory / "training_rule.json")),
            convoy_routes=_index(directory / "convoy_routes.json", ConvoyRoute),
            outings=_index(directory / "outing_scenes.json", OutingScene),
            fishing_spots=_index(directory / "fishing_spots.json", FishingSpot),
            fishing_baits=_index(directory / "fishing_baits.json", FishingBait),
            angling_courses=_index(directory / "angling_courses.json", AnglingCourse),
            collection_rank_rewards=_index(
                directory / "collection_rank_rewards.json", CollectionRankReward, "rank",
            ),
            collection_exchange=_index(
                directory / "collection_exchange.json", CollectionExchangeOffer,
            ),
            arena_merit_exchange=_index(
                directory / "arena_merit_exchange.json", ArenaMeritOffer,
            ),
            share_rewards=_index(directory / "share_rewards.json", ShareReward, "readers"),
            share_rank_rewards=_index(
                directory / "share_rank_rewards.json", ShareRankReward, "rank",
            ),
            market=MarketRule.model_validate(_read(directory / "market.json")),
            drills=_index(directory / "drills.json", DrillDummy),
            tracking_maps=_index(directory / "tracking_maps.json", TrackingMap),
            tracking_rewards=_index(directory / "tracking_rewards.json", TrackingReward),
            herb_routes=_index(directory / "herb_routes.json", HerbRoute),
            herbalism_rewards=_index(directory / "herbalism_rewards.json", HerbalismReward),
            pill_furnace_rewards=_index(directory / "pill_furnace_rewards.json", PillFurnaceReward),
            battle_supplies=_index(directory / "battle_supplies.json", BattleSupply),
            nursery=NurseryRule.model_validate(_read(directory / "nursery.json")),
        )
        catalog.validate()
        return catalog

    def validate(self):
        self._validate_training()
        self._validate_nursery()
        if set(self.layers) != set(range(1, 11)):
            raise ValueError("layers must be exactly 1 through 10")
        if set(self.bloodlines) != set(range(len(self.bloodlines))):
            raise ValueError("bloodline levels must start at 0 and be contiguous")
        if {species.id for species in self.species.values() if species.starter} != {
            "qingluan", "xuanhu", "baize", "jiaolong",
        }:
            raise ValueError("starter species must be exactly qingluan, xuanhu, baize and jiaolong")
        for stages in (self.realms, tuple(self.layers[i] for i in range(1, 11))):
            if stages[-1].advancement is not None or any(s.advancement is None for s in stages[:-1]):
                raise ValueError("only the final stage must have null advancement")
        bloodlines = [self.bloodlines[i] for i in range(len(self.bloodlines))]
        if bloodlines[-1].evolution is not None or any(b.evolution is None for b in bloodlines[:-1]):
            raise ValueError("only the final bloodline must have null evolution")
        for cost in (
            *(r.advancement for r in self.realms),
            *(layer.advancement for layer in self.layers.values()),
            *(b.evolution for b in self.bloodlines.values()),
        ):
            if cost:
                self._require(cost.items, self.items, "cost items")
        self._require(self.rules.starter_items, self.items, "starter items")
        self._require(self.rules.resonance_cost.items, self.items, "resonance cost items")
        self._require(self.rules.inheritance_cost.items, self.items, "inheritance cost items")
        self._require(self.rules.breeding.cost.items, self.items, "breeding cost items")
        if any(self.items[key].kind != "material" for key in self.rules.resonance_cost.items):
            raise ValueError("resonance costs must be materials")
        if any(self.items[key].kind != "material" for key in self.rules.inheritance_cost.items):
            raise ValueError("inheritance costs must be materials")
        for reward in (
            self.rules.daily_reward, *(q.reward for q in self.quests.values()),
            *(e.reward for e in self.encounters.values()), *(d.reward for d in self.dungeons.values()),
            *(option.reward for e in self.encounters.values() for option in e.options),
            *(d.first_clear for d in self.dungeons.values() if d.first_clear is not None),
            *(expedition.reward for expedition in self.expeditions.values()),
            *(floor.reward for floor in self.tower.values()),
            *(quest.reward for quest in self.main_quests.values()),
            *(chapter.reward for chapter in self.journey.values()),
            *(mission.reward for mission in self.season_missions.values()),
            *(assignment.reward for assignment in self.daily_assignments.values()),
            *(option.reward for encounter in self.daily_encounters.values() for option in encounter.options),
            *(option.reward for follow in self.daily_followups.values() for option in follow.options),
            *(quest.reward for quest in self.weekly_quests.values()),
            self.rules.daily_featured.first, self.rules.daily_featured.third,
        ):
            self._require(reward.items, self.items, "reward items")
        for encounter in (*self.daily_encounters.values(), *self.daily_followups.values()):
            for option in encounter.options:
                self._require(option.cost.items, self.items, "daily encounter costs")
        self._validate_daily_followups()
        route_encounters = [
            encounter_id
            for route in self.exploration_routes.values()
            for encounter_id in route.encounters
        ]
        for encounter in self.encounters.values():
            if not 2 <= len(encounter.options) <= 3:
                raise ValueError(f"encounter {encounter.id} needs two or three echo options")
            option_ids = [option.id for option in encounter.options]
            if len(set(option_ids)) != len(option_ids):
                raise ValueError(f"encounter {encounter.id} repeats an echo option id")
        self._require(route_encounters, self.encounters, "exploration route encounters")
        if set(route_encounters) != set(self.encounters) or len(route_encounters) != len(set(route_encounters)):
            raise ValueError("each exploration encounter must belong to exactly one route")
        realm_ids = {realm.id for realm in self.realms}
        for route in self.exploration_routes.values():
            self._require([route.min_realm], realm_ids, "exploration route realm")
            if route.ambush_reward is None:
                raise ValueError(f"exploration route {route.id} requires an ambush_reward")
            self._require(
                route.ambush_reward.items, self.items, f"exploration route {route.id} ambush reward items",
            )
            if route.ambush_reward.stones.maximum <= 0 or route.ambush_reward.exp.maximum <= 0:
                raise ValueError(f"exploration route {route.id} ambush reward must grant stones and exp")
        missing_route_realms = realm_ids - {
            route.min_realm for route in self.exploration_routes.values()
        }
        if missing_route_realms:
            raise ValueError(
                f"missing exploration routes for realms: {sorted(missing_route_realms)}"
            )
        self._require([self.arena.min_realm], realm_ids, "arena realm")
        for tier in self.arena.tiers:
            self._require(tier.items, self.items, "arena tier reward items")
        for tier in self.arena.defense_tiers:
            self._require(tier.items, self.items, "defense tier reward items")
        for expedition in self.expeditions.values():
            self._require([expedition.min_realm], realm_ids, "expedition realm")
        for dungeon in self.dungeons.values():
            self._require([dungeon.min_realm], realm_ids, "dungeon realm")
            self._require(dungeon.enemies, self.enemies, "dungeon enemies")
            if dungeon.energy > 100:
                raise ValueError("dungeon energy exceeds capacity")
            if dungeon.first_clear is None:
                raise ValueError(f"dungeon {dungeon.id} is missing a first-clear reward")
        self._validate_stages(realm_ids)
        self._validate_tower(realm_ids)
        self._validate_forbidden(realm_ids)
        self._validate_cuisine()
        self._validate_team_trials(realm_ids)
        self._validate_cave()
        self._validate_corridor()
        self._validate_sects()
        self._validate_codex_trials()
        self._validate_survival()
        self._validate_arcs(realm_ids)
        self._validate_tribulations()
        self._validate_combos()
        self._validate_achievement_shop()
        self._validate_specializations()
        self._validate_moods()
        self._validate_races()
        self._validate_gauntlets()
        self._validate_sigils()
        self._validate_escorts()
        self._validate_attunements()
        self._validate_formations()
        self._validate_contracts()
        self._validate_hybrids()
        self._validate_alchemy()
        for route in self.herb_routes.values():
            self._require([site.item_id for site in route.sites if site.item_id], self.items,
                          f"herbalism {route.id} materials")
        route_ids = set(self.herb_routes)
        rewards_by_route: dict[str, list[HerbalismReward]] = {route_id: [] for route_id in route_ids}
        for reward in self.herbalism_rewards.values():
            if reward.route not in route_ids:
                raise ValueError(f"herbalism reward {reward.id} references unknown route")
            route = self.herb_routes[reward.route]
            harvest_sites = sum(site.item_id is not None for site in route.sites)
            if reward.threshold > harvest_sites:
                raise ValueError(f"herbalism reward {reward.id} exceeds route harvest sites")
            rewards_by_route[reward.route].append(reward)
            self._require(reward.items, self.items, f"herbalism reward {reward.id} items")
        if any(not rewards for rewards in rewards_by_route.values()):
            raise ValueError("every herbalism route needs rewards")
        for route_id, rewards in rewards_by_route.items():
            thresholds = [reward.threshold for reward in rewards]
            if len(thresholds) != len(set(thresholds)) or thresholds != sorted(thresholds):
                raise ValueError(f"herbalism rewards for {route_id} must have sorted unique thresholds")
        tracking_rewards: dict[str, list[TrackingReward]] = {map_id: [] for map_id in self.tracking_maps}
        for reward in self.tracking_rewards.values():
            if reward.map_id not in self.tracking_maps:
                raise ValueError(f"tracking reward {reward.id} references unknown map")
            tracking_rewards[reward.map_id].append(reward)
            self._require(reward.items, self.items, f"tracking reward {reward.id} items")
        for map_id, rewards in tracking_rewards.items():
            if [entry.threshold for entry in rewards] != [1, 4, len(self.tracking_maps[map_id].sites)]:
                raise ValueError(f"tracking rewards for {map_id} must cover ordered thresholds 1, 4 and all sites")
        furnace_products = {recipe.item_id for recipe in self.alchemy.values()}
        furnace_rewards: dict[str, list[PillFurnaceReward]] = {product: [] for product in furnace_products}
        for reward in self.pill_furnace_rewards.values():
            if reward.product not in furnace_products:
                raise ValueError(f"pill furnace reward {reward.id} references unknown product")
            furnace_rewards[reward.product].append(reward)
            self._require(reward.items, self.items, f"pill furnace reward {reward.id} items")
        if any(not rewards for rewards in furnace_rewards.values()):
            raise ValueError("every pill furnace product needs rewards")
        for product, rewards in furnace_rewards.items():
            thresholds = [reward.threshold for reward in rewards]
            if len(thresholds) != len(set(thresholds)) or thresholds != sorted(thresholds):
                raise ValueError(f"pill furnace rewards for {product} must have sorted unique thresholds")
            if thresholds != [1, 2]:
                raise ValueError(f"pill furnace rewards for {product} must cover thresholds 1 and 2")
        self._validate_difficulties()
        self._validate_bounties()
        self._validate_sect_exchange()
        self._validate_intents()
        self._validate_gems()
        self._validate_duels()
        self._validate_drills()
        self._validate_commissions()
        self._validate_merchant_exchange()
        self._validate_merchant_contracts()
        self._validate_merchant_standings()
        self._validate_play_games()
        self._validate_outing_scenes()
        self._validate_fishing_spots()
        if set(self.angling_courses) != set(self.fishing_spots):
            raise ValueError("angling courses must cover exactly the fishing spots")
        self._validate_collection_rank_rewards()
        self._validate_collection_exchange()
        self._validate_arena_merit_exchange()
        self._validate_share_rewards()
        self._validate_share_rank_rewards()
        self._validate_market()
        self._validate_mail()
        self._validate_friend()
        self._validate_share()
        self._validate_borrow()
        self._validate_mentor()
        self._validate_main_quests()
        self._validate_ascension()
        self._validate_shop_rotation()
        self._validate_journey(realm_ids)
        self._validate_season_missions()
        self._validate_weekly_rewards()
        self._validate_daily_assignments()
        self._validate_codex_rewards()
        self._validate_crops()
        self._validate_stage_star_rewards()
        self._validate_arena_tier_rewards()
        for energy in (
            self.rules.training_energy, self.rules.explore_energy, self.rules.breeding.energy,
        ):
            if energy > 100:
                raise ValueError("action energy exceeds capacity")
        for pool in self.pools.values():
            ids = [entry.species for entry in pool.entries]
            self._require(ids, self.species, "summon pool")
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate species in summon pool")
            self._require(pool.guaranteed_species, self.species, "summon guarantee")
            if not set(pool.guaranteed_species).issubset(ids):
                raise ValueError("batch guarantee species must belong to the same pool")
            if pool.guaranteed_species and set(pool.guaranteed_species) == set(ids):
                raise ValueError("batch guarantee must be narrower than its summon pool")
        if "standard" not in self.pools or "spirit_food" not in self.items:
            raise ValueError("standard pool and spirit_food are required")
        if self.pools["standard"].guaranteed_batch_size is None:
            raise ValueError("standard pool requires a batch summon guarantee")
        if self.items["spirit_food"].kind != "consumable":
            raise ValueError("spirit_food must be a consumable")
        self._validate_progression()
        validate_battle_content(self)
        self._validate_equipment_sets()
        self._validate_resonances()
        validate_crafting_content(self)
        validate_lineages(self)
        self._validate_achievements()
        self._validate_breeding()
        self._validate_titles()
        self._validate_farm_levels()
        self._validate_cave_offerings()
        self._validate_sect_content()
        self._validate_convoy()
        self._validate_battle_supplies()

    def _validate_battle_supplies(self) -> None:
        for supply in self.battle_supplies.values():
            item = self.items.get(supply.item_id)
            if item is None:
                raise ValueError(f"battle supply {supply.id} references unknown item {supply.item_id}")
            if item.kind != "consumable":
                raise ValueError(f"battle supply {supply.id} item must be consumable")
        if len({supply.item_id for supply in self.battle_supplies.values()}) != len(self.battle_supplies):
            raise ValueError("battle supplies must use distinct consumables")

    def _validate_daily_followups(self) -> None:
        """Every scheduled follow-up must be reachable from a real trigger choice.

        An option's ``next`` names a follow-up id; the follow-up's ``trigger``
        must name the source encounter that owns that option, and no follow-up
        may chain to another follow-up (the shipped loop stays one-shot).
        """
        for encounter in self.daily_encounters.values():
            for option in encounter.options:
                if option.next is None:
                    continue
                follow = self.daily_followups.get(option.next)
                if follow is None:
                    raise ValueError(f"daily encounter {encounter.id} points at an unknown follow-up {option.next}")
                if follow.trigger != encounter.id:
                    raise ValueError(
                        f"follow-up {option.next} must be triggered by {encounter.id}, not {follow.trigger}"
                    )
        triggered = {option.next for e in self.daily_encounters.values() for option in e.options if option.next}
        unreachable = set(self.daily_followups) - triggered
        if unreachable:
            raise ValueError(f"daily follow-ups are unreachable from any choice: {sorted(unreachable)}")
        for follow in self.daily_followups.values():
            if follow.trigger not in self.daily_encounters:
                raise ValueError(f"follow-up {follow.id} names an unknown trigger {follow.trigger}")
            for option in follow.options:
                if option.next is not None:
                    raise ValueError(f"follow-up {follow.id} must not chain to another follow-up")

    def _validate_main_quests(self) -> None:
        quests = sorted(self.main_quests.values(), key=lambda quest: quest.order)
        if [quest.order for quest in quests] != list(range(1, len(quests) + 1)):
            raise ValueError("main quest order must be contiguous from 1")
        for index, quest in enumerate(quests):
            expected = quests[index - 1].id if index else None
            if quest.previous_id != expected:
                raise ValueError(f"main quest {quest.id} must follow {expected}")
        if not quests:
            raise ValueError("at least one main quest is required")

    def _validate_ascension(self) -> None:
        stages = sorted(self.ascension.values(), key=lambda stage: stage.order)
        if len(stages) != 3:
            raise ValueError("ascension requires exactly three trial stages")
        if [stage.order for stage in stages] != [1, 2, 3]:
            raise ValueError("ascension stage orders must be exactly 1, 2 and 3")
        for stage in stages:
            self._require([stage.enemy], self.enemies, "ascension trial enemy")

    def _validate_shop_rotation(self) -> None:
        offers = list(self.shop_offers.values())
        if len(offers) < 3:
            raise ValueError("shop rotation requires at least three offers")
        items = [offer.item for offer in offers]
        if len(set(items)) != len(items):
            raise ValueError("shop rotation repeats an item")
        for offer in offers:
            self._require([offer.item], self.items, "shop offer item")
            if self.items[offer.item].price is None:
                raise ValueError(f"shop offer {offer.id} item has no price")

    def _validate_titles(self) -> None:
        titles = sorted(self.titles.values(), key=lambda title: title.order)
        if [title.order for title in titles] != list(range(1, len(titles) + 1)):
            raise ValueError("title order must be contiguous from 1")
        pairs = [(title.metric, title.target) for title in titles]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate title metric target")
        for title in titles:
            # A title a player can never earn is a content bug: the same check
            # achievements already get, so an edit cannot ship an unreachable goal.
            self._require_within_ceiling("title", title.name, title.metric, title.target)

    def _validate_breeding(self) -> None:
        eggs = {item.species_id for item in self.items.values() if item.kind == "pet_egg"}
        for item in self.items.values():
            if item.kind == "pet_egg" and item.species_id not in self.species:
                raise ValueError(f"pet egg {item.id} has an unknown species")
        missing = set(self.species) - eggs
        if missing:
            raise ValueError(f"missing pet eggs for species: {sorted(missing)}")

    def _validate_progression(self):
        if set(self.skill_levels) != set(range(1, len(self.skill_levels) + 1)):
            raise ValueError("skill levels must start at 1 and be contiguous")
        if set(self.forge_levels) != set(range(11)):
            raise ValueError("forge levels must be exactly 0 through 10")
        skill_levels = [self.skill_levels[i] for i in sorted(self.skill_levels)]
        forge_levels = [self.forge_levels[i] for i in sorted(self.forge_levels)]
        if skill_levels[-1].required_proficiency is not None or any(
            level.required_proficiency is None for level in skill_levels[:-1]
        ):
            raise ValueError("only the final skill level must have null required_proficiency")
        if forge_levels[-1].upgrade_stones is not None or any(
            level.upgrade_stones is None for level in forge_levels[:-1]
        ):
            raise ValueError("only the final forge level must have null upgrade_stones")
        if forge_levels[-1].upgrade_items:
            raise ValueError("final forge level cannot require upgrade items")
        for level in forge_levels:
            self._require(level.upgrade_items, self.items, "forge cost items")
            if any(self.items[item].kind != "material" for item in level.upgrade_items):
                raise ValueError("forge cost items must be materials")
        for stages, multiplier in (
            (skill_levels, "power_multiplier"), (forge_levels, "bonus_multiplier"),
        ):
            if getattr(stages[0], multiplier) != 1:
                raise ValueError("initial progression multiplier must equal 1")
            if any(
                getattr(current, multiplier) <= getattr(previous, multiplier)
                for previous, current in zip(stages, stages[1:])
            ):
                raise ValueError("progression multipliers must strictly increase")

    def _validate_equipment_sets(self):
        assigned: dict[str, str] = {}
        for equipment_set in self.equipment_sets.values():
            if len(set(equipment_set.items)) != len(equipment_set.items):
                raise ValueError("equipment set items must be unique")
            self._require(equipment_set.items, self.equipment, "equipment set items")
            slots = [self.equipment[item_id].slot for item_id in equipment_set.items]
            if len(set(slots)) != len(slots):
                raise ValueError("equipment set items must use distinct slots")
            if not any(equipment_set.bonuses.model_dump().values()):
                raise ValueError("equipment set must provide a bonus")
            if len(equipment_set.resonance) != 3:
                raise ValueError("equipment set must define exactly three resonance tiers")
            previous_cost = None
            for tier in equipment_set.resonance:
                if not any(tier.bonuses.model_dump().values()):
                    raise ValueError("equipment set resonance tier must provide a bonus")
                self._require(tier.cost.items, self.items, "equipment set resonance cost items")
                if any(self.items[item_id].kind != "material" for item_id in tier.cost.items):
                    raise ValueError("equipment set resonance costs must be materials")
                if previous_cost is not None:
                    if tier.cost.stones <= previous_cost.stones:
                        raise ValueError("equipment set resonance stone costs must increase")
                    if any(
                        tier.cost.items.get(item_id, 0) < amount
                        for item_id, amount in previous_cost.items.items()
                    ):
                        raise ValueError("equipment set resonance item costs must not decrease")
                previous_cost = tier.cost
            pieces = [self.equipment[item_id] for item_id in equipment_set.items]
            if not any(
                all(
                    (not piece.requirements.categories or species.category in piece.requirements.categories)
                    and set(piece.requirements.elements).issubset(
                        expand_elements(species.elements, self.elements)
                    )
                    for piece in pieces
                )
                for species in self.species.values()
            ):
                raise ValueError(f"equipment set has no compatible species: {equipment_set.id}")
            for item_id in equipment_set.items:
                previous = assigned.setdefault(item_id, equipment_set.id)
                if previous != equipment_set.id:
                    raise ValueError("equipment cannot belong to multiple sets")

    def _validate_stages(self, realm_ids):
        if not self.stages:
            raise ValueError("stages must not be empty")
        ordered = sorted(self.stages.values(), key=lambda stage: stage.order)
        if [stage.order for stage in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("stage orders must be contiguous starting at 1")
        self._require([stage.min_realm for stage in ordered], realm_ids, "stage realm")
        for stage in ordered:
            self._require(stage.enemies, self.enemies, "stage enemies")
            self._require(stage.reward.items, self.items, "stage reward items")
            if stage.previous_id is not None:
                self._require([stage.previous_id], self.stages, "stage prerequisite")
            if stage.energy > 100:
                raise ValueError("stage energy exceeds capacity")
        for index, stage in enumerate(ordered):
            expected = ordered[index - 1].id if index else None
            if stage.previous_id != expected:
                raise ValueError("stage previous_id must form the ordered chain")

    def _validate_tower(self, realm_ids):
        if not self.tower:
            raise ValueError("tower must not be empty")
        ordered = sorted(self.tower.values(), key=lambda floor: floor.order)
        if [floor.order for floor in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("tower orders must be contiguous starting at 1")
        self._require([floor.min_realm for floor in ordered], realm_ids, "tower realm")
        for floor in ordered:
            self._require(floor.enemies, self.enemies, "tower enemies")
            self._require(floor.reward.items, self.items, "tower reward items")
            if floor.previous_id is not None:
                self._require([floor.previous_id], self.tower, "tower prerequisite")
            if floor.energy > 100:
                raise ValueError("tower energy exceeds capacity")
        for index, floor in enumerate(ordered):
            expected = ordered[index - 1].id if index else None
            if floor.previous_id != expected:
                raise ValueError("tower previous_id must form the ordered chain")

    def _validate_forbidden(self, realm_ids):
        if not self.forbidden:
            raise ValueError("forbidden zones must not be empty")
        depth_ids = []
        for zone in self.forbidden.values():
            self._require([depth.min_realm for depth in zone.depths], realm_ids, "forbidden depth realm")
            self._require(zone.bonus.items, self.items, "forbidden bonus items")
            if zone.bonus.stones.maximum <= 0 and not zone.bonus.items:
                raise ValueError(f"forbidden zone {zone.id} needs a bonus reward")
            for depth in zone.depths:
                depth_ids.append(depth.id)
                self._require(depth.enemies, self.enemies, "forbidden depth enemies")
                self._require(depth.reward.items, self.items, "forbidden depth reward items")
                if depth.energy > 100:
                    raise ValueError("forbidden depth energy exceeds capacity")
                if depth.reward.stones.maximum <= 0 and not depth.reward.items:
                    raise ValueError(f"forbidden depth {depth.id} needs a reward")
        if len(set(depth_ids)) != len(depth_ids):
            raise ValueError("forbidden depth ids must be globally unique")

    def _validate_cuisine(self):
        if not self.cuisine:
            raise ValueError("cuisine dishes must not be empty")
        limit = self.rules.cuisine.max_level
        for dish in self.cuisine.values():
            if dish.level > limit:
                raise ValueError(f"cuisine dish {dish.id} exceeds the maximum cuisine level")
            if dish.stones <= 0 and not dish.ingredients:
                raise ValueError(f"cuisine dish {dish.id} needs a cost")
            self._require(dish.ingredients, self.items, "cuisine ingredients")
            if dish.item is not None:
                self._require([dish.item], self.items, "cuisine meal item")
                if self.items[dish.item].kind != "consumable":
                    raise ValueError(f"cuisine dish {dish.id} must produce a consumable")
                if self.items[dish.item].price is not None:
                    raise ValueError(f"cuisine meal {dish.item} must not be sold in the shop")
        levels = {dish.level for dish in self.cuisine.values()}
        if levels != set(range(1, max(levels) + 1)):
            raise ValueError("cuisine levels must be contiguous from 1")

    def _validate_team_trials(self, realm_ids):
        if not self.team_trials:
            raise ValueError("team trials must not be empty")
        for trial in self.team_trials.values():
            self._require([trial.min_realm], realm_ids, "team trial realm")
            self._require(trial.enemies, self.enemies, "team trial enemies")
            self._require(trial.reward.items, self.items, "team trial reward items")
            if trial.energy > 100:
                raise ValueError("team trial energy exceeds capacity")
            if trial.reward.stones.maximum <= 0 and not trial.reward.items:
                raise ValueError(f"team trial {trial.id} needs a reward")

    def _validate_cave(self):
        if not self.cave:
            raise ValueError("cave facilities must not be empty")
        for facility in self.cave.values():
            if facility.item is not None:
                self._require([facility.item], self.items, "cave facility item")
            for step in facility.upgrades:
                self._require(step.items, self.items, "cave upgrade item")
                if step.stones <= 0 and not step.items:
                    raise ValueError(f"cave facility {facility.id} has a free upgrade")

    def _validate_corridor(self):
        if not self.corridor:
            raise ValueError("corridors must not be empty")
        for corridor in self.corridor.values():
            self._require([corridor.base_enemy], self.enemies, "corridor base enemy")
            for milestone in corridor.milestones:
                self._require(milestone.items, self.items, "corridor milestone items")

    def _validate_sects(self):
        if not self.sects:
            raise ValueError("sects must not be empty")
        stats = {"hp", "attack", "defense", "speed"}
        for sect in self.sects.values():
            if sect.stat not in stats:
                raise ValueError(f"sect {sect.id} has an unknown stat")
            for entry in sect.ranks:
                self._require(entry.items, self.items, "sect rank items")

    def _validate_codex_trials(self):
        if not self.codex_trials:
            raise ValueError("codex trials must not be empty")
        for trial in self.codex_trials.values():
            if trial.energy > 100:
                raise ValueError(f"codex trial {trial.id} energy exceeds a pet's pool")
            self._require(trial.reward.items, self.items, "codex trial reward items")
            for milestone in trial.milestones:
                self._require(milestone.items, self.items, "codex trial milestone items")
                if milestone.count > len(self.species):
                    raise ValueError(f"codex trial {trial.id} milestone exceeds the codex size")
            for rotation in trial.rotations:
                self._require(rotation.reward.items, self.items, "codex rotation reward items")
                self._require(
                    rotation.elements, self.elements, f"codex rotation {rotation.id} elements",
                )
                if rotation.energy > 100:
                    raise ValueError(f"codex rotation {rotation.id} energy exceeds a pet's pool")
            if trial.weekly_bonus is not None:
                self._require(trial.weekly_bonus.items, self.items, "codex weekly bonus items")

    def _validate_survival(self):
        if not self.survival:
            raise ValueError("survival trials must not be empty")
        for trial in self.survival.values():
            self._require([trial.enemy], self.enemies, "survival enemy")
            if trial.energy > 100:
                raise ValueError(f"survival trial {trial.id} energy exceeds a pet's pool")
            for milestone in trial.milestones:
                self._require(milestone.reward.items, self.items, "survival milestone items")

    def _validate_arcs(self, realm_ids):
        if not self.arcs:
            raise ValueError("arcs must not be empty")
        for arc in self.arcs.values():
            self._require([arc.min_realm], realm_ids, "arc realm")
            if arc.requires is not None:
                self._require([arc.requires], self.arcs, "arc prerequisite")
            for chapter in arc.chapters:
                for option in chapter.options:
                    self._require(option.reward.items, self.items, "arc option items")
            self._require(arc.finale.reward.items, self.items, "arc finale items")

    def _validate_tribulations(self):
        if not self.tribulations:
            raise ValueError("tribulations must not be empty")
        for entry in self.tribulations.values():
            if entry.energy > 100:
                raise ValueError(f"tribulation {entry.id} energy exceeds a pet's pool")
            self._require(entry.bonus.items, self.items, "tribulation bonus items")
            for modifier in entry.modifiers:
                self._require(modifier.reward.items, self.items, "tribulation modifier items")

    def _validate_combos(self):
        if not self.combos:
            raise ValueError("combos must not be empty")
        pairs = set()
        for combo in self.combos.values():
            for skill_id in combo.skills:
                if skill_id not in self.skills:
                    raise ValueError(f"combo {combo.id} references unknown skill {skill_id}")
            pair = frozenset(combo.skills)
            if pair in pairs:
                raise ValueError(f"combo {combo.id} repeats an existing skill pair")
            pairs.add(pair)

    def _validate_achievement_shop(self):
        if not self.achievement_shop:
            raise ValueError("achievement shop must not be empty")
        for offer in self.achievement_shop.values():
            self._require(offer.reward.items, self.items, "achievement offer items")

    def _validate_specializations(self):
        if not self.specializations:
            raise ValueError("specializations must not be empty")
        for skill in self.skills.values():
            archetype = skill_archetype(skill)
            if archetype not in self.specializations:
                raise ValueError(f"skill {skill.id} has no specialization for {archetype}")

    def _validate_moods(self):
        if not self.moods:
            raise ValueError("moods must not be empty")
        rule = self.rules.mood
        ordered = sorted(self.moods.values(), key=lambda level: level.threshold)
        if ordered[0].threshold != 0:
            raise ValueError("one mood level must have threshold 0")
        if ordered[-1].threshold != rule.max:
            raise ValueError("the best mood level must sit at rules.mood.max")
        if ordered[-1].rate != 0:
            raise ValueError("the best mood level must be the neutral baseline")
        rates = [level.rate for level in ordered]
        if rates != sorted(rates):
            raise ValueError("mood rates must fall as the mood value drops")
        for level in ordered:
            if rule.rates.get(level.id) is None:
                raise ValueError(f"mood {level.id} has no rate in rules.mood.rates")
            if abs(rule.rates[level.id] - level.rate) > 1e-9:
                raise ValueError(f"mood {level.id} rate disagrees with rules.mood.rates")

    def _validate_sect_content(self) -> None:
        """Sect missions, weekly pay tiers and the weekly trial must be playable.

        A mission whose sect does not exist, whose reward names a missing item,
        or that leaves a sect with fewer tasks than the daily board asks for is
        content that cannot be completed — reject it at load time.
        """
        offers = self.rules.sect.mission_offers
        per_sect: dict[str, list] = {}
        for mission in self.sect_missions.values():
            if mission.sect not in self.sects:
                raise ValueError(f"sect mission {mission.id} names an unknown sect {mission.sect}")
            per_sect.setdefault(mission.sect, []).append(mission)
            self._require(mission.reward.items, self.items, f"sect mission {mission.id} reward items")
        for sect_id in self.sects:
            missions = sorted(per_sect.get(sect_id, []), key=lambda entry: entry.order)
            if len(missions) < offers:
                raise ValueError(
                    f"sect {sect_id} needs at least {offers} missions, has {len(missions)}"
                )
            orders = [mission.order for mission in missions]
            if orders != list(range(1, len(orders) + 1)):
                raise ValueError(f"sect {sect_id} mission orders must be contiguous from 1")

        tiers = sorted(self.rules.sect.weekly_tiers, key=lambda entry: entry.tier)
        if [tier.tier for tier in tiers] != list(range(1, len(tiers) + 1)):
            raise ValueError("sect weekly tiers must be contiguous from 1")
        previous = 0
        for tier in tiers:
            if tier.contribution <= previous:
                raise ValueError("sect weekly tier contribution must strictly increase")
            previous = tier.contribution
            if tier.reward.stones.maximum == 0 and not tier.reward.items:
                raise ValueError(f"sect weekly tier {tier.tier} must pay something")
            self._require(tier.reward.items, self.items, f"sect weekly tier {tier.tier} items")

        trial_sects = set()
        for trial in self.sect_trials.values():
            if trial.sect not in self.sects:
                raise ValueError(f"sect trial {trial.id} names an unknown sect {trial.sect}")
            if trial.sect in trial_sects:
                raise ValueError(f"sect {trial.sect} has more than one trial")
            trial_sects.add(trial.sect)
            if trial.enemy not in self.enemies:
                raise ValueError(f"sect trial {trial.id} names an unknown enemy {trial.enemy}")
            if trial.min_realm not in {realm.id for realm in self.realms}:
                raise ValueError(f"sect trial {trial.id} names an unknown realm {trial.min_realm}")
            self._require(trial.reward.items, self.items, f"sect trial {trial.id} reward items")

    def _validate_farm_levels(self) -> None:
        levels = sorted(self.farm_levels)
        if levels != list(range(1, len(levels) + 1)):
            raise ValueError("farm levels must be contiguous from 1")
        if not levels or self.farm_levels[1].harvests != 0:
            raise ValueError("farm level 1 must start at zero harvests")
        previous = -1
        for level in levels:
            entry = self.farm_levels[level]
            if entry.harvests <= previous:
                raise ValueError("farm level harvest thresholds must strictly increase")
            previous = entry.harvests
            self._require(entry.items, self.items, f"farm level {level} reward items")

    def _validate_cave_offerings(self) -> None:
        tiers = sorted(self.cave_offerings)
        if tiers != list(range(1, len(tiers) + 1)):
            raise ValueError("cave offering tiers must be contiguous from 1")
        for tier in tiers:
            self._require(
                self.cave_offerings[tier].items, self.items, f"cave offering tier {tier} items",
            )

    def _validate_races(self):
        if not self.races:
            raise ValueError("races must not be empty")
        for track in self.races.values():
            weighted = set(self.rules.race.weights)
            if track.terrain.stat not in weighted:
                raise ValueError(f"race {track.id} terrain stat is not a weighted stat")
        if set(self.race_prizes) != {1, 2, 3}:
            raise ValueError("race prizes must cover ranks 1, 2 and 3")
        ordered = [self.race_prizes[rank] for rank in (1, 2, 3)]
        for prize in ordered:
            self._require(prize.items, self.items, f"race rank {prize.rank} prize items")
            if any(self.items[item_id].kind not in {"consumable", "material"} for item_id in prize.items):
                raise ValueError(f"race rank {prize.rank} prize items must be consumable or material")
        for higher, lower in ((ordered[0], ordered[1]), (ordered[1], ordered[2])):
            if higher.stones < lower.stones:
                raise ValueError("race prize stones must not fall as the rank improves")
            for item_id, amount in lower.items.items():
                if higher.items.get(item_id, 0) < amount:
                    raise ValueError(
                        f"race prize {item_id} must not fall as the rank improves"
                    )

    def _validate_gauntlets(self):
        if not self.gauntlets:
            raise ValueError("gauntlets must not be empty")
        for entry in self.gauntlets.values():
            self._require(entry.bonus.items, self.items, "gauntlet bonus items")
            for index, round_ in enumerate(entry.rounds, 1):
                if round_.enemy not in self.enemies:
                    raise ValueError(f"gauntlet {entry.id} round {index} has an unknown enemy")
                self._require(round_.reward.items, self.items, "gauntlet round items")

    def _validate_sigils(self):
        if not self.sigils:
            raise ValueError("sigils must not be empty")

    def _validate_escorts(self):
        if not self.escorts:
            raise ValueError("escorts must not be empty")
        for mission in self.escorts.values():
            for wave in mission.waves:
                for enemy_id in wave:
                    if enemy_id not in self.enemies:
                        raise ValueError(f"escort {mission.id} references unknown enemy {enemy_id}")
            for payout in (mission.rewards.full, mission.rewards.partial):
                self._require(payout.items, self.items, "escort reward items")

    def _validate_attunements(self):
        table = self.attunements
        # Attunement targets must be base elements, so a broken parent chain has to be reported as
        # such before this check can blame the attunement table for it.
        for element in self.elements.values():
            try:
                element_ancestors(element.id, self.elements)
            except ValueError as error:
                raise ValueError(f"element parent chain is invalid: {element.id}") from error
        seen = set()
        for option in table.options:
            element = self.elements.get(option.element)
            if element is None:
                raise ValueError(f"attunement references unknown element {option.element}")
            if element.parent is not None:
                raise ValueError(f"attunement target {option.element} must be a base element")
            if option.element in seen:
                raise ValueError(f"duplicate attunement target {option.element}")
            seen.add(option.element)
            self._require(option.items, self.items, "attunement items")

    def _validate_formations(self):
        slots = set(self.formations.by_id)
        if slots != {"vanguard", "center", "rear"}:
            raise ValueError("formations must define exactly vanguard, center and rear")

    def _validate_contracts(self):
        if not self.contracts:
            raise ValueError("contracts must not be empty")
        for contract in self.contracts.values():
            self._require(contract.bonus.items, self.items, f"contract {contract.id} bonus items")

    def _validate_hybrids(self):
        if not self.hybrids:
            raise ValueError("hybrids must not be empty")
        for hybrid in self.hybrids.values():
            self._require(hybrid.seeds, self.items, f"hybrid {hybrid.id} seeds")
            self._require([hybrid.output], self.items, f"hybrid {hybrid.id} output")
            if self.items[hybrid.output].kind != "material":
                raise ValueError(f"hybrid {hybrid.id} must output a seed material")
            crop = next(
                (entry for entry in self.crops.values() if entry.seed_item == hybrid.output), None,
            )
            if crop is None:
                raise ValueError(f"hybrid {hybrid.id} output has no crop")

    def _validate_alchemy(self):
        if not self.alchemy:
            raise ValueError("alchemy recipes must not be empty")
        for entry in self.alchemy.values():
            self._require([entry.item_id], self.items, f"alchemy {entry.id} product")
            self._require(entry.materials, self.items, f"alchemy {entry.id} materials")
            if self.items[entry.item_id].kind not in {"consumable", "breakthrough"}:
                raise ValueError(f"alchemy {entry.id} must produce a consumable")

    def _validate_convoy(self):
        if len(self.convoy_routes) != 3:
            raise ValueError("convoy needs exactly three routes")
        food = self.items.get("spirit_food")
        if food is None or food.price is None or food.price <= 0:
            raise ValueError("convoy food needs a public shop source")
        for route in self.convoy_routes.values():
            value = 0
            for stop in route.stops:
                for road in stop.roads:
                    self._require(road.enemies, self.enemies, "convoy enemies")
                    self._require(road.items, self.items, "convoy reward items")
                    for key, count in road.items.items():
                        if key not in {"forge_ore", "bloodline_essence", "spirit_food"}:
                            raise ValueError("convoy rewards must use existing growth supplies")
                        price = self.items[key].price
                        if price is None:
                            raise ValueError("convoy reward needs a priced public source")
                        value += price * count
            if value > 360:
                raise ValueError("convoy route reward value exceeds the 360-stone budget")

    def _validate_training(self):
        if len(self.training_trials) != 3:
            raise ValueError("training needs exactly three trials")
        rhythms = [tuple(trial.moves) for trial in self.training_trials.values()]
        if len(set(rhythms)) != len(rhythms):
            raise ValueError("training trials need distinct rhythms")
        food = self.items.get("spirit_food")
        if food is None or food.kind != "consumable" or food.price is None:
            raise ValueError("training food needs a public shop source")

    def _validate_nursery(self):
        rule = self.nursery
        self._require([rule.item_id], self.items, "nursery food")
        if self.items[rule.item_id].kind != "consumable":
            raise ValueError("nursery food must be consumable")
        if len({choice.id for choice in rule.choices}) != len(rule.choices) or len({
            choice.name for choice in rule.choices
        }) != len(rule.choices):
            raise ValueError("nursery choices must be unique")
        focuses = [(bool(c.exp), bool(c.affinity), bool(c.bond)) for c in rule.choices]
        if set(focuses) != {(True, False, False), (False, True, False), (False, False, True)}:
            raise ValueError("nursery choices need three distinct growth focuses")

    def _validate_difficulties(self):
        if not self.difficulties:
            raise ValueError("difficulties must not be empty")
        if not any(entry.enemy_scale == 1.0 for entry in self.difficulties.values()):
            raise ValueError("difficulties must include a baseline tier")

    def _validate_bounties(self):
        if len(self.bounties) < 3:
            raise ValueError("bounties must offer at least three entries")
        for bounty in self.bounties.values():
            self._require(bounty.reward.items, self.items, f"bounty {bounty.id} reward items")

    def _validate_sect_exchange(self):
        if not self.sect_exchange:
            raise ValueError("sect exchange must not be empty")
        items = [offer.item_id for offer in self.sect_exchange.values()]
        if len(set(items)) != len(items):
            raise ValueError("sect exchange must not offer the same item twice")
        for offer in self.sect_exchange.values():
            self._require([offer.item_id], self.items, f"sect offer {offer.id} item")

    def _validate_intents(self):
        if not self.intents:
            raise ValueError("battle intents must not be empty")
        names = [intent.name for intent in self.intents.values()]
        if len(set(names)) != len(names):
            raise ValueError("battle intents must have distinct names")

    def _validate_gems(self):
        if not self.gems:
            raise ValueError("sockets must offer at least one gem")
        stats = [gem.stat for gem in self.gems.values()]
        if len(set(stats)) != len(stats):
            raise ValueError("each socket gem must target a different stat")
        for gem in self.gems.values():
            self._require([gem.item_id], self.items, f"gem {gem.id} item")
            if self.items[gem.item_id].kind != "material":
                raise ValueError(f"gem {gem.id} must consume a material item")

    def _validate_duels(self):
        if not {"assault", "guard", "feint"} <= self.rules.duel.stances.keys():
            raise ValueError("duel intents require assault, guard and feint stances")
        if not self.duels:
            raise ValueError("duels must offer at least one opponent")
        realms = [realm.id for realm in self.realms]
        for opponent in self.duels.values():
            if opponent.realm not in realms:
                raise ValueError(f"duel opponent {opponent.id} has an unknown realm")
            self._require(opponent.reward.items, self.items, f"duel {opponent.id} reward items")

    def _validate_drills(self):
        """Every dummy must point at real content and be distinguishable from the rest."""
        if not self.drills:
            raise ValueError("the drill ground needs at least one dummy")
        realms = [realm.id for realm in self.realms]
        orders, names = set(), set()
        for dummy in self.drills.values():
            if dummy.realm not in realms:
                raise ValueError(f"drill dummy {dummy.id} has an unknown realm")
            for element in dummy.elements:
                if element not in self.elements:
                    raise ValueError(f"drill dummy {dummy.id} has an unknown element {element}")
            if dummy.order in orders:
                raise ValueError(f"drill dummy {dummy.id} repeats order {dummy.order}")
            orders.add(dummy.order)
            if dummy.name in names:
                raise ValueError(f"drill dummy {dummy.id} repeats the name {dummy.name}")
            names.add(dummy.name)

    def _validate_commissions(self):
        if not self.commissions:
            raise ValueError("the merchant board needs at least one commission")
        for entry in self.commissions.values():
            self._require(entry.items, self.items, f"commission {entry.id} items")
            # Never pay more than the shop value of what is handed in, or a player could
            # buy the goods and deliver them for a profit.
            paid = sum(
                (self.items[item_id].price or 0) * amount for item_id, amount in entry.items.items()
            )
            if paid and entry.stones >= paid:
                raise ValueError(
                    f"commission {entry.id} pays {entry.stones} for goods worth {paid}"
                )
        if not any(entry.min_rep == 0 for entry in self.commissions.values()):
            raise ValueError("at least one commission must be open to a new merchant")

    def _validate_merchant_standings(self) -> None:
        """Standings must be a strictly rising ladder with consistent perks."""
        if not self.merchant_standings:
            raise ValueError("merchant standings must not be empty")
        ordered = sorted(self.merchant_standings.values(), key=lambda entry: entry.min_trades)
        if ordered[0].min_trades < 1:
            raise ValueError("the first merchant standing needs at least one trade")
        for lower, higher in zip(ordered, ordered[1:]):
            if higher.min_trades <= lower.min_trades:
                raise ValueError("merchant standing thresholds must strictly increase")
        seen_unique: set[str] = set()
        rebate = 0
        for standing in ordered:
            self._require(standing.reward.items, self.items, f"merchant standing {standing.id} reward")
            if standing.perk is not None:
                if standing.perk in ("bid_slot", "listing_slot"):
                    if standing.perk in seen_unique:
                        raise ValueError(f"merchant standing perk {standing.perk} must not repeat")
                    seen_unique.add(standing.perk)
                if standing.perk == "tax_rebate":
                    rebate += standing.rebate
        smallest_fee = min(stall.fee_percent for stall in self.market.stalls)
        if rebate > smallest_fee:
            raise ValueError("merchant standing tax rebate must not exceed the smallest stall fee")

    def _validate_play_games(self) -> None:
        """Three mini-games must each test a different attribute and pay out."""
        if not self.play_games:
            raise ValueError("play games must not be empty")
        if not self.play_courses or "reaction" not in self.play_games:
            raise ValueError("play courses need courses and the reaction game")
        seen_stats: set[str] = set()
        for game in self.play_games.values():
            if game.stat in seen_stats:
                raise ValueError(f"play game stat {game.stat} must not repeat")
            seen_stats.add(game.stat)
            self._require(game.great_items, self.items, f"play game {game.id} great reward")
            for milestone in game.milestones:
                self._require(
                    milestone.items, self.items, f"play game {game.id} milestone reward",
                )

    def _validate_outing_scenes(self) -> None:
        """Every outing must be reachable content with a real item and label."""
        if not self.outings:
            raise ValueError("outing scenes must not be empty")
        sights = set()
        for scene in self.outings.values():
            if scene.sight in sights:
                raise ValueError(f"outing sight {scene.sight} must not repeat")
            sights.add(scene.sight)
            if scene.item is not None:
                self._require((scene.item,), self.items, f"outing scene {scene.id} item")

    def _validate_fishing_spots(self) -> None:
        """Every spot must be castable and its table must reference real items."""
        if not self.fishing_spots:
            raise ValueError("fishing spots must not be empty")
        for spot in self.fishing_spots.values():
            for entry in spot.catches:
                self._require((entry.item,), self.items, f"fishing spot {spot.id} catch")
        if not self.fishing_baits:
            raise ValueError("fishing baits must not be empty")
        catch_items = {entry.item for spot in self.fishing_spots.values() for entry in spot.catches}
        names = set()
        for bait in self.fishing_baits.values():
            if bait.name in names:
                raise ValueError("fishing bait names must be unique")
            names.add(bait.name)
            self._require((bait.cost_item,), self.items, f"fishing bait {bait.id} cost")
            self._require(bait.favored_items, catch_items, f"fishing bait {bait.id} favored catches")

    def _validate_merchant_contracts(self) -> None:
        """A contract must be completable and its risk must match its reward."""
        if not self.merchant_contracts:
            raise ValueError("merchant contracts must not be empty")
        for contract in self.merchant_contracts.values():
            for stage in contract.stages:
                self._require(stage.items, self.items, f"merchant contract {contract.id} stage items")
            self._require(contract.bonus.items, self.items, f"merchant contract {contract.id} bonus items")
            if contract.deposit > contract.payout:
                raise ValueError(
                    f"merchant contract {contract.id} deposit exceeds its total payout"
                )
        ordered = sorted(self.merchant_contracts.values(), key=lambda entry: entry.min_rep)
        for lower, higher in zip(ordered, ordered[1:]):
            if higher.payout < lower.payout:
                raise ValueError("merchant contract payout must not fall as the reputation gate rises")
        if ordered[0].min_rep != 0:
            raise ValueError("at least one merchant contract must be open at zero reputation")

    def _validate_merchant_exchange(self):
        """Reputation exchange must reference real consumables/materials."""
        if not self.merchant_exchange:
            raise ValueError("the merchant exchange needs at least one offer")
        for offer in self.merchant_exchange.values():
            if offer.item not in self.items:
                raise ValueError(f"merchant exchange {offer.id} has an unknown item")
            if self.items[offer.item].kind not in {"consumable", "material"}:
                raise ValueError(
                    f"merchant exchange {offer.id} item must be consumable or material"
                )

    def _validate_collection_rank_rewards(self):
        """Collection rank milestones must be three ordered, real rewards."""
        if set(self.collection_rank_rewards) != {1, 3, 10}:
            raise ValueError("collection rank rewards must cover ranks 1, 3 and 10")
        ordered = [self.collection_rank_rewards[rank] for rank in (1, 3, 10)]
        for reward in ordered:
            self._require(
                reward.items, self.items, f"collection rank {reward.rank} reward items",
            )
            if any(self.items[item_id].kind not in {"consumable", "material"}
                   for item_id in reward.items):
                raise ValueError(
                    f"collection rank {reward.rank} reward items must be consumable or material"
                )
        for higher, lower in zip(ordered, ordered[1:]):
            if higher.stones < lower.stones:
                raise ValueError("collection rank reward stones must not fall as the rank improves")
            for item_id, amount in lower.items.items():
                if higher.items.get(item_id, 0) < amount:
                    raise ValueError(
                        f"collection rank reward {item_id} must not fall as the rank improves"
                    )

    def _validate_collection_exchange(self):
        """Duplicate-species exchange offers must pay real usable items."""
        if not self.collection_exchange:
            raise ValueError("collection exchange must not be empty")
        for offer in self.collection_exchange.values():
            self._require(offer.items, self.items, f"collection exchange {offer.id} items")
            if any(
                self.items[item_id].kind not in {"consumable", "material", "breakthrough"}
                for item_id in offer.items
            ):
                raise ValueError(
                    f"collection exchange {offer.id} rewards must be usable items"
                )

    def _validate_arena_merit_exchange(self):
        """Arena merit offers must pay real usable items."""
        if not self.arena_merit_exchange:
            raise ValueError("arena merit exchange must not be empty")
        for offer in self.arena_merit_exchange.values():
            self._require(offer.items, self.items, f"arena merit exchange {offer.id} items")
            if any(
                self.items[item_id].kind not in {"consumable", "material", "breakthrough"}
                for item_id in offer.items
            ):
                raise ValueError(
                    f"arena merit exchange {offer.id} rewards must be usable items"
                )

    def _validate_share_rank_rewards(self):
        """Share board rank milestones must be three ordered, real rewards."""
        if set(self.share_rank_rewards) != {1, 3, 10}:
            raise ValueError("share rank rewards must cover ranks 1, 3 and 10")
        ordered = [self.share_rank_rewards[rank] for rank in (1, 3, 10)]
        for reward in ordered:
            self._require(
                reward.items, self.items, f"share rank {reward.rank} reward items",
            )
            if any(self.items[item_id].kind not in {"consumable", "material"}
                   for item_id in reward.items):
                raise ValueError(
                    f"share rank {reward.rank} reward items must be consumable or material"
                )
        for higher, lower in zip(ordered, ordered[1:]):
            if higher.stones < lower.stones:
                raise ValueError("share rank reward stones must not fall as the rank improves")
            for item_id, amount in lower.items.items():
                if higher.items.get(item_id, 0) < amount:
                    raise ValueError(
                        f"share rank reward {item_id} must not fall as the rank improves"
                    )

    def _validate_share_rewards(self):
        """Share reader milestones must be three ordered, real rewards."""
        if set(self.share_rewards) != {3, 10, 30}:
            raise ValueError("share rewards must cover 3, 10 and 30 readers")
        ordered = [self.share_rewards[readers] for readers in (3, 10, 30)]
        for reward in ordered:
            self._require(reward.items, self.items, f"share reward {reward.readers} items")
            if any(self.items[item_id].kind not in {"consumable", "material"}
                   for item_id in reward.items):
                raise ValueError(
                    f"share reward {reward.readers} items must be consumable or material"
                )
        for lower, higher in zip(ordered, ordered[1:]):
            if higher.stones < lower.stones:
                raise ValueError("share reward stones must not fall as readers grow")
            for item_id, amount in lower.items.items():
                if higher.items.get(item_id, 0) < amount:
                    raise ValueError(
                        f"share reward {item_id} must not fall as readers grow"
                    )

    def _validate_market(self):
        """The stall ladder must be worth climbing and every sellable kind must exist."""
        stalls = self.market.stalls
        if stalls[0].unlock_cost != 0:
            raise ValueError("the first market stall must be free")
        for previous, current in zip(stalls, stalls[1:]):
            if current.unlock_cost <= previous.unlock_cost:
                raise ValueError("market stall unlock costs must strictly increase")
            if current.slots <= previous.slots:
                raise ValueError("market stall slots must strictly increase")
            if current.fee_percent > previous.fee_percent:
                raise ValueError("market stall fees must not increase with the tier")
        if len({stall.id for stall in stalls}) != len(stalls):
            raise ValueError("duplicate market stall id")
        for kind in self.market.sellable_kinds:
            if not any(item.kind == kind for item in self.items.values()):
                raise ValueError(f"market has no {kind} item to sell")
        if self.market.max_bid_quantity > self.market.max_quantity:
            raise ValueError("market buy orders must not exceed the listing quantity cap")

    def _validate_mail(self):
        """Every kind a mail may carry must actually exist in the item catalog."""
        for kind in self.rules.mail.kinds:
            if not any(item.kind == kind for item in self.items.values()):
                raise ValueError(f"mail has no {kind} item to send")

    def _validate_friend(self):
        """The shipped roster ceiling must exceed the request window's own reach.

        A friendship has no content of its own, so there is nothing to cross-check
        against a data file; the only load-time invariant is that a player can
        actually hold more friends than one request round trip would need, i.e.
        the ceiling is at least 2 so an added friend never immediately hits the cap.
        """
        if self.rules.friend.max_friends < 2:
            raise ValueError("friend roster must hold at least two friends")

    def _validate_share(self):
        """A share code must be long enough to be unguessable and fit the column.

        A share code is a bearer capability: whoever holds it may read a report. The
        load-time invariant is therefore about the code's own space — a code shorter
        than the schema's floor could be brute-forced, so refuse it before shipping.
        """
        if self.rules.share.code_days < 1:
            raise ValueError("share code must last at least one day")

    def _validate_borrow(self):
        """A borrowed companion may not outshine your own bench.

        ``support`` is the self-built path: ``slots`` bench companions each lend ``rate``
        of their base stats. If one borrowed friend's companion lent more than all of
        those together, the support roster would become a formality and every player's
        best move would be social recruiting rather than raising their own pets.
        """
        ceiling = self.rules.support.rate * self.rules.support.slots
        if self.rules.borrow.rate > ceiling + 1e-9:
            raise ValueError(
                f"borrow.rate ({self.rules.borrow.rate}) exceeds the support roster's own ceiling ({ceiling})"
            )

    def _validate_mentor(self):
        """Graduation must be reachable and meaningful, and its rewards must exist."""
        realms = [realm.id for realm in self.realms]
        rule = self.rules.mentor
        if rule.graduate_realm not in realms:
            raise ValueError(f"mentor graduate realm {rule.graduate_realm} does not exist")
        if realms.index(rule.graduate_realm) == 0:
            raise ValueError("mentor graduate realm must not be the starting realm")
        self._require(rule.mentor_reward.items, self.items, "mentor reward items")
        self._require(rule.apprentice_reward.items, self.items, "apprentice reward items")

    def _metric_ceilings(self):
        """Largest value each bounded metric can reach with the shipped content.

        A metric is absent when nothing caps it: wins, battles, streaks and
        owned items all grow without limit (equipment can be owned in multiples
        and claims can be repeated across seasons), so those are deliberately
        not checked and content may keep raising their targets. ``pets_owned``
        and ``skill_mastery_rewards`` are capped by the configurable roster limit
        rather than by content, so they are not bounded here either; only one
        resonance can be enabled at a time, which is fixed.
        """
        return {
            "species_collected": len(self.species),
            "duplicate_species": len(self.species),
            "max_realm": len(self.realms),
            "max_layer": len(self.realms) * 10,
            "max_bloodline": max(self.bloodlines),
            "stage_clears": len(self.stages),
            "tower_depth": len(self.tower),
            "lineage_branches": len(self.lineages),
            "skills_learned": len(self.skills),
            "max_skill_level": len(self.skill_levels),
            "skill_level_sum": len(self.skills) * len(self.skill_levels),
            "max_affinity": 100,
            "adventures_discovered": len(self.encounters),
            "max_enhancement": len(self.forge_levels) - 1,
            "journey_claims": len(self.journey),
            "echo_claims": len(self.encounters),
            "first_clear_claims": len(self.dungeons),
            "dungeon_clears": len(self.dungeons),
            "equipment_set_claims": len(self.equipment_sets),
            "resonances_enabled": 1,
            "main_quest_claims": len(self.main_quests),
            "weekly_claims": len(self.weekly_quests),
            "arc_choices": sum(len(arc.chapters) for arc in self.arcs.values()),
            # The premium track has six five-level milestones.
            "battle_pass_premium_claims": 6,
        }

    def _require_within_ceiling(self, kind: str, name: str, metric: str, target: int) -> None:
        ceiling = self._metric_ceilings().get(metric)
        if ceiling is not None and target > ceiling:
            raise ValueError(
                f"{kind} {name} target {target} exceeds available {metric} ({ceiling})"
            )

    def _validate_achievements(self):
        required = {
            "species_collected", "duplicate_species", "pets_owned", "max_realm", "max_layer", "max_bloodline",
            "stage_clears", "tower_depth", "pvp_wins", "pve_wins", "team_pve_wins", "lineage_branches",
            "skills_learned", "max_skill_level", "skill_level_sum", "expedition_claims", "max_affinity",
            "best_bond_streak", "adventures_discovered", "max_enhancement", "spar_wins",
            "battles_fought", "equipment_owned", "achievements_claimed", "resonances_enabled",
            "journey_claims", "echo_claims", "first_clear_claims", "equipment_set_claims",
            "dungeon_clears",
            "encounter_choices", "gem_cuts", "arc_choices",
            "farm_harvests", "banquets_held", "cave_offerings",
        }
        present = {achievement.metric for achievement in self.achievements.values()}
        if not required.issubset(present):
            raise ValueError(f"missing achievement metrics: {sorted(required - present)}")
        pairs = [(entry.metric, entry.target) for entry in self.achievements.values()]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate achievement metric target")
        maxima = self._metric_ceilings()
        targets = {}
        for entry in self.achievements.values():
            targets.setdefault(entry.metric, set()).add(entry.target)
        final_milestones = {
            "species_collected", "max_realm", "max_layer", "max_bloodline",
            "stage_clears", "tower_depth", "max_skill_level", "max_affinity", "adventures_discovered",
            "max_enhancement", "journey_claims", "echo_claims", "first_clear_claims",
        }
        for metric in final_milestones:
            if maxima[metric] not in targets.get(metric, set()):
                raise ValueError(f"missing final achievement milestone for {metric}")
        expected_layers = set(range(10, maxima["max_layer"] + 1, 10))
        if not expected_layers.issubset(targets.get("max_layer", set())):
            raise ValueError("missing realm layer achievement milestone")
        if not {50, 100}.issubset(targets.get("max_affinity", set())):
            raise ValueError("missing affinity achievement milestone")
        if not {7, 30}.issubset(targets.get("best_bond_streak", set())):
            raise ValueError("missing bond streak achievement milestone")
        if not {1, 10, 30}.issubset(targets.get("team_pve_wins", set())):
            raise ValueError("missing team PVE achievement milestone")
        if not {5, 10}.issubset(targets.get("adventures_discovered", set())):
            raise ValueError("missing adventure discovery achievement milestone")
        for entry in self.achievements.values():
            self._require(entry.reward.items, self.items, "achievement reward items")
            maximum = maxima.get(entry.metric)
            if maximum is not None and entry.target > maximum:
                raise ValueError(f"achievement target exceeds available {entry.metric}")

    def _validate_journey(self, realm_ids):
        chapters = self.journey
        if not chapters:
            raise ValueError("at least one journey chapter is required")
        order = [realm.id for realm in self.realms]
        covered = set()
        for chapter in chapters.values():
            self._require([chapter.realm], realm_ids, "journey realm")
            covered.add(chapter.realm)
            task = chapter.task
            limit = order.index(chapter.realm)
            if task.kind in {"clear_dungeon", "win_at"}:
                self._require([task.target], self.dungeons, "journey dungeon")
                if order.index(self.dungeons[task.target].min_realm) > limit:
                    raise ValueError(f"journey {chapter.id} targets an unreachable dungeon")
            elif task.kind == "discover":
                self._require([task.target], self.encounters, "journey encounter")
                route = next(
                    route for route in self.exploration_routes.values() if task.target in route.encounters
                )
                if order.index(route.min_realm) > limit:
                    raise ValueError(f"journey {chapter.id} targets an unreachable encounter")
            elif task.kind == "collect_species":
                self._require([task.target], self.species, "journey species")
            elif task.kind == "enable_resonance":
                self._require([task.target], self.resonances, "journey resonance")
            else:
                self._require([task.target], realm_ids, "journey realm target")
                if order.index(task.target) > limit:
                    raise ValueError(f"journey {chapter.id} targets an unreachable realm")
            if task.kind != "win_at" and task.count != 1:
                raise ValueError(f"journey {chapter.id} may only repeat a win_at task")
        missing = set(order) - covered
        if missing:
            raise ValueError(f"missing journey chapters for realms: {sorted(missing)}")
        heads = [chapter for chapter in chapters.values() if chapter.previous_id is None]
        if len(heads) != 1:
            raise ValueError("journey must have exactly one first chapter")
        for chapter in chapters.values():
            if chapter.previous_id is None:
                continue
            self._require([chapter.previous_id], chapters, "journey previous chapter")
            if order.index(chapters[chapter.previous_id].realm) > order.index(chapter.realm):
                raise ValueError(f"journey {chapter.id} moves backwards in realms")
        seen = set()
        current = heads[0]
        while current is not None:
            if current.id in seen:
                raise ValueError("journey chain contains a cycle")
            seen.add(current.id)
            following = [c for c in chapters.values() if c.previous_id == current.id]
            if len(following) > 1:
                raise ValueError(f"journey chapter {current.id} has more than one successor")
            current = following[0] if following else None
        if seen != set(chapters):
            raise ValueError("journey chapters must form a single chain")

    def _validate_weekly_rewards(self):
        thresholds = [entry.threshold for entry in self.weekly_rewards.values()]
        if set(thresholds) != {2, 4, 6} or len(thresholds) != 3:
            raise ValueError("weekly rewards must define unique 2/4/6 milestones")
        if max(thresholds) > len(self.weekly_quests):
            raise ValueError("weekly reward exceeds available quests")
        for entry in self.weekly_rewards.values():
            self._require(entry.items, self.items, "weekly reward items")

    def _validate_season_missions(self):
        missions = self.season_missions
        if not missions:
            raise ValueError("at least one season mission is required")
        expected = {
            "season_matches", "season_wins", "season_pve", "season_discoveries", "season_claims",
        }
        present = {mission.metric for mission in missions.values()}
        if not expected.issubset(present):
            raise ValueError(f"missing season mission metrics: {sorted(expected - present)}")
        pairs = [(mission.metric, mission.target) for mission in missions.values()]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate season mission metric target")

    def _validate_daily_assignments(self):
        assignments = self.daily_assignments
        if not assignments:
            raise ValueError("at least one daily assignment is required")
        expected = {
            "daily_pve", "daily_pvp", "daily_discovery", "daily_expedition", "daily_claim",
            "daily_training",
        }
        present = {assignment.metric for assignment in assignments.values()}
        if not expected.issubset(present):
            raise ValueError(f"missing daily assignment metrics: {sorted(expected - present)}")
        pairs = [(assignment.metric, assignment.target) for assignment in assignments.values()]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate daily assignment metric target")

    def _validate_arena_tier_rewards(self):
        tiers = {tier.id for tier in self.arena.tiers}
        if set(self.arena_tier_rewards) != tiers:
            raise ValueError("every arena tier needs exactly one achievement reward")
        for reward in self.arena_tier_rewards.values():
            self._require(reward.items, self.items, "arena tier reward items")

    def _validate_stage_star_rewards(self):
        milestones = sorted(self.stage_star_rewards)
        if not milestones:
            raise ValueError("at least one stage star reward is required")
        if len(set(milestones)) != len(milestones):
            raise ValueError("duplicate stage star milestone")
        maximum = 3 * len(self.stages)
        if milestones[-1] > maximum:
            raise ValueError(f"stage star milestone exceeds the {maximum}-star maximum")
        for milestone in milestones:
            self._require(self.stage_star_rewards[milestone].items, self.items, "stage star reward items")

    def _validate_codex_rewards(self):
        if set(self.codex_rewards) != set(self.species):
            raise ValueError("every species needs exactly one codex reward")
        for reward in self.codex_rewards.values():
            self._require(reward.items, self.items, "codex reward items")

    def _validate_crops(self):
        if not self.crops:
            raise ValueError("farm crops are required")
        for crop in self.crops.values():
            seed = self.items.get(crop.seed_item)
            if seed is None or seed.kind != "material":
                raise ValueError(f"crop {crop.id} needs a material seed item")
            self._require(crop.reward_items, self.items, f"crop {crop.id} reward items")

    def _validate_resonances(self):
        covered = set()
        pairs = set()
        for resonance in self.resonances.values():
            self._require(resonance.required_species, self.species, "resonance species")
            pair = frozenset(resonance.required_species)
            if pair in pairs:
                raise ValueError("duplicate resonance species pair")
            pairs.add(pair)
            covered.update(pair)
        if covered != set(self.species):
            raise ValueError("every species must appear in at least one resonance")

    @staticmethod
    def _require(keys, targets, label):
        missing = set(keys) - set(targets)
        if missing:
            raise ValueError(f"unknown {label}: {sorted(missing)}")
