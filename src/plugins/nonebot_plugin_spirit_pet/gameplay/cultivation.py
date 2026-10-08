from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from ..utils.energy import restore_energy
from ..utils.time import cooldown_left
from .pet_targets import pet_id, selected_pet
from .quests import advance

MAJOR_BREAKTHROUGH_PITY = 0.05


def breakthrough_chance(pet, cost, bonus: float = 0.0) -> float:
    failures = pet.major_breakthrough_failures if pet.layer == 10 else 0
    return min(1.0, cost.chance + pet.affinity / 1000 + bonus + failures * MAJOR_BREAKTHROUGH_PITY)


def train(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = selected_pet(ctx, arg, "修炼")
    rules = ctx.content.rules
    ctx.check_action(player, pet, "train", rules.training_energy, ctx.config.spirit_pet_train_cooldown)
    gained = _training_exp(ctx, pet)
    pet.exp += gained
    pet.energy -= rules.training_energy
    player.last_train = ctx.now
    if pet.pet_id == player.active_pet_id:
        ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "train")
    return Reply("吐纳修炼", (
        f"{pet.name}（编号 {pet.pet_id}）吸纳天地灵气。",
        f"修为 +{gained}，精力 -{rules.training_energy}。",
    ), ("灵宠列表", "我的灵宠"))


def _breakthrough_arguments(arg: str) -> tuple[str, str]:
    parts = arg.split()
    if not parts:
        return "", ""
    if parts[0].isascii() and parts[0].isdecimal():
        if len(parts) > 2:
            raise GameError("格式：灵宠突破 [灵宠编号] [破境丹]。")
        return parts[0], parts[1] if len(parts) == 2 else ""
    if len(parts) > 1:
        raise GameError("格式：灵宠突破 [灵宠编号] [破境丹]。")
    return "", parts[0]


def co_train(ctx: Context, arg: str) -> Reply:
    if not arg:
        raise GameError("格式：灵宠合修 灵宠编号。请先召唤一只与当前出战灵宠同族的灵宠。")
    player, active = ctx.player(), ctx.pet()
    partner_id = pet_id(arg)
    if partner_id == active.pet_id:
        raise GameError("合修需要另一只同族灵宠，不能选择当前出战灵宠。")
    partner = next((pet for pet in ctx.repo.owned_pets(ctx.user_id) if pet.pet_id == partner_id), None)
    if partner is None:
        archived = ctx.repo.conn.execute(
            "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1",
            (ctx.user_id, partner_id),
        ).fetchone()
        if archived is not None:
            raise GameError(f"{archived['name']}已封存，请先复原后再合修。")
        raise GameError("没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
    if partner.species_id != active.species_id:
        raise GameError("合修双方必须是同一种族。")

    rules = ctx.content.rules
    ctx.check_action(player, active, "train", rules.training_energy, ctx.config.spirit_pet_train_cooldown)
    ctx.require_idle_pet(partner)
    restore_energy(partner, ctx.now, ctx.config.spirit_pet_energy_interval)
    if partner.energy < rules.training_energy:
        raise GameError(f"{partner.name}精力不足，需要 {rules.training_energy} 点。")

    active_gain = _training_exp(ctx, active)
    partner_gain = _training_exp(ctx, partner)
    active.exp += active_gain
    partner.exp += partner_gain
    active.energy -= rules.training_energy
    partner.energy -= rules.training_energy
    player.last_train = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "train")
    return Reply("同族合修", (
        f"{active.name}修为 +{active_gain}，精力 -{rules.training_energy}。",
        f"{partner.name}修为 +{partner_gain}，精力 -{rules.training_energy}。",
        "本次合修只计一次每日修炼任务；修炼冷却仍由玩家共享。",
    ), ("灵宠列表", "我的灵宠", "灵宠任务"))


def available_co_training_partner(ctx: Context):
    player = ctx.repo.player(ctx.user_id)
    if player is None or player.active_pet_id is None:
        return None
    active = ctx.repo.pet(player.active_pet_id)
    rules = ctx.content.rules
    if (
        active.archived
        or ctx.repo.active_expedition(active.pet_id) is not None
        or cooldown_left(player.last_train, ctx.now, ctx.config.spirit_pet_train_cooldown)
        or _available_energy(ctx, active) < rules.training_energy
    ):
        return None
    for partner in ctx.repo.owned_pets(ctx.user_id):
        if partner.pet_id == active.pet_id or partner.species_id != active.species_id:
            continue
        if ctx.repo.active_expedition(partner.pet_id) is None and _available_energy(ctx, partner) >= rules.training_energy:
            return partner
    return None


def _available_energy(ctx: Context, pet) -> int:
    restored = max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval
    return min(100, pet.energy + restored)


def _training_exp(ctx: Context, pet) -> int:
    bounds = ctx.content.rules.training_exp
    bonus = ctx.content.species[pet.species_id].training_bonus
    return int(ctx.rng.randint(bounds.minimum, bounds.maximum) * (1 + bonus) * (pet.realm + 1))


def breakthrough(ctx: Context, arg: str) -> Reply:
    pet_arg, item_arg = _breakthrough_arguments(arg)
    player = ctx.player()
    pet = selected_pet(ctx, pet_arg, "突破")
    ctx.require_idle_pet(pet)
    major = pet.layer == 10
    cost = ctx.content.realms[pet.realm].advancement if major else ctx.content.layers[pet.layer].advancement
    if cost is None:
        raise GameError("已达当前最高境界十层。")
    scale = 1 if major else pet.realm + 1
    exp, stones = cost.exp * scale, cost.stones * scale
    if pet.exp < exp or player.stones < stones:
        raise GameError(f"突破需要 {exp} 修为和 {stones} 灵石。")
    bonus = 0.0
    if item_arg:
        item = named(ctx.content.items, item_arg)
        if item.kind != "breakthrough":
            raise GameError("该道具不能辅助突破。")
        if cost.chance >= 1:
            raise GameError("小境界突破必定成功，无需破境丹。")
        ctx.repo.consume_item(ctx.user_id, item.id, 1)
        bonus = item.effects.breakthrough_bonus
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    player.stones -= stones
    chance = breakthrough_chance(pet, cost, bonus)
    if pet.pet_id == player.active_pet_id:
        ctx.repo.invalidate_ready(ctx.user_id)
    if ctx.rng.random() < chance:
        previous_failures = pet.major_breakthrough_failures
        pet.exp -= exp
        if major:
            pet.realm += 1
            pet.layer = 1
            pet.major_breakthrough_failures = 0
        else:
            pet.layer += 1
        advance(ctx, "breakthrough")
        stage = f"{ctx.content.realms[pet.realm].name} {pet.layer}层"
        lines = [f"{pet.name}踏入{stage}！", f"修为 -{exp}，灵石 -{stones}。"]
        if major and previous_failures:
            lines.append(f"连续失败积累的额外成功率 +{previous_failures * MAJOR_BREAKTHROUGH_PITY:.0%} 已清零。")
        return Reply("大境界破境成功" if major else "小境界突破成功", tuple(lines))
    if major:
        pet.major_breakthrough_failures += 1
    lost = exp // 4
    pet.exp -= lost
    lines = [f"境界不变，损失 {lost} 修为、{stones} 灵石，已用道具不返还。"]
    if major:
        next_chance = breakthrough_chance(pet, cost)
        failures = pet.major_breakthrough_failures
        lines.append(
            f"破境积累：连续失败 {failures} 次，额外成功率 +{failures * MAJOR_BREAKTHROUGH_PITY:.0%}；"
            f"下次成功率（不含破境丹）{next_chance:.0%}。"
        )
    return Reply("破境未成", tuple(lines))


def evolve(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = selected_pet(ctx, arg, "进化")
    ctx.require_idle_pet(pet)
    cost = ctx.content.bloodlines[pet.bloodline].evolution
    if cost is None:
        raise GameError("已达当前最高血脉。")
    if pet.exp < cost.exp or player.stones < cost.stones:
        raise GameError(f"进化需要 {cost.exp} 修为、{cost.stones} 灵石和血脉材料，请查看我的灵宠。")
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    pet.exp -= cost.exp
    player.stones -= cost.stones
    if pet.pet_id == player.active_pet_id:
        ctx.repo.invalidate_ready(ctx.user_id)
    if ctx.rng.random() >= cost.chance:
        return Reply("进化未成", ("血脉未改变，本次修为、灵石和材料已消耗。",))
    pet.bloodline += 1
    advance(ctx, "evolve")
    return Reply("血脉觉醒", (
        f"{pet.name}进化为{ctx.content.bloodlines[pet.bloodline].name}。",
        f"修为 -{cost.exp}，灵石 -{cost.stones}，进化材料已消耗。",
    ))
