from ..application.context import Context
from ..domain.battle_content import Requirement
from ..domain.models import GameError
from ..domain.state import Pet


def check_requirements(ctx: Context, pet: Pet, requirement: Requirement):
    species = ctx.content.species[pet.species_id]
    minimum = next(i for i, realm in enumerate(ctx.content.realms) if realm.id == requirement.min_realm)
    if pet.realm < minimum:
        raise GameError(f"需要{ctx.content.realms[minimum].name}境界。")
    if requirement.categories and species.category not in requirement.categories:
        raise GameError("当前宠物类别不兼容。")
    if not set(requirement.elements).issubset(species.elements):
        names = "、".join(ctx.content.elements[key].name for key in requirement.elements)
        raise GameError(f"元素不兼容，需要同时具备：{names}。")


def requirement_text(ctx: Context, requirement: Requirement) -> str:
    elements = "、".join(ctx.content.elements[key].name for key in requirement.elements) or "通用"
    categories = "、".join(ctx.content.categories[key].name for key in requirement.categories) or "全类别"
    realm = next(realm.name for realm in ctx.content.realms if realm.id == requirement.min_realm)
    return f"{elements} · {categories} · {realm}起"
