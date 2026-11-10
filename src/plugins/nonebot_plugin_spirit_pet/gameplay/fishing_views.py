"""Read-only catch probabilities, bait choices and durable cast history."""

import json
from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import BEIJING
from . import fishing

BASKET_PAGE_SIZE = 5


def detail(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) not in (1, 2):
        raise GameError("格式：灵宠垂钓 详情 地点 [饵料]。")
    spot = fishing._spot(ctx, parts[0])
    bait = fishing.bait_for(ctx, spot, parts[1] if len(parts) == 2 else "")
    bait_name = bait.name if bait else "素饵"
    pet = fishing.preview_pet(ctx)
    have = fishing.caught(ctx, spot)
    weights = fishing.weights(spot, bait)
    total = sum(weights)
    lines = [
        spot.description,
        f"门槛：{ctx.content.realms[spot.realm].name if spot.realm else '不限'}"
        f" · 每竿精力 {spot.energy} · 今日剩 {fishing.left_today(ctx)} 竿。",
        f"当前{bait_name} · 鱼获 {len(have)}/{len(spot.catches)}。",
    ]
    links = []
    if bait:
        stock = ctx.repo.inventory(ctx.user_id).get(bait.cost_item, 0)
        lines.append(
            f"每竿消耗{ctx.content.items[bait.cost_item].name} ×{bait.cost_quantity}（持有 {stock}）"
            f" · 偏向鱼获权重 ×{bait.multiplier}，其余权重不变。"
        )
    else:
        lines.append("素饵不消耗额外物品；择饵只改变概率，不保证钓中。")
    for entry, weight in zip(spot.catches, weights):
        item = ctx.content.items[entry.item]
        mark = "已集" if entry.item in have else "未集"
        favored = " · 偏向" if bait and entry.item in bait.favored_items else ""
        lines.append(
            f"{item.name} ×{entry.minimum}-{entry.maximum} · {mark}"
            f" · {weight}/{total}（约 {100 * weight / total:.1f}%）{favored}"
        )
    reason = fishing.block_reason(ctx, spot, pet, bait)
    lines.append(f"暂不可抛竿：{reason}。" if reason else f"可用{bait_name}抛竿。")
    if not reason:
        links.append(InlineCommand(
            len(lines) - 1, "抛竿", f"灵宠垂钓 {spot.name}" + (f" {bait.name}" if bait else ""),
        ))
    elif ctx.repo.player(ctx.user_id) is None:
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    elif pet is None:
        links.append(InlineCommand(len(lines) - 1, "选择伙伴", "灵宠列表"))

    lines.append("择饵预览：")
    lines.append("素饵 · 无额外消耗 · 原始鱼获权重。")
    if bait:
        links.append(InlineCommand(len(lines) - 1, "查看概率", f"灵宠垂钓 详情 {spot.name}"))
    stock = ctx.repo.inventory(ctx.user_id)
    for option in ctx.content.fishing_baits.values():
        targets = [ctx.content.items[entry.item].name for entry in spot.catches
                   if entry.item in option.favored_items]
        cost = ctx.content.items[option.cost_item].name
        lines.append(
            f"{option.name} · {cost} ×{option.cost_quantity}（持有 {stock.get(option.cost_item, 0)}）"
            + (f" · {'、'.join(targets)}权重 ×{option.multiplier}" if targets else " · 此处无偏向鱼获")
        )
        if targets and (bait is None or option.id != bait.id):
            links.append(InlineCommand(
                len(lines) - 1, "查看概率", f"灵宠垂钓 详情 {spot.name} {option.name}",
            ))
    return Reply(f"{spot.name} · 鱼获与择饵", tuple(lines), (
        "灵宠垂钓", "灵宠垂钓 鱼篓", "灵宠背包", "灵宠灵田",
    ), tuple(links))


def basket(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) > 1:
        raise GameError("格式：灵宠垂钓 鱼篓 [页码]。")
    number = quantity(parts[0] if parts else "1", 999)
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM fishing_casts WHERE user_id=?", (ctx.user_id,),
    ).fetchone()[0]
    pages = max(1, (count + BASKET_PAGE_SIZE - 1) // BASKET_PAGE_SIZE)
    if number > pages:
        raise GameError(f"鱼篓共 {pages} 页。")
    rows = ctx.repo.conn.execute(
        "SELECT created_at,snapshot FROM fishing_casts WHERE user_id=? ORDER BY cast_id DESC"
        " LIMIT ? OFFSET ?", (ctx.user_id, BASKET_PAGE_SIZE, (number - 1) * BASKET_PAGE_SIZE),
    ).fetchall()
    lines = [f"鱼篓共 {count} 竿 · 第 {number}/{pages} 页。"]
    if not rows:
        lines.append("还没有逐竿记录；旧版鱼获收集与集齐奖励仍然保留。")
        if ctx.repo.player(ctx.user_id) is None:
            lines.append("尚未结契，先完成领养，再和伙伴去水边。")
    for row in rows:
        saved = json.loads(row["snapshot"])
        stamp = datetime.fromtimestamp(row["created_at"], BEIJING).strftime("%Y-%m-%d %H:%M")
        cost = (f"、{saved['cost_name']} ×{saved['cost_quantity']}" if saved["cost_quantity"] else "")
        lines.append(
            f"{stamp} · {saved['pet_name']} · {saved['spot_name']} / {saved['bait_name']}"
            f" · {saved['item_name']} ×{saved['amount']} · 消耗精力 {saved['energy']}{cost}"
        )
    commands = []
    if number > 1:
        commands.append(f"灵宠垂钓 鱼篓 {number - 1}")
    if number < pages:
        commands.append(f"灵宠垂钓 鱼篓 {number + 1}")
    commands.extend(("灵宠垂钓", "灵宠背包"))
    links = (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),) if ctx.repo.player(ctx.user_id) is None else ()
    return Reply("灵宠垂钓 · 鱼篓", tuple(lines), tuple(commands), links)
