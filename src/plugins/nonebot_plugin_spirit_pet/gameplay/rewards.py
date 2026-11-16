from ..application.context import Context
from ..domain.content import Reward
from ..domain.models import GameError


def grant(ctx: Context, reward: Reward, user_id: str | None = None, *, pet_id: int | None = None) -> tuple[str, ...]:
    player = ctx.player(user_id)
    pet = None
    if reward.exp.maximum > 0:
        if pet_id is None:
            pet = ctx.pet(user_id)
        else:
            pet = ctx.repo.pet(pet_id)
            if pet is None or pet.user_id != player.user_id:
                raise GameError("没有属于你的这只灵宠。")
            if pet.archived:
                raise ctx.archived_active_pet(pet, player.user_id)
        ctx.require_idle_pet(pet)
    exp = ctx.rng.randint(reward.exp.minimum, reward.exp.maximum)
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    if pet is not None:
        pet.exp += exp
    player.stones += stones
    lines = [f"修为 +{exp}，灵石 +{stones}"]
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        ctx.repo.add_item(player.user_id, item_id, amount)
        if amount:
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return tuple(lines)
