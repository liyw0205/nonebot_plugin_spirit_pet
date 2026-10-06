from ..application.context import Context
from ..domain.content import Reward


def grant(ctx: Context, reward: Reward, user_id: str | None = None) -> tuple[str, ...]:
    player = ctx.player(user_id)
    pet = ctx.pet(user_id)
    exp = ctx.rng.randint(reward.exp.minimum, reward.exp.maximum)
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    pet.exp += exp
    player.stones += stones
    lines = [f"修为 +{exp}，灵石 +{stones}"]
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        ctx.repo.add_item(player.user_id, item_id, amount)
        if amount:
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return tuple(lines)
