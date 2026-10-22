from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import equipment_inventory

BASE_STONES = 150
STONES_PER_LEVEL = 60
ORE_PER_LEVEL = 2


def reforge_cost(enhancement: int) -> tuple[int, int]:
    """(stones, forge_ore) for a source at `enhancement`."""
    return BASE_STONES + enhancement * STONES_PER_LEVEL, enhancement * ORE_PER_LEVEL


def _catalog_order(ctx: Context, slot: str) -> list[str]:
    return [item_id for item_id, gear in ctx.content.equipment.items() if gear.slot == slot]


def _resolve(ctx: Context, arg: str):
    item = named(ctx.content.items, arg.strip())
    gear = ctx.content.equipment.get(item.id) if item.kind == "equipment" else None
    if gear is None:
        raise GameError("未找到该装备，请检查名称或编号。")
    return item, gear


def reforge_help(ctx: Context, arg: str) -> Reply:
    return Reply("装备重铸", (
        "把背包中的一件装备重铸为同部位的另一件 +0 装备。",
        f"费用：{BASE_STONES} 灵石基础 + 每级强化 {STONES_PER_LEVEL} 灵石与 {ORE_PER_LEVEL} 锻灵矿。",
        "示例：灵宠重铸 青岚翎",
    ), ("灵宠背包", "灵宠工坊"))


def reforge(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if not arg.strip():
        if player is None:
            return Reply("装备重铸", (
                "把背包中的一件装备重铸为同部位的另一件 +0 装备。",
                f"费用：{BASE_STONES} 灵石基础 + 每级强化 {STONES_PER_LEVEL} 灵石与 {ORE_PER_LEVEL} 锻灵矿。",
                "尚未结契，先完成领养。",
            ), ("灵宠帮助",), (InlineCommand(2, "开始领养", "灵宠领养 "),))
        return reforge_help(ctx, arg)
    item, gear = _resolve(ctx, arg)
    if player is None:
        raise GameError("尚未结契，先完成领养再重铸装备。")
    from . import equipment_inventory as inv
    enhancement = inv.highest_enhancement(ctx, item.id)
    stones, ore = reforge_cost(enhancement)
    if player.stones < stones:
        raise GameError(f"重铸需要 {stones} 灵石，当前灵石不足。")
    if ore:
        ore_row = ctx.repo.conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id='forge_ore'", (ctx.user_id,),
        ).fetchone()
        if ore_row is None or ore_row["quantity"] < ore:
            raise GameError(f"重铸需要 {ore} 锻灵矿，当前数量不足。")

    order = _catalog_order(ctx, gear.slot)
    if len(order) <= 1:
        raise GameError(f"该部位只有{item.name}一件装备，无法重铸。")
    index = order.index(item.id)
    target_id = order[(index + 1) % len(order)]
    target = ctx.content.equipment[target_id]
    if target_id == item.id:
        raise GameError(f"该部位没有其他装备可以重铸。")

    inv.take(ctx, item.id, enhancement, 1)
    player.stones -= stones
    if ore:
        ctx.repo.consume_item(ctx.user_id, "forge_ore", ore)
    inv.put(ctx, target_id, 0, 1)
    from .gear_words import roll as roll_words, describe as describe_words
    roll_words(ctx, target_id, 0)
    word_line = describe_words(ctx, target_id, 0)
    return Reply("装备重铸", (
        f"{item.name} +{enhancement} 已重铸为 {target.name} +0。",
        f"花费灵石 {stones}、锻灵矿 {ore}。",
        *([word_line] if word_line else []),
        "重铸后的装备可以在背包中穿戴或继续强化。",
    ), ("灵宠背包", "灵宠工坊", "灵宠装备"))
