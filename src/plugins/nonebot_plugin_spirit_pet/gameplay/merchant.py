"""灵宠商会: a daily commission board with reputation.

Materials and crops only had two exits — fixed crafting costs and ``灵宠回收`` at
40% of shop price. The merchant board asks for specific goods and pays better than
recycling, but only for the orders of the day, so holding stock is a real decision.

State lives in ``quest_progress`` (no schema change):

* ``merchant_rep`` — lifetime reputation, monotonic
* ``merchant_order_<Beijing day>_<commission id>`` — delivered today (``claimed=1``)
* ``merchant_bonus_<Beijing day>`` — the all-clear bonus already paid today

The day's offers are derived from the day ordinal over the whole pool, so the board
is stable within a day and rotates the next; reputation gates whether an offer can
be delivered (``min_rep``), which is what makes the all-clear bonus a long-term goal.
"""

from datetime import date

from ..application.context import Context
from ..domain.commission_content import Commission
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day

REP_KEY = "merchant_rep"
ORDER_PREFIX = "merchant_order_"
BONUS_PREFIX = "merchant_bonus_"


def rule(ctx: Context):
    return ctx.content.rules.merchant


def rep(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, REP_KEY),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _write_progress(ctx: Context, key: str, value: int, claimed: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=excluded.claimed",
        (ctx.user_id, key, value, claimed),
    )


def day_ordinal(now: int) -> int:
    return date.fromisoformat(beijing_day(now)).toordinal()


def pool(ctx: Context) -> list[Commission]:
    return sorted(ctx.content.commissions.values(), key=lambda entry: entry.id)


def todays(ctx: Context, user_id: str | None = None) -> list[Commission]:
    """The day's window over the orders this reputation can take.

    Stable within a day for a given reputation total; crossing a ``min_rep`` gate
    widens the pool and therefore refreshes the board mid-day (delivered orders
    keep their markers, and the all-clear bonus stays once per day).
    """
    current = rep(ctx, user_id)
    entries = [entry for entry in pool(ctx) if entry.min_rep <= current]
    if not entries:
        return []
    count = min(rule(ctx).offers_per_day, len(entries))
    start = day_ordinal(ctx.now) % len(entries)
    return [entries[(start + index) % len(entries)] for index in range(count)]


def order_key(now: int, entry: Commission) -> str:
    return f"{ORDER_PREFIX}{beijing_day(now)}_{entry.id}"


def bonus_key(now: int) -> str:
    return f"{BONUS_PREFIX}{beijing_day(now)}"


def delivered(ctx: Context, entry: Commission, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, order_key(ctx.now, entry)),
    ).fetchone()
    return row is not None


def bonus_claimed(ctx: Context, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, bonus_key(ctx.now)),
    ).fetchone()
    return row is not None


def owned(ctx: Context, item_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (user_id or ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def next_threshold(ctx: Context, current: int) -> int | None:
    """Lowest reputation a higher-tier order asks for, above the current total."""
    gates = sorted({entry.min_rep for entry in pool(ctx) if entry.min_rep > current})
    return gates[0] if gates else None


def _demand_text(ctx: Context, entry: Commission, user_id: str | None = None) -> str:
    parts = []
    for item_id, amount in entry.items.items():
        held = owned(ctx, item_id, user_id)
        name = ctx.content.items[item_id].name
        parts.append(f"{name} {amount}" if held >= amount else f"{name} {held}/{amount}")
    return "、".join(parts)


def _reward_text(ctx: Context, entry: Commission) -> str:
    return f"灵石 {entry.stones} · 声望 {entry.rep}"


def _missing(ctx: Context, entry: Commission) -> list[str]:
    return [
        f"{ctx.content.items[item_id].name} 缺 {amount - owned(ctx, item_id)}"
        for item_id, amount in entry.items.items()
        if owned(ctx, item_id) < amount
    ]


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠商会 [交付 <委托名|序号> | 兑换 [名称|序号]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠商会",
            (
                "尚未结契，先完成领养，才能替商会跑腿。",
                f"商会每天放出 {rule(ctx).offers_per_day} 份委托：交付指定物品，换取灵石与声望。",
                "声望越高，能接的委托越好；交齐当天全部委托另有日清奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    player = ctx.player()
    current = rep(ctx)
    offers = todays(ctx)
    from . import merchant_exchange
    balance = merchant_exchange.available(ctx, player.user_id)
    lines = [
        f"商会声望：{current}（累计）· 可用 {balance}",
        f"今日委托 {len(offers)} 份（每日轮换，按声望解锁更高阶委托）。",
    ]
    links = []
    for index, entry in enumerate(offers, 1):
        status = "今日已交" if delivered(ctx, entry) else (
            "可交付" if not _missing(ctx, entry) else "物品不足"
        )
        lines.append(
            f"{index}. {entry.name} · 需求 {_demand_text(ctx, entry)} · 回报 {_reward_text(ctx, entry)} · {status}"
        )
        if status == "可交付":
            links.append(InlineCommand(len(lines) - 1, "交付", f"灵宠商会 交付 {entry.name}"))
    threshold = next_threshold(ctx, current)
    if threshold is not None:
        lines.append(f"再攒 {threshold - current} 点声望，就能接更高阶的委托。")
    if bonus_claimed(ctx):
        lines.append("日清奖励：今日已领取。")
    else:
        lines.append(
            f"日清奖励：交齐今日全部委托可得 灵石 {rule(ctx).all_clear_stones}"
            f" · 声望 {rule(ctx).all_clear_rep}。"
        )
    lines.append("可用声望可在商会兑换灵粮、材料与丹药。")
    links.append(InlineCommand(len(lines) - 1, "商会兑换", "灵宠商会 兑换"))
    return Reply("灵宠商会", tuple(lines), ("灵宠商会", "灵宠背包", "灵宠目标"), tuple(links))


def deliver(ctx: Context, arg: str) -> Reply:
    name = arg.strip()
    if not name:
        raise GameError("格式：灵宠商会 交付 <委托名|序号>。")
    offers = todays(ctx)
    entry = _offer(ctx, offers, name)
    current = rep(ctx)
    if delivered(ctx, entry):
        raise GameError(f"今日的{entry.name}已经交过了，明天再来。")
    if current < entry.min_rep:
        raise GameError(f"{entry.name}需要声望 {entry.min_rep}，你当前 {current}。")
    missing = _missing(ctx, entry)
    if missing:
        raise GameError(f"物品不足：还需{'、'.join(missing)}。")
    demand = _demand_text(ctx, entry)
    for item_id, amount in entry.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    player = ctx.player()
    player.stones += entry.stones
    total_rep = current + entry.rep
    _write_progress(ctx, order_key(ctx.now, entry), 0, 1)
    lines = [
        f"{entry.name}已交付：{demand} 换得 {_reward_text(ctx, entry)}。",
    ]
    if not bonus_claimed(ctx) and all(delivered(ctx, other) for other in offers):
        bonus = rule(ctx)
        player.stones += bonus.all_clear_stones
        total_rep += bonus.all_clear_rep
        _write_progress(ctx, bonus_key(ctx.now), 0, 1)
        lines.append(
            f"今日委托全部交齐，日清奖励：灵石 {bonus.all_clear_stones} · 声望 {bonus.all_clear_rep}。"
        )
    _write_progress(ctx, REP_KEY, total_rep, 1)
    lines.append(f"商会声望：{total_rep}。")
    remaining = [other.name for other in offers if not delivered(ctx, other)]
    if remaining:
        lines.append(f"今日还可交：{'、'.join(remaining)}。")
    return Reply("委托完成", tuple(lines), ("灵宠商会", "灵宠背包", "灵宠目标"))


def _offer(ctx: Context, offers: list[Commission], value: str) -> Commission:
    """Resolve by name, id or 1-based index inside today's board only."""
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(offers):
            return offers[index - 1]
        raise GameError(f"今日只有 {len(offers)} 份委托，序号超出范围。")
    for entry in offers:
        if value in (entry.id, entry.name):
            return entry
    if any(value in (entry.id, entry.name) for entry in pool(ctx)):
        raise GameError(f"{value}今天没有上架，明天再来看看。")
    raise GameError("未找到该委托，请检查名称或序号。")


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "交付":
        return deliver(ctx, " ".join(parts[1:]))
    if parts[0] == "兑换":
        from . import merchant_exchange
        return merchant_exchange.dispatch(ctx, " ".join(parts[1:]))
    if parts[0] in {"大单", "接单", "交货", "弃单", "记录"}:
        from . import merchant_contract
        return merchant_contract.dispatch(ctx, arg)
    raise GameError("格式：灵宠商会 [交付 <委托名|序号> | 兑换 [名称|序号] | 大单]。")


def objective_line(ctx: Context, user_id: str) -> str:
    current = rep(ctx, user_id)
    offers = todays(ctx, user_id)
    done = sum(1 for entry in offers if delivered(ctx, entry, user_id))
    return f"商会：声望 {current} · 今日已交 {done}/{len(offers)}"
