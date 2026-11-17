"""Lineup presets: three stored rosters the player can switch to in one command.

Switching rosters is the most repeated pre-fight action in the game, and every switch currently
means retyping the pet ids of the current trio. A preset snapshots the roster; applying one validates
every member again (still owned, not sealed, not on an expedition, still 1-3 distinct species) before
any write, so a stale preset can never drop the player into an illegal lineup.

State is `quest_progress`: `lineup_preset_<n>` (``progress`` = member count) plus one row per member,
`lineup_preset_<n>_<pet_id>`. Keeping members in rows instead of a "1 2 3" string means ids are never
re-parsed and a removed pet simply fails to match.
"""

from collections import Counter

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from . import equipment, formation, skills
from .ascension_rules import skill_slots
from .compatibility import check_requirements
from .equipment_inventory import put, take

MARKER = "lineup_preset_"
TACTIC_MARKER = "lineup_tactic_"
SLOTS = (1, 2, 3)


def _marker(slot: int) -> str:
    return f"{MARKER}{slot}"


def _member_prefix(slot: int) -> str:
    return f"{MARKER}{slot}_"


def _member(slot: int, pet_id: int) -> str:
    return f"{_member_prefix(slot)}{pet_id}"


def _tactic_prefix(slot: int) -> str:
    return f"{TACTIC_MARKER}{slot}_"


def _tactic_key(slot: int, kind: str, pet_id: int, *parts: str | int) -> str:
    suffix = "_".join(str(part) for part in parts)
    return f"{_tactic_prefix(slot)}{kind}_{pet_id}" + (f"_{suffix}" if suffix else "")


def _tactic_exists(ctx: Context, slot: int) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id LIKE ? LIMIT 1",
        (ctx.user_id, f"{_tactic_prefix(slot)}%"),
    ).fetchone() is not None


def _tactic_snapshot(ctx: Context, slot: int, pet_ids: tuple[int, ...]):
    if not _tactic_exists(ctx, slot):
        return None
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{_tactic_prefix(slot)}%"),
    ).fetchall()
    if not any(row["quest_id"] == f"{_tactic_prefix(slot)}v1" for row in rows):
        raise GameError("战术预设版本记录不完整，请重新保存该预设。")
    formations: dict[int, str] = {}
    skill_counts: dict[int, int] = {}
    selected_skills: dict[int, set[str]] = {}
    gear_counts: dict[int, int] = {}
    selected_gear: dict[int, dict[str, tuple[str, int]]] = {}
    recorded_pet_ids: set[int] = set()
    prefix = _tactic_prefix(slot)
    for row in rows:
        key = row["quest_id"][len(prefix):]
        if key == "v1":
            if int(row["progress"]) != 1 or int(row["claimed"]) != 1:
                raise GameError("战术预设版本记录无效，请重新保存该预设。")
            continue
        if int(row["claimed"]) != 1:
            raise GameError("战术预设的成员记录不完整，请重新保存该预设。")
        if key.startswith("skill_count_") or key.startswith("gear_count_"):
            kind, pet_text = key.rsplit("_", 1)
            if not pet_text.isdecimal():
                raise GameError("战术预设的成员编号无效，请重新保存该预设。")
            pet_id = int(pet_text)
            recorded_pet_ids.add(pet_id)
            (skill_counts if kind == "skill_count" else gear_counts)[pet_id] = int(row["progress"])
            continue
        kind, _, rest = key.partition("_")
        pet_text, _, detail = rest.partition("_")
        if not pet_text.isdecimal():
            raise GameError("战术预设的成员编号无效，请重新保存该预设。")
        pet_id = int(pet_text)
        recorded_pet_ids.add(pet_id)
        if kind == "formation" and detail:
            if pet_id in formations:
                raise GameError("战术预设的阵位记录不完整，请重新保存该预设。")
            formations[pet_id] = detail
        elif kind == "skill" and detail:
            selected_skills.setdefault(pet_id, set()).add(detail)
        elif kind == "gear" and detail:
            gear = detail.split("_", 2)
            if len(gear) != 3 or not gear[1].isdecimal() or not gear[2]:
                raise GameError("战术预设的装备记录不完整，请重新保存该预设。")
            equipment_slot, enhancement, item_id = gear[0], int(gear[1]), gear[2]
            member_gear = selected_gear.setdefault(pet_id, {})
            if equipment_slot in member_gear:
                raise GameError("战术预设重复记录了同一装备位置，请重新保存该预设。")
            member_gear[equipment_slot] = (item_id, enhancement)
        else:
            raise GameError("战术预设包含无法识别的配置，请重新保存该预设。")

    expected = set(pet_ids)
    if (recorded_pet_ids != expected or set(skill_counts) != expected
            or set(gear_counts) != expected):
        raise GameError("战术预设的伙伴记录不完整，请重新保存该预设。")
    for pet_id in pet_ids:
        if len(selected_skills.get(pet_id, set())) != skill_counts[pet_id]:
            raise GameError("战术预设的灵术记录不完整，请重新保存该预设。")
        if len(selected_gear.get(pet_id, {})) != gear_counts[pet_id]:
            raise GameError("战术预设的装备记录不完整，请重新保存该预设。")
    return {
        "formations": formations,
        "skills": selected_skills,
        "gear": selected_gear,
    }


def _save_tactic(ctx: Context, slot: int, pet_ids: tuple[int, ...]) -> None:
    prefix = _tactic_prefix(slot)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{prefix}%"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, f"{prefix}v1"),
    )
    for pet_id in pet_ids:
        position = formation.position_of(ctx, pet_id)
        if position is not None:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, _tactic_key(slot, "formation", pet_id, position)),
            )
        selected = {key for key, active in skills.learned(ctx, pet_id).items() if active}
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (ctx.user_id, _tactic_key(slot, "skill_count", pet_id), len(selected)),
        )
        for skill_id in selected:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, _tactic_key(slot, "skill", pet_id, skill_id)),
            )
        gear = equipment.loadout(ctx, pet_id)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (ctx.user_id, _tactic_key(slot, "gear_count", pet_id), len(gear)),
        )
        for equipment_slot, (item_id, enhancement) in gear.items():
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, _tactic_key(
                    slot, "gear", pet_id, equipment_slot, enhancement, item_id,
                )),
            )


def _inventory_quantity(ctx: Context, item_id: str, enhancement: int) -> int:
    if enhancement == 0:
        row = ctx.repo.conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
            (ctx.user_id, item_id),
        ).fetchone()
    else:
        row = ctx.repo.conn.execute(
            "SELECT quantity FROM unequipped_equipment WHERE user_id=? AND item_id=? AND enhancement=?",
            (ctx.user_id, item_id, enhancement),
        ).fetchone()
    return int(row["quantity"]) if row is not None else 0


def _validate_tactic(ctx: Context, pet_ids: tuple[int, ...], snapshot) -> None:
    if snapshot is None:
        return
    for pet_id in pet_ids:
        pet = ctx.repo.pet(pet_id)
        ctx.require_idle_pet(pet)
        position = snapshot["formations"].get(pet_id)
        if position is not None and position not in ctx.content.formations.by_id:
            raise GameError(f"{pet.name}的阵位已不在当前内容中，请重新保存战术预设。")

        learned = skills.learned(ctx, pet_id)
        selected = snapshot["skills"].get(pet_id, set())
        if len(selected) > skill_slots(ctx, pet):
            raise GameError(f"{pet.name}的战术灵术超过当前携带上限。")
        for skill_id in selected:
            skill = ctx.content.skills.get(skill_id)
            if skill is None:
                raise GameError(f"{pet.name}的战术包含已下线灵术 {skill_id}，请重新保存。")
            if skill_id not in learned:
                raise GameError(f"{pet.name}已不再拥有灵术 {skill.name}，请重新保存战术预设。")
            check_requirements(ctx, pet, skill.requirements)

        for equipment_slot, (item_id, enhancement) in snapshot["gear"].get(pet_id, {}).items():
            item = ctx.content.items.get(item_id)
            if item is None or item.kind != "equipment" or item.equipment_id is None:
                raise GameError(f"{pet.name}的战术装备已下线，请重新保存战术预设。")
            gear = ctx.content.equipment.get(item.equipment_id)
            if (gear is None or gear.slot != equipment_slot or equipment_slot not in equipment.SLOTS
                    or enhancement not in ctx.content.forge_levels):
                raise GameError(f"{pet.name}的战术装备记录不兼容，请重新保存战术预设。")
            check_requirements(ctx, pet, gear.requirements)

    current = {pet_id: equipment.loadout(ctx, pet_id) for pet_id in pet_ids}
    needed: Counter[tuple[str, int]] = Counter()
    returned: Counter[tuple[str, int]] = Counter()
    for pet_id in pet_ids:
        target = snapshot["gear"].get(pet_id, {})
        for equipment_slot, current_gear in current[pet_id].items():
            if target.get(equipment_slot) != current_gear:
                item = ctx.content.items.get(current_gear[0])
                if (item is None or item.kind != "equipment" or item.equipment_id is None
                        or current_gear[1] not in ctx.content.forge_levels):
                    raise GameError("当前穿戴的装备内容已失效，无法安全换出；阵容与装备未更改。")
                returned[current_gear] += 1
        for equipment_slot, target_gear in target.items():
            if current[pet_id].get(equipment_slot) != target_gear:
                needed[target_gear] += 1
    for (item_id, enhancement), amount in needed.items():
        available = _inventory_quantity(ctx, item_id, enhancement) + returned[item_id, enhancement]
        if available < amount:
            name = ctx.content.items[item_id].name
            raise GameError(f"战术装备不足：{name} +{enhancement} 需要 {amount} 件，可用 {available} 件。")


def _apply_tactic(ctx: Context, pet_ids: tuple[int, ...], snapshot) -> None:
    ctx.repo.set_active_pets(ctx.user_id, list(pet_ids))
    for pet_id in pet_ids:
        position = snapshot["formations"].get(pet_id)
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
            (ctx.user_id, f"formation_{pet_id}_%"),
        )
        if position is not None:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, f"formation_{pet_id}_{position}"),
            )
        ctx.repo.conn.execute(
            "UPDATE learned_skills SET equipped=0 WHERE pet_id=?", (pet_id,),
        )
        for skill_id in snapshot["skills"].get(pet_id, set()):
            ctx.repo.conn.execute(
                "UPDATE learned_skills SET equipped=1 WHERE pet_id=? AND skill_id=?",
                (pet_id, skill_id),
            )

    changes = []
    for pet_id in pet_ids:
        current = equipment.loadout(ctx, pet_id)
        target = snapshot["gear"].get(pet_id, {})
        for equipment_slot in equipment.SLOTS:
            old, new = current.get(equipment_slot), target.get(equipment_slot)
            if old != new:
                changes.append((pet_id, equipment_slot, old, new))
    for pet_id, equipment_slot, old, _ in changes:
        if old is None:
            continue
        put(ctx, *old)
        ctx.repo.conn.execute(
            "DELETE FROM equipment WHERE pet_id=? AND slot=?", (pet_id, equipment_slot),
        )
    for pet_id, equipment_slot, _, new in changes:
        if new is None:
            continue
        item_id, enhancement = new
        take(ctx, item_id, enhancement)
        ctx.repo.conn.execute(
            "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, ?)",
            (pet_id, equipment_slot, item_id, enhancement),
        )


def _tactic_matches_current(ctx: Context, pet_ids: tuple[int, ...], snapshot) -> bool:
    for pet_id in pet_ids:
        if formation.position_of(ctx, pet_id) != snapshot["formations"].get(pet_id):
            return False
        current_skills = {key for key, active in skills.learned(ctx, pet_id).items() if active}
        if current_skills != snapshot["skills"].get(pet_id, set()):
            return False
        if equipment.loadout(ctx, pet_id) != snapshot["gear"].get(pet_id, {}):
            return False
    return True


def _tactic_status(ctx: Context, slot: int, pet_ids: tuple[int, ...]) -> str:
    if not _tactic_exists(ctx, slot):
        return "旧式阵容（只保存伙伴编号）"
    try:
        snapshot = _tactic_snapshot(ctx, slot, pet_ids)
        _validate_tactic(ctx, pet_ids, snapshot)
    except GameError as exc:
        return f"战术暂不可应用（{exc}）"
    positions = sum(1 for pet_id in pet_ids if pet_id in snapshot["formations"])
    skill_count = sum(len(snapshot["skills"].get(pet_id, set())) for pet_id in pet_ids)
    gear_count = sum(len(snapshot["gear"].get(pet_id, {})) for pet_id in pet_ids)
    current = tuple(pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id))
    applied = current == pet_ids and _tactic_matches_current(ctx, pet_ids, snapshot)
    state = "已应用" if applied else "已保存"
    return f"完整战术 · {state} · 阵位 {positions}/{len(pet_ids)} · 灵术 {skill_count} · 装备 {gear_count}"


def slots_of(ctx: Context) -> dict[int, tuple[int, ...]]:
    """Every stored preset, preserving explicit order and the legacy id sort."""
    stored: dict[int, dict[int, int]] = {}
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
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
        stored.setdefault(slot, {})[int(tail)] = int(row["progress"])
    result = {}
    for slot in SLOTS:
        members = stored.get(slot, {})
        order = list(members.values())
        if len(set(order)) == len(order) and set(order) == set(range(1, len(order) + 1)):
            result[slot] = tuple(pet_id for pet_id, _ in sorted(members.items(), key=lambda item: item[1]))
        else:
            result[slot] = tuple(sorted(members))
    return result


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
    lines = [f"当前出战：{_names(ctx, current)}。"]
    links = []
    for slot in SLOTS:
        members = stored_slots[slot]
        state = "空"
        if members:
            problems = _problems(ctx, members)
            tactic = _tactic_status(ctx, slot, members)
            state = (
                f"可应用 · {_names(ctx, members)} · {tactic}"
                if not problems and not tactic.startswith("战术暂不可应用")
                else f"不可应用（{problems[0] if problems else tactic}）· {_names(ctx, members)}"
            )
            if members == current and tactic.startswith("旧式阵容"):
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
    problems = _problems(ctx, current)
    if problems:
        raise GameError(f"当前阵容不能保存：{problems[0]}。")
    clear(ctx, str(slot), quiet=True)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)",
        (ctx.user_id, _marker(slot), len(current)),
    )
    for order, pet_id in enumerate(current, 1):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)",
            (ctx.user_id, _member(slot, pet_id), order),
        )
    _save_tactic(ctx, slot, current)
    _validate_tactic(ctx, current, _tactic_snapshot(ctx, slot, current))
    return Reply(
        "预设已保存",
        (
            f"预设 {slot} 已保存当前战术：{_names(ctx, current)}。",
            "已快照每位伙伴的阵位、携带灵术与真实装备；应用时会校验并原子恢复，不复制装备。",
        ),
        ("灵宠出战预设", "灵宠阵位", "灵宠整备"),
    )


def apply(ctx: Context, arg: str) -> Reply:
    slot = _slot(arg, "格式：灵宠出战预设 应用 <1-3>。")
    player = ctx.player()
    members = stored(ctx, slot)
    problems = _problems(ctx, members)
    if problems:
        raise GameError(f"预设 {slot} 暂时不能应用：{problems[0]}。")
    snapshot = _tactic_snapshot(ctx, slot, members)
    if snapshot is not None:
        _validate_tactic(ctx, members, snapshot)
    current = tuple(pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id))
    if current == members and (snapshot is None or _tactic_matches_current(ctx, members, snapshot)):
        return Reply(
            "预设已应用",
            (f"预设 {slot} 与当前阵容一致，伙伴战术也已应用：{_names(ctx, members)}。",),
            ("灵宠出战预设", "灵宠出战", "灵宠整备"),
        )
    if snapshot is None:
        ctx.repo.set_active_pets(ctx.user_id, list(members))
    else:
        _apply_tactic(ctx, members, snapshot)
    ctx.repo.invalidate_ready(player.user_id)
    return Reply(
        "预设已应用",
        (
            f"已应用预设 {slot}：{_names(ctx, members)}。",
            "已恢复阵位、携带灵术与真实装备；技能成长、同心、精力与背包中的装备数量保持守恒。"
            if snapshot is not None else "这是旧版阵容预设，只切换伙伴；其他配置保持不变。",
        ),
        ("灵宠出战预设", "灵宠阵位", "灵宠整备"),
    )


def clear(ctx: Context, arg: str, *, quiet: bool = False) -> Reply:
    slot = _slot(arg, "格式：灵宠出战预设 清除 <1-3>。")
    ctx.player()
    had = stored(ctx, slot)
    had_tactic = _tactic_exists(ctx, slot)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND (quest_id=? OR quest_id LIKE ?)",
        (ctx.user_id, _marker(slot), f"{_member_prefix(slot)}%"),
    )
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{_tactic_prefix(slot)}%"),
    )
    if quiet:
        return Reply("预设已清除", ())
    if not had and not had_tactic:
        raise GameError(f"预设 {slot} 尚未保存。")
    return Reply(
        "预设已清除",
        (f"预设 {slot} 已清除（原阵容：{_names(ctx, had)}，{'含战术快照' if had_tactic else '旧版阵容'}），当前伙伴配置不变。",),
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
