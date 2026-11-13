"""Repeatable exchange of duplicate-species collection stamps.

Stamps are derived from the pets table instead of being minted separately:
each copy after the first of a species contributes one stamp.  Only spending
is persisted, so releasing or archiving a pet never creates a second balance
ledger and the normal transaction wrapper can roll the whole exchange back.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity

SPENT_KEY = "collection_stamps_spent"
MAX_QUANTITY = 99


def duplicate_stamps(ctx: Context, user_id: str | None = None) -> int:
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT COALESCE(SUM(amount - 1), 0) AS stamps FROM ("
        "SELECT species_id, COUNT(*) AS amount FROM pets WHERE user_id=? "
        "GROUP BY species_id HAVING COUNT(*) > 1)",
        (owner,),
    ).fetchone()
    return int(row["stamps"])


def spent(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, SPENT_KEY),
    ).fetchone()
    return int(row["progress"]) if row else 0


def balance(ctx: Context, user_id: str | None = None) -> int:
    return max(0, duplicate_stamps(ctx, user_id) - spent(ctx, user_id))


def offers(ctx: Context):
    return sorted(ctx.content.collection_exchange.values(), key=lambda entry: entry.cost)


def _offer(ctx: Context, value: str):
    entries = offers(ctx)
    if value.isdecimal():
        index = int(value)
        if 1 <= index <= len(entries):
            return entries[index - 1]
        raise GameError(f"收集兑换共有 {len(entries)} 项，序号需在 1-{len(entries)} 之间。")
    return named(ctx.content.collection_exchange, value)


def _reward_text(ctx: Context, offer, multiplier: int = 1) -> str:
    parts = []
    if offer.stones:
        parts.append(f"灵石 {offer.stones * multiplier}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount * multiplier}"
        for item_id, amount in offer.items.items()
    )
    return " + ".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠收集兑换 [序号|名称] [数量]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "重复拥有同一种族的灵宠，每只多出的伙伴可化为 1 枚收集印记。",
            "收集印记兑换只读预览；先完成领养并收得重复种族后才能兑换。",
        ]
        lines.extend(
            f"{index}. {offer.name} · {offer.cost} 印记 · {_reward_text(ctx, offer)} · 可兑换"
            for index, offer in enumerate(offers(ctx), 1)
        )
        return Reply("灵宠收集兑换", tuple(lines), ("灵宠帮助",), ())

    available = balance(ctx, player.user_id)
    lines = [
        f"收集印记：可用 {available}（派生 {duplicate_stamps(ctx, player.user_id)}，已用 {spent(ctx, player.user_id)}）。",
        "印记来自同族复数伙伴；兑换不会删除伙伴或影响图鉴一次性奖励。",
    ]
    links = []
    for index, offer in enumerate(offers(ctx), 1):
        state = "可兑换" if available >= offer.cost else f"还差 {offer.cost - available} 枚"
        lines.append(f"{index}. {offer.name} · {offer.cost} 印记 · {_reward_text(ctx, offer)} · {state}")
        if available >= offer.cost:
            links.append(InlineCommand(len(lines) - 1, "兑换", f"灵宠收集兑换 {index}"))
    lines.append("格式：灵宠收集兑换 <序号|名称> [数量]。")
    return Reply(
        "灵宠收集兑换", tuple(lines),
        ("灵宠收集", "灵宠背包", "灵宠目标", "灵宠帮助"), tuple(links),
    )


def redeem(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if parts and parts[0] == "兑换":
        parts = parts[1:]
    if not 1 <= len(parts) <= 2:
        raise GameError("格式：灵宠收集兑换 <序号|名称> [数量]。")
    offer = _offer(ctx, parts[0])
    amount = quantity(parts[1], MAX_QUANTITY) if len(parts) == 2 else 1
    player = ctx.player()
    missing = set(offer.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"兑换物品定义缺失：{', '.join(sorted(missing))}；本次未扣除印记。")
    cost = offer.cost * amount
    available = balance(ctx, player.user_id)
    if available < cost:
        raise GameError(f"收集印记不足：{offer.name}需要 {cost} 枚，当前可用 {available} 枚。")

    next_spent = spent(ctx, player.user_id) + cost
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, SPENT_KEY, next_spent),
    )
    player.stones += offer.stones * amount
    for item_id, item_amount in offer.items.items():
        ctx.repo.add_item(player.user_id, item_id, item_amount * amount)
    return Reply("收集印记兑换", (
        f"兑换成功：{offer.name} ×{amount}，消耗 {cost} 枚收集印记。",
        f"获得 {_reward_text(ctx, offer, amount)}。",
        f"收集印记：可用 {balance(ctx, player.user_id)}（已用 {next_spent}）。",
    ), ("灵宠收集兑换", "灵宠收集", "灵宠背包", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return catalog(ctx, "") if not arg.strip() else redeem(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    return f"收集印记：可用 {balance(ctx, user_id)}（派生 {duplicate_stamps(ctx, user_id)}，已用 {spent(ctx, user_id)}）"


__all__ = [
    "MAX_QUANTITY", "SPENT_KEY", "balance", "catalog", "dispatch", "duplicate_stamps",
    "offers", "objective_line", "redeem", "spent",
]
