from ..application.context import Context
from ..domain.content import Item
from ..domain.models import GameError, Reply


def hatch(ctx: Context, item: Item, amount: int) -> Reply:
    ctx.player()
    if len(ctx.repo.owned_pets(ctx.user_id)) + amount > ctx.config.spirit_pet_max_pets:
        raise GameError("灵宠名册容量不足，灵卵未消耗。")
    species = ctx.content.species[item.species_id]
    lineage_eggs = ctx.repo.consume_pet_eggs(ctx.user_id, item.id, amount, ctx.now)
    pets = [
        ctx.repo.create_pet(ctx.user_id, species.id, species.name, species.initial_affinity, ctx.now)
        for _ in range(amount)
    ]
    for egg_record_id, pet in zip(lineage_eggs, pets):
        if egg_record_id is not None:
            ctx.repo.hatch_lineage_egg(ctx.user_id, egg_record_id, pet.pet_id, pet.name, ctx.now)
    reply = Reply("灵卵孵化", (
        f"{item.name} -{amount}。",
        *(f"获得{pet.name}，灵宠编号 {pet.pet_id}。" for pet in pets),
    ), ("灵宠列表", "我的灵宠", "灵宠谱系", "灵宠背包"))
    ctx.repo.record_pedigree_operation(
        ctx.operation_id, ctx.user_id, "hatch", ctx.now,
        {"item_id": item.id, "amount": amount,
         "children": [pet.pet_id for pet in pets], "lineage_eggs": lineage_eggs},
        reply,
    )
    return reply
