"""Alchemy consumes fixed materials and stones for a known yield of pills."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import item_amount, named
from . import counters

KEY = "alchemy_"


def recipes(ctx: Context):
    return sorted(ctx.content.alchemy.values(), key=lambda entry: entry.stones)


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def cost_text(ctx: Context, entry) -> str:
    materials = "、".join(
        f"{ctx.content.items[item_id].name} ×{amount}" for item_id, amount in entry.materials.items()
    )
    return f"{materials} · 灵石 {entry.stones}"


def effect_text(ctx: Context, entry) -> str:
    effects = ctx.content.items[entry.item_id].effects
    parts = []
    if effects.energy:
        parts.append(f"精力 +{effects.energy}")
    if effects.exp:
        parts.append(f"修为 +{effects.exp}")
    if effects.affinity:
        parts.append(f"亲密 +{effects.affinity}")
    if effects.breakthrough_bonus:
        parts.append(f"破境加成 +{int(effects.breakthrough_bonus * 100)}%")
    return " · ".join(parts) or "无额外效果"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠炼丹 [<丹方> [数量]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠炼丹",
            (
                "尚未结契，先完成领养，才能开炉炼丹。",
                "丹方消耗灵田作物与材料，炼出灵坊出售的丹药。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = ["炼丹消耗丹方所列材料与灵石；一次最多炼 10 份，材料不足时整笔拒绝。"]
    lines.append("缺少材料时，可进药山采集，返程所得也能播种或炼丹。")
    links = [InlineCommand(1, "进山采药", "灵宠采药")]
    lines.append("每日还可开一炉丹炉，按配伍争取双份丹药，也可能毁丹。")
    links.append(InlineCommand(len(lines) - 1, "预览丹炉", "灵宠丹炉"))
    for entry in recipes(ctx):
        product = ctx.content.items[entry.item_id]
        lines.append(
            f"{entry.name} → {product.name} ×{entry.yield_} · {effect_text(ctx, entry)}"
            f" · 每份 {cost_text(ctx, entry)}"
        )
        missing = [
            f"{ctx.content.items[item_id].name} 缺 {amount - _owned(ctx, item_id)}"
            for item_id, amount in entry.materials.items()
            if _owned(ctx, item_id) < amount
        ]
        if ctx.player().stones < entry.stones:
            missing.append(f"灵石 缺 {entry.stones - ctx.player().stones}")
        lines.append("  " + (f"暂不可炼：{'、'.join(missing)}" if missing else "材料齐备，可开炉"))
        if not missing:
            links.append(InlineCommand(len(lines) - 2, "炼丹", f"灵宠炼丹 {entry.name}"))
    return Reply("灵宠炼丹", tuple(lines), ("灵宠炼丹", "灵宠背包", "灵宠灵田"), tuple(links))


def brew(ctx: Context, arg: str) -> Reply:
    name, amount = item_amount(arg)
    player = ctx.player()
    entry = named(ctx.content.alchemy, name)
    cost = entry.stones * amount
    if player.stones < cost:
        raise GameError(f"灵石不足：炼 {amount} 份{entry.name}需要 {cost}，当前 {player.stones}。")
    short = [
        f"{ctx.content.items[item_id].name} {need * amount - _owned(ctx, item_id)}"
        for item_id, need in entry.materials.items()
        if _owned(ctx, item_id) < need * amount
    ]
    if short:
        raise GameError(f"材料不足：还需{'、'.join(short)}。")

    for item_id, need in entry.materials.items():
        ctx.repo.consume_item(ctx.user_id, item_id, need * amount)
    player.stones -= cost
    produced = entry.yield_ * amount
    ctx.repo.add_item(ctx.user_id, entry.item_id, produced)
    counters.bump(ctx, "alchemy_brews")
    product = ctx.content.items[entry.item_id]
    return Reply(
        "炼丹完成",
        (
            f"炼成 {product.name} ×{produced}：{amount} 份材料与 {cost} 灵石已消耗。",
            f"每份效果：{effect_text(ctx, entry)}。",
            f"当前持有 {product.name} {_owned(ctx, entry.item_id)} 个。",
        ),
        ("灵宠炼丹", "灵宠背包", f"灵宠使用 {product.name}"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else brew(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "炼丹：尚未结契"
    ready = sum(
        1 for entry in recipes(ctx)
        if all(_owned(ctx, item_id) >= amount for item_id, amount in entry.materials.items())
        and ctx.player(user_id).stones >= entry.stones
    )
    return f"炼丹：{ready} 种丹方可开炉" if ready else f"炼丹：可炼 {len(recipes(ctx))} 种丹方"
