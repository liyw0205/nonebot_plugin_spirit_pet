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


SELECTOR = "伙伴"


def split_selector(arg: str) -> tuple[str, str]:
    """Split a trailing ``伙伴 <名字|编号>`` selector off a command argument.

    The selector is only recognised as the literal ``伙伴`` token, so existing
    arguments (item, skill and sigil names) keep their old meaning byte for byte.
    """
    text = arg.strip()
    marker = f" {SELECTOR} "
    if marker in text:
        head, _, tail = text.rpartition(marker)
        return head.strip(), tail.strip()
    prefix = f"{SELECTOR} "
    if text.startswith(prefix):
        return "", text[len(prefix):].strip()
    if text == SELECTOR or text.endswith(f" {SELECTOR}"):
        raise GameError("请填写伙伴名字或编号，例如：伙伴 3。")
    return text, ""


def named_pet(ctx: Context, value: str, action: str):
    """Resolve one in-roster pet by 编号 or exact name for a preparation action."""
    ctx.player()
    text = value.strip()
    if not text:
        raise GameError("请填写伙伴名字或编号，例如：伙伴 3。")
    owned = ctx.repo.owned_pets(ctx.user_id)
    if text.isascii() and text.isdecimal():
        target_id = pet_id(text)
        target = next((pet for pet in owned if pet.pet_id == target_id), None)
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
    matches = [pet for pet in owned if pet.name == text]
    if len(matches) > 1:
        raise GameError(f"有 {len(matches)} 位伙伴都叫{text}，请改用编号。")
    if not matches:
        archived = ctx.repo.conn.execute(
            "SELECT name FROM pets WHERE user_id=? AND name=? AND archived=1",
            (ctx.user_id, text),
        ).fetchone()
        if archived is not None:
            raise GameError(f"{archived['name']}已封存，请先复原后再{action}。")
        raise GameError(f"没有找到名为{text}的在册伙伴，请查看 灵宠列表。")
    restore_energy(matches[0], ctx.now, ctx.config.spirit_pet_energy_interval)
    return matches[0]


def target_pet(ctx: Context, value: str, action: str):
    """The named pet when a selector was supplied, otherwise the active pet."""
    if value.strip():
        return named_pet(ctx, value, action)
    return ctx.pet()


def note_prep_change(ctx: Context, pet) -> None:
    """Cancel team readiness only when the changed pet is actually in the roster."""
    roster = {member.pet_id for member in ctx.repo.active_pets(ctx.user_id)}
    if pet.pet_id in roster:
        ctx.repo.invalidate_ready(ctx.user_id)
