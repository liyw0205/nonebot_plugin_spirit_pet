from ..application.context import Context
from ..domain.models import GameError, Reply
from .equipment import loadout, selected_slot
from .pet_targets import named_pet, note_prep_change, split_selector


def enhance(ctx: Context, arg: str) -> Reply:
    """Raise the worn item one level, or straight to an optional target level.

    A target level is settled atomically: every step from the current level up to
    the target is priced from the forge ladder and charged in one transaction, so
    a shortfall leaves the equipment, stones and materials untouched.
    """
    player = ctx.player()
    body, who = split_selector(arg)
    pet = named_pet(ctx, who, "强化灵物") if who else ctx.pet()
    ctx.require_idle_pet(pet)
    parts = body.split()
    if len(parts) > 2:
        raise GameError("格式：灵宠强化 灵器 [目标等级] [伙伴 名字|编号]。")
    slot = selected_slot(ctx, pet.pet_id, parts[0] if parts else "")
    item_id, level = loadout(ctx, pet.pet_id)[slot]
    name = ctx.content.items[item_id].name
    maximum = len(ctx.content.forge_levels) - 1
    target = None
    if len(parts) == 2:
        if not parts[1].isdecimal() or not 1 <= int(parts[1]) <= maximum:
            raise GameError(f"目标等级须为 1-{maximum} 的整数。")
        target = int(parts[1])
        if target <= level:
            raise GameError(f"{name}当前 +{level}，目标等级须更高。")

    steps = []
    for step in range(level, target if target is not None else level + 1):
        current = ctx.content.forge_levels[step]
        if current.upgrade_stones is None:
            if target is None:
                raise GameError("该装备已达最高强化等级。")
            raise GameError(f"该装备最高只能强化到 +{step}。")
        steps.append(current)

    stones = sum(current.upgrade_stones for current in steps)
    materials: dict[str, int] = {}
    for current in steps:
        for key, amount in current.upgrade_items.items():
            materials[key] = materials.get(key, 0) + amount
    costs = [f"{stones} 灵石"]
    costs.extend(f"{ctx.content.items[key].name} {amount}" for key, amount in materials.items())
    if player.stones < stones:
        raise GameError(f"强化需要 {'、'.join(costs)}，灵石不足。")
    for key, amount in materials.items():
        ctx.repo.consume_item(ctx.user_id, key, amount)
    player.stones -= stones
    reached = level + len(steps)
    ctx.repo.conn.execute(
        "UPDATE equipment SET enhancement=? WHERE pet_id=? AND slot=?", (reached, pet.pet_id, slot),
    )
    note_prep_change(ctx, pet)
    return Reply("灵物淬炼", (
        f"{pet.name}的{name}强化至 +{reached}。",
        f"消耗 {'、'.join(costs)}；装备属性倍率 {ctx.content.forge_levels[reached].bonus_multiplier:g}。",
    ), ("灵宠装备", "灵宠背包"))
