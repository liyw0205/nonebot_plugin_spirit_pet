from ..application.context import Context
from ..domain.content import Stats
from .combat import Fighter, pet_stats
from .compatibility import check_requirements
from .equipment import equipped
from .skills import learned


def combatant(ctx: Context, user_id: str | None = None) -> Fighter:
    pet = ctx.pet(user_id)
    species = ctx.content.species[pet.species_id]
    stats = pet_stats(pet, ctx.content).model_dump()
    for item_id in equipped(ctx, pet.pet_id).values():
        item = ctx.content.items[item_id]
        gear = ctx.content.equipment[item.equipment_id]
        check_requirements(ctx, pet, gear.requirements)
        for key, bonus in gear.bonuses.model_dump().items():
            stats[key] += bonus
    selected = []
    for skill_id, active in learned(ctx, pet.pet_id).items():
        if active:
            skill = ctx.content.skills[skill_id]
            check_requirements(ctx, pet, skill.requirements)
            selected.append(skill)
    name = f"{ctx.player(user_id).dao_name}的{pet.name}"
    return Fighter.create(name, Stats(**stats), tuple(species.elements), tuple(selected))
