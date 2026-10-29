"""Support roster: two bench slots that lend part of a pet's base stats to the active pet.

State lives in the existing ``quest_progress`` table as ``support_1`` / ``support_2``
(progress = pet id). The bonus is derived from ``pet_stats`` of the benched pet and is
applied by ``loadout.combatant`` to the owner's active pet only.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .combat import pet_stats

SLOT = "support_"
STAT_LABELS = (("hp", "气血"), ("attack", "攻击"), ("defense", "防御"), ("speed", "速度"))


def max_slots(ctx: Context) -> int:
    return ctx.content.rules.support.slots


def rate(ctx: Context) -> float:
    return ctx.content.rules.support.rate


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def assigned(ctx: Context, user_id: str | None = None) -> dict[int, int]:
    slots = {}
    for slot in range(1, max_slots(ctx) + 1):
        pet_id = _progress(ctx, f"{SLOT}{slot}", user_id)
        if pet_id:
            slots[slot] = pet_id
    return slots


def _load(ctx: Context, pet_id: int):
    try:
        return ctx.repo.pet(pet_id)
    except GameError:
        return None


def active_ids(ctx: Context, user_id: str | None = None) -> set[int]:
    return {pet.pet_id for pet in ctx.repo.active_pets(user_id or ctx.user_id)}


def _contributions(ctx: Context, pet) -> dict[str, int]:
    stats = pet_stats(pet, ctx.content)
    value = rate(ctx)
    return {
        key: int(getattr(stats, key) * value)
        for key, _ in STAT_LABELS
    }


def bonus(ctx: Context, user_id: str | None = None) -> dict[str, int]:
    """Summed support contribution, skipping pets that vanished or went away."""
    total = {key: 0 for key, _ in STAT_LABELS}
    for slot, pet_id in assigned(ctx, user_id).items():
        pet = _load(ctx, pet_id)
        if pet is None or pet.archived:
            continue
        if ctx.repo.active_expedition(pet.pet_id) is not None:
            continue
        for key, value in _contributions(ctx, pet).items():
            total[key] += value
    return total


def _bonus_text(values: dict[str, int]) -> str:
    return " · ".join(f"{label} +{values[key]}" for key, label in STAT_LABELS if values[key])


def _eligible(ctx: Context) -> list:
    lineup = active_ids(ctx)
    used = set(assigned(ctx).values())
    return [
        pet for pet in sorted(ctx.repo.owned_pets(ctx.user_id), key=lambda item: item.pet_id)
        if not pet.archived
        and pet.pet_id not in lineup
        and pet.pet_id not in used
        and ctx.repo.active_expedition(pet.pet_id) is None
    ]


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠助战 [设置|清除] <1|2> [伙伴名]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠助战",
            (
                "尚未结契，先完成领养，才能安排助战席。",
                "助战席上的伙伴不上场，但会把自身基础四维的一部分借给当前出战伙伴。",
                "出战阵容里的伙伴、封存或外出派遣的伙伴不能担任助战。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    slots = assigned(ctx)
    lines = [
        f"助战席 {len(slots)}/{max_slots(ctx)} · 每席借出该伙伴基础四维的 {rate(ctx):.0%}"
        "（不含装备、淬魂与师门）。",
    ]
    links = []
    for slot in range(1, max_slots(ctx) + 1):
        pet_id = slots.get(slot)
        pet = _load(ctx, pet_id) if pet_id else None
        if pet is None:
            lines.append(f"{slot} 席：空")
            continue
        lines.append(f"{slot} 席：{pet.name} · {_bonus_text(_contributions(ctx, pet))}")
        links.append(InlineCommand(len(lines) - 1, "清除", f"灵宠助战 清除 {slot}"))
    candidates = _eligible(ctx)
    if candidates:
        empty = next((slot for slot in range(1, max_slots(ctx) + 1) if slot not in slots), None)
        lines.append("可担任助战的伙伴：")
        for pet in candidates:
            lines.append(f"{pet.name} · {_bonus_text(_contributions(ctx, pet))}")
            if empty is not None:
                links.append(InlineCommand(len(lines) - 1, "设为助战", f"灵宠助战 设置 {empty} {pet.name}"))
    else:
        lines.append("当前没有可担任助战的伙伴（出战、封存或外出的伙伴不可用）。")
    lines.append("助战只加成当前出战伙伴；更换或清除会取消组队准备。")
    return Reply("灵宠助战", tuple(lines), ("灵宠助战", "我的灵宠", "灵宠目标"), tuple(links))


def _lookup(ctx: Context, name: str):
    row = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND name=? ORDER BY pet_id LIMIT 1",
        (ctx.user_id, name),
    ).fetchone()
    return None if row is None else ctx.repo.pet(int(row["pet_id"]))


def _set(ctx: Context, key: str, value: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, value),
    )


def assign(ctx: Context, arg: str) -> Reply:
    ctx.player()
    parts = arg.split()
    if len(parts) < 2:
        raise GameError("格式：灵宠助战 设置 <1|2> <伙伴名>。")
    if not parts[0].isdecimal():
        raise GameError("席位必须是 1 或 2。")
    slot = int(parts[0])
    if slot < 1 or slot > max_slots(ctx):
        raise GameError(f"席位超出范围：当前只有 {max_slots(ctx)} 席。")
    name = " ".join(parts[1:])
    pet = _lookup(ctx, name)
    if pet is None:
        raise GameError(f"没有找到名为{name}的伙伴。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，不能担任助战。")
    ctx.require_idle_pet(pet)
    if pet.pet_id in active_ids(ctx):
        raise GameError(f"{pet.name}已在出战阵容，不能担任助战。")
    for other, pet_id in assigned(ctx).items():
        if other != slot and pet_id == pet.pet_id:
            raise GameError(f"{pet.name}已在 {other} 席助战。")
    _set(ctx, f"{SLOT}{slot}", pet.pet_id)
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"{slot} 席已设为{pet.name}：{_bonus_text(_contributions(ctx, pet))} 借给当前出战伙伴。",
        f"助战席 {len(assigned(ctx))}/{max_slots(ctx)}。",
    ]
    return Reply("灵宠助战", tuple(lines), ("灵宠助战", "我的灵宠", "灵宠目标"))


def clear(ctx: Context, arg: str) -> Reply:
    ctx.player()
    parts = arg.split()
    if len(parts) != 1 or not parts[0].isdecimal():
        raise GameError("格式：灵宠助战 清除 <1|2>。")
    slot = int(parts[0])
    if slot < 1 or slot > max_slots(ctx):
        raise GameError(f"席位超出范围：当前只有 {max_slots(ctx)} 席。")
    if slot not in assigned(ctx):
        raise GameError(f"{slot} 席当前是空的。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, f"{SLOT}{slot}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply(
        "灵宠助战",
        (f"{slot} 席已清空。", f"助战席 {len(assigned(ctx))}/{max_slots(ctx)}。"),
        ("灵宠助战", "我的灵宠", "灵宠目标"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "设置":
        return assign(ctx, " ".join(parts[1:]))
    if parts[0] == "清除":
        return clear(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠助战 [设置|清除] <1|2> [伙伴名]。")


def objective_line(ctx: Context, user_id: str) -> str:
    return f"助战：{len(assigned(ctx, user_id))}/{max_slots(ctx)} 席"
