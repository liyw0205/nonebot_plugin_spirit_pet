from dataclasses import dataclass
from typing import Callable

from ..domain.models import Reply
from ..gameplay import adventure, cultivation, duels, economy, equipment, forging, identity, information, pets, quests, skills, teams
from .context import Context


@dataclass(frozen=True)
class Command:
    handler: Callable[[Context, str], Reply]
    arguments: bool = False


ACTIONS = {
    "help": Command(information.help_game),
    "identity": Command(identity.profile),
    "dao_name": Command(identity.rename, True),
    "status": Command(information.status),
    "catalog": Command(information.catalog, True),
    "rank": Command(information.rank),
    "pvp_rank": Command(information.pvp_rank),
    "adopt": Command(pets.adopt, True),
    "summon": Command(pets.summon, True),
    "pet_list": Command(pets.pet_list, True),
    "switch": Command(pets.switch, True),
    "rename": Command(pets.rename, True),
    "sign": Command(economy.sign),
    "bag": Command(economy.bag),
    "shop": Command(economy.shop),
    "buy": Command(economy.buy, True),
    "use": Command(economy.use, True),
    "feed": Command(economy.feed),
    "train": Command(cultivation.train),
    "breakthrough": Command(cultivation.breakthrough, True),
    "evolve": Command(cultivation.evolve),
    "explore": Command(adventure.explore),
    "dungeons": Command(adventure.dungeons),
    "challenge": Command(adventure.challenge, True),
    "quests": Command(quests.quests),
    "claim": Command(quests.claim, True),
    "pvp": Command(duels.pvp, True),
    "spar": Command(duels.spar, True),
    "accept": Command(duels.accept),
    "reject": Command(duels.reject),
    "team_create": Command(teams.create),
    "team_join": Command(teams.join, True),
    "team_status": Command(teams.status),
    "team_ready": Command(teams.ready),
    "team_unready": Command(teams.unready),
    "team_leave": Command(teams.leave),
    "team_challenge": Command(teams.challenge, True),
    "equipment": Command(equipment.view, True),
    "equipment_catalog": Command(equipment.catalog),
    "unequip": Command(equipment.unequip, True),
    "enhance": Command(forging.enhance, True),
    "skills": Command(skills.view),
    "skill_catalog": Command(skills.catalog),
    "learn": Command(skills.learn, True),
    "equip_skill": Command(skills.equip, True),
    "unequip_skill": Command(skills.unequip, True),
}
COMMANDS = {
    "灵宠": "help", "灵宠帮助": "help", "我的道号": "identity", "灵宠道号": "dao_name", "我的灵宠": "status",
    "灵宠图鉴": "catalog", "灵宠排行": "rank", "灵宠论剑榜": "pvp_rank",
    "灵宠领养": "adopt", "灵宠召唤": "summon", "灵宠列表": "pet_list", "灵宠切换": "switch",
    "灵宠改名": "rename", "灵宠签到": "sign", "灵宠背包": "bag", "灵宠商店": "shop",
    "灵宠购买": "buy", "灵宠使用": "use", "灵宠喂养": "feed", "灵宠修炼": "train",
    "灵宠突破": "breakthrough", "灵宠进化": "evolve", "灵宠历练": "explore",
    "灵宠秘境": "dungeons", "灵宠挑战": "challenge", "灵宠任务": "quests", "灵宠领奖": "claim",
    "灵宠论剑": "pvp", "灵宠切磋": "spar", "灵宠应战": "accept", "灵宠拒战": "reject",
    "灵宠组队": "team_create", "灵宠入队": "team_join", "灵宠队伍": "team_status",
    "灵宠准备": "team_ready", "灵宠取消准备": "team_unready", "灵宠退队": "team_leave",
    "灵宠组队挑战": "team_challenge",
    "灵宠装备": "equipment", "灵宠装备图鉴": "equipment_catalog", "灵宠卸装": "unequip",
    "灵宠强化": "enhance",
    "灵宠技能": "skills", "灵宠技能图鉴": "skill_catalog", "灵宠学习": "learn",
    "灵宠携带": "equip_skill", "灵宠卸技": "unequip_skill",
}
