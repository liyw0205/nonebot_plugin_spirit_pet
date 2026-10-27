"""Daily featured shop: three rotating offers with a discount and a stock cap.

The pool lives in `data/shop_rotation.json`; each Beijing day takes three
consecutive entries from the id-sorted pool, so the page is stable within a day
and rotates the next day. Purchases are recorded per offer and day in
`quest_progress` as `shop_offer_<date>_<offer id>` with the bought count as
`progress`; a new day simply uses a new key, so stock resets without a schema
change or cleanup. The normal `灵宠购买` path is untouched: this is an extra
discounted, limited path, not a replacement for the shop.
"""

from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import item_amount
from ..utils.time import beijing_day

OFFER_PREFIX = "shop_offer_"
OFFERS_PER_DAY = 3


def _ordinal(now: int) -> int:
    return date.fromisoformat(beijing_day(now)).toordinal()


def offers(ctx: Context, offset: int = 0) -> tuple:
    """Today's (or tomorrow's) three offers, stable within a day."""
    pool = sorted(ctx.content.shop_offers.values(), key=lambda offer: offer.id)
    start = (_ordinal(ctx.now) + offset) % len(pool)
    return tuple(pool[(start + index) % len(pool)] for index in range(OFFERS_PER_DAY))


def discounted_price(offer, item) -> int:
    return max(1, item.price * (100 - offer.discount) // 100)


def offer_key(now: int, offer) -> str:
    return f"{OFFER_PREFIX}{beijing_day(now)}_{offer.id}"


def bought(ctx: Context, offer) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, offer_key(ctx.now, offer)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _offer_for(ctx: Context, value: str):
    for offer in offers(ctx):
        item = ctx.content.items[offer.item]
        if value in (offer.item, item.name):
            return offer
    return None


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    today = offers(ctx)
    lines = [
        f"今日特供 · {beijing_day(ctx.now)}",
        "每日按北京时间轮换三件；折扣价与库存仅当日有效，售罄后次日重置。",
    ]
    links = []
    for offer in today:
        item = ctx.content.items[offer.item]
        owned = bought(ctx, offer) if player else 0
        remaining = max(0, offer.stock - owned)
        state = "售罄" if remaining == 0 else f"剩 {remaining} 件"
        lines.append(
            f"{item.name} · 原价 {item.price} → 特供 {discounted_price(offer, item)} 灵石"
            f" · 今日 {offer.stock} 件，{state} · 已购 {owned}"
        )
        if player is not None and remaining:
            links.append(InlineCommand(
                len(lines) - 1, "购买特供", f"灵宠特供 {item.name}",
            ))
    tomorrow = offers(ctx, offset=1)
    lines.append("明日预告：" + "、".join(ctx.content.items[offer.item].name for offer in tomorrow) + "。")
    if player is None:
        lines.append("尚未结契，先完成领养，才能购买特供。")
        return Reply("灵宠特供", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))
    return Reply("灵宠特供", tuple(lines), ("灵宠商店", "灵宠背包", "灵宠目标"), tuple(links))


def buy(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    name, amount = item_amount(arg)
    offer = _offer_for(ctx, name)
    if offer is None:
        raise GameError("今日特供没有该物品，请查看 灵宠特供。")
    item = ctx.content.items[offer.item]
    owned = bought(ctx, offer)
    remaining = offer.stock - owned
    if remaining <= 0:
        raise GameError(f"{item.name}今日特供已售罄，明日再来。")
    if amount > remaining:
        raise GameError(f"{item.name}今日特供仅剩 {remaining} 件。")
    price = discounted_price(offer, item)
    cost = price * amount
    if player.stones < cost:
        raise GameError("灵石不足。")
    player.stones -= cost
    ctx.repo.add_item(ctx.user_id, item.id, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (ctx.user_id, offer_key(ctx.now, offer), amount),
    )
    return Reply("灵坊特供", (
        f"{item.name} +{amount}，灵石 -{cost}（原价 {item.price * amount}，省 {item.price * amount - cost}）。",
        f"今日特供剩余 {remaining - amount} 件。",
    ), ("灵宠特供", "灵宠背包", "灵宠商店"))


def entry(ctx: Context, arg: str) -> Reply:
    """Bare command opens the page; an item argument buys that offer."""
    return buy(ctx, arg) if arg.strip() else catalog(ctx, arg)
