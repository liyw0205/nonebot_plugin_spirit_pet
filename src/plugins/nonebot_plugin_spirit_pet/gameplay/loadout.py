from ..application.context import Context
from ..domain.content import Stats
from ..domain.models import GameError
from .combat import Fighter, pet_stats
from .compatibility import check_requirements
from .equipment import active_sets, loadout
from .mastery import progress
from .skills import learned


def combatant(ctx: Context, user_id: str | None = None, *, recover_energy: bool = True) -> Fighter:
    if recover_energy:
        pet = ctx.pet(user_id)
    else:
        active_pet_id = ctx.player(user_id).active_pet_id
        if active_pet_id is None:
            raise GameError("尚未选择出战灵宠。")
        pet = ctx.repo.pet(active_pet_id)
    species = ctx.content.species[pet.species_id]
    stats = pet_stats(pet, ctx.content).model_dump()
    resonance_name = None
    resonance = ctx.repo.player_resonance(ctx.player(user_id).user_id)
    if resonance is not None:
        definition = ctx.content.resonances.get(resonance["resonance_id"])
        if definition is not None and pet.species_id in definition.required_species:
            for key, rate in definition.bonuses.model_dump().items():
                if rate:
                    stats[key] = int(stats[key] * (1 + rate) + 0.5)
            resonance_name = definition.name
    for item_id, enhancement in loadout(ctx, pet.pet_id).values():
        item = ctx.content.items[item_id]
        gear = ctx.content.equipment[item.equipment_id]
        check_requirements(ctx, pet, gear.requirements)
        multiplier = ctx.content.forge_levels[enhancement].bonus_multiplier
        for key, bonus in gear.bonuses.model_dump().items():
            stats[key] += int(bonus * multiplier)
    equipment_set_names = []
    for equipment_set in active_sets(ctx, pet.pet_id):
        equipment_set_names.append(equipment_set.name)
        for key, bonus in equipment_set.bonuses.model_dump().items():
            stats[key] += bonus
    selected = []
    skill_multipliers = {}
    progression = progress(ctx, pet.pet_id)
    for skill_id, active in learned(ctx, pet.pet_id).items():
        if active:
            skill = ctx.content.skills[skill_id]
            check_requirements(ctx, pet, skill.requirements)
            selected.append(skill)
            skill_multipliers[skill_id] = ctx.content.skill_levels[progression[skill_id][0]].power_multiplier
    name = f"{ctx.player(user_id).dao_name}的{pet.name}"
    return Fighter.create(
        name, Stats(**stats), tuple(species.elements), tuple(selected),
        primary_element=species.primary_element, pet_id=pet.pet_id,
        talent=ctx.content.talents[species.talent], skill_multipliers=skill_multipliers,
        resonance_name=resonance_name, affinity=pet.affinity,
        equipment_sets=tuple(equipment_set_names),
    )
