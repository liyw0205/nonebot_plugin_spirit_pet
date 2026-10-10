from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from ..utils.randomness import weighted_choice
from .cultivation import available_co_training_partner
from .identity import random_name


def adopt(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id):
        raise GameError("你已与灵宠结契，可通过灵宠召唤获得更多灵宠。")
    starters = {key: value for key, value in ctx.content.species.items() if value.starter}
    species = named(starters, arg) if arg else weighted_choice(ctx.rng, list(starters.values()), [1] * len(starters))
    player = ctx.repo.create_player(ctx.user_id, random_name(ctx), ctx.content.rules.starter_stones, ctx.now)
    pet = ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
    ctx.repo.set_active_pets(ctx.user_id, [pet.pet_id])
    for item_id, amount in ctx.content.rules.starter_items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    return Reply("灵契初成", (
        f"你的道号：{player.dao_name}。",
        f"你与{pet.name}缔结了灵契，编号 {pet.pet_id}。",
        "伙伴已自动出战，可以一起修炼与历练了。",
        f"境界：{ctx.content.realms[0].name}一层 · 血脉：{ctx.content.bloodlines[0].name}",
        f"获赠 {player.stones} 灵石。",
    ), ("我的信息", "我的灵宠", "灵宠帮助 成长"))


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
    guaranteed_species = set(pool.guaranteed_species)
    guarantee_due = pool.guaranteed_batch_size is not None and count >= pool.guaranteed_batch_size
    rare_drawn = False
    forced_guarantee = False
    draws = []
    for index in range(count):
        force_rare = guarantee_due and index == count - 1 and not rare_drawn
        entries = (
            [entry for entry in pool.entries if entry.species in guaranteed_species]
            if force_rare else pool.entries
        )
        entry = weighted_choice(ctx.rng, entries, [entry.weight for entry in entries])
        rare_drawn = rare_drawn or entry.species in guaranteed_species
        forced_guarantee = forced_guarantee or force_rare
        draws.append(entry)
    for entry in draws:
        species = ctx.content.species[entry.species]
        pet = ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
        lines.append(f"编号 {pet.pet_id}：{pet.name}")
    if guarantee_due:
        lines.append(
            "十连珍稀保底触发。" if forced_guarantee else "本次十连已提前抽得珍稀灵宠，保底不追加。"
        )
    return Reply("山海召唤", (f"灵石 -{cost}。", *lines), ("灵宠列表", "我的灵宠", "灵宠图鉴"))


def pet_list(ctx: Context, arg: str) -> Reply:
    ctx.player()
    owned = ctx.repo.owned_pets(ctx.user_id)
    active_ids = {pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id)}
    page = quantity(arg or "1", 999)
    pages = max(1, (len(owned) + 4) // 5)
    if page > pages:
        raise GameError(f"共 {pages} 页。")
    selected = owned[(page - 1) * 5:page * 5]
    archived_count = ctx.repo.archived_pet_count(ctx.user_id)
    lines = [f"在册 {len(owned)}/{ctx.config.spirit_pet_max_pets} · 封存 {archived_count} 只。"]
    has_expedition = False
    for pet in selected:
        expedition = ctx.repo.active_expedition(pet.pet_id)
        activity = ""
        if expedition is not None:
            has_expedition = True
            state = "外出中" if ctx.now < expedition["finishes_at"] else "待领取"
            activity = f" · {state}：{expedition['task_name']}"
        lines.append(
            f"{'*' if pet.pet_id in active_ids else ''}编号 {pet.pet_id}：{pet.name}"
            f"（{ctx.content.species[pet.species_id].name}）"
            f" · {ctx.content.realms[pet.realm].name} {pet.layer}层{activity}"
        )
    co_training_partner = available_co_training_partner(ctx)
    if co_training_partner is not None:
        lines.append(f"同族合修可用：{co_training_partner.name}（编号 {co_training_partner.pet_id}）。")
    archive_commands = [
        f"灵宠封存 {pet.pet_id}" for pet in selected
        if pet.pet_id not in active_ids
    ][:2 if co_training_partner is not None else 3]
    commands = (
        [f"灵宠合修 {co_training_partner.pet_id}"] if co_training_partner is not None else []
    )
    commands.extend(archive_commands)
    commands.extend(("我的灵宠", "灵宠封存库"))
    commands.append("灵宠出战")
    if has_expedition:
        commands.append("灵宠行程")
    if page > 1:
        commands.append(f"灵宠列表 {page - 1}")
    if page < pages:
        commands.append(f"灵宠列表 {page + 1}")
    if len(commands) < 8:
        commands.append("灵宠召唤")
    return Reply(f"灵宠名册 {page}/{pages}", tuple(lines), tuple(commands))


def archive_list(ctx: Context, arg: str) -> Reply:
    ctx.player()
    count = ctx.repo.archived_pet_count(ctx.user_id)
    pages = max(1, (count + 4) // 5)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"封存库共 {pages} 页。")
    selected = ctx.repo.archived_pets(ctx.user_id, limit=5, offset=(page - 1) * 5)
    if not selected:
        return Reply("灵宠封存库", ("尚无封存的灵宠。",), ("灵宠列表", "灵宠召唤"))
    lines = tuple(
        f"编号 {pet.pet_id}：{pet.name}（{ctx.content.species[pet.species_id].name}）"
        f" · {ctx.content.realms[pet.realm].name} {pet.layer}层 · 血脉 {ctx.content.bloodlines[pet.bloodline].name}"
        for pet in selected
    )
    commands = [f"灵宠复原 {pet.pet_id}" for pet in selected]
    if page > 1:
        commands.append(f"灵宠封存库 {page - 1}")
    if page < pages:
        commands.append(f"灵宠封存库 {page + 1}")
    commands.append("灵宠列表")
    return Reply(f"灵宠封存库 {page}/{pages}", lines, tuple(commands))


def _owned_pet_by_id(ctx: Context, arg: str):
    if not arg:
        raise GameError("请填写灵宠编号，可先查看 灵宠列表 或 灵宠封存库。")
    pet_id = quantity(arg, 9_223_372_036_854_775_807)
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的这只灵宠。")
    return ctx.repo.pet(pet_id)


def archive(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = _owned_pet_by_id(ctx, arg)
    if pet.archived:
        raise GameError(f"{pet.name}已经封存，可在灵宠封存库中复原。")
    if pet.pet_id in {active.pet_id for active in ctx.repo.active_pets(ctx.user_id)}:
        raise GameError("当前出战灵宠不能封存，请先调整出战阵容。")
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        raise GameError(f"{pet.name}仍有未结行程，不能封存；请先查看灵宠行程。")
    ctx.repo.invalidate_ready(ctx.user_id)
    pet.archived = True
    active_count = sum(not owned.archived for owned in ctx.repo.owned_pets(ctx.user_id))
    return Reply("灵宠封存", (
        f"{pet.name}（编号 {pet.pet_id}）已封存，名册空位 +1。",
        f"在册 {active_count}/{ctx.config.spirit_pet_max_pets}。",
    ), ("灵宠封存库", "灵宠列表", "灵宠召唤"))


def restore(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet = _owned_pet_by_id(ctx, arg)
    if not pet.archived:
        raise GameError(f"{pet.name}不在封存库中。")
    active_count = len(ctx.repo.owned_pets(ctx.user_id))
    maximum = ctx.config.spirit_pet_max_pets
    if active_count >= maximum:
        raise GameError(f"在册名额已满（{active_count}/{maximum}），请先封存一只非出战灵宠。")
    pet.archived = False
    return Reply("灵宠复原", (
        f"{pet.name}（编号 {pet.pet_id}）已回到在册名册。",
        f"在册 {active_count + 1}/{maximum}；复原不会自动切换出战灵宠。",
    ), (f"灵宠切换 {pet.pet_id}", "灵宠封存库", "灵宠列表"))


def switch(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if any(separator in arg for separator in (" ", "，", ",")):
        return lineup(ctx, arg)
    owned = ctx.repo.owned_pets(ctx.user_id)
    matches = [pet for pet in owned if str(pet.pet_id) == arg]
    if not matches:
        matches = [pet for pet in owned if pet.name == arg]
    if len(matches) != 1:
        if arg.isascii() and arg.isdecimal() and len(arg) <= 19:
            row = ctx.repo.conn.execute(
                "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1",
                (ctx.user_id, int(arg)),
            ).fetchone()
            if row is not None:
                raise GameError(f"{row['name']}已封存，请先发送 灵宠复原 {arg}。")
        raise GameError("未找到灵宠或名字重复，请用灵宠列表中的编号切换。")
    player.active_pet_id = matches[0].pet_id
    ctx.repo.set_active_pets(ctx.user_id, [matches[0].pet_id])
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵宠出战", (f"当前灵宠：{matches[0].name}（编号 {matches[0].pet_id}）。",))


def lineup(ctx: Context, arg: str) -> Reply:
    """Set one to three distinct species as the player's battle roster."""
    ctx.player()
    if not arg:
        active = ctx.repo.active_pets(ctx.user_id)
        return Reply(
            "灵宠出战阵容",
            tuple(f"{index}. {pet.name}（编号 {pet.pet_id} · {ctx.content.species[pet.species_id].name}）"
                  for index, pet in enumerate(active, 1)),
            (f"灵宠出战 {' '.join(str(pet.pet_id) for pet in active)}", "灵宠列表"),
        )
    parts = [part for part in arg.replace("，", " ").replace(",", " ").split() if part]
    if not 1 <= len(parts) <= 3 or any(not part.isdecimal() for part in parts):
        raise GameError("格式：灵宠出战 编号 [编号] [编号]，最多三只。")
    ids = [int(part) for part in parts]
    ctx.repo.set_active_pets(ctx.user_id, ids)
    ctx.repo.invalidate_ready(ctx.user_id)
    active = ctx.repo.active_pets(ctx.user_id)
    names = "、".join(f"{pet.name}（{pet.pet_id}）" for pet in active)
    return Reply("灵宠出战阵容", (f"当前出战：{names}。", "同一阵容不能重复宠物种类，最多出战三只。"),
                 ("灵宠列表", "灵宠出战"))
