"""灵宠集市: a player-run market for materials and pills.

Every listing escrows its stack out of the seller's bag, so a sold, cancelled or
expired listing moves the items exactly once. State lives in two schema-22 tables:

* ``market_listings`` — one row per listing with its price, deadline and state
* ``market_sales`` — the permanent ledger of completed sales (gross, tax, net)

The stall tier is a plain ``quest_progress`` row (``market_stall``), so no extra
column is needed. Expired listings settle lazily the next time the market is
opened; every transition is guarded by ``state='active'`` so the same escrow can
never be paid back twice.

Pricing is set by the seller and bounded by content. A sale charges the seller a
tax based on their stall tier: ``fee = gross * fee_percent // 100`` and the seller
receives ``gross - fee``. The tax leaves the economy; no player receives it.
"""

import re

from ..application.context import Context
from ..domain.market_content import MarketRule, Stall
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from ..utils.time import beijing_day

STALL_KEY = "market_stall"
PAGE_SIZE = 5
SALE_PAGE_SIZE = 5


def rule(ctx: Context) -> MarketRule:
    return ctx.content.market


def stalls(ctx: Context) -> list[Stall]:
    return list(ctx.content.market.stalls)


def tier_index(ctx: Context, user_id: str | None = None) -> int:
    """Current stall ladder position (0-based), clamped to the shipped tiers."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, STALL_KEY),
    ).fetchone()
    if row is None:
        return 0
    return min(max(int(row["progress"]) - 1, 0), len(stalls(ctx)) - 1)


def tier(ctx: Context, user_id: str | None = None) -> Stall:
    return stalls(ctx)[tier_index(ctx, user_id)]


def next_tier(ctx: Context, user_id: str | None = None) -> Stall | None:
    index = tier_index(ctx, user_id) + 1
    return stalls(ctx)[index] if index < len(stalls(ctx)) else None


def _write_stall(ctx: Context, tier_number: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=excluded.claimed",
        (ctx.user_id, STALL_KEY, tier_number),
    )


def owned(ctx: Context, item_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (user_id or ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def active_listings(ctx: Context, user_id: str | None = None) -> list:
    return ctx.repo.conn.execute(
        "SELECT * FROM market_listings WHERE seller_id=? AND state='active' ORDER BY listing_id",
        (user_id or ctx.user_id,),
    ).fetchall()


def board(ctx: Context) -> list:
    """Every active listing, cheapest first within each item."""
    return ctx.repo.conn.execute(
        "SELECT * FROM market_listings WHERE state='active'"
        " ORDER BY item_id, unit_price, listing_id"
    ).fetchall()


def sweep_expired(ctx: Context) -> int:
    """Close listings past their deadline and return the escrow to each seller.

    A listing whose item left the catalog is closed the same way: the id can no
    longer be rendered or priced, so it must not stay on the board. Its stack is
    deliberately not handed back through ``add_item`` — the item no longer exists
    in content, and a dead id in the bag would only confuse the shop pages.
    """
    rows = ctx.repo.conn.execute(
        "SELECT listing_id, seller_id, item_id, quantity, expires_at FROM market_listings"
        " WHERE state='active' ORDER BY listing_id",
    ).fetchall()
    closed_count = 0
    for row in rows:
        known = row["item_id"] in ctx.content.items
        if known and row["expires_at"] > ctx.now:
            continue
        closed = ctx.repo.conn.execute(
            "UPDATE market_listings SET state='expired', closed_at=?"
            " WHERE listing_id=? AND state='active'",
            (ctx.now, row["listing_id"]),
        )
        if closed.rowcount == 1:
            closed_count += 1
            if known:
                ctx.repo.add_item(row["seller_id"], row["item_id"], row["quantity"])
    return closed_count


def _item_name(ctx: Context, item_id: str) -> str:
    item = ctx.content.items.get(item_id)
    return item.name if item is not None else item_id


def uid_of(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return f"UID {player.internal_id + 9999}" if player is not None else "未知修士"


def _item(ctx: Context, value: str):
    item = ctx.content.items.get(value)
    if item is None:
        item = next((entry for entry in ctx.content.items.values() if entry.name == value), None)
    if item is None:
        raise GameError("未找到该物品，请检查名称。")
    return item


def _price(ctx: Context, value: str) -> int:
    market = rule(ctx)
    if not re.fullmatch(r"[0-9]+", value) or not (
        market.min_unit_price <= int(value) <= market.max_unit_price
    ):
        raise GameError(f"单价须为 {market.min_unit_price}-{market.max_unit_price} 的整数。")
    return int(value)


def _listing_id(value: str, action: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise GameError(f"格式：灵宠集市 {action} <陈列编号>。")
    return int(value)


def page(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠集市",
            (
                "尚未结契，先完成领养，才能摆摊或买货。",
                "集市里是其他玩家上架的材料与丹药：卖家定价，买家按标价买入。",
                f"首次摆摊免费，{rule(ctx).listing_days} 天未售出会自动退回背包。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sweep(ctx)
    player = ctx.player()
    rows = board(ctx)
    entries = [(row, ctx.content.items[row["item_id"]]) for row in rows]
    page_data = paginate(entries, arg, "灵宠集市", "灵宠集市", PAGE_SIZE)
    current = tier(ctx)
    lines = [
        f"灵石：{player.stones} · 在售 {len(rows)} 件 · "
        f"我的摊位：{current.name}（{len(active_listings(ctx))}/{current.slots}）",
    ]
    links = []
    for row, item in page_data.entries:
        total = row["unit_price"] * row["quantity"]
        owner = "自家摊位" if row["seller_id"] == ctx.user_id else uid_of(ctx, row["seller_id"])
        days = max(0, (row["expires_at"] - ctx.now + 86399) // 86400)
        lines.append(
            f"{row['listing_id']}. {item.name} ×{row['quantity']} · 单价 {row['unit_price']}"
            f" · 总价 {total} 灵石 · {owner} · 剩 {days} 天"
        )
        if row["seller_id"] != ctx.user_id and player.stones >= total:
            links.append(InlineCommand(
                len(lines) - 1, "购买", f"灵宠集市 购买 {row['listing_id']}",
            ))
    if not entries:
        lines.append("集市暂时空空如也。")
        lines.append("想出手？上架材料或丹药，等别的修士来买。")
        links.append(InlineCommand(len(lines) - 1, "上架物品", "灵宠集市 上架 "))
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    commands = (*page_data.navigation, "灵宠集市 我的", "灵宠背包", "灵宠目标")[:4]
    return Reply("灵宠集市", tuple(lines), commands, tuple(links))


def mine(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠集市 我的。")
    sweep(ctx)
    player = ctx.player()
    current = tier(ctx)
    listings = active_listings(ctx)
    lines = [
        f"摊位：{current.name} · 陈列 {len(listings)}/{current.slots}"
        f" · 成交税 {current.fee_percent}% · 灵石 {player.stones}",
    ]
    links = []
    upcoming = next_tier(ctx)
    if upcoming is None:
        lines.append("已是最高等级的商号，陈列位与税率都到顶了。")
    elif player.stones >= upcoming.unlock_cost:
        lines.append(
            f"下一级 {upcoming.name}：{upcoming.unlock_cost} 灵石"
            f" · 陈列 {upcoming.slots} 位 · 成交税 {upcoming.fee_percent}%"
        )
        links.append(InlineCommand(len(lines) - 1, "升级摊位", "灵宠集市 升级"))
    else:
        lines.append(
            f"下一级 {upcoming.name}：{upcoming.unlock_cost} 灵石"
            f"（还差 {upcoming.unlock_cost - player.stones}）"
        )
    if listings:
        lines.append("在售")
        for row in listings:
            item = ctx.content.items[row["item_id"]]
            lines.append(
                f"#{row['listing_id']} {item.name} ×{row['quantity']}"
                f" · 单价 {row['unit_price']} · 到期 {beijing_day(row['expires_at'])}"
            )
            links.append(InlineCommand(
                len(lines) - 1, "下架", f"灵宠集市 下架 {row['listing_id']}",
            ))
    else:
        lines.append("在售：暂无。发送 灵宠集市 上架 物品 数量 单价 即可摆摊。")
    sales = ctx.repo.conn.execute(
        "SELECT * FROM market_sales WHERE seller_id=? ORDER BY sold_at DESC, listing_id DESC LIMIT 3",
        (ctx.user_id,),
    ).fetchall()
    lines.append("最近成交")
    if sales:
        for sale in sales:
            item = ctx.content.items.get(sale["item_id"])
            name = item.name if item is not None else sale["item_id"]
            lines.append(
                f"{beijing_day(sale['sold_at'])[5:]} {name} ×{sale['quantity']}"
                f" · 实收 {sale['net']} 灵石（税 {sale['fee']}）"
            )
    else:
        lines.append("还没有成交记录。")
    return Reply("我的摊位", tuple(lines), ("灵宠集市", "灵宠集市 记录", "灵宠背包"), tuple(links))


def records(ctx: Context, arg: str = "") -> Reply:
    ctx.player()
    sweep(ctx)
    sales = ctx.repo.conn.execute(
        "SELECT * FROM market_sales WHERE seller_id=? ORDER BY sold_at DESC, listing_id DESC",
        (ctx.user_id,),
    ).fetchall()
    page_data = paginate(sales, arg, "成交记录", "灵宠集市 记录", SALE_PAGE_SIZE)
    totals = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(net), 0) AS net, COALESCE(SUM(fee), 0) AS fee"
        " FROM market_sales WHERE seller_id=?",
        (ctx.user_id,),
    ).fetchone()
    lines = [
        f"累计成交 {totals['n']} 笔 · 实收 {totals['net']} 灵石 · 缴税 {totals['fee']} 灵石",
    ]
    for sale in page_data.entries:
        lines.append(
            f"{beijing_day(sale['sold_at'])} · {_item_name(ctx, sale['item_id'])}"
            f" ×{sale['quantity']}"
            f" · 总价 {sale['gross']} · 税 {sale['fee']} · 实收 {sale['net']}"
        )
    if not sales:
        lines.append("还没有成交记录。")
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    return Reply(
        "成交记录", tuple(lines), (*page_data.navigation, "灵宠集市 我的", "灵宠背包")[:4],
    )


def list_item(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 3:
        raise GameError(
            "格式：灵宠集市 上架 <物品名> <数量> <单价>，例如 灵宠集市 上架 锻灵矿 5 90。"
        )
    ctx.player()
    name, amount_text, price_text = parts
    item = _item(ctx, name)
    market = rule(ctx)
    if item.kind not in market.sellable_kinds:
        raise GameError(f"{item.name}不能摆上集市，只有材料和丹药可以上架。")
    amount = quantity(amount_text, market.max_quantity)
    price = _price(ctx, price_text)
    sweep(ctx)
    current = tier(ctx)
    if len(active_listings(ctx)) >= current.slots:
        raise GameError(f"{current.name}只有 {current.slots} 个陈列位，先下架一件或升级摊位。")
    held = owned(ctx, item.id)
    if held < amount:
        raise GameError(f"{item.name}不足：持有 {held}，需要 {amount}。")
    ctx.repo.consume_item(ctx.user_id, item.id, amount)
    cursor = ctx.repo.conn.execute(
        "INSERT INTO market_listings(seller_id, item_id, quantity, unit_price,"
        " created_at, expires_at, state) VALUES (?, ?, ?, ?, ?, ?, 'active')",
        (
            ctx.user_id, item.id, amount, price, ctx.now,
            ctx.now + market.listing_days * 86400,
        ),
    )
    listing_id = int(cursor.lastrowid)
    return Reply(
        "上架成功",
        (
            f"#{listing_id} {item.name} ×{amount} · 单价 {price} · 总价 {price * amount} 灵石。",
            f"{market.listing_days} 天后未售出会自动退回背包；成交税按摊位等级从卖家所得中扣除。",
            f"当前摊位：{current.name} · 陈列 {len(active_listings(ctx))}/{current.slots}。",
        ),
        ("灵宠集市", "灵宠集市 我的", "灵宠背包"),
    )


def buy(ctx: Context, arg: str) -> Reply:
    listing_id = _listing_id(arg, "购买")
    ctx.player()
    sweep(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM market_listings WHERE listing_id=?", (listing_id,),
    ).fetchone()
    if row is None or row["state"] == "expired":
        raise GameError("未找到这件陈列，它可能已经下架或到期。")
    if row["state"] != "active":
        raise GameError("这件物品已经不在售了。")
    if row["seller_id"] == ctx.user_id:
        raise GameError("不能购买自家摊位上的物品。")
    item = ctx.content.items[row["item_id"]]
    total = row["unit_price"] * row["quantity"]
    buyer = ctx.player()
    if buyer.stones < total:
        raise GameError(f"灵石不足：需要 {total}，当前 {buyer.stones}。")
    seller = ctx.repo.player(row["seller_id"])
    if seller is None:
        raise GameError("卖家已离开集市，暂时无法成交。")
    closed = ctx.repo.conn.execute(
        "UPDATE market_listings SET state='sold', closed_at=?, buyer_id=?"
        " WHERE listing_id=? AND state='active'",
        (ctx.now, ctx.user_id, listing_id),
    )
    if closed.rowcount != 1:
        raise GameError("这件物品刚刚被别人买走了。")
    fee = total * tier(ctx, row["seller_id"]).fee_percent // 100
    net = total - fee
    buyer.stones -= total
    seller.stones += net
    ctx.repo.add_item(ctx.user_id, item.id, row["quantity"])
    ctx.repo.conn.execute(
        "INSERT INTO market_sales(listing_id, seller_id, buyer_id, item_id, quantity,"
        " unit_price, gross, fee, net, sold_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            listing_id, row["seller_id"], ctx.user_id, item.id, row["quantity"],
            row["unit_price"], total, fee, net, ctx.now,
        ),
    )
    return Reply(
        "购买成功",
        (
            f"{item.name} ×{row['quantity']} 已入乾坤袋，付 {total} 灵石。",
            f"卖家 {uid_of(ctx, row['seller_id'])} 实收 {net} 灵石（摊位税 {fee}）。",
        ),
        ("灵宠集市", "灵宠背包", "灵宠集市 我的"),
    )


def cancel(ctx: Context, arg: str) -> Reply:
    listing_id = _listing_id(arg, "下架")
    ctx.player()
    sweep(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM market_listings WHERE listing_id=?", (listing_id,),
    ).fetchone()
    if row is None or row["state"] == "expired":
        raise GameError("未找到这件陈列，它可能已经到期。")
    if row["seller_id"] != ctx.user_id:
        raise GameError("只能下架自家摊位上的物品。")
    if row["state"] != "active":
        raise GameError("这件物品已经不在售了。")
    closed = ctx.repo.conn.execute(
        "UPDATE market_listings SET state='cancelled', closed_at=?"
        " WHERE listing_id=? AND state='active'",
        (ctx.now, listing_id),
    )
    if closed.rowcount != 1:
        raise GameError("这件物品已经不在售了。")
    ctx.repo.add_item(ctx.user_id, row["item_id"], row["quantity"])
    item = ctx.content.items[row["item_id"]]
    return Reply(
        "下架成功",
        (f"{item.name} ×{row['quantity']} 已退回乾坤袋。",),
        ("灵宠集市", "灵宠集市 我的", "灵宠背包"),
    )


def upgrade(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠集市 升级。")
    sweep(ctx)
    player = ctx.player()
    upcoming = next_tier(ctx)
    if upcoming is None:
        raise GameError("已经是最高等级的摊位，无需再升级。")
    if player.stones < upcoming.unlock_cost:
        raise GameError(
            f"灵石不足：升到{upcoming.name}需要 {upcoming.unlock_cost}，当前 {player.stones}。"
        )
    player.stones -= upcoming.unlock_cost
    _write_stall(ctx, tier_index(ctx) + 2)
    return Reply(
        "摊位升级",
        (
            f"摊位升为{upcoming.name}：陈列 {upcoming.slots} 位 · 成交税 {upcoming.fee_percent}%。",
            f"花费 {upcoming.unlock_cost} 灵石，余 {player.stones}。",
        ),
        ("灵宠集市", "灵宠集市 我的", "灵宠背包"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if re.fullmatch(r"[0-9]+", head):
        return page(ctx, head)
    if head == "我的":
        return mine(ctx, rest)
    if head == "记录":
        return records(ctx, rest)
    if head == "上架":
        return list_item(ctx, rest)
    if head == "购买":
        return buy(ctx, rest)
    if head == "下架":
        return cancel(ctx, rest)
    if head == "升级":
        return upgrade(ctx, rest)
    if head == "求购":
        if not rest or re.fullmatch(r"[0-9]+", rest.strip()):
            return bid_page(ctx, rest)
        return place_bid(ctx, rest)
    if head == "应单":
        return fill_bid(ctx, rest)
    if head == "撤单":
        return cancel_bid(ctx, rest)
    if head == "求购记录":
        return bid_records(ctx, rest)
    raise GameError(
        "格式：灵宠集市 [页码|上架 物品 数量 单价|购买 编号|下架 编号|我的|记录|升级|"
        "求购 [物品 数量 单价]|应单 编号|撤单 编号|求购记录]。"
    )


# --------------------------------------------------------------------- buy orders

BID_PAGE_SIZE = 5


def active_bids(ctx: Context, user_id: str | None = None) -> list:
    """Buy orders the player still has open (stones already escrowed)."""
    return ctx.repo.conn.execute(
        "SELECT * FROM market_bids WHERE buyer_id=? AND state='active' ORDER BY bid_id",
        (user_id or ctx.user_id,),
    ).fetchall()


def bid_board(ctx: Context) -> list:
    """Every open buy order, best-paying first within each item."""
    return ctx.repo.conn.execute(
        "SELECT * FROM market_bids WHERE state='active' ORDER BY item_id, unit_price DESC, bid_id",
    ).fetchall()


def sweep_bids(ctx: Context) -> int:
    """Close overdue or orphaned buy orders and refund the escrow exactly once.

    Mirrors ``sweep_expired``: an order whose item left the catalog is closed too,
    and because the escrow is stones (not a stack) the refund is always payable —
    a dead item id never has to be put back into anyone's bag.
    """
    rows = ctx.repo.conn.execute(
        "SELECT bid_id, buyer_id, item_id, escrow, expires_at FROM market_bids"
        " WHERE state='active' ORDER BY bid_id",
    ).fetchall()
    closed_count = 0
    for row in rows:
        known = row["item_id"] in ctx.content.items
        if known and row["expires_at"] > ctx.now:
            continue
        closed = ctx.repo.conn.execute(
            "UPDATE market_bids SET state='expired', closed_at=? WHERE bid_id=? AND state='active'",
            (ctx.now, row["bid_id"]),
        )
        if closed.rowcount == 1:
            closed_count += 1
            buyer = ctx.repo.player(row["buyer_id"])
            if buyer is not None:
                buyer.stones += int(row["escrow"])
    return closed_count


def sweep(ctx: Context) -> None:
    """Both sweeps run together wherever the market is opened."""
    sweep_expired(ctx)
    sweep_bids(ctx)


def _bid_id(value: str, action: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise GameError(f"格式：灵宠集市 {action} <求购编号>。")
    return int(value)


def _bid_quantity(ctx: Context, value: str) -> int:
    return quantity(value, rule(ctx).max_bid_quantity)


def place_bid(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 3:
        raise GameError(
            "格式：灵宠集市 求购 <物品名> <数量> <单价>，例如 灵宠集市 求购 锻灵矿 5 90。"
        )
    player = ctx.player()
    name, amount_text, price_text = parts
    item = _item(ctx, name)
    market = rule(ctx)
    if item.kind not in market.sellable_kinds:
        raise GameError(f"{item.name}不能求购，只有材料和丹药可以挂求购。")
    amount = _bid_quantity(ctx, amount_text)
    price = _price(ctx, price_text)
    sweep(ctx)
    if len(active_bids(ctx)) >= market.bid_slots:
        raise GameError(
            f"同时最多挂 {market.bid_slots} 条求购，先撤一条或等它成交。"
        )
    escrow = amount * price
    if player.stones < escrow:
        raise GameError(f"灵石不足：求购需先付全款 {escrow}，当前 {player.stones}。")
    player.stones -= escrow
    cursor = ctx.repo.conn.execute(
        "INSERT INTO market_bids(buyer_id, item_id, quantity, unit_price, escrow,"
        " created_at, expires_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')",
        (player.user_id, item.id, amount, price, escrow, ctx.now,
         ctx.now + market.bid_days * 86400),
    )
    bid_id = int(cursor.lastrowid)
    return Reply(
        "求购已挂出",
        (
            f"#{bid_id} 收 {item.name} ×{amount} · 单价 {price} · 已托管 {escrow} 灵石。",
            f"其他修士可用 灵宠集市 应单 {bid_id} 交货收款，{market.bid_days} 天后未成交自动退回。",
            f"余 {player.stones} 灵石 · 求购 {len(active_bids(ctx))}/{market.bid_slots}。",
        ),
        ("灵宠集市 求购", "灵宠集市 我的", "灵宠背包"),
    )


def fill_bid(ctx: Context, arg: str) -> Reply:
    bid_id = _bid_id(arg, "应单")
    ctx.player()
    sweep(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM market_bids WHERE bid_id=?", (bid_id,),
    ).fetchone()
    if row is None or row["state"] == "expired":
        raise GameError("未找到这条求购，它可能已成交或到期。")
    if row["state"] != "active":
        raise GameError("这条求购已经不在等货了。")
    if row["buyer_id"] == ctx.user_id:
        raise GameError("不能应自己的求购。")
    item = ctx.content.items.get(row["item_id"])
    if item is None:
        raise GameError("这条求购的物品已下架，无法交割。")
    held = owned(ctx, item.id)
    if held < row["quantity"]:
        raise GameError(f"{item.name}不足：持有 {held}，需要 {row['quantity']}。")
    buyer = ctx.repo.player(row["buyer_id"])
    if buyer is None:
        raise GameError("买家已离开集市，暂时无法交割。")
    closed = ctx.repo.conn.execute(
        "UPDATE market_bids SET state='filled', closed_at=?, seller_id=?"
        " WHERE bid_id=? AND state='active'",
        (ctx.now, ctx.user_id, bid_id),
    )
    if closed.rowcount != 1:
        raise GameError("这条求购刚刚已被别人应单。")
    ctx.repo.consume_item(ctx.user_id, item.id, row["quantity"])
    ctx.repo.add_item(row["buyer_id"], item.id, row["quantity"])
    gross = int(row["escrow"])
    fee = gross * tier(ctx).fee_percent // 100
    net = gross - fee
    ctx.player().stones += net
    ctx.repo.conn.execute(
        "INSERT INTO market_bid_sales(bid_id, buyer_id, seller_id, item_id, quantity,"
        " unit_price, gross, fee, net, sold_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (bid_id, row["buyer_id"], ctx.user_id, item.id, row["quantity"],
         row["unit_price"], gross, fee, net, ctx.now),
    )
    return Reply(
        "应单成功",
        (
            f"{item.name} ×{row['quantity']} 已交给 UID {buyer.internal_id + 9999}。",
            f"托管 {gross} 灵石已结清：实收 {net}（摊位税 {fee}）。",
        ),
        ("灵宠集市", "灵宠集市 记录", "灵宠背包"),
    )


def cancel_bid(ctx: Context, arg: str) -> Reply:
    bid_id = _bid_id(arg, "撤单")
    ctx.player()
    sweep(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM market_bids WHERE bid_id=?", (bid_id,),
    ).fetchone()
    if row is None or row["state"] == "expired":
        raise GameError("未找到这条求购，它可能已到期。")
    if row["buyer_id"] != ctx.user_id:
        raise GameError("只能撤回自己挂的求购。")
    if row["state"] != "active":
        raise GameError("这条求购已经不在等货了。")
    closed = ctx.repo.conn.execute(
        "UPDATE market_bids SET state='cancelled', closed_at=? WHERE bid_id=? AND state='active'",
        (ctx.now, bid_id),
    )
    if closed.rowcount != 1:
        raise GameError("这条求购已经不在等货了。")
    buyer = ctx.player()
    buyer.stones += int(row["escrow"])
    return Reply(
        "求购已撤回",
        (f"托管 {row['escrow']} 灵石已退回，余 {buyer.stones}。",),
        ("灵宠集市 求购", "灵宠集市 我的", "灵宠背包"),
    )


def bid_page(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠集市 求购",
            (
                "尚未结契，先完成领养，才能挂求购或应单。",
                "求购是买方挂出的反向挂单：先付全款托管，谁有货谁来应单。",
                f"求购 {rule(ctx).bid_days} 天未成交会自动退款。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sweep(ctx)
    player = ctx.player()
    market = rule(ctx)
    rows = bid_board(ctx)
    entries = [(row, ctx.content.items[row["item_id"]]) for row in rows]
    page_data = paginate(entries, arg, "灵宠集市 求购", "灵宠集市 求购", BID_PAGE_SIZE)
    lines = [
        f"灵石：{player.stones} · 在等货的求购 {len(rows)} 条"
        f" · 我挂出 {len(active_bids(ctx))}/{market.bid_slots}。",
    ]
    links = []
    for row, item in page_data.entries:
        mine = row["buyer_id"] == ctx.user_id
        owner = "自家求购" if mine else uid_of(ctx, row["buyer_id"])
        days = max(0, (row["expires_at"] - ctx.now + 86399) // 86400)
        held = owned(ctx, item.id)
        lines.append(
            f"{row['bid_id']}. 收 {item.name} ×{row['quantity']} · 单价 {row['unit_price']}"
            f" · 托管 {row['escrow']} 灵石 · {owner} · 剩 {days} 天 · 我持有 {held}"
        )
        if not mine and held >= row["quantity"]:
            links.append(InlineCommand(
                len(lines) - 1, "应单", f"灵宠集市 应单 {row['bid_id']}",
            ))
    if not entries:
        lines.append("暂时没有人在收东西。")
        lines.append("想收货？挂一条求购，先付全款，等有货的人来应单。")
        links.append(InlineCommand(len(lines) - 1, "挂求购", "灵宠集市 求购 "))
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    commands = (*page_data.navigation, "灵宠集市", "灵宠集市 我的")[:4]
    return Reply("灵宠集市 求购", tuple(lines), commands, tuple(links))


def bid_records(ctx: Context, arg: str = "") -> Reply:
    """Both sides of the player's filled buy orders, newest first."""
    ctx.player()
    sweep(ctx)
    sales = ctx.repo.conn.execute(
        "SELECT * FROM market_bid_sales WHERE buyer_id=? OR seller_id=?"
        " ORDER BY sold_at DESC, bid_id DESC",
        (ctx.user_id, ctx.user_id),
    ).fetchall()
    page_data = paginate(sales, arg, "求购记录", "灵宠集市 求购记录", SALE_PAGE_SIZE)
    bought = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(gross), 0) AS gross FROM market_bid_sales WHERE buyer_id=?",
        (ctx.user_id,),
    ).fetchone()
    sold = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(net), 0) AS net, COALESCE(SUM(fee), 0) AS fee"
        " FROM market_bid_sales WHERE seller_id=?",
        (ctx.user_id,),
    ).fetchone()
    lines = [
        f"收货 {bought['n']} 笔 · 付出 {bought['gross']} 灵石"
        f" · 交货 {sold['n']} 笔 · 实收 {sold['net']} 灵石（税 {sold['fee']}）",
    ]
    for sale in page_data.entries:
        role = "收货" if sale["buyer_id"] == ctx.user_id else "交货"
        lines.append(
            f"{beijing_day(sale['sold_at'])} · {role} {_item_name(ctx, sale['item_id'])}"
            f" ×{sale['quantity']} · 单价 {sale['unit_price']}"
            f" · 总价 {sale['gross']} · 税 {sale['fee']} · 实收 {sale['net']}"
        )
    if not sales:
        lines.append("还没有成交过的求购。")
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    return Reply(
        "求购记录", tuple(lines), (*page_data.navigation, "灵宠集市 求购", "灵宠集市")[:4],
    )


def objective_line(ctx: Context, user_id: str) -> str:
    current = tier(ctx, user_id)
    used = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM market_listings WHERE seller_id=? AND state='active'",
        (user_id,),
    ).fetchone()[0])
    open_bids = len(active_bids(ctx, user_id))
    return f"集市：{current.name} · 在售 {used}/{current.slots} · 求购 {open_bids}/{rule(ctx).bid_slots}"
