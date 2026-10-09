from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import item_amount, named
from ..utils.energy import add_energy
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .pet_targets import selected_pet
from .quests import advance
from .rewards import grant


def sign(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    today = beijing_day(ctx.now)
    if player.sign_day >= today:
        raise GameError("今日已领取仙缘，明日再来。（每日北京时间 00:00 刷新）")
    player.sign_day = today
    advance(ctx, "sign")
    return Reply("今日仙缘", grant(ctx, ctx.content.rules.daily_reward))


def bag(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    inventory = ctx.repo.inventory(ctx.user_id)
    reinforced = ctx.repo.conn.execute(
        "SELECT item_id, enhancement, quantity FROM unequipped_equipment "
        "WHERE user_id=? AND quantity>0 ORDER BY item_id, enhancement DESC", (ctx.user_id,),
    ).fetchall()
    return Reply("乾坤袋", (
        f"灵石：{player.stones}",
        *(f"{ctx.content.items[key].name}：{value}" for key, value in inventory.items()),
        *(f"{ctx.content.items[row['item_id']].name} +{row['enhancement']}：{row['quantity']}"
          for row in reinforced),
    ), ("灵宠商店", "灵宠喂养", "灵宠进化"))


def shop(ctx: Context, arg: str) -> Reply:
    available = {key: item for key, item in ctx.content.items.items() if item.price is not None}
    if arg and not arg.isdecimal():
        item = named(available, arg)
        commands = [f"灵宠购买 {item.name}"]
        if item.kind == "equipment":
            gear = ctx.content.equipment[item.equipment_id]
            commands.extend((f"灵宠装备图鉴 {gear.name}", f"灵宠工坊 {item.name}"))
        elif item.kind == "skill_book":
            commands.append(f"灵宠技能图鉴 {ctx.content.skills[item.skill_id].name}")
        return Reply(f"山海灵坊 · {item.name}", (
            f"售价：{item.price} 灵石。", item.description,
        ), (*commands, "灵宠商店", "灵宠背包"))
    page = paginate(available.values(), arg, "山海灵坊", "灵宠商店")
    return Reply(f"山海灵坊 {page.number}/{page.total}", tuple(
        f"{item.name}：{item.price} 灵石 · {item.description}"
        for item in page.entries
    ), (*(f"灵宠商店 {item.name}" for item in page.entries), *page.navigation, "灵宠背包"))


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
    return Reply("灵坊购得", (f"{item.name} +{amount}，灵石 -{cost}。",))


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
    return Reply("灵粮温养" if item.id == "spirit_food" else "使用道具", (
        f"{item.name} -{amount}，精力 +{energy}，修为 +{exp}，亲密 +{affinity}。",
    ))


def feed(ctx: Context, arg: str) -> Reply:
    pet = selected_pet(ctx, arg, "喂养")
    return _use_consumable(ctx, ctx.content.items["spirit_food"], 1, pet)
