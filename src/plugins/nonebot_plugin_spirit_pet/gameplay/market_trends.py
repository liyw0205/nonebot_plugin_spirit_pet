"""灵宠行情: what things actually sold for, not what people are asking.

This module reads the two ledgers in aggregate and reports, per item and over a bounded
window, the cleared unit-price band: sample count, cheapest, median and dearest. Nothing
is stored.

Two deliberate choices:

* the headline is the **median**, not the mean — one wild sale should not redefine "the
  going rate", and market prices are exactly the distribution where means lie;
* an item with no sales in the window says so, and never prints 0 灵石 as if a sale
  happened at zero.
"""

from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import BEIJING

TITLE = "灵宠行情"
COMMAND = "灵宠集市"
PAGE_SIZE = 5
SOURCE_LISTING = "挂单"
SOURCE_BID = "求购"


def rule(ctx: Context):
    return ctx.content.market


def window(ctx: Context) -> tuple[int, int]:
    """Inclusive lower bound and the window length used in prose."""
    days = rule(ctx).trend_days
    return ctx.now - days * 86400, days


def _rows(ctx: Context, item_id: str | None = None) -> list[dict]:
    """Every cleared sale inside the window, from both ledgers."""
    since, _ = window(ctx)
    sql = (
        "SELECT item_id, quantity, unit_price, sold_at, '{}' AS source FROM {}"
        " WHERE sold_at >= ?"
    )
    sales = [
        dict(row)
        for row in ctx.repo.conn.execute(
            sql.format(SOURCE_LISTING, "market_sales"), (since,)
        ).fetchall()
    ]
    sales.extend(
        dict(row)
        for row in ctx.repo.conn.execute(
            sql.format(SOURCE_BID, "market_bid_sales"), (since,)
        ).fetchall()
    )
    if item_id is not None:
        sales = [row for row in sales if row["item_id"] == item_id]
    return sales


def summary(prices: list[int]) -> tuple[int, int, int]:
    """(min, median, max) with a documented even-count convention.

    For an even number of samples the median is the integer average of the two middle
    prices, so the headline is always a price a player could actually type.
    """
    ordered = sorted(prices)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) // 2
    return ordered[0], median, ordered[-1]


def _by_item(ctx: Context) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in _rows(ctx):
        grouped.setdefault(row["item_id"], []).append(row)
    return grouped


def _name(ctx: Context, item_id: str) -> str:
    item = ctx.content.items.get(item_id)
    return item.name if item is not None else item_id


def _item(ctx: Context, value: str):
    item = ctx.content.items.get(value)
    if item is None:
        item = next((entry for entry in ctx.content.items.values() if entry.name == value), None)
    if item is None:
        raise GameError("未找到该物品，请检查名称。")
    return item


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, BEIJING).strftime("%m-%d")


def _line(ctx: Context, item_id: str, rows: list[dict]) -> str:
    prices = [row["unit_price"] for row in rows]
    low, mid, high = summary(prices)
    units = sum(row["quantity"] for row in rows)
    return (
        f"{_name(ctx, item_id)}：中位 {mid} · 最低 {low} · 最高 {high}"
        f" · 成交 {len(rows)} 笔（{units} 件）"
    )


def page(ctx: Context, arg: str) -> Reply:
    """List every item that actually cleared inside the window, paginated."""
    since, days = window(ctx)
    grouped = {
        item_id: rows for item_id, rows in _by_item(ctx).items() if rows
    }
    if not grouped:
        return Reply(TITLE, (
            f"最近 {days} 天集市没有任何成交。",
            "有成交后，这里会给出每件物品的成交中位价、区间与笔数。",
            "行情只读成交账本，不展示任何人的挂单价格。",
        ), ("灵宠集市", "灵宠集市 记录", "灵宠帮助"),
            (InlineCommand(0, "去集市看看", "灵宠集市"),))
    ordered = sorted(grouped.items(), key=lambda entry: (-len(entry[1]), entry[0]))
    pages = max(1, (len(ordered) + PAGE_SIZE - 1) // PAGE_SIZE)
    number = quantity(arg or "1", 999)
    if number > pages:
        raise GameError(f"行情共 {pages} 页。")
    selected = ordered[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]
    lines = [
        f"最近 {days} 天成交 {len(ordered)} 种物品 · 第 {number}/{pages} 页。",
    ]
    links = []
    for item_id, rows in selected:
        lines.append(_line(ctx, item_id, rows))
        links.append(InlineCommand(len(lines) - 1, "查看", f"{COMMAND} 行情 {item_id}"))
    lines.append("中位价是窗口内成交单价的中位数，不是挂单价；成交笔数少的物品参考价值有限。")
    commands = [f"{COMMAND} 行情", COMMAND, f"{COMMAND} 记录"]
    if pages > 1:
        commands.append(f"{COMMAND} 行情 {number - 1}" if number > 1 else f"{COMMAND} 行情 {number + 1}")
    return Reply(TITLE, tuple(lines), tuple(commands)[:4], tuple(links))


def detail(ctx: Context, value: str) -> Reply:
    item = _item(ctx, value)
    rows = sorted(_rows(ctx, item.id), key=lambda row: (row["sold_at"], row["source"]), reverse=True)
    _, days = window(ctx)
    if not rows:
        return Reply(f"{TITLE} · {item.name}", (
            f"最近 {days} 天{item.name}没有任何成交。",
            "没有成交不等于没有挂单：想看当前标价请发 灵宠集市。",
        ), (f"{COMMAND} 行情", COMMAND, "灵宠帮助"))
    prices = [row["unit_price"] for row in rows]
    low, mid, high = summary(prices)
    units = sum(row["quantity"] for row in rows)
    lines = [
        f"最近 {days} 天成交 {len(rows)} 笔，共 {units} 件。"
        f"单价中位 {mid} · 最低 {low} · 最高 {high}。",
        "最近成交：",
    ]
    for row in rows[:PAGE_SIZE]:
        lines.append(
            f"{_day(row['sold_at'])} · {row['source']} · {row['unit_price']} 灵石 × {row['quantity']}"
        )
    if len(rows) > PAGE_SIZE:
        lines.append(f"仅显示最近 {PAGE_SIZE} 笔。")
    lines.append("卖家用它定价，买家用来判断求购价是否可能被应单。")
    return Reply(f"{TITLE} · {item.name}", tuple(lines),
                 (f"{COMMAND} 行情", COMMAND, f"{COMMAND} 求购"))


def dispatch(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text:
        return page(ctx, "")
    if text.isdecimal():
        return page(ctx, text)
    return detail(ctx, text)


def objective_line(ctx: Context, user_id: str) -> str:
    """Deliberately short: 行情 is a lookup, not a progression track."""
    return f"行情：最近 {rule(ctx).trend_days} 天成交"


__all__ = ["PAGE_SIZE", "SOURCE_BID", "SOURCE_LISTING", "TITLE", "detail", "dispatch", "page", "summary", "window"]
