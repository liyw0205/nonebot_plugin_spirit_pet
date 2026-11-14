"""Weekly meal deliveries consume real cuisine products and grow order reputation."""

from sqlite3 import Row

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.cuisine_order_content import CuisineOrder
from ..domain.cuisine_content import CuisineDish
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day, beijing_week
from . import cuisine
from .rewards import grant

TITLE = "灵宠膳房订单"
PREFIX = "cuisine_order_"


def entries(ctx: Context) -> list[CuisineOrder]:
    return sorted(ctx.content.cuisine_orders.values(), key=lambda order: order.required_reputation)


def _week(ctx: Context) -> tuple[int, int, str]:
    start, end = beijing_week(ctx.now)
    return start, end, beijing_day(start)


def _key(week: str, order_id: str) -> str:
    return f"{PREFIX}{week}_{order_id}"


def _records(ctx: Context, user_id: str, week: str) -> dict[str, Row]:
    prefix = f"{PREFIX}{week}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id,progress,claimed FROM quest_progress "
        "WHERE user_id=? AND substr(quest_id,1,?)=?",
        (user_id, len(prefix), prefix),
    )
    return {
        order_id: row for row in rows
        if (order_id := row["quest_id"][len(prefix):]) in ctx.content.cuisine_orders
    }


def reputation(records: dict[str, Row]) -> int:
    return sum(int(record["progress"]) for record in records.values() if record["claimed"])


def _has_future_receipt(ctx: Context, user_id: str, start: int) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')='cuisine_order' "
        "AND json_extract(snapshot,'$.week_start')>? LIMIT 1",
        (user_id, start),
    ).fetchone() is not None


def _missing(ctx: Context, user_id: str, order: CuisineOrder) -> int:
    dish = ctx.content.cuisine[order.dish_id]
    assert dish.item is not None
    return max(0, order.portions - cuisine.owned_item(ctx, user_id, dish.item))


def _validate_order(ctx: Context, order: CuisineOrder) -> CuisineDish:
    try:
        CuisineOrder.model_validate(order.model_dump())
    except ValueError as exc:
        raise GameError("订单定义暂不可用，本次未交付；请稍后再试。") from exc
    dish = ctx.content.cuisine.get(order.dish_id)
    if dish is None or dish.item is None or dish.item not in ctx.content.items:
        raise GameError("订单菜谱或成品定义缺失，本次未交付；请稍后再试。")
    if not dish.level <= order.cuisine_level <= ctx.content.rules.cuisine.max_level:
        raise GameError("订单厨艺门槛异常，本次未交付；请稍后再试。")
    missing = set(order.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"订单奖励定义缺失：{', '.join(sorted(missing))}；本次未交付。")
    return dish


def _status(ctx: Context, user_id: str, order: CuisineOrder, records: dict, rep: int) -> str:
    record = records.get(order.id)
    if record is not None:
        return "已交付" if record["claimed"] else "交付记录异常"
    if cuisine.level(ctx, user_id) < order.cuisine_level:
        return f"需厨艺 {order.cuisine_level} 级"
    if rep < order.required_reputation:
        return f"需订单声望 {order.required_reputation}（当前 {rep}）"
    missing = _missing(ctx, user_id, order)
    if missing:
        return f"灵膳不足 {missing} 份"
    return "可交付"


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠膳房订单；交付请用 灵宠订单交付 订单编号。")
    start, end, week = _week(ctx)
    player = ctx.repo.player(ctx.user_id)
    records = _records(ctx, ctx.user_id, week) if player else {}
    rep = reputation(records)
    level = cuisine.level(ctx, ctx.user_id) if player else 0
    lines = [
        f"本周 {beijing_day(start)} 至 {beijing_day(end - 1)} · 厨艺 {level} 级 · 订单声望 {rep}。",
        "单膳即时烹饪或掌勺成品均可交付；每单每周一次，周一重置订单和声望。",
    ]
    clock_blocked = bool(player and _has_future_receipt(ctx, player.user_id, start))
    links = []
    for order in entries(ctx):
        try:
            dish = _validate_order(ctx, order)
        except GameError:
            lines.append(f"{order.name} · 订单定义暂不可用")
            continue
        item = ctx.content.items[dish.item]
        status = (
            "系统日期早于订单记录" if clock_blocked
            else _status(ctx, ctx.user_id, order, records, rep) if player else "尚未结契"
        )
        reward = [f"灵石 {order.stones}"] if order.stones else []
        reward.extend(
            f"{ctx.content.items[item_id].name} {amount}"
            for item_id, amount in order.items.items()
        )
        lines.append(
            f"{order.name} · 厨艺 {order.cuisine_level} 级 · 需声望 {order.required_reputation} · "
            f"交付 {item.name} ×{order.portions} · 声望 +{order.reputation} · "
            f"奖励 {'、'.join(reward)} · {status}"
        )
        if status == "可交付":
            links.append(InlineCommand(
                len(lines) - 1, "交付灵膳", f"灵宠订单交付 {order.id} {week}",
            ))
    if player is None:
        lines.append("尚未结契，先完成领养，再烹制并交付灵膳。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠膳房", "灵宠背包"), tuple(links))


def deliver(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) not in (1, 2):
        raise GameError("格式：灵宠订单交付 订单编号。")
    order = ctx.content.cuisine_orders.get(parts[0])
    if order is None:
        order = next((order for order in entries(ctx) if order.name == parts[0]), None)
    if order is None:
        raise GameError("没有这份灵膳订单，请查看 灵宠膳房订单。")
    start, end, week = _week(ctx)
    if len(parts) == 2 and parts[1] != week:
        raise GameError("这份订单已跨周，请重新查看灵宠膳房订单。")
    player = ctx.player()
    dish = _validate_order(ctx, order)
    if _has_future_receipt(ctx, player.user_id, start):
        raise GameError("系统日期早于灵膳订单记录，请等待日期恢复。")
    records = _records(ctx, player.user_id, week)
    if order.id in records:
        if records[order.id]["claimed"]:
            raise GameError(f"本周「{order.name}」已交付。")
        raise GameError("灵膳订单记录异常，请联系管理员检查存档。")
    level = cuisine.level(ctx, player.user_id)
    if level < order.cuisine_level:
        raise GameError(f"厨艺不足：「{order.name}」需要厨艺 {order.cuisine_level} 级，当前 {level} 级。")
    rep = reputation(records)
    if rep < order.required_reputation:
        raise GameError(f"订单声望不足：「{order.name}」需要 {order.required_reputation}，当前 {rep}。")
    assert dish.item is not None
    item = ctx.content.items[dish.item]
    owned = cuisine.owned_item(ctx, player.user_id, dish.item)
    if owned < order.portions:
        raise GameError(f"{item.name}不足：需要 {order.portions} 份，当前 {owned} 份。")

    ctx.repo.consume_item(player.user_id, dish.item, order.portions)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1)",
        (player.user_id, _key(week, order.id), order.reputation),
    )
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=order.stones, maximum=order.stones),
        items={item_id: Range(minimum=amount, maximum=amount)
               for item_id, amount in order.items.items()},
    )
    payout = grant(ctx, reward, player.user_id)
    total = rep + order.reputation
    reply = Reply(
        TITLE,
        (f"「{order.name}」已交付 {item.name} ×{order.portions} · 订单声望 {rep} → {total}。",
         *payout, f"本周周期至 {beijing_day(end - 1)}，后续订单按厨艺与声望逐档开放。"),
        (TITLE, "灵宠膳房", "灵宠背包"),
    )
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
        "kind": "cuisine_order", "week_start": start, "order_id": order.id,
        "item_id": dish.item, "portions": order.portions, "reputation": order.reputation,
        "reward": order.model_dump(),
    }, reply)
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠膳房订单；交付请用 灵宠订单交付 订单编号。")
    return catalog(ctx)


def objective_line(ctx: Context, user_id: str) -> str:
    start, _, week = _week(ctx)
    records = _records(ctx, user_id, week)
    rep = reputation(records)
    delivered = sum(bool(record["claimed"]) for record in records.values())
    ready = 0
    if not _has_future_receipt(ctx, user_id, start):
        for order in entries(ctx):
            try:
                _validate_order(ctx, order)
            except GameError:
                continue
            ready += _status(ctx, user_id, order, records, rep) == "可交付"
    return f"膳房订单：本周已交付 {delivered}/{len(entries(ctx))} · 声望 {rep} · 可交付 {ready} 单"


__all__ = ["TITLE", "catalog", "deliver", "dispatch", "entries", "objective_line", "reputation"]
