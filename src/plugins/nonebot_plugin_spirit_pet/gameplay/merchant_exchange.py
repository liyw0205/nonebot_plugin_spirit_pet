"""Merchant reputation exchange: turn surplus reputation into goods.

``merchant_rep`` is a lifetime total and gates which commissions appear. This
module adds a spendable view without touching that total:

* ``merchant_spent`` — reputation already exchanged (monotonic)
* ``merchant_buy_<week start>_<offer id>`` — purchases in the current Beijing week

Available reputation is ``max(0, lifetime - spent)``. Because the offer gates
keep reading the lifetime total, spending can never re-lock a commission.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from . import merchant

SPENT_KEY = "merchant_spent"
BUY_PREFIX = "merchant_buy_"


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def spent(ctx: Context, user_id: str | None = None) -> int:
    return _progress(ctx, SPENT_KEY, user_id)


def available(ctx: Context, user_id: str | None = None) -> int:
    return max(0, merchant.rep(ctx, user_id) - spent(ctx, user_id))


def _buy_key(offer_id: str, now: int) -> str:
    return f"{BUY_PREFIX}{beijing_week(now)[0]}_{offer_id}"


def purchased(ctx: Context, offer_id: str, user_id: str | None = None) -> int:
    return _progress(ctx, _buy_key(offer_id, ctx.now), user_id)


def offers(ctx: Context) -> list:
    return sorted(ctx.content.merchant_exchange.values(), key=lambda entry: entry.id)


def _offer(ctx: Context, value: str):
    entries = offers(ctx)
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(entries):
            return entries[index - 1]
    for entry in entries:
        if value in (entry.id, entry.name):
            return entry
    raise GameError("未找到该兑换项，请检查名称或序号。")


def _remaining(ctx: Context, offer, user_id: str | None = None) -> int:
    return max(0, offer.weekly_limit - purchased(ctx, offer.id, user_id))


def _offer_text(ctx: Context, offer) -> str:
    item = ctx.content.items[offer.item]
    return f"{item.name} ×{offer.amount} · 声望 {offer.cost_rep} · 本周 {_remaining(ctx, offer)}/{offer.weekly_limit}"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠商会 兑换 [名称|序号]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "商会声望达到委托门槛后，仍可用累计声望的可用余额兑换补给。",
            "累计声望只增不减，兑换不会降低它，也不会让已解锁的委托重新锁上。",
            *(
                f"{index}. {offer.name} · {ctx.content.items[offer.item].name} ×{offer.amount}"
                f" · 声望 {offer.cost_rep} · 每周 {offer.weekly_limit} 份"
                for index, offer in enumerate(offers(ctx), 1)
            ),
            "尚未结契，先完成领养，才能替商会跑腿并兑换。",
        ]
        return Reply("商会兑换", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    total = merchant.rep(ctx, player.user_id)
    used = spent(ctx, player.user_id)
    lines = [
        f"商会声望：累计 {total} · 已兑 {used} · 可用 {available(ctx, player.user_id)}。",
        "兑换从可用余额扣除，累计声望不变；每周一 00:00 重置限购。",
    ]
    links = []
    for index, offer in enumerate(offers(ctx), 1):
        status = "可兑换" if _remaining(ctx, offer, player.user_id) > 0 else "本周已兑完"
        if status == "可兑换" and available(ctx, player.user_id) < offer.cost_rep:
            status = f"还差 {offer.cost_rep - available(ctx, player.user_id)} 声望"
        lines.append(f"{index}. {offer.name} · {_offer_text(ctx, offer)} · {status}")
        if status == "可兑换":
            links.append(InlineCommand(len(lines) - 1, "兑换", f"灵宠商会 兑换 {offer.name}"))
    lines.append("返回商会看板可继续交付今日委托。")
    links.append(InlineCommand(len(lines) - 1, "返回商会", "灵宠商会"))
    return Reply("商会兑换", tuple(lines), ("灵宠背包", "灵宠目标", "灵宠帮助"), tuple(links))


def exchange(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        raise GameError("格式：灵宠商会 兑换 <名称|序号>。")
    player = ctx.player()
    offer = _offer(ctx, value)
    remaining = _remaining(ctx, offer, player.user_id)
    if remaining <= 0:
        raise GameError(f"{offer.name}本周已兑完，下周一 00:00 再来。")
    balance = available(ctx, player.user_id)
    if balance < offer.cost_rep:
        raise GameError(
            f"可用声望不足：需要 {offer.cost_rep}，当前 {balance}；累计声望不会因兑换减少。"
        )
    item = ctx.content.items.get(offer.item)
    if item is None:
        raise GameError("兑换物品定义缺失；尚未扣除声望。")
    current_spent = spent(ctx, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, SPENT_KEY, current_spent + offer.cost_rep),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1, claimed=1",
        (player.user_id, _buy_key(offer.id, ctx.now), 1),
    )
    ctx.repo.add_item(player.user_id, offer.item, offer.amount)
    return Reply("商会兑换", (
        f"{offer.name}：{item.name} ×{offer.amount} 已入包。",
        f"声望 累计 {merchant.rep(ctx, player.user_id)} · 已兑 {current_spent + offer.cost_rep}"
        f" · 可用 {available(ctx, player.user_id)}。",
        f"本周还可兑换 {remaining - 1}/{offer.weekly_limit} 份。",
    ), ("灵宠商会 兑换", "灵宠商会", "灵宠背包"))


def dispatch(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        return catalog(ctx, "")
    return exchange(ctx, value)


__all__ = [
    "BUY_PREFIX", "SPENT_KEY", "available", "catalog", "dispatch", "exchange",
    "offers", "purchased", "spent",
]
