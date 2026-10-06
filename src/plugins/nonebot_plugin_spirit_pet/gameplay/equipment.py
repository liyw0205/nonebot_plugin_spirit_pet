from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .compatibility import check_requirements, requirement_text

SLOTS = {"weapon": "灵器", "armor": "护甲", "charm": "饰品"}


def equipped(ctx: Context, pet_id: int) -> dict[str, str]:
    return dict(ctx.repo.conn.execute("SELECT slot, item_id FROM equipment WHERE pet_id=?", (pet_id,)))


def view(ctx: Context, arg: str) -> Reply:
    if arg:
        return equip(ctx, arg)
    pet = ctx.pet()
    items = equipped(ctx, pet.pet_id)
    return Reply(f"{pet.name}的装备", tuple(
        f"{label}：{ctx.content.items[items[slot]].name if slot in items else '未装备'}"
        for slot, label in SLOTS.items()
    ), ("灵宠装备图鉴", "灵宠商店"))


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
    current = equipped(ctx, pet.pet_id).get(gear.slot)
    if current == item.id:
        raise GameError("该灵物已经装备。")
    ctx.repo.consume_item(ctx.user_id, item.id, 1)
    if current:
        ctx.repo.add_item(ctx.user_id, current, 1)
    ctx.repo.conn.execute(
        "INSERT INTO equipment VALUES (?, ?, ?) ON CONFLICT(pet_id, slot) DO UPDATE SET item_id=excluded.item_id",
        (pet.pet_id, gear.slot, item.id),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("装备灵物", (
        f"{pet.name}装备了{item.name}，占用{SLOTS[gear.slot]}位。",
        "替换下的旧装备已返回背包。" if current else "装备期间该灵物不在背包中。",
    ))


def unequip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    items = equipped(ctx, pet.pet_id)
    slot = next((key for key, label in SLOTS.items() if arg in {key, label}), None)
    if slot is None:
        slot = next((key for key, item in items.items() if arg == ctx.content.items[item].name), None)
    if slot not in items:
        raise GameError("该位置没有装备，请填写灵器、护甲、饰品或已装备名称。")
    item_id = items[slot]
    ctx.repo.conn.execute("DELETE FROM equipment WHERE pet_id=? AND slot=?", (pet.pet_id, slot))
    ctx.repo.add_item(ctx.user_id, item_id, 1)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("卸下灵物", (f"{ctx.content.items[item_id].name}已返回背包。",))
