from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .compatibility import check_requirements, requirement_text

SLOTS = {"weapon": "灵器", "armor": "护甲", "charm": "饰品"}


def equipped(ctx: Context, pet_id: int) -> dict[str, str]:
    return {slot: item_id for slot, (item_id, _) in loadout(ctx, pet_id).items()}


def loadout(ctx: Context, pet_id: int) -> dict[str, tuple[str, int]]:
    return {
        row["slot"]: (row["item_id"], row["enhancement"])
        for row in ctx.repo.conn.execute(
            "SELECT slot, item_id, enhancement FROM equipment WHERE pet_id=?", (pet_id,),
        )
    }


def selected_slot(ctx: Context, pet_id: int, arg: str) -> str:
    items = equipped(ctx, pet_id)
    slot = next((key for key, label in SLOTS.items() if arg in {key, label}), None)
    if slot is None:
        slot = next((key for key, item in items.items() if arg == ctx.content.items[item].name), None)
    if slot not in items:
        raise GameError("该位置没有装备，请填写灵器、护甲、饰品或已装备名称。")
    return slot


def _stored_enhancement(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT MAX(enhancement) AS enhancement FROM unequipped_equipment "
        "WHERE user_id=? AND item_id=? AND quantity>0", (ctx.user_id, item_id),
    ).fetchone()
    return row["enhancement"] or 0


def _take_item(ctx: Context, item_id: str, enhancement: int) -> None:
    if not enhancement:
        ctx.repo.consume_item(ctx.user_id, item_id, 1)
        return
    updated = ctx.repo.conn.execute(
        "UPDATE unequipped_equipment SET quantity=quantity-1 "
        "WHERE user_id=? AND item_id=? AND enhancement=? AND quantity>0",
        (ctx.user_id, item_id, enhancement),
    )
    if updated.rowcount != 1:
        raise GameError("道具数量不足。")


def _return_item(ctx: Context, item_id: str, enhancement: int) -> None:
    if not enhancement:
        ctx.repo.add_item(ctx.user_id, item_id, 1)
        return
    ctx.repo.conn.execute(
        "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, item_id, enhancement) DO UPDATE SET quantity=quantity+1",
        (ctx.user_id, item_id, enhancement),
    )


def view(ctx: Context, arg: str) -> Reply:
    if arg:
        return equip(ctx, arg)
    pet = ctx.pet()
    items = loadout(ctx, pet.pet_id)
    lines, commands = [], []
    for slot, label in SLOTS.items():
        if slot not in items:
            lines.append(f"{label}：未装备")
            continue
        item_id, level = items[slot]
        item = ctx.content.items[item_id]
        gear = ctx.content.equipment[item.equipment_id]
        forge = ctx.content.forge_levels[level]
        bonuses = {key: int(value * forge.bonus_multiplier) for key, value in gear.bonuses.model_dump().items()}
        lines.append(
            f"{label}：{item.name} +{level} · 气血 +{bonuses['hp']} 攻击 +{bonuses['attack']}"
            f" 防御 +{bonuses['defense']} 速度 +{bonuses['speed']}"
        )
        if forge.upgrade_stones is None:
            lines.append("强化：已满级。")
            continue
        costs = [f"{forge.upgrade_stones} 灵石"]
        costs.extend(f"{ctx.content.items[key].name} {amount}" for key, amount in forge.upgrade_items.items())
        lines.append(f"强化至 +{level + 1}：{'、'.join(costs)}。")
        commands.append(f"灵宠强化 {label}")
    return Reply(f"{pet.name}的装备", tuple(lines), (*commands, "灵宠装备图鉴", "灵宠商店"))


def catalog(ctx: Context, arg: str) -> Reply:
    return Reply("灵物图鉴", tuple(
        f"{gear.name} · {SLOTS[gear.slot]} · {requirement_text(ctx, gear.requirements)}"
        f" · 气血 +{gear.bonuses.hp} 攻击 +{gear.bonuses.attack}"
        f" 防御 +{gear.bonuses.defense} 速度 +{gear.bonuses.speed}"
        for gear in ctx.content.equipment.values()
    ), ("灵宠商店", "灵宠装备"))


def equip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    item = named(ctx.content.items, arg)
    if item.kind != "equipment":
        raise GameError("该物品不是装备。")
    gear = ctx.content.equipment[item.equipment_id]
    check_requirements(ctx, pet, gear.requirements)
    current = loadout(ctx, pet.pet_id).get(gear.slot)
    enhancement = _stored_enhancement(ctx, item.id)
    if current and current[0] == item.id and enhancement <= current[1]:
        raise GameError("该灵物已经装备。")
    _take_item(ctx, item.id, enhancement)
    if current:
        _return_item(ctx, *current)
    ctx.repo.conn.execute(
        "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(pet_id, slot) DO UPDATE SET item_id=excluded.item_id, enhancement=excluded.enhancement",
        (pet.pet_id, gear.slot, item.id, enhancement),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("装备灵物", (
        f"{pet.name}装备了{item.name} +{enhancement}，占用{SLOTS[gear.slot]}位。",
        "替换下的旧装备已返回背包。" if current else "装备期间该灵物不在背包中。",
    ))


def unequip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    slot = selected_slot(ctx, pet.pet_id, arg)
    item_id, enhancement = loadout(ctx, pet.pet_id)[slot]
    ctx.repo.conn.execute("DELETE FROM equipment WHERE pet_id=? AND slot=?", (pet.pet_id, slot))
    _return_item(ctx, item_id, enhancement)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("卸下灵物", (f"{ctx.content.items[item_id].name} +{enhancement}已返回背包。",))
