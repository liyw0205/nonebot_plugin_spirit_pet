from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import item_amount, named
from ..utils.energy import add_energy, restore_energy
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .pet_targets import selected_pet
from .quests import advance
from .rewards import grant
from . import checkin_rewards


def sign(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    today = beijing_day(ctx.now)
    if player.sign_day >= today:
        raise GameError("今日已领取仙缘，明日再来。（每日北京时间 00:00 刷新）")
    previous_sign_day = player.sign_day
    player.sign_day = today
    advance(ctx, "sign")
    streak, best = checkin_rewards.record_sign(ctx, player, previous_sign_day)
    next_milestone = next((days for days, _, _, _ in checkin_rewards.MILESTONES if days > streak), None)
    reward_lines = grant(ctx, ctx.content.rules.daily_reward)
    streak_line = len(reward_lines)
    lines = [*reward_lines, f"连续签到：当前 {streak} 天 · 历史最佳 {best} 天。"]
    if next_milestone is not None:
        lines.append(f"下一里程碑：连续 {next_milestone} 天。")
    elif any(not checkin_rewards._claimed(ctx, player.user_id, days) for days, _, _, _ in checkin_rewards.MILESTONES):
        lines.append("所有连续签到里程碑均已达成，可前往领取。")
    return Reply("今日仙缘", tuple(lines), inline_commands=(
        InlineCommand(streak_line, "查看奖励", "灵宠签到奖励"),
    ))


def _active_pet_or_none(ctx: Context):
    """The active pet with the same energy refresh `Context.pet` applies, or None."""
    player = ctx.player()
    if player.active_pet_id is None:
        return None
    pet = ctx.repo.pet(player.active_pet_id)
    if pet.archived:
        return None
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    return pet


def _recovery_available(effects, pet) -> bool:
    return bool(effects.exp) or (bool(effects.energy) and pet.energy < 100) or (
        bool(effects.affinity) and pet.affinity < 100
    )


def _can_use(ctx: Context, item) -> bool:
    """Mirror `_use_consumable`'s guard so no surface offers a rejected action."""
    pet = _active_pet_or_none(ctx)
    if pet is None or ctx.repo.active_expedition(pet.pet_id) is not None:
        return False
    return _recovery_available(item.effects, pet)


def _has_roster_room(ctx: Context) -> bool:
    return len(ctx.repo.owned_pets(ctx.user_id)) + 1 <= ctx.config.spirit_pet_max_pets


def _item_steps(ctx: Context, item) -> tuple[str, ...]:
    """The runnable follow-up for a held item, or empty when nothing is safe to offer."""
    if item.kind == "consumable":
        if item.id == "spirit_food":
            return ("灵宠喂养",) if _can_use(ctx, item) else ()
        return (f"灵宠使用 {item.name} 1",) if _can_use(ctx, item) else ()
    if item.kind == "pet_egg":
        return (f"灵宠使用 {item.name} 1",) if _has_roster_room(ctx) else ()
    if item.kind == "equipment":
        return (f"灵宠装备图鉴 {ctx.content.equipment[item.equipment_id].name}",)
    if item.kind == "skill_book":
        return (f"灵宠技能图鉴 {ctx.content.skills[item.skill_id].name}",)
    return ()


_BAG_GROUPS = (
    ("消耗品", ("consumable",)),
    ("灵卵", ("pet_egg",)),
    ("装备灵物", ("equipment",)),
    ("灵术秘笈", ("skill_book",)),
    ("材料与丹药", ("material", "breakthrough")),
)
_BAG_LABELS = {
    "consumable": "使用", "pet_egg": "孵化", "equipment": "装备图鉴", "skill_book": "灵术图鉴",
}


def _bag_label(item, step: str) -> str:
    return "喂养" if step.startswith("灵宠喂养") else _BAG_LABELS[item.kind]


def bag(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    inventory = ctx.repo.inventory(ctx.user_id)
    reinforced = ctx.repo.conn.execute(
        "SELECT item_id, enhancement, quantity FROM unequipped_equipment "
        "WHERE user_id=? AND quantity>0 ORDER BY item_id, enhancement DESC", (ctx.user_id,),
    ).fetchall()
    lines = [f"灵石：{player.stones}"]
    links = []
    # Grouped by kind with each row's purpose, so the bag explains what is held and
    # links the one next step that the business layer would actually accept.
    for title, kinds in _BAG_GROUPS:
        entries = [
            (ctx.content.items[key], value) for key, value in inventory.items()
            if ctx.content.items[key].kind in kinds
        ]
        if not entries:
            continue
        lines.append(title)
        for item, amount in entries:
            lines.append(f"{item.name}：{amount} · {item.description}")
            steps = _item_steps(ctx, item)
            if steps:
                links.append(InlineCommand(len(lines) - 1, _bag_label(item, steps[0]), steps[0]))
    if reinforced:
        lines.append("强化装备")
        for row in reinforced:
            item = ctx.content.items[row["item_id"]]
            lines.append(f"{item.name} +{row['enhancement']}：{row['quantity']} · {item.description}")
            links.append(InlineCommand(
                len(lines) - 1, "装备图鉴",
                f"灵宠装备图鉴 {ctx.content.equipment[item.equipment_id].name}",
            ))
    if len(lines) == 1:
        lines.append("乾坤袋空空如也，先去灵坊看看。")
    return Reply("乾坤袋", tuple(lines), ("灵宠商店", "灵宠喂养", "灵宠进化"), tuple(links))


def shop(ctx: Context, arg: str) -> Reply:
    available = {key: item for key, item in ctx.content.items.items() if item.price is not None}
    if arg and not arg.isdecimal():
        item = named(available, arg)
        commands = [f"灵宠购买 {item.name}"]
        if item.kind == "equipment":
            gear = ctx.content.equipment[item.equipment_id]
            commands.extend((f"灵宠装备图鉴 {gear.name}", f"灵宠工坊 {item.name}"))
            links = (
                InlineCommand(1, "查看装备图鉴", f"灵宠装备图鉴 {gear.name}"),
                InlineCommand(1, "查看打造配方", f"灵宠工坊 {item.name}"),
            )
        elif item.kind == "skill_book":
            skill_name = ctx.content.skills[item.skill_id].name
            commands.append(f"灵宠技能图鉴 {skill_name}")
            links = (InlineCommand(1, "查看灵术图鉴", f"灵宠技能图鉴 {skill_name}"),)
        else:
            links = ()
        return Reply(f"山海灵坊 · {item.name}", (
            f"售价：{item.price} 灵石。", item.description,
        ), (*commands, "灵宠商店", "灵宠背包"), links)
    page = paginate(available.values(), arg, "山海灵坊", "灵宠商店")
    lines = tuple(
        f"{item.name}：{item.price} 灵石 · {item.description}"
        for item in page.entries
    )
    # Each row links its own detail; the row command leaves the button set, so every
    # listed item stays reachable under the four-button cap.
    links = tuple(
        InlineCommand(index, "查看详情", f"灵宠商店 {item.name}")
        for index, item in enumerate(page.entries)
    )
    return Reply(
        f"山海灵坊 {page.number}/{page.total}", lines, (*page.navigation, "灵宠背包"), links,
    )


def buy(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    name, amount = item_amount(arg)
    item = named(ctx.content.items, name)
    if item.price is None:
        raise GameError("该道具不在商店出售。")
    cost = item.price * amount
    if player.stones < cost:
        raise GameError("灵石不足。")
    player.stones -= cost
    ctx.repo.add_item(ctx.user_id, item.id, amount)
    return Reply("灵坊购得", (f"{item.name} +{amount}，灵石 -{cost}。",), (
        "灵宠背包", *_item_steps(ctx, item), "灵宠商店",
    ))


def recycle(ctx: Context, arg: str) -> Reply:
    """Turn surplus items back into stones at the shop-recycle rate."""
    player = ctx.player()
    name, amount = item_amount(arg)
    item = named(ctx.content.items, name)
    if item.kind == "equipment":
        raise GameError("装备请用 灵宠分解 回收材料。")
    if item.price is None:
        raise GameError("该道具不在灵坊出售，无法回收。")
    percent = ctx.content.rules.recycle_percent
    stones = item.price * amount * percent // 100
    if stones <= 0:
        raise GameError(f"回收 {amount} 个{item.name}不足 1 灵石，请一次回收更多。")
    ctx.repo.consume_item(ctx.user_id, item.id, amount)
    player.stones += stones
    return Reply("灵坊回收", (
        f"{item.name} -{amount}，灵石 +{stones}。",
        f"回收价为售价的 {percent}%；当前灵石 {player.stones}。",
    ), ("灵宠背包", "灵宠商店", "灵宠装备"))


def use(ctx: Context, arg: str) -> Reply:
    name, amount = item_amount(arg)
    item = named(ctx.content.items, name)
    if item.kind == "pet_egg":
        from .hatching import hatch

        return hatch(ctx, item, amount)
    if item.kind != "consumable":
        raise GameError("材料用于进化；破境丹用于突破；装备与秘笈请用灵宠装备、灵宠学习。")
    pet = ctx.pet()
    return _use_consumable(ctx, item, amount, pet)


def _use_consumable(ctx: Context, item, amount: int, pet) -> Reply:
    ctx.require_idle_pet(pet)
    effects = item.effects
    if not effects.exp and (not effects.energy or pet.energy == 100) and (
        not effects.affinity or pet.affinity == 100
    ):
        raise GameError("当前属性已满，无需消耗该道具。")
    ctx.repo.consume_item(ctx.user_id, item.id, amount)
    energy = add_energy(pet, effects.energy * amount, ctx.now)
    exp = effects.exp * amount
    affinity = min(100 - pet.affinity, effects.affinity * amount)
    pet.exp += exp
    pet.affinity += affinity
    if item.id == "spirit_food":
        advance(ctx, "feed")
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    # Repeat only while another dose would still be accepted; the post-use values are
    # read from the mutated pet, not a stale row.
    repeat = ("灵宠喂养",) if item.id == "spirit_food" else (f"灵宠使用 {item.name} 1",)
    steps = repeat if _recovery_available(effects, pet) else ()
    return Reply("灵粮温养" if item.id == "spirit_food" else "使用道具", (
        f"{item.name} -{amount}，精力 +{energy}，修为 +{exp}，亲密 +{affinity}。",
    ), ("灵宠背包", *steps, "我的灵宠"))


def feed(ctx: Context, arg: str) -> Reply:
    pet = selected_pet(ctx, arg, "喂养")
    return _use_consumable(ctx, ctx.content.items["spirit_food"], 1, pet)
