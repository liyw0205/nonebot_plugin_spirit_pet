from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from .compatibility import check_requirements, requirement_text
from .equipment_inventory import highest_enhancement, put, take

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


def active_sets(ctx: Context, pet_id: int):
    equipped_ids = {
        ctx.content.items[item_id].equipment_id
        for item_id, _ in loadout(ctx, pet_id).values()
    }
    return tuple(
        equipment_set for equipment_set in ctx.content.equipment_sets.values()
        if set(equipment_set.items).issubset(equipped_ids)
    )


def _gear_item(ctx: Context, equipment_id: str):
    return next(item for item in ctx.content.items.values() if item.equipment_id == equipment_id)


def selected_slot(ctx: Context, pet_id: int, arg: str) -> str:
    items = equipped(ctx, pet_id)
    slot = next((key for key, label in SLOTS.items() if arg in {key, label}), None)
    if slot is None:
        slot = next((key for key, item in items.items() if arg == ctx.content.items[item].name), None)
    if slot not in items:
        raise GameError("该位置没有装备，请填写灵器、护甲、饰品或已装备名称。")
    return slot


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
    equipped_ids = {
        ctx.content.items[item_id].equipment_id for item_id, _ in items.values()
    }
    for equipment_set in ctx.content.equipment_sets.values():
        count = sum(equipment_id in equipped_ids for equipment_id in equipment_set.items)
        if count:
            state = "已激活" if count == len(equipment_set.items) else "未激活"
            lines.append(f"套装：{equipment_set.name} {count}/{len(equipment_set.items)} · {state}")
            if count == len(equipment_set.items):
                lines.append(
                    "套装加成：" + _bonus_text(equipment_set.bonuses.model_dump()) + "。"
                )
    return Reply(f"{pet.name}的装备", tuple(lines), (*commands, "灵宠套装", "灵宠装备图鉴", "灵宠商店"))


def catalog(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        gear = named(ctx.content.equipment, arg)
        item = next(item for item in ctx.content.items.values() if item.equipment_id == gear.id)
        commands = [f"灵宠工坊 {item.name}", f"灵宠装备 {item.name}"]
        if item.price is not None:
            commands.insert(0, f"灵宠购买 {item.name}")
        return Reply(f"灵物图鉴 · {gear.name}", (
            f"部位：{SLOTS[gear.slot]}。", f"适用：{requirement_text(ctx, gear.requirements)}。",
            f"基础加成：气血 +{gear.bonuses.hp} 攻击 +{gear.bonuses.attack}"
            f" 防御 +{gear.bonuses.defense} 速度 +{gear.bonuses.speed}。",
            f"灵坊售价：{item.price} 灵石。" if item.price is not None else "不在灵坊出售。",
        ), (*commands, "灵宠装备图鉴", "灵宠装备"))
    page = paginate(ctx.content.equipment.values(), arg, "灵物图鉴", "灵宠装备图鉴")
    return Reply(f"灵物图鉴 {page.number}/{page.total}", tuple(
        f"{gear.name} · {SLOTS[gear.slot]} · {requirement_text(ctx, gear.requirements)}"
        f" · 气血 +{gear.bonuses.hp} 攻击 +{gear.bonuses.attack}"
        f" 防御 +{gear.bonuses.defense} 速度 +{gear.bonuses.speed}"
        for gear in page.entries
    ), (*(f"灵宠装备图鉴 {gear.name}" for gear in page.entries), *page.navigation, "灵宠装备"))


def sets(ctx: Context, arg: str) -> Reply:
    from . import equipment_set_rewards

    player = ctx.repo.player(ctx.user_id)
    user_id = player.user_id if player else ctx.user_id
    active = equipment_set_rewards.active_set_ids(ctx, user_id)
    if arg and not arg.isdecimal():
        equipment_set = named(ctx.content.equipment_sets, arg)
        state = equipment_set_rewards.state(
            ctx, user_id, equipment_set.id, active, player is not None,
        )
        pet = ctx.repo.pet(player.active_pet_id) if player and player.active_pet_id is not None else None
        current = loadout(ctx, pet.pet_id) if pet else {}
        inventory = ctx.repo.inventory(user_id) if player else {}
        lines = [equipment_set.description, f"套件（需同一只灵宠装备 {len(equipment_set.items)} 件）："]
        links = []
        can_equip = pet is not None
        missing_parts = []
        incompatible_parts = []
        for equipment_id in equipment_set.items:
            gear = ctx.content.equipment[equipment_id]
            item = _gear_item(ctx, equipment_id)
            equipped = current.get(gear.slot)
            if pet is None:
                item_state = "尚未结契" if player is None else "无出战灵宠"
                compatible = False
                level = None
            elif equipped and equipped[0] == item.id:
                item_state, compatible, level = f"本宠已装备 +{equipped[1]}", True, equipped[1]
            else:
                try:
                    check_requirements(ctx, pet, gear.requirements)
                    compatible = True
                except GameError:
                    compatible = False
                level = _available_enhancement(ctx, user_id, item.id, inventory)
                if not compatible:
                    item_state = "当前宠物不适配"
                    incompatible_parts.append(item.name)
                elif level is None:
                    item_state = "背包缺少"
                    missing_parts.append(item.name)
                else:
                    item_state = f"背包可用 +{level}"
            if pet is not None and not compatible:
                can_equip = False
            if pet is not None and not (equipped and equipped[0] == item.id) and level is None:
                can_equip = False
            lines.append(f"{SLOTS[gear.slot]}：{item.name} · {item_state}。")
            line_index = len(lines) - 1
            links.append(InlineCommand(line_index, "查看装备", f"灵宠装备图鉴 {gear.name}"))
            if item.price is not None:
                links.append(InlineCommand(line_index, "查看灵坊", f"灵宠商店 {item.name}"))
            if any(recipe.item_id == item.id for recipe in ctx.content.recipes.values()):
                links.append(InlineCommand(line_index, "查看打造", f"灵宠工坊 {item.name}"))

        if pet is None:
            lines.append("装配状态：尚无可操作的出战灵宠。")
            can_equip = False
        elif equipment_set.id in active:
            lines.append(f"装配状态：{pet.name}已穿齐该套装。")
            can_equip = False
        elif ctx.repo.active_expedition(pet.pet_id) is not None:
            lines.append(f"装配状态：{pet.name}仍在行程中，暂不能穿戴。")
            can_equip = False
        elif missing_parts or incompatible_parts:
            issues = []
            if incompatible_parts:
                issues.append(f"不适配：{'、'.join(incompatible_parts)}")
            if missing_parts:
                issues.append(f"缺少：{'、'.join(missing_parts)}")
            lines.append(f"装配状态：{'；'.join(issues)}。")
        elif can_equip:
            lines.append(f"装配状态：可由{pet.name}一键穿戴。")
            links.append(InlineCommand(
                len(lines) - 1, "穿戴套装",
                f"灵宠套装穿戴 {pet.pet_id} {equipment_set.name}",
            ))
        else:
            lines.append("装配状态：当前出战灵宠不适配该套装。")

        lines.extend((
            f"套装加成：{_bonus_text(equipment_set.bonuses.model_dump())}。",
            f"首次完成奖励：{equipment_set_rewards.reward_text(ctx, equipment_set.id)} · {state}。",
        ))
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取奖励", f"灵宠套装领奖 {equipment_set.name}"))
        return Reply(
            f"装备套装 · {equipment_set.name}", tuple(lines),
            ("灵宠装备", "灵宠目标", "灵宠套装"), tuple(links),
        )
    page = paginate(ctx.content.equipment_sets.values(), arg, "装备套装", "灵宠套装")
    lines, links = [], []
    for equipment_set in page.entries:
        current_state = equipment_set_rewards.state(
            ctx, user_id, equipment_set.id, active, player is not None,
        )
        lines.append(
            f"{equipment_set.name} · {len(equipment_set.items)}件 · "
            f"{_bonus_text(equipment_set.bonuses.model_dump())} · "
            f"首次完成 {equipment_set_rewards.reward_text(ctx, equipment_set.id)} · {current_state}"
        )
        if current_state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励", f"灵宠套装领奖 {equipment_set.name}",
            ))
    commands = (
        *(f"灵宠套装 {equipment_set.name}" for equipment_set in page.entries),
        *page.navigation, "灵宠装备", "灵宠目标",
    )
    return Reply(f"装备套装 {page.number}/{page.total}", tuple(lines), commands, tuple(links))


def _bonus_text(bonuses: dict[str, int]) -> str:
    labels = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
    return " ".join(f"{labels[key]} +{value}" for key, value in bonuses.items() if value)


def _available_enhancement(
    ctx: Context, user_id: str, item_id: str, inventory: dict[str, int],
) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT MAX(enhancement) AS enhancement FROM unequipped_equipment "
        "WHERE user_id=? AND item_id=? AND quantity>0", (user_id, item_id),
    ).fetchone()
    if row["enhancement"] is not None:
        return int(row["enhancement"])
    return 0 if inventory.get(item_id, 0) > 0 else None


def wear_set(ctx: Context, arg: str) -> Reply:
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        raise GameError("格式：灵宠套装穿戴 宠物编号 套装名。")
    target_pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    equipment_set = named(ctx.content.equipment_sets, parts[1])
    player = ctx.player()
    if player.active_pet_id != target_pet_id:
        raise GameError("当前出战伙伴已变化，请重新打开套装详情后再穿戴。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    current = loadout(ctx, pet.pet_id)
    inventory = ctx.repo.inventory(player.user_id)
    plan = []

    # Validate every piece before moving any inventory or equipment row.
    for equipment_id in equipment_set.items:
        gear = ctx.content.equipment[equipment_id]
        item = _gear_item(ctx, equipment_id)
        check_requirements(ctx, pet, gear.requirements)
        equipped = current.get(gear.slot)
        if equipped and equipped[0] == item.id:
            continue
        enhancement = _available_enhancement(ctx, player.user_id, item.id, inventory)
        if enhancement is None:
            raise GameError(
                f"背包缺少{item.name}，请先查看 灵宠商店 {item.name} 或 灵宠工坊 {item.name}。"
            )
        plan.append((gear, item, enhancement, equipped))

    if not plan:
        raise GameError(f"{pet.name}已经穿齐「{equipment_set.name}」，无需重复穿戴。")

    for gear, item, enhancement, equipped in plan:
        take(ctx, item.id, enhancement)
        if equipped:
            put(ctx, *equipped)
        ctx.repo.conn.execute(
            "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(pet_id, slot) DO UPDATE SET item_id=excluded.item_id, enhancement=excluded.enhancement",
            (pet.pet_id, gear.slot, item.id, enhancement),
        )
    ctx.repo.invalidate_ready(player.user_id)
    lines = [f"{pet.name}已穿戴「{equipment_set.name}」。"]
    lines.extend(f"{SLOTS[gear.slot]}：{item.name} +{enhancement}" for gear, item, enhancement, _ in plan)
    lines.append("替换下的装备已返还背包；套装加成仅在同一只灵宠穿齐后生效。")
    return Reply("套装穿戴", tuple(lines), ("灵宠装备", f"灵宠套装 {equipment_set.name}", "灵宠目标"))


def equip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    item = named(ctx.content.items, arg)
    if item.kind != "equipment":
        raise GameError("该物品不是装备。")
    gear = ctx.content.equipment[item.equipment_id]
    check_requirements(ctx, pet, gear.requirements)
    current = loadout(ctx, pet.pet_id).get(gear.slot)
    enhancement = highest_enhancement(ctx, item.id)
    if current and current[0] == item.id and enhancement <= current[1]:
        raise GameError("该灵物已经装备。")
    take(ctx, item.id, enhancement)
    if current:
        put(ctx, *current)
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
    ctx.require_idle_pet(pet)
    slot = selected_slot(ctx, pet.pet_id, arg)
    item_id, enhancement = loadout(ctx, pet.pet_id)[slot]
    ctx.repo.conn.execute("DELETE FROM equipment WHERE pet_id=? AND slot=?", (pet.pet_id, slot))
    put(ctx, item_id, enhancement)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("卸下灵物", (f"{ctx.content.items[item_id].name} +{enhancement}已返回背包。",))
