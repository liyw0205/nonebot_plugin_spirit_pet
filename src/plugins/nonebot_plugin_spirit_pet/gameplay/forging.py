from ..application.context import Context
from ..domain.models import GameError, Reply
from .equipment import loadout, selected_slot


def enhance(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    ctx.require_idle_pet(pet)
    slot = selected_slot(ctx, pet.pet_id, arg)
    item_id, level = loadout(ctx, pet.pet_id)[slot]
    current = ctx.content.forge_levels[level]
    if current.upgrade_stones is None:
        raise GameError("该装备已达最高强化等级。")
    costs = [f"{current.upgrade_stones} 灵石"]
    costs.extend(f"{ctx.content.items[key].name} {amount}" for key, amount in current.upgrade_items.items())
    if player.stones < current.upgrade_stones:
        raise GameError(f"强化需要 {'、'.join(costs)}，灵石不足。")
    for key, amount in current.upgrade_items.items():
        ctx.repo.consume_item(ctx.user_id, key, amount)
    player.stones -= current.upgrade_stones
    ctx.repo.conn.execute(
        "UPDATE equipment SET enhancement=? WHERE pet_id=? AND slot=?", (level + 1, pet.pet_id, slot),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵物淬炼", (
        f"{pet.name}的{ctx.content.items[item_id].name}强化至 +{level + 1}。",
        f"消耗 {'、'.join(costs)}；装备属性倍率 {ctx.content.forge_levels[level + 1].bonus_multiplier:g}。",
    ), ("灵宠装备", "灵宠背包"))
