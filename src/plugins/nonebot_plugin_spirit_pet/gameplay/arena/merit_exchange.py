"""Current-season arena merit exchange.

Merit is derived from immutable ranked results: one point per active challenge
won in the current Beijing month. Only spending is persisted in quest_progress,
so a replay or concurrent redemption cannot mint or spend a second balance.
"""

from ...application.context import Context
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import named, quantity
from ...utils.time import season_bounds
from .seasons import current_season

SPENT_PREFIX = "arena_merit_spent_"
MAX_QUANTITY = 99


def season_id(ctx: Context) -> str:
    latest = ctx.repo.conn.execute("SELECT MAX(observed_at) AS observed_at FROM seasons").fetchone()
    if latest["observed_at"] is not None and ctx.now < latest["observed_at"]:
        raise GameError("服务器时间早于已记录的赛季时间，请等待时钟恢复后再试。")
    return season_bounds(ctx.now)[0]


def spent_key(season: str) -> str:
    return f"{SPENT_PREFIX}{season}"


def earned(ctx: Context, user_id: str, season: str | None = None) -> int:
    season = season or season_id(ctx)
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS wins FROM pvp_results "
        "WHERE season_id=? AND challenger_id=? AND winner_id=challenger_id",
        (season, user_id),
    ).fetchone()
    return int(row["wins"])


def spent(ctx: Context, user_id: str, season: str | None = None) -> int:
    season = season or season_id(ctx)
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, spent_key(season)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def balance(ctx: Context, user_id: str | None = None, season: str | None = None) -> int:
    owner = user_id or ctx.user_id
    current = season or season_id(ctx)
    return max(0, earned(ctx, owner, current) - spent(ctx, owner, current))


def offers(ctx: Context):
    return sorted(ctx.content.arena_merit_exchange.values(), key=lambda entry: entry.cost)


def _offer(ctx: Context, value: str):
    listed = offers(ctx)
    if value.isdecimal():
        index = int(value)
        if 1 <= index <= len(listed):
            return listed[index - 1]
        raise GameError(f"论剑战勋兑换共有 {len(listed)} 项，序号需在 1-{len(listed)} 之间。")
    return named(ctx.content.arena_merit_exchange, value)


def _reward_text(ctx: Context, offer, multiplier: int = 1) -> str:
    parts = [f"灵石 {offer.stones * multiplier}"] if offer.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else f'物品 {item_id}'} {amount * multiplier}"
        for item_id, amount in offer.items.items()
    )
    return " + ".join(parts)


def _usable(ctx: Context, offer) -> bool:
    return all(
        item_id in ctx.content.items
        and ctx.content.items[item_id].kind in {"consumable", "material", "breakthrough"}
        for item_id in offer.items
    )


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠论剑战勋 [兑换 <序号|名称> <数量>]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "本赛季每场主动论剑获胜可得 1 枚战勋，切磋、平局、被动防守不计。",
            "论剑战勋兑换只读预览；先完成领养并参加论剑后才能兑换。",
        ]
        lines.extend(
            f"{index}. {offer.name} · {offer.cost} 战勋 · {_reward_text(ctx, offer)}"
            for index, offer in enumerate(offers(ctx), 1)
        )
        return Reply("论剑战勋兑换", tuple(lines), ("灵宠帮助",), ())

    current = season_id(ctx)
    total = earned(ctx, player.user_id, current)
    used = spent(ctx, player.user_id, current)
    available = max(0, total - used)
    lines = [
        f"赛季 {current} · 战勋可用 {available}（获得 {total}，已用 {used}）。",
        "战勋只来自本赛季主动论剑胜场，换季后余额重新计算，不继承上季。",
    ]
    links = []
    for index, offer in enumerate(offers(ctx), 1):
        state = (
            "奖励待修复" if not _usable(ctx, offer)
            else "可兑换" if available >= offer.cost
            else f"还差 {offer.cost - available} 枚"
        )
        lines.append(f"{index}. {offer.name} · {offer.cost} 战勋 · {_reward_text(ctx, offer)} · {state}")
        if state == "可兑换":
            links.append(InlineCommand(len(lines) - 1, "兑换", f"灵宠论剑战勋 兑换 {index}"))
    lines.append("格式：灵宠论剑战勋 兑换 <序号|名称> [数量]。")
    return Reply(
        "论剑战勋兑换", tuple(lines),
        ("灵宠赛季", "灵宠论剑榜", "灵宠目标", "灵宠背包"), tuple(links),
    )


def redeem(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if parts and parts[0] == "兑换":
        parts = parts[1:]
    if not 1 <= len(parts) <= 2:
        raise GameError("格式：灵宠论剑战勋 兑换 <序号|名称> [数量]。")
    offer = _offer(ctx, parts[0])
    amount = quantity(parts[1], MAX_QUANTITY) if len(parts) == 2 else 1
    player = ctx.player()
    current = current_season(ctx)
    current_id = current.season_id
    missing = set(offer.items) - set(ctx.content.items)
    if missing or not _usable(ctx, offer):
        names = ", ".join(sorted(missing)) if missing else "兑换物品类型错误"
        raise GameError(f"兑换奖励定义缺失或不可用：{names}；本次未扣除战勋。")
    cost = offer.cost * amount
    available = balance(ctx, player.user_id, current_id)
    if available < cost:
        raise GameError(f"论剑战勋不足：{offer.name}需要 {cost} 枚，当前可用 {available} 枚。")

    next_spent = spent(ctx, player.user_id, current_id) + cost
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, spent_key(current_id), next_spent),
    )
    player.stones += offer.stones * amount
    for item_id, item_amount in offer.items.items():
        ctx.repo.add_item(player.user_id, item_id, item_amount * amount)
    return Reply("论剑战勋兑换", (
        f"兑换成功：{offer.name} ×{amount}，消耗 {cost} 枚战勋。",
        f"获得 {_reward_text(ctx, offer, amount)}。",
        f"赛季 {current_id} · 战勋可用 {balance(ctx, player.user_id, current_id)}（已用 {next_spent}）。",
    ), ("灵宠论剑战勋", "灵宠赛季", "灵宠背包", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return catalog(ctx, "") if not arg.strip() else redeem(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    current = season_id(ctx)
    return f"论剑战勋：可用 {balance(ctx, user_id, current)} · 本季胜场 {earned(ctx, user_id, current)}"
