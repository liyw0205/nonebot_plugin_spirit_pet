"""Sect contribution exchange: spend contribution without losing the rank.

Contribution used to be a one-way ladder — every daily practice pushed `sect_contrib_<id>` up, the rank
was derived from that number, and once rank 5 was reached the currency had nowhere to go. Exchange adds
a second row, `sect_spent_<id>`, so the **total** still decides the rank and the spendable balance is
`total - spent`. Redeeming therefore never demotes a player or weakens their sect passive.

Weekly stock is a count per offer, `sect_exchange_<week-start>_<offer>`, which resets by changing the
key next week while the spent total persists.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_week
from . import sects

SPENT = "sect_spent_"
EXCHANGE = "sect_exchange_"


def spent(ctx: Context, sect, user_id: str | None = None) -> int:
    return sects._progress(ctx, f"{SPENT}{sect.id}", user_id)


def balance(ctx: Context, sect, user_id: str | None = None) -> int:
    """Contribution that can still be spent; the rank keeps using the total."""
    return max(0, sects.contribution(ctx, sect, user_id) - spent(ctx, sect, user_id))


def offers(ctx: Context):
    return sorted(ctx.content.sect_exchange.values(), key=lambda offer: offer.cost)


def _week(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def bought_this_week(ctx: Context, offer, user_id: str | None = None) -> int:
    return sects._progress(ctx, f"{EXCHANGE}{_week(ctx)}_{offer.id}", user_id)


def cost_text(ctx: Context, offer) -> str:
    return f"{ctx.content.items[offer.item_id].name} ×1 · 贡献 {offer.cost}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠贡献 [兑换 <物品> [数量]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠贡献",
            ("尚未结契，先完成领养，才能查看贡献兑换。", "拜入师门后每日修行积累贡献，可用于兑换。"),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    member = sects.current(ctx)
    if member is None:
        return Reply("灵宠贡献", ("尚未拜入师门，先去 灵宠师门 拜入。",), ("灵宠师门", "灵宠帮助"))
    total = sects.contribution(ctx, member)
    available = balance(ctx, member)
    lines = [
        f"门派：{member.name} · 总贡献 {total}（决定阶位）· 可用贡献 {available}",
        "兑换只扣可用贡献，不会降低阶位或被动；每周库存按自然周重置。",
    ]
    links = []
    for offer in offers(ctx):
        used = bought_this_week(ctx, offer)
        left = max(0, offer.weekly_limit - used)
        lines.append(
            f"{ctx.content.items[offer.item_id].name} · {cost_text(ctx, offer)}"
            f" · 本周剩余 {left}/{offer.weekly_limit}"
        )
        if left and available >= offer.cost:
            links.append(InlineCommand(
                len(lines) - 1, "兑换", f"灵宠贡献 兑换 {ctx.content.items[offer.item_id].name}",
            ))
    return Reply("灵宠贡献", tuple(lines), ("灵宠贡献", "灵宠师门", "灵宠背包"), tuple(links))


def redeem(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not 1 <= len(parts) <= 2:
        raise GameError("格式：灵宠贡献 兑换 <物品> [数量]。")
    amount = 1
    if len(parts) == 2:
        if not parts[1].isdecimal() or not 1 <= int(parts[1]) <= 5:
            raise GameError("数量须为 1-5 的整数。")
        amount = int(parts[1])
    ctx.player()
    member = sects.current(ctx)
    if member is None:
        raise GameError("尚未拜入师门，先去 灵宠师门 拜入。")
    offer = named({entry.item_id: entry for entry in offers(ctx)}, parts[0])
    left = offer.weekly_limit - bought_this_week(ctx, offer)
    if left < amount:
        raise GameError(f"本周库存不足：{offer.name}还剩 {max(0, left)} 份。")
    available = balance(ctx, member)
    cost = offer.cost * amount
    if available < cost:
        raise GameError(f"可用贡献不足：需要 {cost}，当前 {available}（总贡献 {sects.contribution(ctx, member)}）。")

    sects._set(ctx, f"{SPENT}{member.id}", spent(ctx, member) + cost)
    sects._set(ctx, f"{EXCHANGE}{_week(ctx)}_{offer.id}", bought_this_week(ctx, offer) + amount)
    ctx.repo.add_item(ctx.user_id, offer.item_id, amount)
    item = ctx.content.items[offer.item_id]
    return Reply(
        "兑换完成",
        (
            f"用 {cost} 贡献换得 {item.name} ×{amount}。",
            f"可用贡献 {available - cost} · 总贡献 {sects.contribution(ctx, member)}（阶位不变）。",
            f"本周 {offer.name} 剩余 {left - amount}/{offer.weekly_limit}。",
        ),
        ("灵宠贡献", "灵宠背包", "灵宠师门"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "兑换":
        return redeem(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠贡献 [兑换 <物品> [数量]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "贡献兑换：尚未结契"
    member = sects.current(ctx, user_id)
    if member is None:
        return "贡献兑换：尚未拜入师门"
    available = balance(ctx, member, user_id)
    return f"贡献兑换：可用贡献 {available}"
