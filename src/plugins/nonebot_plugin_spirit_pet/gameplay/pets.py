import re

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from ..utils.randomness import weighted_choice
from .identity import random_name


def adopt(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id):
        raise GameError("你已与灵宠结契，可通过灵宠召唤获得更多灵宠。")
    starters = {key: value for key, value in ctx.content.species.items() if value.starter}
    species = named(starters, arg) if arg else weighted_choice(ctx.rng, list(starters.values()), [1] * len(starters))
    player = ctx.repo.create_player(ctx.user_id, random_name(ctx), ctx.content.rules.starter_stones)
    pet = ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
    player.active_pet_id = pet.pet_id
    for item_id, amount in ctx.content.rules.starter_items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    return Reply("灵契初成", (
        f"你的道号：{player.dao_name}。",
        f"你与{pet.name}缔结了灵契，编号 {pet.pet_id}。",
        f"境界：{ctx.content.realms[0].name}一层 · 血脉：{ctx.content.bloodlines[0].name}",
        f"获赠 {player.stones} 灵石。",
    ))


def summon(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    count = quantity(arg or "1", 10)
    if len(ctx.repo.owned_pets(ctx.user_id)) + count > ctx.config.spirit_pet_max_pets:
        raise GameError(f"灵宠名册上限为 {ctx.config.spirit_pet_max_pets} 只。")
    pool = ctx.content.pools["standard"]
    cost = count * pool.stones
    if player.stones < cost:
        raise GameError(f"召唤需要 {cost} 灵石。")
    player.stones -= cost
    lines = []
    for _ in range(count):
        entry = weighted_choice(ctx.rng, pool.entries, [entry.weight for entry in pool.entries])
        species = ctx.content.species[entry.species]
        pet = ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
        lines.append(f"编号 {pet.pet_id}：{pet.name}")
    return Reply("山海召唤", (f"灵石 -{cost}。", *lines), ("灵宠列表", "我的灵宠", "灵宠图鉴"))


def pet_list(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    owned = ctx.repo.owned_pets(ctx.user_id)
    page = quantity(arg or "1", 999)
    pages = max(1, (len(owned) + 4) // 5)
    if page > pages:
        raise GameError(f"共 {pages} 页。")
    lines = []
    for pet in owned[(page - 1) * 5:page * 5]:
        expedition = ctx.repo.active_expedition(pet.pet_id)
        activity = ""
        if expedition is not None:
            state = "外出中" if ctx.now < expedition["finishes_at"] else "待领取"
            activity = f" · {state}：{expedition['task_name']}"
        lines.append(
            f"{'*' if pet.pet_id == player.active_pet_id else ''}编号 {pet.pet_id}：{pet.name}"
            f"（{ctx.content.species[pet.species_id].name}）"
            f" · {ctx.content.realms[pet.realm].name} {pet.layer}层{activity}"
        )
    return Reply(f"灵宠名册 {page}/{pages}", tuple(lines), ("我的灵宠", "灵宠召唤", "灵宠行程"))


def switch(ctx: Context, arg: str) -> Reply:
    owned = ctx.repo.owned_pets(ctx.user_id)
    matches = [pet for pet in owned if str(pet.pet_id) == arg]
    if not matches:
        matches = [pet for pet in owned if pet.name == arg]
    if len(matches) != 1:
        raise GameError("未找到灵宠或名字重复，请用灵宠列表中的编号切换。")
    player = ctx.player()
    player.active_pet_id = matches[0].pet_id
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵宠出战", (f"当前灵宠：{matches[0].name}（编号 {matches[0].pet_id}）。",))


def rename(ctx: Context, arg: str) -> Reply:
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{1,12}", arg):
        raise GameError("名字限 1-12 个汉字、英文字母或数字。")
    ctx.pet().name = arg
    return Reply("赐名结缘", (f"灵宠从此名为：{arg}。",))
