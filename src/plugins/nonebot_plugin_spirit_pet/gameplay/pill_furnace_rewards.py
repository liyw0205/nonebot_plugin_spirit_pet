"""Milestones derived from settled furnace receipts, paid once per product."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.pill_furnace_reward_content import PillFurnaceReward
from ..utils.arguments import named, quantity
from .rewards import grant

TITLE = "丹炉成品赏"
CLAIM_PREFIX = "pill_furnace_reward_"


def _counts(ctx: Context, user_id: str) -> dict[str, int]:
    # Every move has a snapshot; only a successful final receipt counts, once
    # per furnace, irrespective of whether it produced one or two portions.
    rows = ctx.repo.conn.execute(
        "SELECT json_extract(snapshot,'$.recipe.item') AS product, "
        "COUNT(DISTINCT json_extract(snapshot,'$.run_id')) AS amount "
        "FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')='pill_furnace' "
        "AND json_extract(snapshot,'$.status')='finished' "
        "AND json_type(snapshot,'$.run_id')='integer' "
        "AND json_type(snapshot,'$.portions')='integer' AND json_extract(snapshot,'$.portions')>0 "
        "GROUP BY product", (user_id,),
    )
    products = {recipe.item_id for recipe in ctx.content.alchemy.values()}
    return {row["product"]: int(row["amount"]) for row in rows if row["product"] in products}


def _entries(ctx: Context, product: str):
    return sorted((entry for entry in ctx.content.pill_furnace_rewards.values()
                   if entry.product == product), key=lambda entry: entry.threshold)


def claim_id(product: str, threshold: int) -> str:
    return f"{CLAIM_PREFIX}{product}_{threshold}"


def _records(ctx: Context, user_id: str):
    return {row["quest_id"]: row for row in ctx.repo.conn.execute(
        "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, CLAIM_PREFIX + "*"),
    )}


def _available(ctx: Context, entry) -> bool:
    try:
        PillFurnaceReward.model_validate(entry.model_dump())
    except ValueError:
        return False
    return all(item_id in ctx.content.items for item_id in entry.items)


def _reward_text(ctx: Context, entry) -> str:
    if not _available(ctx, entry):
        return "奖励暂不可用"
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in entry.items.items())
    return "、".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠丹炉赏；领取请用 灵宠丹炉领奖 丹药名 档位。")
    registered = ctx.repo.player(ctx.user_id) is not None
    counts = _counts(ctx, ctx.user_id) if registered else {}
    records = _records(ctx, ctx.user_id) if registered else {}
    lines = ["按每种丹药成功结丹的炉数累计；单份、双份都计一炉，毁丹与弃炉不计。"]
    links = []
    for product in dict.fromkeys(recipe.item_id for recipe in ctx.content.alchemy.values()):
        name, count = ctx.content.items[product].name, counts.get(product, 0)
        lines.append(f"{name} · 成功 {count} 炉")
        for entry in _entries(ctx, product):
            record = records.get(claim_id(product, entry.threshold))
            if record is not None:
                status = "已领取" if record["claimed"] else "领取记录异常"
            elif not registered:
                status = "未结契"
            elif count < entry.threshold:
                status = f"还差 {entry.threshold - count} 炉"
            else:
                status = "可领取"
            lines.append(f"{entry.threshold} 炉 · {entry.name} · {_reward_text(ctx, entry)} · {status}")
            if status == "可领取" and _available(ctx, entry):
                links.append(InlineCommand(len(lines) - 1, "领取成品赏",
                                           f"灵宠丹炉领奖 {name} {entry.threshold}"))
    if not registered:
        lines.append("尚未结契，先领养伙伴，再准备丹材开炉。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), ("灵宠丹炉", "灵宠背包", "灵宠帮助 血脉与道具"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠丹炉领奖 丹药名 档位，例如 灵宠丹炉领奖 回元丹 1。")
    products = {recipe.item_id: ctx.content.items[recipe.item_id] for recipe in ctx.content.alchemy.values()}
    product = named(products, parts[0])
    threshold = quantity(parts[1], 99)
    entry = next((entry for entry in _entries(ctx, product.id) if entry.threshold == threshold), None)
    if entry is None:
        raise GameError("该丹药没有此档成品赏，请查看 灵宠丹炉赏。")
    player = ctx.player()
    key = claim_id(product.id, threshold)
    record = _records(ctx, player.user_id).get(key)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"{product.name} {threshold} 炉奖励已经领取。")
        raise GameError("丹炉奖励领取记录异常，请联系管理员检查存档。")
    count = _counts(ctx, player.user_id).get(product.id, 0)
    if count < threshold:
        raise GameError(f"{product.name} 成功 {count} 炉，尚未达到 {threshold} 炉。")
    if not _available(ctx, entry):
        raise GameError("奖励定义暂不可用，本次未领取；请稍后再试。")
    reward = Reward(exp=Range(minimum=0, maximum=0),
                    stones=Range(minimum=entry.stones, maximum=entry.stones),
                    items={item_id: Range(minimum=amount, maximum=amount)
                           for item_id, amount in entry.items.items()})
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, key, count),
    )
    return Reply(TITLE, (f"{product.name}「{entry.name}」已领取 · 成功 {count} 炉。", *result),
                 ("灵宠丹炉赏", "灵宠背包", "灵宠丹炉"))


def objective_line(ctx: Context, user_id: str) -> str:
    counts, records = _counts(ctx, user_id), _records(ctx, user_id)
    pending = sum(counts.get(entry.product, 0) >= entry.threshold
                  and claim_id(entry.product, entry.threshold) not in records
                  and _available(ctx, entry) for entry in ctx.content.pill_furnace_rewards.values())
    return f"丹炉成品赏：成功 {sum(counts.values())} 炉 · 可领 {pending} 档"
