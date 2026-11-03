"""灵宠配装: save a companion's three gear slots and re-equip them in one command.

Gear is bound to a pet (``equipment(pet_id, slot, item_id, enhancement)``) and the game
has several modes that want opposite builds — speed gear for 竞速, 气血/防御 for 守关,
攻击 for 图鉴试炼. Re-equipping by hand is three ``灵宠装备`` commands plus three returns to
the bag, and players juggle that every time they switch modes.

A preset is a snapshot of what that pet is *wearing*, not a copy of the items: applying one
moves real gear out of the bag, exactly like ``灵宠装备`` does, and pushes the gear being
replaced back. Nothing is duplicated, so no preset can be used to conjure a second copy.

Presets live in ``quest_progress`` with the payload in the key, the way titles and
specializations already store theirs (no schema change):

* ``gear<pet_id>_<preset>_<slot>_<enhancement>_<item_id>`` — one row per equipped slot.

Keeping ``item_id`` last means the key can be parsed with a single ``split("_", 4)`` even
though item ids contain underscores.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.state import Pet
from . import equipment
from .equipment_inventory import put, take

PREFIX = "gear"
SLOTS = equipment.SLOTS
PRESET_COUNT = 3
TITLE = "灵宠配装"
_SLOT_ORDER = ("weapon", "armor", "charm")


def _owned_pet(ctx: Context, pet_id: int):
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的这只灵宠。")
    return ctx.repo.pet(pet_id)


def _key(pet_id: int, preset: int, slot: str, enhancement: int, item_id: str) -> str:
    return f"{PREFIX}{pet_id}_{preset}_{slot}_{enhancement}_{item_id}"


def _parse(quest_id: str):
    """(pet_id, preset, slot, enhancement, item_id) or None for a foreign key."""
    head, preset, slot, enhancement, item_id = quest_id.split("_", 4)
    if not head[len(PREFIX):].isdecimal() or not preset.isdecimal() or not enhancement.isdecimal():
        return None
    if slot not in SLOTS:
        return None
    return int(head[len(PREFIX):]), int(preset), slot, int(enhancement), item_id


def saved(ctx: Context, pet_id: int, preset: int | None = None) -> dict[int, dict[str, tuple[str, int]]]:
    """Every stored preset for this pet: ``{preset: {slot: (item_id, enhancement)}}``."""
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{PREFIX}{pet_id}_%"),
    ).fetchall()
    out: dict[int, dict[str, tuple[str, int]]] = {}
    for row in rows:
        parsed = _parse(row["quest_id"])
        if parsed is None or parsed[0] != pet_id:
            continue
        _, index, slot, enhancement, item_id = parsed
        if preset is not None and index != preset:
            continue
        out.setdefault(index, {})[slot] = (item_id, enhancement)
    return out


def _requirement(ctx: Context, arg: str, pet: Pet | None = None) -> tuple[Pet, int]:
    """Resolve ``[<编号>] <1-3>``; the bare form targets the active pet."""
    parts = arg.split()
    if len(parts) == 1:
        target = pet or ctx.pet()
        number = parts[0]
    elif len(parts) == 2:
        target = _owned_pet(ctx, int(parts[0])) if parts[0].isdecimal() else None
        if target is None:
            raise GameError("格式：灵宠配装 保存|应用|清除 [编号] <1-3>。")
        number = parts[1]
    else:
        raise GameError("格式：灵宠配装 保存|应用|清除 [编号] <1-3>。")
    if not number.isdecimal():
        raise GameError("配装序号必须是 1、2 或 3。")
    index = int(number)
    if not 1 <= index <= PRESET_COUNT:
        raise GameError(f"配装只有 {PRESET_COUNT} 套，序号取 1-{PRESET_COUNT}。")
    return target, index


def _gear_name(ctx: Context, item_id: str, enhancement: int) -> str:
    item = ctx.content.items.get(item_id)
    name = item.name if item is not None else item_id
    return f"{name} +{enhancement}" if enhancement else name


def _summary(ctx: Context, slots: dict[str, tuple[str, int]]) -> str:
    if not slots:
        return "空"
    return "、".join(
        f"{SLOTS[slot]} {_gear_name(ctx, *slots[slot])}"
        for slot in _SLOT_ORDER if slot in slots
    )


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [保存|应用|清除 序号] [编号]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能给伙伴存配装。",
                "配装保存的是伙伴当前穿戴的三件灵物；应用时按序号一键换回。",
                "配装不复制装备：应用会真的把装备从背包移到伙伴身上。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.pet()
    current = equipment.loadout(ctx, pet.pet_id)
    stored = saved(ctx, pet.pet_id)
    lines = [f"{pet.name}（编号 {pet.pet_id}）当前：{_summary(ctx, current)}。"]
    links = []
    for index in range(1, PRESET_COUNT + 1):
        slots = stored.get(index, {})
        same = slots == current if slots else False
        state = " · 与当前一致" if same else ""
        lines.append(f"{index} 套：{_summary(ctx, slots)}{state}")
        if slots:
            links.append(InlineCommand(len(lines) - 1, "应用", f"{TITLE} 应用 {index}"))
            links.append(InlineCommand(len(lines) - 1, "覆盖", f"{TITLE} 保存 {index}"))
            links.append(InlineCommand(len(lines) - 1, "清除", f"{TITLE} 清除 {index}"))
        else:
            links.append(InlineCommand(len(lines) - 1, "保存", f"{TITLE} 保存 {index}"))
    lines.append("保存记录当前穿戴；应用会把当前装备退回背包并换上配装里的三件。")
    return Reply(
        TITLE, tuple(lines),
        (TITLE, "灵宠装备", "灵宠装备套装", "我的灵宠"),
        tuple(links[:8]),
    )


def save(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet, index = _requirement(ctx, arg)
    current = equipment.loadout(ctx, pet.pet_id)
    if not current:
        raise GameError(f"{pet.name}当前没有穿戴灵物，没有可保存的配装。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{PREFIX}{pet.pet_id}_{index}_%"),
    )
    for slot, (item_id, enhancement) in current.items():
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (ctx.user_id, _key(pet.pet_id, index, slot, enhancement, item_id)),
        )
    return Reply(TITLE, (
        f"已把{pet.name}当前的 {len(current)} 件灵物存为第 {index} 套：{_summary(ctx, current)}。",
        "以后发 灵宠配装 应用 "
        f"{index} 可一键换回；配装引用的是真实装备，不是复制品。",
    ), (TITLE, "灵宠装备", "我的灵宠"))


def _in_bag(ctx: Context, item_id: str, enhancement: int, pet_id: int) -> bool:
    """Is this exact gear piece available to equip right now?"""
    current = equipment.loadout(ctx, pet_id)
    if any(gear == (item_id, enhancement) for gear in current.values()):
        return True
    if not enhancement:
        row = ctx.repo.conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
        ).fetchone()
        return row is not None and int(row["quantity"]) > 0
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM unequipped_equipment WHERE user_id=? AND item_id=? AND enhancement=?",
        (ctx.user_id, item_id, enhancement),
    ).fetchone()
    return row is not None and int(row["quantity"]) > 0


def apply(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet, index = _requirement(ctx, arg)
    ctx.require_idle_pet(pet)
    slots = saved(ctx, pet.pet_id, index).get(index, {})
    if not slots:
        raise GameError(f"第 {index} 套还没有保存任何配装。")
    current = equipment.loadout(ctx, pet.pet_id)
    if slots == current:
        raise GameError(f"当前穿戴已经是第 {index} 套，无需更换。")
    missing = [
        _gear_name(ctx, item_id, enhancement)
        for slot, (item_id, enhancement) in slots.items()
        if current.get(slot) != (item_id, enhancement)
        and not _in_bag(ctx, item_id, enhancement, pet.pet_id)
    ]
    if missing:
        raise GameError("这些灵物已不在背包中：" + "、".join(missing) + "。")
    for slot in _SLOT_ORDER:
        if slot not in slots:
            continue
        item_id, enhancement = slots[slot]
        if current.get(slot) == (item_id, enhancement):
            continue
        take(ctx, item_id, enhancement)
        if slot in current:
            put(ctx, *current[slot])
        ctx.repo.conn.execute(
            "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(pet_id, slot) DO UPDATE SET item_id=excluded.item_id,"
            " enhancement=excluded.enhancement",
            (pet.pet_id, slot, item_id, enhancement),
        )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply(TITLE, (
        f"{pet.name}已换第 {index} 套：{_summary(ctx, slots)}。",
        "换下的灵物已退回背包。",
    ), (TITLE, "灵宠装备", "我的灵宠"))


def clear(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet, index = _requirement(ctx, arg)
    if not saved(ctx, pet.pet_id, index).get(index):
        raise GameError(f"第 {index} 套是空的。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{PREFIX}{pet.pet_id}_{index}_%"),
    )
    return Reply(TITLE, (
        f"已清除{pet.name}的第 {index} 套配装。",
        "伙伴身上正穿着的灵物不受影响。",
    ), (TITLE, "灵宠装备", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if head == "保存":
        return save(ctx, rest)
    if head == "应用":
        return apply(ctx, rest)
    if head == "清除":
        return clear(ctx, rest)
    raise GameError(f"格式：{TITLE} [保存|应用|清除 序号] [编号]。")


def objective_line(ctx: Context, user_id: str) -> str:
    """Deliberately not surfaced: a preset is a convenience, not progress."""
    return ""


__all__ = [
    "PREFIX", "PRESET_COUNT", "TITLE", "apply", "clear", "dispatch", "page", "save", "saved",
]
