from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .equipment_inventory import highest_enhancement, put, take

SLOT_NAMES = {"weapon": "灵器", "armor": "护甲", "charm": "饰品"}


def _equipment(ctx: Context, value: str):
    item = named(ctx.content.items, value)
    if item.kind != "equipment" or item.equipment_id is None:
        raise GameError(f"{item.name}不是装备灵物，无法继承强化。")
    return item


def _slot(ctx: Context, item) -> str:
    return ctx.content.equipment[item.equipment_id].slot


def _bag_quantity(ctx: Context, item_id: str, enhancement: int) -> int:
    if enhancement == 0:
        return ctx.repo.inventory(ctx.user_id).get(item_id, 0)
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM unequipped_equipment WHERE user_id=? AND item_id=? AND enhancement=?",
        (ctx.user_id, item_id, enhancement),
    ).fetchone()
    return row["quantity"] if row else 0


def cost(ctx: Context, level: int) -> tuple[int, dict[str, int]]:
    """Inheritance costs scale with the source's enhancement level."""
    rule = ctx.content.rules.inheritance_cost
    return rule.stones * level, {key: amount * level for key, amount in rule.items.items()}


def _cost_text(ctx: Context, stones: int, items: dict[str, int]) -> str:
    parts = [f"{stones} 灵石"]
    parts.extend(f"{ctx.content.items[key].name} {amount}" for key, amount in items.items())
    return "、".join(parts)


def inherit(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠强化继承 源装备 目标装备，例如 灵宠强化继承 青岚翎 灵心铃。")
    source, target = _equipment(ctx, parts[0]), _equipment(ctx, parts[1])
    if source.id == target.id:
        raise GameError("继承需要两件不同的装备。")
    source_slot, target_slot = _slot(ctx, source), _slot(ctx, target)
    if source_slot != target_slot:
        raise GameError(
            f"继承双方必须是同一部位：{source.name}是{SLOT_NAMES[source_slot]}，"
            f"{target.name}是{SLOT_NAMES[target_slot]}。"
        )
    # The source is the highest enhanced copy in the bag; the target must be a fresh +0 copy.
    level = highest_enhancement(ctx, source.id)
    if level == 0 or _bag_quantity(ctx, source.id, level) < 1:
        raise GameError(f"背包内没有强化过的{source.name}，无法继承。")
    if highest_enhancement(ctx, target.id) > 0:
        raise GameError(f"{target.name}已有强化等级，请改用未强化的同部位装备作为目标。")
    if _bag_quantity(ctx, target.id, 0) < 1:
        raise GameError(f"背包内没有未强化的{target.name}。")

    stones, items = cost(ctx, level)
    inventory = ctx.repo.inventory(ctx.user_id)
    if player.stones < stones or any(inventory.get(key, 0) < amount for key, amount in items.items()):
        raise GameError(f"继承需要 {_cost_text(ctx, stones, items)}。")
    for key, amount in items.items():
        ctx.repo.consume_item(ctx.user_id, key, amount)
    player.stones -= stones
    take(ctx, source.id, level, 1)
    put(ctx, source.id, 0, 1)
    take(ctx, target.id, 0, 1)
    put(ctx, target.id, level, 1)
    return Reply("强化继承完成", (
        f"{source.name}的 +{level} 已继承给{target.name}。",
        f"{source.name}回到 +0，{target.name}变为 +{level}。",
        f"消耗 {_cost_text(ctx, stones, items)}。",
    ), ("灵宠装备", "灵宠背包", "灵宠工坊"))
