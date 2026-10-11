import re

from ..application.context import Context
from ..domain.crafting_content import Recipe, salvage_yield
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import item_amount, named, quantity
from .equipment_inventory import put, take


def _materials(ctx: Context, materials: dict[str, int], amount: int = 1) -> str:
    return "、".join(f"{ctx.content.items[key].name} {count * amount}" for key, count in materials.items())


def _enhancement(ctx: Context, value: str) -> int:
    if not re.fullmatch(r"\+[0-9]{1,2}", value) or int(value[1:]) not in ctx.content.forge_levels:
        raise GameError(f"强化等级须为 +0 至 +{max(ctx.content.forge_levels)}。")
    return int(value[1:])


def _detail(ctx: Context, recipe: Recipe, level: int) -> Reply:
    maximum = max(ctx.content.forge_levels)
    return Reply(f"百工灵谱 · {recipe.name}", (
        f"打造一件 +0：{recipe.stones} 灵石、{_materials(ctx, recipe.materials)}。",
        f"分解一件 +{level}：{_materials(ctx, salvage_yield(recipe, ctx.content.forge_levels, level))}。",
        f"基础回收：{_materials(ctx, recipe.salvage_materials)}；强化材料回收累计投入的"
        f" {recipe.enhancement_refund_percent}%（每种材料向下取整），最多按 +{maximum} 累计投入计算。",
        "分解仅消耗背包装备，不返还打造或强化灵石。",
    ), (f"灵宠打造 {recipe.name}", f"灵宠分解 {recipe.name} +{level}", "灵宠工坊", "灵宠背包"), (
        InlineCommand(0, "查看装备属性", f"灵宠装备图鉴 {recipe.name}"),
    ))


def catalog(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        parts = arg.split()
        if not 1 <= len(parts) <= 2:
            raise GameError("格式：灵宠工坊 装备名称 [+强化等级]。")
        recipe = named(ctx.content.recipes, parts[0])
        return _detail(ctx, recipe, _enhancement(ctx, parts[1]) if len(parts) == 2 else 0)
    recipes = list(ctx.content.recipes.values())
    page = quantity(arg or "1", 999)
    pages = (len(recipes) + 4) // 5
    if page > pages:
        raise GameError(f"百工灵谱共 {pages} 页。")
    selected = recipes[(page - 1) * 5:page * 5]
    lines = tuple(
        f"{recipe.name} · {recipe.stones} 灵石、{_materials(ctx, recipe.materials)}"
        f" · +0分解回收 {_materials(ctx, recipe.salvage_materials)}"
        for recipe in selected
    )
    commands = [f"灵宠工坊 {recipe.name}" for recipe in selected]
    if page > 1:
        commands.append(f"灵宠工坊 {page - 1}")
    if page < pages:
        commands.append(f"灵宠工坊 {page + 1}")
    return Reply(f"百工灵谱 {page}/{pages}", lines, tuple(commands))


def craft(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    name, amount = item_amount(arg)
    recipe = named(ctx.content.recipes, name)
    cost = recipe.stones * amount
    if player.stones < cost:
        raise GameError(f"打造需要 {cost} 灵石，当前灵石不足。")
    for key, count in recipe.materials.items():
        ctx.repo.consume_item(ctx.user_id, key, count * amount)
    player.stones -= cost
    put(ctx, recipe.item_id, 0, amount)
    return Reply("百工铸灵", (
        f"{recipe.name} +0 获得 {amount} 件，已放入背包。",
        f"消耗 {cost} 灵石、{_materials(ctx, recipe.materials, amount)}。",
    ), (f"灵宠装备 {recipe.name}", "灵宠背包", f"灵宠工坊 {recipe.name}"))


def salvage(ctx: Context, arg: str) -> Reply:
    ctx.player()
    parts = arg.split()
    if not 1 <= len(parts) <= 3:
        raise GameError("格式：灵宠分解 装备名称 [+强化等级] [数量]；不写等级只分解 +0。")
    recipe = named(ctx.content.recipes, parts[0])
    level, amount, tail = 0, 1, parts[1:]
    if tail and tail[0].startswith("+"):
        level = _enhancement(ctx, tail.pop(0))
    if len(tail) > 1:
        raise GameError("格式：灵宠分解 装备名称 [+强化等级] [数量]。")
    if tail:
        amount = quantity(tail[0])
    returned = salvage_yield(recipe, ctx.content.forge_levels, level)
    try:
        take(ctx, recipe.item_id, level, amount)
    except GameError:
        raise GameError(
            f"背包中的{recipe.name} +{level}数量不足；已穿戴装备不会被分解，强化件需显式填写 +等级。"
        ) from None
    for key, count in returned.items():
        ctx.repo.add_item(ctx.user_id, key, count * amount)
    return Reply("灵物归元", (
        f"已分解背包中的{recipe.name} +{level}，共 {amount} 件。",
        f"回收 {_materials(ctx, returned, amount)}；不返还灵石。",
    ), ("灵宠背包", f"灵宠工坊 {recipe.name} +{level}"))
