import json
from dataclasses import asdict

from ...application.context import Context
from ...domain.models import GameError, Reply
from ...utils.time import beijing_day
from ..combat import fight
from ..loadout import combatant
from ..mastery import award_mastery
from .common import current_season
from .eligibility import check_ranked
from .scoring import settle_ranked


def _target(ctx: Context, dao_name: str):
    target = ctx.repo.player_by_name(dao_name)
    if target is None:
        raise GameError("该道号不存在，请填写对方的道号。")
    if target.user_id == ctx.user_id:
        raise GameError("不能向自己发起对战。")
    if target.active_pet_id is None:
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
    battle = fight(
        [combatant(ctx, recover_energy=False)], [combatant(ctx, target.user_id, recover_energy=False)],
        ctx.rng, ctx.content.elements,
    )
    delta, scores = settle_ranked(ctx, season, target.user_id, battle)
    attacking_pet.energy -= season.rules.energy
    ctx.player().last_pvp = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    mastery = award_mastery(ctx, ctx.user_id, battle.skill_uses[0].get(attacking_pet.pet_id, {}))
    reply = Reply("论剑结算", (
        f"{ctx.player().dao_name}的{attacking_pet.name} 挑战 {target.dao_name}的{defending_pet.name}镜像"
        f" · {battle.rounds} 回合", *battle.lines, *scores, *mastery,
        f"挑战者精力 -{season.rules.energy}；防守方精力与冷却不变，不增加熟练度、不取消出征准备。",
    ), ("灵宠论剑榜", "灵宠匹配", "我的灵宠"))
    winner = None if battle.winner == -1 else (ctx.user_id, target.user_id)[battle.winner]
    ctx.repo.conn.execute(
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (season.season_id, ctx.user_id, target.user_id, attacking_pet.pet_id, defending_pet.pet_id,
         winner, beijing_day(ctx.now), ctx.now, delta, ctx.operation_id,
         json.dumps(asdict(reply), ensure_ascii=False)),
    )
    return reply


def spar(ctx: Context, arg: str) -> Reply:
    challenger = ctx.player()
    if not arg:
        raise GameError("请发送 灵宠切磋 对方道号。")
    target = _target(ctx, arg)
    if challenger.active_pet_id is None:
        raise GameError("尚未选择出战灵宠。")
    attacking_pet = ctx.repo.pet(challenger.active_pet_id)
    defending_pet = ctx.repo.pet(target.active_pet_id)
    ctx.require_idle_pet(attacking_pet)
    battle = fight(
        [combatant(ctx, recover_energy=False)], [combatant(ctx, target.user_id, recover_energy=False)],
        ctx.rng, ctx.content.elements,
    )
    result = "双方战平。" if battle.winner == -1 else f"{(challenger, target)[battle.winner].dao_name}获胜。"
    return Reply("切磋结算", (
        f"{challenger.dao_name}的{attacking_pet.name} 对 {target.dao_name}的{defending_pet.name}镜像"
        f" · {battle.rounds} 回合", *battle.lines, result,
        "切磋不消耗资源，不计赛季积分和熟练度。",
    ), ("我的灵宠", "灵宠论剑榜"))
