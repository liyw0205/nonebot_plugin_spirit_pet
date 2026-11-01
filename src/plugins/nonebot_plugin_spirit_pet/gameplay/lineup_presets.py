"""Lineup presets: three stored rosters the player can switch to in one command.

Switching rosters is the most repeated pre-fight action in the game, and every switch currently
means retyping the pet ids of the current trio. A preset snapshots the roster; applying one validates
every member again (still owned, not sealed, not on an expedition, still 1-3 distinct species) before
any write, so a stale preset can never drop the player into an illegal lineup.

State is `quest_progress`: `lineup_preset_<n>` (``progress`` = member count) plus one row per member,
`lineup_preset_<n>_<pet_id>`. Keeping members in rows instead of a "1 2 3" string means ids are never
re-parsed and a removed pet simply fails to match.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply

MARKER = "lineup_preset_"
SLOTS = (1, 2, 3)


def _marker(slot: int) -> str:
    return f"{MARKER}{slot}"


def _member_prefix(slot: int) -> str:
    return f"{MARKER}{slot}_"


def _member(slot: int, pet_id: int) -> str:
    return f"{_member_prefix(slot)}{pet_id}"


def slots_of(ctx: Context) -> dict[int, tuple[int, ...]]:
    """Every stored preset: slot -> ordered pet ids (empty tuple when unset)."""
    stored: dict[int, set[int]] = {}
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{MARKER}%"),
    ).fetchall()
    for row in rows:
        rest = row["quest_id"][len(MARKER):]
        head, _, tail = rest.partition("_")
        if not head.isdecimal() or not tail:
            continue
        slot = int(head)
        if slot not in SLOTS or not tail.isdecimal():
            continue
        stored.setdefault(slot, set()).add(int(tail))
    return {slot: tuple(sorted(stored.get(slot, ()))) for slot in SLOTS}


def stored(ctx: Context, slot: int) -> tuple[int, ...]:
    return slots_of(ctx).get(slot, ())


def _problems(ctx: Context, pet_ids: tuple[int, ...]) -> list[str]:
    """Why this stored set cannot be applied right now (empty when it can)."""
    if not pet_ids:
        return ["未保存"]
    if not 1 <= len(pet_ids) <= 3:
        return ["超出三只"]
    pets = []
    for pet_id in pet_ids:
        row = ctx.repo.conn.execute(
            "SELECT pet_id, user_id, species_id, name, archived FROM pets WHERE pet_id=?", (pet_id,),
        ).fetchone()
        if row is None or row["user_id"] != ctx.user_id:
            return ["其中一只已不在名册"]
        if row["archived"]:
            return [f"{row['name']}已封存"]
        pets.append(row)
    species = [row["species_id"] for row in pets]
    if len(set(species)) != len(species):
        return ["存在重复种类"]
    for row in pets:
        if ctx.repo.active_expedition(row["pet_id"]) is not None:
            return [f"{row['name']}正在外出派遣"]
    return []


def _names(ctx: Context, pet_ids: tuple[int, ...]) -> str:
    if not pet_ids:
        return "空"
    parts = []
    for pet_id in pet_ids:
        row = ctx.repo.conn.execute("SELECT name FROM pets WHERE pet_id=?", (pet_id,)).fetchone()
        parts.append(row["name"] if row else f"#{pet_id}")
    return "、".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠出战预设 [保存|应用|清除 <1-3>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠出战预设",
            ("尚未结契，先完成领养，才能保存出战预设。", "三套预设各自保存一支出战阵容，随时一键切换。"),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    current = tuple(pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id))
    stored_slots = slots_of(ctx)
    lines = [f"当前出战：{_names(ctx, current)}；预设保存的是阵容，不会自动更换阵位与同心。"]
    links = []
    for slot in SLOTS:
        members = stored_slots[slot]
        state = "空"
        if members:
            problems = _problems(ctx, members)
            state = f"可应用 · {_names(ctx, members)}" if not problems else f"不可应用（{problems[0]}）· {_names(ctx, members)}"
            if members == current:
                state += " · 已应用"
        lines.append(f"预设 {slot}：{state}")
        if members:
            links.append(InlineCommand(len(lines) - 1, "应用", f"灵宠出战预设 应用 {slot}"))
            links.append(InlineCommand(len(lines) - 1, "清除", f"灵宠出战预设 清除 {slot}"))
        if current:
            links.append(InlineCommand(len(lines) - 1, "保存", f"灵宠出战预设 保存 {slot}"))
    return Reply("灵宠出战预设", tuple(lines), ("灵宠出战预设", "灵宠出战", "我的灵宠"), tuple(links))


def _slot(arg: str, usage: str) -> int:
    text = arg.strip()
    if not text.isdecimal() or int(text) not in SLOTS:
        raise GameError(usage)
    return int(text)


def save(ctx: Context, arg: str) -> Reply:
    slot = _slot(arg, "格式：灵宠出战预设 保存 <1-3>。")
    ctx.player()
    current = tuple(pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id))
    if not current:
        raise GameError("当前没有出战阵容，先用 灵宠出战 安排。")
    clear(ctx, str(slot), quiet=True)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)",
        (ctx.user_id, _marker(slot), len(current)),
    )
    for pet_id in current:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
            (ctx.user_id, _member(slot, pet_id)),
        )
    return Reply(
        "预设已保存",
        (f"预设 {slot} 已保存当前阵容：{_names(ctx, current)}。", "应用该预设即可一键切回这套阵容。"),
        ("灵宠出战预设", "灵宠出战"),
    )


def apply(ctx: Context, arg: str) -> Reply:
    slot = _slot(arg, "格式：灵宠出战预设 应用 <1-3>。")
    player = ctx.player()
    members = stored(ctx, slot)
    problems = _problems(ctx, members)
    if problems:
        raise GameError(f"预设 {slot} 暂时不能应用：{problems[0]}。")
    current = tuple(pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id))
    if current == members:
        return Reply(
            "预设已应用",
            (f"预设 {slot} 与当前阵容一致：{_names(ctx, members)}。",),
            ("灵宠出战预设", "灵宠出战"),
        )
    ctx.repo.set_active_pets(ctx.user_id, list(members))
    ctx.repo.invalidate_ready(player.user_id)
    return Reply(
        "预设已应用",
        (f"出战阵容已切到预设 {slot}：{_names(ctx, members)}。", "阵位与同心按各伙伴自身设置继续生效。"),
        ("灵宠出战预设", "灵宠阵位", "我的灵宠"),
    )


def clear(ctx: Context, arg: str, *, quiet: bool = False) -> Reply:
    slot = _slot(arg, "格式：灵宠出战预设 清除 <1-3>。")
    ctx.player()
    had = stored(ctx, slot)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND (quest_id=? OR quest_id LIKE ?)",
        (ctx.user_id, _marker(slot), f"{_member_prefix(slot)}%"),
    )
    if quiet:
        return Reply("预设已清除", ())
    if not had:
        raise GameError(f"预设 {slot} 尚未保存。")
    return Reply(
        "预设已清除",
        (f"预设 {slot} 已清除（原阵容：{_names(ctx, had)}），当前出战阵容不变。",),
        ("灵宠出战预设", "灵宠出战"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    action = parts[0]
    rest = " ".join(parts[1:])
    if action == "保存":
        return save(ctx, rest)
    if action == "应用":
        return apply(ctx, rest)
    if action == "清除":
        return clear(ctx, rest)
    raise GameError("格式：灵宠出战预设 [保存|应用|清除 <1-3>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "出战预设：尚未结契"
    filled = sum(1 for members in slots_of(ctx).values() if members)
    return f"出战预设：已保存 {filled}/3" if filled else "出战预设：尚未保存"
