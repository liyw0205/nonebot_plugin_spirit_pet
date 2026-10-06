from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .quests import advance


def train(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    rules = ctx.content.rules
    ctx.check_action(player, pet, "train", rules.training_energy, ctx.config.spirit_pet_train_cooldown)
    bounds = rules.training_exp
    bonus = ctx.content.species[pet.species_id].training_bonus
    gained = int(ctx.rng.randint(bounds.minimum, bounds.maximum) * (1 + bonus) * (pet.realm + 1))
    pet.exp += gained
    pet.energy -= rules.training_energy
    player.last_train = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "train")
    return Reply("吐纳修炼", (f"{pet.name}吸纳天地灵气。", f"修为 +{gained}，精力 -{rules.training_energy}。"))


def breakthrough(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    major = pet.layer == 10
    cost = ctx.content.realms[pet.realm].advancement if major else ctx.content.layers[pet.layer].advancement
    if cost is None:
        raise GameError("已达当前最高境界十层。")
    scale = 1 if major else pet.realm + 1
    exp, stones = cost.exp * scale, cost.stones * scale
    if pet.exp < exp or player.stones < stones:
        raise GameError(f"突破需要 {exp} 修为和 {stones} 灵石。")
    bonus = 0.0
    if arg:
        item = named(ctx.content.items, arg)
        if item.kind != "breakthrough":
            raise GameError("该道具不能辅助突破。")
        if cost.chance >= 1:
            raise GameError("小境界突破必定成功，无需破境丹。")
        ctx.repo.consume_item(ctx.user_id, item.id, 1)
        bonus = item.effects.breakthrough_bonus
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    player.stones -= stones
    chance = min(1.0, cost.chance + bonus + pet.affinity / 1000)
    ctx.repo.invalidate_ready(ctx.user_id)
    if ctx.rng.random() < chance:
        pet.exp -= exp
        if major:
            pet.realm += 1
            pet.layer = 1
        else:
            pet.layer += 1
        stage = f"{ctx.content.realms[pet.realm].name} {pet.layer}层"
        return Reply("大境界破境成功" if major else "小境界突破成功", (
            f"{pet.name}踏入{stage}！", f"修为 -{exp}，灵石 -{stones}。",
        ))
    lost = exp // 4
    pet.exp -= lost
    return Reply("破境未成", (f"境界不变，损失 {lost} 修为、{stones} 灵石，已用道具不返还。",))


def evolve(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    cost = ctx.content.bloodlines[pet.bloodline].evolution
    if cost is None:
        raise GameError("已达当前最高血脉。")
    if pet.exp < cost.exp or player.stones < cost.stones:
        raise GameError(f"进化需要 {cost.exp} 修为、{cost.stones} 灵石和血脉材料，请查看我的灵宠。")
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    pet.exp -= cost.exp
    player.stones -= cost.stones
    ctx.repo.invalidate_ready(ctx.user_id)
    if ctx.rng.random() >= cost.chance:
        return Reply("进化未成", ("血脉未改变，本次修为、灵石和材料已消耗。",))
    pet.bloodline += 1
    advance(ctx, "evolve")
    return Reply("血脉觉醒", (
        f"{pet.name}进化为{ctx.content.bloodlines[pet.bloodline].name}。",
        f"修为 -{cost.exp}，灵石 -{cost.stones}，进化材料已消耗。",
    ))
