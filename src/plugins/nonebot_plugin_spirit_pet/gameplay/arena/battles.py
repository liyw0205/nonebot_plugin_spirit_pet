import json
from dataclasses import asdict

from ...application.context import Context
from ...domain.models import GameError, Reply
from ...utils.time import beijing_day
from ..combat import fight
from ..battle_records import capture_snapshot, record_battle
from ..loadout import combatants
from ..mastery import award_mastery
from ..quests import advance
from .common import current_season
from .eligibility import check_ranked
from .scoring import settle_ranked


def _target(ctx: Context, dao_name: str):
    target = ctx.repo.player_by_name(dao_name)
    if target is None:
        raise GameError("该道号不存在，请填写对方的道号。")
    if target.user_id == ctx.user_id:
        raise GameError("不能向自己发起对战。")
    if not ctx.repo.active_pets(target.user_id):
        raise GameError("该道友尚未选择出战灵宠。")
    return target


def pvp(ctx: Context, arg: str) -> Reply:
    ctx.player()
    previous = ctx.repo.conn.execute(
        "SELECT challenger_id, reply FROM pvp_results WHERE operation_id=?", (ctx.operation_id,),
    ).fetchone()
    if previous is not None:
        if previous["challenger_id"] != ctx.user_id:
            raise GameError("该挑战消息已被处理，不能复用。")
        data = json.loads(previous["reply"])
        return Reply(data["title"], tuple(data["lines"]), tuple(data["commands"]))
    if not arg:
        from .seasons import rank

        return rank(ctx, "")
    target = _target(ctx, arg)
    season = current_season(ctx)
    attacking_pet, defending_pet = check_ranked(ctx, season, ctx.user_id, target.user_id)
    attackers = combatants(ctx, recover_energy=False)
    defenders = combatants(ctx, target.user_id, recover_energy=False)
    capture = capture_snapshot(
        ctx, (attackers, defenders),
        ([ctx.user_id] * len(attackers), [target.user_id] * len(defenders)),
    )
    battle = fight(attackers, defenders, ctx.rng, ctx.content.elements)
    delta, scores = settle_ranked(ctx, season, target.user_id, battle)
    if battle.winner == 0:
        advance(ctx, "pvp")
    for pet in ctx.active_pets(ctx.user_id):
        pet.energy -= season.rules.energy
    ctx.player().last_pvp = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    mastery_lines = []
    for pet in ctx.active_pets(ctx.user_id):
        mastery_lines.extend(award_mastery(ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {})))
    reply = Reply("论剑结算", (
        f"{ctx.player().dao_name}的{len(attackers)}宠阵容 挑战 {target.dao_name}的{len(defenders)}宠阵容镜像"
        f" · {battle.rounds} 回合", *battle.lines, *scores, *mastery_lines,
        f"挑战者精力 -{season.rules.energy}；防守方精力与冷却不变，不增加熟练度、不取消出征准备。",
    ), ("灵宠论剑榜", "灵宠匹配", "灵宠战报", "我的灵宠"))
    winner = None if battle.winner == -1 else (ctx.user_id, target.user_id)[battle.winner]
    ctx.repo.conn.execute(
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (season.season_id, ctx.user_id, target.user_id, attacking_pet.pet_id, defending_pet.pet_id,
         winner, beijing_day(ctx.now), ctx.now, delta, ctx.operation_id,
         json.dumps(asdict(reply), ensure_ascii=False)),
    )
    record_battle(ctx, kind="pvp", battle_key=season.season_id,
                  battle_name=f"{season.season_id} 赛季", battle=battle,
                  capture=capture, reply=reply)
    return reply


def spar(ctx: Context, arg: str) -> Reply:
    challenger = ctx.player()
    if not arg:
        raise GameError("请发送 灵宠切磋 对方道号。")
    target = _target(ctx, arg)
    if challenger.active_pet_id is None:
        raise GameError("尚未选择出战灵宠。")
    attacking_pets = ctx.repo.active_pets(ctx.user_id)
    defending_pets = ctx.repo.active_pets(target.user_id)
    for pet in attacking_pets:
        ctx.require_idle_pet(pet)
    attacking_pet = attacking_pets[0]
    defending_pet = defending_pets[0]
    attackers = combatants(ctx, recover_energy=False)
    defenders = combatants(ctx, target.user_id, recover_energy=False)
    capture = capture_snapshot(
        ctx, (attackers, defenders),
        ([ctx.user_id] * len(attackers), [target.user_id] * len(defenders)),
    )
    battle = fight(attackers, defenders, ctx.rng, ctx.content.elements)
    result = "双方战平。" if battle.winner == -1 else f"{(challenger, target)[battle.winner].dao_name}获胜。"
    reply = Reply("切磋结算", (
        f"{challenger.dao_name}的{len(attackers)}宠阵容 对 {target.dao_name}的{len(defenders)}宠阵容镜像"
        f" · {battle.rounds} 回合", *battle.lines, result,
        "切磋不消耗资源，不计赛季积分和熟练度。",
    ), ("灵宠战报", "我的灵宠", "灵宠论剑榜"))
    record_battle(ctx, kind="spar", battle_key="", battle=battle, capture=capture, reply=reply)
    return reply
