from dataclasses import dataclass
from typing import Callable

from ..domain.models import Reply
from ..gameplay import adventure, cultivation, economy, equipment, forging, identity, information, pets, quests, skills
from ..gameplay import companionship, crafting, expeditions, lineage, pve_stages, tower
from ..gameplay import breeding
from ..gameplay import main_quest
from ..gameplay import daily_dungeon
from ..gameplay import weekly_quests
from ..gameplay import inheritance
from ..gameplay import titles
from ..gameplay import objectives
from ..gameplay import sweep
from ..gameplay import first_clear
from ..gameplay import free_summon
from ..gameplay import journey
from ..gameplay import echoes
from ..gameplay import season_missions
from ..gameplay import daily_assignment
from ..gameplay import achievements, resonance
from ..gameplay import codex
from ..gameplay import stage_stars
from ..gameplay import battle_records, help
from ..gameplay.arena import battles, matching, seasons
from ..gameplay.arena import tier_rewards
from ..gameplay.teams import management, party, requests
from .context import Context


@dataclass(frozen=True)
class Command:
    handler: Callable[[Context, str], Reply]
    arguments: bool = False
    registered: bool = True


ACTIONS = {
    "help": Command(help.help_game, True, registered=False),
    "identity": Command(identity.profile, registered=False),
    "status": Command(information.status),
    "catalog": Command(information.catalog, True, registered=False),
    "rank": Command(information.rank, registered=False),
    "adventure_rank": Command(information.adventure_rank, registered=False),
    "pvp_rank": Command(seasons.rank, True, registered=False),
    "season": Command(seasons.status, True),
    "season_rewards": Command(seasons.catalog, True),
    "season_claim": Command(seasons.claim, True),
    "match": Command(matching.candidates, True),
    "adopt": Command(pets.adopt, True, registered=False),
    "summon": Command(pets.summon, True),
    "pet_list": Command(pets.pet_list, True),
    "pet_archive_list": Command(pets.archive_list, True),
    "pet_archive": Command(pets.archive, True),
    "pet_restore": Command(pets.restore, True),
    "switch": Command(pets.switch, True),
    "lineup": Command(pets.lineup, True),
    "sign": Command(economy.sign),
    "bag": Command(economy.bag),
    "shop": Command(economy.shop, True, registered=False),
    "buy": Command(economy.buy, True),
    "recycle": Command(economy.recycle, True),
    "use": Command(economy.use, True),
    "feed": Command(economy.feed, True),
    "bond": Command(companionship.bond, True),
    "train": Command(cultivation.train, True),
    "co_train": Command(cultivation.co_train, True),
    "breeding": Command(breeding.breeding, True, registered=False),
    "main_quests": Command(main_quest.catalog, True, registered=False),
    "main_quest_claim": Command(main_quest.claim, True),
    "daily_dungeon": Command(daily_dungeon.catalog, True, registered=False),
    "daily_dungeon_claim": Command(daily_dungeon.claim, True),
    "weekly_quests": Command(weekly_quests.catalog, True, registered=False),
    "weekly_quest_claim": Command(weekly_quests.claim, True),
    "inheritance": Command(inheritance.inherit, True),
    "titles": Command(titles.catalog, True, registered=False),
    "objectives": Command(objectives.objectives, True, registered=False),
    "sweep": Command(sweep.sweep, True),
    "first_clear": Command(first_clear.catalog, True, registered=False),
    "first_clear_claim": Command(first_clear.claim, True),
    "free_summon": Command(free_summon.catalog, True, registered=False),
    "free_summon_claim": Command(free_summon.claim, True),
    "journey": Command(journey.catalog, True, registered=False),
    "journey_claim": Command(journey.claim, True),
    "echoes": Command(echoes.catalog, True, registered=False),
    "echo_choose": Command(echoes.choose, True),
    "season_missions": Command(season_missions.catalog, True, registered=False),
    "season_mission_claim": Command(season_missions.claim, True),
    "daily_assignment": Command(daily_assignment.catalog, True, registered=False),
    "daily_assignment_claim": Command(daily_assignment.claim, True),
    "breakthrough": Command(cultivation.breakthrough, True),
    "evolve": Command(cultivation.evolve, True),
    "lineage_catalog": Command(lineage.catalog, True, registered=False),
    "lineage_choose": Command(lineage.choose, True),
    "explore": Command(adventure.explore, True, registered=False),
    "adventure_codex": Command(adventure.adventure_codex, True, registered=False),
    "dungeons": Command(adventure.dungeons, True, registered=False),
    "challenge": Command(adventure.challenge, True),
    "stage_catalog": Command(pve_stages.catalog, True, registered=False),
    "stage_challenge": Command(pve_stages.challenge, True),
    "tower_catalog": Command(tower.catalog, True, registered=False),
    "tower_challenge": Command(tower.challenge, True),
    "achievements": Command(achievements.achievements, True, registered=False),
    "achievement_claim": Command(achievements.claim, True),
    "collection": Command(achievements.collection, True, registered=False),
    "codex": Command(codex.catalog, True, registered=False),
    "codex_claim": Command(codex.claim, True),
    "stage_stars": Command(stage_stars.catalog, True, registered=False),
    "stage_stars_claim": Command(stage_stars.claim, True),
    "arena_tier_rewards": Command(tier_rewards.catalog, True, registered=False),
    "arena_tier_claim": Command(tier_rewards.claim, True),
    "resonance": Command(resonance.resonance, True),
    "team_stage_challenge": Command(pve_stages.team_challenge, True),
    "quests": Command(quests.quests),
    "claim": Command(quests.claim, True),
    "expedition_catalog": Command(expeditions.catalog, True, registered=False),
    "expedition_start": Command(expeditions.start, True),
    "expedition_status": Command(expeditions.status, True),
    "expedition_claim": Command(expeditions.claim, True),
    "expedition_cancel": Command(expeditions.cancel, True),
    "pvp": Command(battles.pvp, True),
    "spar": Command(battles.spar, True),
    "battle_reports": Command(battle_records.reports, True),
    "team_create": Command(party.create),
    "team_join": Command(requests.join, True),
    "team_invite": Command(requests.invite, True),
    "team_requests": Command(requests.inbox, True),
    "team_accept": Command(requests.accept, True),
    "team_reject": Command(requests.reject, True),
    "team_withdraw": Command(requests.withdraw, True),
    "team_status": Command(party.status, True),
    "team_ready": Command(party.ready),
    "team_unready": Command(party.unready),
    "team_leave": Command(management.leave),
    "team_kick": Command(management.kick, True),
    "team_transfer": Command(management.transfer, True),
    "team_disband": Command(management.disband),
    "team_challenge": Command(party.challenge, True),
    "equipment": Command(equipment.view, True),
    "equipment_sets": Command(equipment.sets, True, registered=False),
    "equipment_catalog": Command(equipment.catalog, True, registered=False),
    "unequip": Command(equipment.unequip, True),
    "enhance": Command(forging.enhance, True),
    "recipe_catalog": Command(crafting.catalog, True, registered=False),
    "craft": Command(crafting.craft, True),
    "salvage": Command(crafting.salvage, True),
    "skills": Command(skills.view),
    "skill_catalog": Command(skills.catalog, True, registered=False),
    "learn": Command(skills.learn, True),
    "equip_skill": Command(skills.equip, True),
    "unequip_skill": Command(skills.unequip, True),
}
COMMANDS = {
    "灵宠": "help", "灵宠帮助": "help", "我的信息": "identity",
    "我的灵宠": "status", "我的宠": "status",
    "灵宠图鉴": "catalog", "灵宠排行": "rank", "灵宠奇闻榜": "adventure_rank", "灵宠论剑榜": "pvp_rank",
    "灵宠赛季": "season", "灵宠赛季奖励": "season_rewards", "灵宠赛季领奖": "season_claim",
    "灵宠段位奖励": "arena_tier_rewards", "灵宠段位领奖": "arena_tier_claim",
    "灵宠匹配": "match",
    "灵宠领养": "adopt", "灵宠召唤": "summon", "灵宠列表": "pet_list", "灵宠切换": "switch",
    "灵宠封存库": "pet_archive_list", "灵宠封存": "pet_archive", "灵宠复原": "pet_restore",
    "灵宠出战": "lineup", "灵宠阵容": "lineup", "灵宠签到": "sign", "灵宠背包": "bag", "灵宠商店": "shop",
    "灵宠购买": "buy", "灵宠使用": "use", "灵宠喂养": "feed", "灵宠互动": "bond", "灵宠修炼": "train", "灵宠回收": "recycle",
    "灵宠合修": "co_train",
    "灵宠培育": "breeding",
    "灵宠主线": "main_quests", "灵宠主线领奖": "main_quest_claim",
    "灵宠今日秘境": "daily_dungeon", "灵宠今日秘境领奖": "daily_dungeon_claim",
    "灵宠周常": "weekly_quests", "灵宠周常领奖": "weekly_quest_claim",
    "灵宠强化继承": "inheritance",
    "灵宠称号": "titles", "灵宠目标": "objectives",
    "灵宠扫荡": "sweep", "灵宠秘境首通": "first_clear", "灵宠秘境首通领奖": "first_clear_claim", "灵宠每周召唤": "free_summon", "灵宠每周召唤领取": "free_summon_claim", "灵宠行纪": "journey", "灵宠行纪领奖": "journey_claim", "灵宠回响": "echoes", "灵宠回响选择": "echo_choose", "灵宠赛季任务": "season_missions", "灵宠赛季任务领奖": "season_mission_claim", "灵宠课题": "daily_assignment", "灵宠课题领奖": "daily_assignment_claim",
    "灵宠突破": "breakthrough", "灵宠进化": "evolve", "灵宠历练": "explore", "灵宠奇闻": "adventure_codex",
    "灵宠秘境": "dungeons", "灵宠挑战": "challenge", "灵宠任务": "quests", "灵宠领奖": "claim",
    "灵宠关卡": "stage_catalog", "灵宠挑战关卡": "stage_challenge",
    "灵宠关卡星级": "stage_stars", "灵宠关卡星级领奖": "stage_stars_claim",
    "灵宠万灵塔": "tower_catalog", "灵宠挑战万灵塔": "tower_challenge",
    "灵宠组队关卡": "team_stage_challenge",
    "灵宠成就": "achievements", "灵宠成就领奖": "achievement_claim", "灵宠收集": "collection",
    "灵宠图鉴奖励": "codex", "灵宠图鉴领奖": "codex_claim",
    "灵宠共鸣": "resonance",
    "灵宠委托": "expedition_catalog", "灵宠派遣": "expedition_start", "灵宠行程": "expedition_status",
    "灵宠归来": "expedition_claim", "灵宠召回": "expedition_cancel",
    "灵宠论剑": "pvp", "灵宠切磋": "spar",
    "灵宠战报": "battle_reports",
    "灵宠组队": "team_create", "灵宠入队": "team_join", "灵宠队伍": "team_status",
    "灵宠准备": "team_ready", "灵宠取消准备": "team_unready", "灵宠退队": "team_leave",
    "灵宠组队挑战": "team_challenge",
    "灵宠邀请": "team_invite", "灵宠队务": "team_requests",
    "灵宠队伍同意": "team_accept", "灵宠队伍拒绝": "team_reject", "灵宠队伍撤回": "team_withdraw",
    "灵宠踢人": "team_kick", "灵宠转让": "team_transfer", "灵宠解散": "team_disband",
    "灵宠装备": "equipment", "灵宠装备图鉴": "equipment_catalog", "灵宠卸装": "unequip",
    "灵宠套装": "equipment_sets",
    "灵宠强化": "enhance",
    "灵宠血脉": "lineage_catalog", "灵宠分支": "lineage_choose",
    "灵宠工坊": "recipe_catalog", "灵宠打造": "craft", "灵宠分解": "salvage",
    "灵宠技能": "skills", "灵宠技能图鉴": "skill_catalog", "灵宠学习": "learn",
    "灵宠携带": "equip_skill", "灵宠卸技": "unequip_skill",
}
