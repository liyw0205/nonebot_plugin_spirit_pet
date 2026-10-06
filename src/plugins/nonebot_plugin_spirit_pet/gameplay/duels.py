from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.time import beijing_day
from .combat import fight
from .loadout import combatant


def _available(ctx: Context, first: str, second: str):
    energy = ctx.content.rules.pvp_energy
    for user_id in (first, second):
        ctx.check_action(ctx.player(user_id), ctx.pet(user_id), "pvp", energy, ctx.config.spirit_pet_pvp_cooldown)
    pair = tuple(sorted((first, second)))
    row = ctx.repo.conn.execute(
        "SELECT last_day FROM pvp_pairs WHERE first_id=? AND second_id=?", pair,
    ).fetchone()
    if row and row["last_day"] >= beijing_day(ctx.now):
        raise GameError("双方今日已结算过论剑积分，可以改为切磋。")


def invite(ctx: Context, target_name: str, mode: str) -> Reply:
    ctx.player()
    target_player = ctx.repo.player_by_name(target_name)
    if target_player is None:
        raise GameError("该道号不存在，请填写对方的道号。")
    target = target_player.user_id
    if target == ctx.user_id:
        raise GameError("不能向自己发起对战。")
    conn = ctx.repo.conn
    conn.execute("DELETE FROM duels WHERE expires_at<=?", (ctx.now,))
    pending = conn.execute(
        "SELECT 1 FROM duels WHERE challenger_id IN (?, ?) OR target_id IN (?, ?)",
        (ctx.user_id, target, ctx.user_id, target),
    ).fetchone()
    if pending:
        raise GameError("一方已有待处理邀请，请先应战、拒战或等待过期。")
    if mode == "pvp":
        _available(ctx, ctx.user_id, target)
    conn.execute(
        "INSERT INTO duels(challenger_id, target_id, mode, expires_at) VALUES (?, ?, ?, ?)",
        (ctx.user_id, target, mode, ctx.now + ctx.config.spirit_pet_invitation_ttl),
    )
    return Reply("论剑邀请" if mode == "pvp" else "切磋邀请", (
        f"{ctx.player().dao_name}向{target_player.dao_name}发起对战。",
        f"仅目标玩家可应战，邀请 {ctx.config.spirit_pet_invitation_ttl} 秒后失效。",
        "论剑消耗双方精力并计积分；切磋不消耗精力、不计积分、不发奖励。",
    ), ("灵宠应战", "灵宠拒战"))


def pvp(ctx: Context, arg: str) -> Reply:
    return invite(ctx, arg, "pvp")


def spar(ctx: Context, arg: str) -> Reply:
    return invite(ctx, arg, "spar")


def accept(ctx: Context, arg: str) -> Reply:
    duel = ctx.repo.conn.execute(
        "SELECT * FROM duels WHERE target_id=? AND expires_at>?", (ctx.user_id, ctx.now),
    ).fetchone()
    if not duel:
        raise GameError("没有可应战的邀请，或邀请已过期。")
    first, second = duel["challenger_id"], duel["target_id"]
    if duel["mode"] == "pvp":
        _available(ctx, first, second)
    pets = [ctx.pet(first), ctx.pet(second)]
    battle = fight(
        [combatant(ctx, first)], [combatant(ctx, second)], ctx.rng, ctx.content.elements,
    )
    ctx.repo.conn.execute("DELETE FROM duels WHERE duel_id=?", (duel["duel_id"],))
    lines = [
        f"{ctx.player(first).dao_name}的{pets[0].name} 对 {ctx.player(second).dao_name}的{pets[1].name}"
        f" · {battle.rounds} 回合", *battle.lines,
    ]
    if duel["mode"] == "pvp":
        players = [ctx.player(first), ctx.player(second)]
        for player, pet in zip(players, pets):
            player.last_pvp = ctx.now
            pet.energy -= ctx.content.rules.pvp_energy
            ctx.repo.invalidate_ready(player.user_id)
        pair = tuple(sorted((first, second)))
        ctx.repo.conn.execute(
            "INSERT INTO pvp_pairs VALUES (?, ?, ?) ON CONFLICT(first_id, second_id) "
            "DO UPDATE SET last_day=excluded.last_day", (*pair, beijing_day(ctx.now)),
        )
        if battle.winner != -1:
            loser = players[1 - battle.winner]
            delta = min(ctx.content.rules.pvp_rating_delta, loser.rating)
            loser.rating -= delta
            players[battle.winner].rating += delta
            lines.append(f"{pets[battle.winner].name}获胜，积分 +{delta}；对方 -{delta}。")
        else:
            lines.append("双方战平，积分不变。")
        lines.append(f"双方精力 -{ctx.content.rules.pvp_energy}，无灵石或道具奖励。")
    else:
        lines.append("双方战平。" if battle.winner == -1 else f"{pets[battle.winner].name}胜出。")
        lines.append("切磋不消耗资源，不计积分。")
    return Reply("论剑结算" if duel["mode"] == "pvp" else "切磋结算", tuple(lines))


def reject(ctx: Context, arg: str) -> Reply:
    deleted = ctx.repo.conn.execute(
        "DELETE FROM duels WHERE (target_id=? OR challenger_id=?) AND expires_at>?",
        (ctx.user_id, ctx.user_id, ctx.now),
    )
    if not deleted.rowcount:
        raise GameError("没有待处理的对战邀请。")
    return Reply("对战取消", ("邀请已拒绝或撤回，未消耗任何资源。",))
