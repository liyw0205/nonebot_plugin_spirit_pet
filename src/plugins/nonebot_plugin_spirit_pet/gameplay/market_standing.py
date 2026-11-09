"""Merchant standing: a ladder of lifetime real trades with permanent perks.

Progress is derived from ``market_sales`` + ``market_bid_sales`` row counts
(permanent ledgers), never stored — so rejects, cancels, expiry and message
replays cannot double-count a trade. Each rung's one-time reward is claimed
through 灵宠集市 掌柜领奖.
"""

from ..application.context import Context
from ..domain.merchant_standing_content import MerchantStanding
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from .rewards import grant as _grant_reward

CLAIM_PREFIX = "merchant_standing_"

# -------------------------------------------------------------------- helpers


def trades(ctx: Context, user_id: str) -> int:
    """Lifetime real trades this player made as the seller."""
    rows = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM market_sales WHERE seller_id=?",
        (user_id,),
    ).fetchone()
    direct = int(rows[0]) if rows else 0
    rows = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM market_bid_sales WHERE seller_id=?",
        (user_id,),
    ).fetchone()
    bids = int(rows[0]) if rows else 0
    return direct + bids


def sorted_standings(ctx: Context) -> list[MerchantStanding]:
    return sorted(
        ctx.content.merchant_standings.values(),
        key=lambda entry: entry.min_trades,
    )


def current(ctx: Context, user_id: str) -> MerchantStanding | None:
    """Highest rung whose threshold the player has reached, or None."""
    my_trades = trades(ctx, user_id)
    result = None
    for entry in sorted_standings(ctx):
        if my_trades >= entry.min_trades:
            result = entry
    return result


def next_(ctx: Context, user_id: str) -> MerchantStanding | None:
    """Next unreached rung, or None if at the top."""
    my_trades = trades(ctx, user_id)
    for entry in sorted_standings(ctx):
        if my_trades < entry.min_trades:
            return entry
    return None


def claimable_list(ctx: Context, user_id: str) -> list[MerchantStanding]:
    """Rungs the player has reached but not yet claimed."""
    my_trades = trades(ctx, user_id)
    unclaimed = []
    for entry in sorted_standings(ctx):
        if my_trades < entry.min_trades:
            break
        row = ctx.repo.conn.execute(
            "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
            (user_id, _claim_id(entry.id)),
        ).fetchone()
        if row is None:
            unclaimed.append(entry)
    return unclaimed


def _claim_id(standing_id: str) -> str:
    return f"{CLAIM_PREFIX}{standing_id}"


# -------------------------------------------------------------------- effective perks


def listing_slots(ctx: Context, user_id: str) -> int:
    """Base stall slots + standing listing_slot bonus."""
    from . import market as _market

    extra = 0
    for entry in sorted_standings(ctx):
        if trades(ctx, user_id) < entry.min_trades:
            break
        if entry.perk == "listing_slot":
            extra += 1
    stall = _market.tier(ctx, user_id)
    return stall.slots + extra


def bid_slots(ctx: Context, user_id: str) -> int:
    """Base market bid_slots + standing bid_slot bonus."""
    extra = 0
    for entry in sorted_standings(ctx):
        if trades(ctx, user_id) < entry.min_trades:
            break
        if entry.perk == "bid_slot":
            extra += 1
    return ctx.content.market.bid_slots + extra


def fee_percent(ctx: Context, user_id: str) -> int:
    """Stall fee minus cumulative tax_rebate from reached standings."""
    from . import market as _market

    rebate = 0
    for entry in sorted_standings(ctx):
        if trades(ctx, user_id) < entry.min_trades:
            break
        rebate += entry.rebate
    stall = _market.tier(ctx, user_id)
    return max(0, stall.fee_percent - rebate)


# -------------------------------------------------------------------- claim


def claim(ctx: Context, arg: str) -> Reply:
    target = arg.strip()
    if not target:
        raise GameError("格式：灵宠集市 掌柜领奖 <品阶名>，例如 灵宠集市 掌柜领奖 学徒掌柜。")
    player = ctx.player()
    my_trades = trades(ctx, player.user_id)
    entry = next(
        (e for e in ctx.content.merchant_standings.values() if e.name == target),
        None,
    )
    if entry is None:
        raise GameError(f"未找到品阶「{target}」，可发送 灵宠集市 掌柜 查看。")
    if my_trades < entry.min_trades:
        raise GameError(
            f"商路品阶「{entry.name}」需要 {entry.min_trades} 笔成交，当前 {my_trades}。"
        )
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (player.user_id, _claim_id(entry.id)),
    ).fetchone()
    if row is not None and row["claimed"]:
        raise GameError(f"品阶「{entry.name}」的奖励已经领取。")
    if row is not None:
        raise GameError("领奖记录异常，请联系管理员。")
    result = _grant_reward(ctx, entry.reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, _claim_id(entry.id), my_trades),
    )
    return Reply(
        "掌柜领奖",
        (f"品阶「{entry.name}」奖励已领取。", *result),
        ("灵宠集市 掌柜", "灵宠目标"),
    )


# -------------------------------------------------------------------- hub page


def hub(ctx: Context, arg: str = "") -> Reply:
    """掌柜 page: current standing, trades, next threshold, perks, claimable."""
    if arg.strip():
        raise GameError("格式：灵宠集市 掌柜。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "商路品阶按累计成交笔数提升，每晋升一品有一次性奖励与永久经营特权。",
        ]
        for entry in sorted_standings(ctx):
            parts = [
                f"「{entry.name}」{entry.min_trades} 笔",
                entry.perk_text,
            ]
            lines.append(" · ".join(parts))
        lines.append("尚未结契，先完成领养。")
        return Reply(
            "灵宠集市 掌柜",
            tuple(lines),
            ("灵宠帮助",),
            (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),),
        )
    my_trades = trades(ctx, player.user_id)
    cur = current(ctx, player.user_id)
    nxt = next_(ctx, player.user_id)
    claimable_entries = claimable_list(ctx, player.user_id)
    lines = [
        f"商路品阶：{cur.name if cur else '—'} · 累计成交 {my_trades} 笔",
    ]
    if nxt is not None:
        lines.append(f"下一品：{nxt.name}（还需 {max(0, nxt.min_trades - my_trades)} 笔）")
    else:
        lines.append("已登商会执事之巅，所有品阶尽揽。")
    lines.append("经营特权：")
    lines.append(f"  陈列位：{listing_slots(ctx, player.user_id)}（含特权加成）")
    lines.append(f"  求购位：{bid_slots(ctx, player.user_id)}（含特权加成）")
    if cur is not None:
        eff = fee_percent(ctx, player.user_id)
        base = ctx.content.market.stalls[0].fee_percent
        if eff < base:
            lines.append(f"  成交税：{eff}%（减免 {base - eff}%）")
        else:
            lines.append(f"  成交税：{eff}%")
    else:
        lines.append(f"  成交税：{fee_percent(ctx, player.user_id)}%")
    links = []
    for entry in claimable_entries:
        items_text = []
        if entry.reward.stones.maximum:
            items_text.append(f"灵石 {entry.reward.stones.maximum}")
        for item_id, bounds in entry.reward.items.items():
            item_name = ctx.content.items[item_id].name if item_id in ctx.content.items else item_id
            items_text.append(f"{item_name} {bounds.maximum}")
        label = f"领取{entry.name}"
        lines.append(f"「{entry.name}」可领：{' · '.join(items_text)}")
        links.append(InlineCommand(
            len(lines) - 1, label, f"灵宠集市 掌柜领奖 {entry.name}",
        ))
    if not claimable_entries:
        lines.append("尚无待领取的品阶奖励，多成交稳步提升。")
    return Reply(
        "灵宠集市 掌柜",
        tuple(lines),
        ("灵宠集市", "灵宠目标"),
        tuple(links),
    )


# -------------------------------------------------------------------- history

HISTORY_PAGE_SIZE = 10


def history(ctx: Context, arg: str = "") -> Reply:
    """Past claimed rungs and their reward dates."""
    ctx.player()
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress, claimed FROM quest_progress"
        " WHERE user_id=? AND quest_id LIKE ? AND claimed=1 ORDER BY quest_id",
        (ctx.user_id, f"{CLAIM_PREFIX}%"),
    ).fetchall()
    page_data = paginate(rows, arg, "掌柜记录", "灵宠集市 掌柜记录", HISTORY_PAGE_SIZE)
    lines = []
    for row in page_data.entries:
        standing_id = row["quest_id"][len(CLAIM_PREFIX):]
        entry = ctx.content.merchant_standings.get(standing_id)
        name = entry.name if entry is not None else standing_id
        lines.append(f"{name}（达成 {row['progress']} 笔时领取）")
    if not rows:
        lines.append("尚未领取过品阶奖励。")
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    return Reply(
        "掌柜记录",
        tuple(lines),
        (*page_data.navigation, "灵宠集市 掌柜", "灵宠目标")[:4],
    )


def objective_line(ctx: Context, user_id: str) -> str:
    my_trades = trades(ctx, user_id)
    cur = current(ctx, user_id)
    nxt = next_(ctx, user_id)
    name = cur.name if cur else "待起步"
    if nxt is not None:
        need = max(0, nxt.min_trades - my_trades)
        return f"商路：{name} · 累计 {my_trades} 笔 · 还差 {need} 笔升 {nxt.name}"
    return f"商路：{name} · 累计 {my_trades} 笔 · 已满阶"


__all__ = [
    "CLAIM_PREFIX",
    "trades", "sorted_standings", "current", "next_", "claimable_list",
    "listing_slots", "bid_slots", "fee_percent",
    "hub", "claim", "history", "objective_line",
]
