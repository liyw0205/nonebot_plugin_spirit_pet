from ..application.context import Context
from ..domain.models import GameError
from ..utils.energy import restore_energy

MAX_PET_ID = 9_223_372_036_854_775_807


def pet_id(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise GameError("请填写灵宠列表中的有效编号。")
    result = int(value)
    if not 1 <= result <= MAX_PET_ID:
        raise GameError("请填写灵宠列表中的有效编号。")
    return result


def selected_pet(ctx: Context, value: str, action: str):
    if not value:
        return ctx.pet()
    ctx.player()
    target_id = pet_id(value)
    target = next((pet for pet in ctx.repo.owned_pets(ctx.user_id) if pet.pet_id == target_id), None)
    if target is not None:
        restore_energy(target, ctx.now, ctx.config.spirit_pet_energy_interval)
        return target
    archived = ctx.repo.conn.execute(
        "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1",
        (ctx.user_id, target_id),
    ).fetchone()
    if archived is not None:
        raise GameError(f"{archived['name']}已封存，请先复原后再{action}。")
    raise GameError("没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
