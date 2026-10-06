from ..application.context import Context
from ..domain.content import Item
from ..domain.models import GameError, Reply


def hatch(ctx: Context, item: Item, amount: int) -> Reply:
    ctx.player()
    if len(ctx.repo.owned_pets(ctx.user_id)) + amount > ctx.config.spirit_pet_max_pets:
        raise GameError("灵宠名册容量不足，灵卵未消耗。")
    species = ctx.content.species[item.species_id]
    ctx.repo.consume_item(ctx.user_id, item.id, amount)
    pets = [
        ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
        for _ in range(amount)
    ]
    return Reply("灵卵孵化", (
        f"{item.name} -{amount}。",
        *(f"获得{pet.name}，灵宠编号 {pet.pet_id}。" for pet in pets),
    ), ("灵宠列表", "我的灵宠"))
