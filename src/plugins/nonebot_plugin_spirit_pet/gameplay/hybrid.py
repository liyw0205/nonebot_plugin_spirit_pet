"""Seed hybridisation: fuse two different seeds into a seed that shops never sell.

Every crop in the game is either bought or dropped, so surplus seeds of the cheap tiers pile up with
nothing to do once the player unlocks better ones. A hybrid recipe consumes one seed of each of two
different crops plus stones and produces a seed that cannot be bought — the only way to reach the
frost-wheat and crimson-lotus lines is to spend the low tiers on them.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named

KEY = "hybrid_"


def recipes(ctx: Context):
    return sorted(ctx.content.hybrids.values(), key=lambda recipe: recipe.stones)


def recipe(ctx: Context, arg: str):
    return named(ctx.content.hybrids, arg)


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def cost_text(ctx: Context, entry) -> str:
    seeds = "、".join(f"{ctx.content.items[seed].name} ×1" for seed in entry.seeds)
    return f"{seeds} · 灵石 {entry.stones}"


def yield_text(ctx: Context, entry) -> str:
    crop = next(crop for crop in ctx.content.crops.values() if crop.seed_item == entry.output)
    parts = [f"{crop.duration} 秒成熟"]
    if crop.reward_exp:
        parts.append(f"修为 {crop.reward_exp}")
    if crop.reward_stones:
        parts.append(f"灵石 {crop.reward_stones}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}-{bounds.maximum}"
        for item_id, bounds in crop.reward_items.items()
    )
    return "、".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠杂交 [<配方>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠杂交",
            (
                "尚未结契，先完成领养，才能调配种子。",
                "杂交会消耗两种不同的种子与灵石，产出商店买不到的新种子。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = ["杂交消耗每种配方指定的两种种子各 1 个，另付灵石；产物只能靠杂交获得。"]
    links = []
    for entry in recipes(ctx):
        crop = next(crop for crop in ctx.content.crops.values() if crop.seed_item == entry.output)
        lines.append(
            f"{entry.name} · {cost_text(ctx, entry)} · 产出 {ctx.content.items[entry.output].name}"
            f"（{yield_text(ctx, entry)}）"
        )
        short = [
            f"{ctx.content.items[seed].name} 缺 {1 - _owned(ctx, seed)}"
            for seed in entry.seeds
            if _owned(ctx, seed) < 1
        ]
        if ctx.player().stones < entry.stones:
            short.append(f"灵石 缺 {entry.stones - ctx.player().stones}")
        lines.append("  " + (f"暂不可配：{'、'.join(short)}" if short else "材料齐备，可调配"))
        if not short:
            links.append(InlineCommand(len(lines) - 2, "杂交", f"灵宠杂交 {entry.name}"))
    return Reply("灵宠杂交", tuple(lines), ("灵宠杂交", "灵宠灵田", "灵宠背包"), tuple(links))


def brew(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠杂交 <配方>。")
    player = ctx.player()
    entry = recipe(ctx, text)
    missing = [
        f"{ctx.content.items[seed].name} ×1"
        for seed in entry.seeds
        if _owned(ctx, seed) < 1
    ]
    if missing:
        raise GameError(f"种子不足：还需要{'、'.join(missing)}。")
    if player.stones < entry.stones:
        raise GameError(f"灵石不足：杂交需要 {entry.stones}，当前 {player.stones}。")

    for seed in entry.seeds:
        ctx.repo.consume_item(ctx.user_id, seed, 1)
    player.stones -= entry.stones
    ctx.repo.add_item(ctx.user_id, entry.output, 1)
    output = ctx.content.items[entry.output]
    return Reply(
        "杂交完成",
        (
            f"{entry.name}调配成功：{cost_text(ctx, entry)}已消耗，得到 {output.name} ×1。",
            f"播种后{yield_text(ctx, entry)}。",
            "杂交产物不在灵坊出售，只能靠调配获得。",
        ),
        ("灵宠杂交", "灵宠灵田", "灵宠播种 1 " + output.name),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else brew(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "杂交：尚未结契"
    ready = 0
    for entry in recipes(ctx):
        if all(_owned(ctx, seed) >= 1 for seed in entry.seeds) and ctx.player(user_id).stones >= entry.stones:
            ready += 1
    return f"杂交：{ready} 种配方可调配" if ready else f"杂交：可配 {len(recipes(ctx))} 种配方"
