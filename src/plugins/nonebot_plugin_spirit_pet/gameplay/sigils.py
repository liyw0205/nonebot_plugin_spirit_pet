"""Pet sigils: two flat-stat slots per pet, unlocked by account or pet progress.

A sigil is never bought or consumed — it unlocks once the player's derived progress reaches its
requirement, and from then on it can be moved between pets freely. State is one ``quest_progress``
row per occupied slot, keyed ``sigil_<pet_id>_<slot>_<sigil_id>`` (the sigil id must live in the key
because ``progress`` is an integer).

Unlock sources are all derived, so no counter is duplicated: claimed achievements, distinct species
collected, the pet's bond level and the pet's realm.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from .achievements import claimed_count
from .bond_levels import current_level
from .collection_rank import collected_species

PREFIX = "sigil_"
SLOTS = 2
STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
KIND_LABELS = {"achievements": "成就领取", "collection": "收集种族", "bond": "羁绊等级", "realm": "境界"}


def equipped(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[int, str]:
    """Slot number → sigil id for this pet, read from the key prefix."""
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{PREFIX}{pet_id}_%"),
    ).fetchall()
    filled = {}
    for row in rows:
        rest = row["quest_id"][len(PREFIX) + len(str(pet_id)) + 1:]
        slot_text, _, sigil_id = rest.partition("_")
        if slot_text.isdecimal() and sigil_id in ctx.content.sigils:
            filled[int(slot_text)] = sigil_id
    return filled


def _progress(ctx: Context, kind: str, pet, user_id: str | None = None) -> int:
    owner = user_id or ctx.user_id
    if kind == "achievements":
        return claimed_count(ctx, owner)
    if kind == "collection":
        return collected_species(ctx, owner)
    if kind == "bond":
        return current_level(ctx, pet.pet_id)
    if kind == "realm":
        return pet.realm + 1
    raise GameError("未知的符印解锁条件。")


def requirement_text(ctx: Context, sigil, pet=None, user_id: str | None = None) -> str:
    rule = sigil.requires
    label = KIND_LABELS[rule.kind]
    if pet is None:
        return f"{label} {rule.value}"
    return f"{label} {_progress(ctx, rule.kind, pet, user_id)}/{rule.value}"


def unlocked(ctx: Context, sigil, pet, user_id: str | None = None) -> bool:
    return _progress(ctx, sigil.requires.kind, pet, user_id) >= sigil.requires.value


def bonus_text(ctx: Context, sigil) -> str:
    return "、".join(
        f"{STAT_LABELS[key]} +{value}"
        for key, value in sigil.bonuses.model_dump().items() if value
    )


def total_bonus(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, int]:
    totals = {"hp": 0, "attack": 0, "defense": 0, "speed": 0}
    for sigil_id in equipped(ctx, pet_id, user_id).values():
        for key, value in ctx.content.sigils[sigil_id].bonuses.model_dump().items():
            totals[key] += value
    return totals


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠符印 [装备 <符印>|卸下 <符印>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠符印",
            (
                "尚未结契，先完成领养，才能为伙伴镶嵌符印。",
                "符印不需要材料：达成成就、收集、羁绊或境界条件后自动解锁，可自由换给其他伙伴。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.pet()
    filled = equipped(ctx, pet.pet_id)
    slots_text = "、".join(
        f"{slot}号 {ctx.content.sigils[sigil_id].name}" for slot, sigil_id in sorted(filled.items())
    ) or "空"
    lines = [
        f"{pet.name}：符印槽 {len(filled)}/{SLOTS} · {slots_text}。",
        "符印提供固定四维加成，不参与任何倍率；每只伙伴两个槽，同一枚符印不能重复装备。",
    ]
    links = []
    for sigil in ctx.content.sigils.values():
        owned = sigil.id in filled.values()
        if owned:
            state = "已装备"
        elif unlocked(ctx, sigil, pet):
            state = "可装备"
        else:
            state = f"未解锁（{requirement_text(ctx, sigil, pet)}）"
        lines.append(
            f"{sigil.name} · {bonus_text(ctx, sigil)} · 需要 {requirement_text(ctx, sigil, pet)} · {state}"
        )
        row = len(lines) - 1
        if owned:
            links.append(InlineCommand(row, "卸下", f"灵宠符印 卸下 {sigil.name}"))
        elif state == "可装备" and len(filled) < SLOTS:
            links.append(InlineCommand(row, "装备", f"灵宠符印 装备 {sigil.name}"))
    lines.append("格式：灵宠符印 装备 <符印> / 灵宠符印 卸下 <符印>。")
    return Reply("灵宠符印", tuple(lines), ("灵宠符印", "我的灵宠", "灵宠技能"), tuple(links))


def equip(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠符印 装备 <符印>。")
    pet = ctx.pet()
    sigil = named(ctx.content.sigils, arg)
    filled = equipped(ctx, pet.pet_id)
    if sigil.id in filled.values():
        raise GameError(f"{pet.name}已经装备了{sigil.name}。")
    if not unlocked(ctx, sigil, pet):
        raise GameError(
            f"{sigil.name}尚未解锁：需要 {requirement_text(ctx, sigil, pet)}。"
        )
    if len(filled) >= SLOTS:
        raise GameError(f"{pet.name}的两个符印槽都已占用，请先卸下一枚。")
    ctx.require_idle_pet(pet)

    slot = next(number for number in range(1, SLOTS + 1) if number not in filled)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1)"
        " ON CONFLICT(user_id, quest_id) DO NOTHING",
        (ctx.user_id, f"{PREFIX}{pet.pet_id}_{slot}_{sigil.id}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("镶嵌符印", (
        f"{pet.name}在 {slot} 号槽装备了{sigil.name}：{bonus_text(ctx, sigil)}。",
        f"符印槽 {len(filled) + 1}/{SLOTS}；符印不消耗材料，可随时卸下换给其他伙伴。",
    ), ("灵宠符印", "我的灵宠"))


def unequip(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠符印 卸下 <符印>。")
    pet = ctx.pet()
    sigil = named(ctx.content.sigils, arg)
    filled = equipped(ctx, pet.pet_id)
    slots = [slot for slot, sigil_id in filled.items() if sigil_id == sigil.id]
    if not slots:
        raise GameError(f"{pet.name}没有装备{sigil.name}。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{PREFIX}{pet.pet_id}_{slots[0]}_{sigil.id}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("卸下符印", (
        f"{pet.name}卸下了{sigil.name}，{slots[0]} 号槽空出。",
        "符印仍在，解锁状态不会消失。",
    ), ("灵宠符印", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "装备":
        return equip(ctx, " ".join(parts[1:]))
    if parts[0] == "卸下":
        return unequip(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠符印 [装备 <符印>|卸下 <符印>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None or player.active_pet_id is None:
        return "符印：尚未选择主战灵宠"
    filled = equipped(ctx, player.active_pet_id, user_id)
    return f"符印：已装备 {len(filled)}/{SLOTS}"
