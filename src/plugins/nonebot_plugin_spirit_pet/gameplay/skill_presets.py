"""Per-pet skill presets: save three battle-ready skill loadouts.

A preset stores the set of carried skills, not their mastery or any pet stat.
Rows live in `quest_progress` so schema 20 stays frozen:

* `skill_preset_<pet_id>_<slot>` marks the slot and stores its skill count in
  `progress`;
* `skill_preset_<pet_id>_<slot>_<skill_id>` marks one carried skill.

Per-skill rows (rather than one bitmask) keep presets readable when the skill
catalog grows or a skill id changes: unknown entries can be rejected explicitly
instead of silently shifting bit positions. Saving and applying never spend
resources, and applying validates every stored skill before touching
`learned_skills`, so a bad preset cannot partially change a loadout.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from . import skills
from .ascension_rules import skill_slots
from .compatibility import check_requirements

SLOTS = (1, 2, 3)
SLOT_PREFIX = "skill_preset_"
_ACTIONS = ("保存", "应用", "清除")
_COMMANDS = ("灵宠技能", "灵宠技能图鉴", "灵宠商店")


def _base(pet_id: int, slot: int) -> str:
    return f"{SLOT_PREFIX}{pet_id}_{slot}"


def _skill_ids(ctx: Context, pet_id: int, slot: int) -> list[str]:
    base = _base(pet_id, slot)
    prefix = f"{base}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{prefix}%"),
    )
    return sorted(
        row["quest_id"][len(prefix):]
        for row in rows
        if row["quest_id"].startswith(prefix)
    )


def _saved(ctx: Context, pet_id: int, slot: int) -> list[str] | None:
    """The stored skill ids, or None when the slot was never saved."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _base(pet_id, slot)),
    ).fetchone()
    return None if row is None else _skill_ids(ctx, pet_id, slot)


def _delete(ctx: Context, pet_id: int, slot: int) -> None:
    base = _base(pet_id, slot)
    for key in [base, *(f"{base}_{skill_id}" for skill_id in _skill_ids(ctx, pet_id, slot))]:
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
            (ctx.user_id, key),
        )


def _skill_name(ctx: Context, skill_id: str) -> str:
    skill = ctx.content.skills.get(skill_id)
    return skill.name if skill else f"未知灵术({skill_id})"


def _reply(lines: tuple[str, ...], slot: int | None = None) -> Reply:
    commands = _COMMANDS if slot is None else (*_COMMANDS, "灵宠技能预设")
    return Reply("技能预设", lines, commands)


def catalog(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("技能预设", (
            "每只伙伴可保存 3 套战前灵术配置，切换时不必逐门携带或卸下。",
            "尚未结契，先完成领养，再配置自己的灵术方案。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))
    pet = ctx.pet()
    current = {skill_id for skill_id, equipped in skills.learned(ctx, pet.pet_id).items() if equipped}
    lines = [
        f"{pet.name} · 携带上限 {skill_slots(ctx, pet)} 门 · 当前："
        + ("、".join(_skill_name(ctx, skill_id) for skill_id in sorted(current)) or "无"),
        "每只伙伴可保存 3 套方案；应用前会重新校验学习记录、适用条件与携带上限。",
    ]
    links = []
    for slot in SLOTS:
        stored = _saved(ctx, pet.pet_id, slot)
        if stored is None:
            lines.append(f"方案 {slot} · 未保存")
            links.append(InlineCommand(len(lines) - 1, "保存当前", f"灵宠技能预设 保存 {slot}"))
            continue
        names = "、".join(_skill_name(ctx, skill_id) for skill_id in stored) or "空方案"
        state = "已应用" if set(stored) == current else "已保存"
        lines.append(f"方案 {slot} · {state} · {names}")
        line = len(lines) - 1
        links.extend((
            InlineCommand(line, "保存当前", f"灵宠技能预设 保存 {slot}"),
            InlineCommand(line, "应用", f"灵宠技能预设 应用 {slot}"),
            InlineCommand(line, "清除", f"灵宠技能预设 清除 {slot}"),
        ))
    return Reply(f"技能预设 · {pet.name}", tuple(lines), _COMMANDS, tuple(links))


def save(ctx: Context, pet, slot: int) -> Reply:
    current = skills.learned(ctx, pet.pet_id)
    target = sorted(skill_id for skill_id, equipped in current.items() if equipped)
    limit = skill_slots(ctx, pet)
    if len(target) > limit:
        raise GameError(f"当前携带 {len(target)} 门，已超过上限 {limit} 门，请先调整后再保存。")
    _delete(ctx, pet.pet_id, slot)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (ctx.user_id, _base(pet.pet_id, slot), len(target)),
    )
    for skill_id in target:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (ctx.user_id, f"{_base(pet.pet_id, slot)}_{skill_id}"),
        )
    return _reply((
        f"方案 {slot} 已保存：{'、'.join(_skill_name(ctx, skill_id) for skill_id in target) or '空方案'}。",
        "保存不消耗资源；应用时会重新校验学习记录与适用条件。",
    ), slot)


def apply(ctx: Context, pet, slot: int) -> Reply:
    ctx.require_idle_pet(pet)
    stored = _saved(ctx, pet.pet_id, slot)
    if stored is None:
        raise GameError(f"方案 {slot} 尚未保存，请先发送 灵宠技能预设 保存 {slot}。")
    current = skills.learned(ctx, pet.pet_id)
    limit = skill_slots(ctx, pet)
    if len(stored) > limit:
        raise GameError(f"方案 {slot} 有 {len(stored)} 门灵术，超过当前携带上限 {limit} 门。")
    for skill_id in stored:
        skill = ctx.content.skills.get(skill_id)
        if skill is None:
            raise GameError(f"方案 {slot} 包含已不存在的灵术：{skill_id}。")
        if skill_id not in current:
            raise GameError(f"方案 {slot} 包含尚未学会的灵术：{skill.name}。")
        check_requirements(ctx, pet, skill.requirements)
    target = set(stored)
    if {skill_id for skill_id, equipped in current.items() if equipped} == target:
        return _reply((f"方案 {slot} 已是当前配置，未做改动。",), slot)
    ctx.repo.conn.execute(
        "UPDATE learned_skills SET equipped=0 WHERE pet_id=?", (pet.pet_id,),
    )
    for skill_id in stored:
        ctx.repo.conn.execute(
            "UPDATE learned_skills SET equipped=1 WHERE pet_id=? AND skill_id=?",
            (pet.pet_id, skill_id),
        )
    ctx.repo.invalidate_ready(ctx.user_id)
    return _reply((
        f"已应用方案 {slot}：{'、'.join(_skill_name(ctx, skill_id) for skill_id in stored) or '全部卸下'}。",
        f"当前携带 {len(stored)}/{limit} 门；技能等级与熟练度未改变。",
    ), slot)


def clear(ctx: Context, pet, slot: int) -> Reply:
    if _saved(ctx, pet.pet_id, slot) is None:
        return _reply((f"方案 {slot} 本来就是空的，未做改动。",), slot)
    _delete(ctx, pet.pet_id, slot)
    return _reply((
        f"方案 {slot} 已清除。",
        "当前携带的灵术不会被卸下；如需恢复，请重新保存或逐门调整。",
    ), slot)


def _slot(value: str) -> int:
    if value not in {"1", "2", "3"}:
        raise GameError("方案编号是 1-3。")
    return int(value)


def entry(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if len(parts) != 2 or parts[0] not in _ACTIONS:
        raise GameError("格式：灵宠技能预设 [保存|应用|清除] <1-3>。")
    action, value = parts
    slot = _slot(value)
    pet = ctx.pet()
    if action == "保存":
        return save(ctx, pet, slot)
    if action == "应用":
        return apply(ctx, pet, slot)
    return clear(ctx, pet, slot)
