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
from .pet_targets import named_pet, note_prep_change, split_selector

PREFIX = "sigil_"
SLOTS = 2
STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
KIND_LABELS = {"achievements": "成就领取", "collection": "收集种族", "bond": "羁绊等级", "realm": "境界"}
RANK_PREFIX = "sigil_rank_"
RANKS = 3
RANK_STEP_PERCENT = 20
# 精炼到 N 阶的代价（灵石, 材料）——1 阶是解锁即可用的初始状态。
REFINE_COSTS = {
    2: (400, {"forge_ore": 2}),
    3: (1200, {"bloodline_essence": 2}),
}


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


def rank(ctx: Context, sigil_id: str, user_id: str | None = None) -> int:
    """Refinement rank of one sigil (1..RANKS); ranks are account-wide."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{RANK_PREFIX}{sigil_id}"),
    ).fetchone()
    if row is None:
        return 1
    return max(1, min(RANKS, int(row["progress"])))


def scaled(value: int, level: int) -> int:
    """Base bonus grown by 20% of itself per refinement step."""
    return value + value * (level - 1) * RANK_STEP_PERCENT // 100


def bonus_text(ctx: Context, sigil, level: int | None = None) -> str:
    level = rank(ctx, sigil.id) if level is None else level
    return "、".join(
        f"{STAT_LABELS[key]} +{scaled(value, level)}"
        for key, value in sigil.bonuses.model_dump().items() if value
    )


def total_bonus(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, int]:
    totals = {"hp": 0, "attack": 0, "defense": 0, "speed": 0}
    for sigil_id in equipped(ctx, pet_id, user_id).values():
        level = rank(ctx, sigil_id, user_id)
        for key, value in ctx.content.sigils[sigil_id].bonuses.model_dump().items():
            totals[key] += scaled(value, level)
    return totals


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠符印 [装备 <符印>|卸下 <符印>|精炼 <符印>|总览|伙伴 <名字|编号>]。")
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
    return _detail(ctx, pet)


def _detail(ctx: Context, pet) -> Reply:
    roster = {member.pet_id for member in ctx.repo.active_pets(ctx.user_id)}
    suffix = "" if pet.pet_id in roster else f" 伙伴 {pet.pet_id}"
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
        level = rank(ctx, sigil.id)
        rank_text = f"精炼 {level}/{RANKS}"
        lines.append(
            f"{sigil.name} · {bonus_text(ctx, sigil)} · {rank_text}"
            f" · 需要 {requirement_text(ctx, sigil, pet)} · {state}"
        )
        row = len(lines) - 1
        if owned:
            links.append(InlineCommand(row, "卸下", f"灵宠符印 卸下 {sigil.name}{suffix}"))
        elif state == "可装备" and len(filled) < SLOTS:
            links.append(InlineCommand(row, "装备", f"灵宠符印 装备 {sigil.name}{suffix}"))
        if level < RANKS and state != "未解锁" and not state.startswith("未解锁"):
            links.append(InlineCommand(
                row, f"精炼至{level + 1}阶", f"灵宠符印 精炼 {sigil.name}{suffix}",
            ))
    lines.append("格式：灵宠符印 装备 <符印> / 卸下 <符印> / 精炼 <符印>；为后备伙伴操作时在末尾加 伙伴 <名字|编号>。")
    return Reply("灵宠符印", tuple(lines), ("灵宠符印", "我的灵宠", "灵宠技能"), tuple(links))


def _total_text(totals: dict[str, int]) -> str:
    parts = [f"{STAT_LABELS[key]} +{value}" for key, value in totals.items() if value]
    return "、".join(parts) if parts else "无固定加成"


def overview(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠符印 总览。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠符印 总览", (
            "尚未结契，先完成领养，才能查看伙伴的符印配置。",
            "总览只读，不切换出战、不改变符印。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    pets = ctx.repo.owned_pets(ctx.user_id)
    active_ids = {pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id)}
    lines = [f"本命符印总览 · {len(pets)} 位伙伴。"]
    for pet in pets:
        filled = equipped(ctx, pet.pet_id)
        totals = total_bonus(ctx, pet.pet_id)
        unlocked_count = sum(
            1 for sigil in ctx.content.sigils.values() if unlocked(ctx, sigil, pet)
        )
        marker = " · 当前出战" if pet.pet_id in active_ids else ""
        lines.append(
            f"{pet.name}（编号 {pet.pet_id}）{marker} · 符印 {len(filled)}/{SLOTS}"
            f" · 总加成 {_total_text(totals)} · 已解锁 {unlocked_count} 枚"
        )
        if filled:
            detail = "；".join(
                f"{slot}号 {ctx.content.sigils[sigil_id].name}（{bonus_text(ctx, ctx.content.sigils[sigil_id])}）"
                for slot, sigil_id in sorted(filled.items())
            )
            lines.append(f"   {detail}")
        else:
            lines.append("   未装备符印。")
    if not pets:
        lines.append("还没有在册伙伴。")
    lines.append("总览只读，不切换出战、不改变符印；每只伙伴两个槽，加成互不叠加。")
    return Reply("灵宠符印 总览", tuple(lines), ("灵宠符印", "我的灵宠", "灵宠技能"))


def equip(ctx: Context, arg: str) -> Reply:
    body, who = split_selector(arg)
    if not body.strip():
        raise GameError("格式：灵宠符印 装备 <符印> [伙伴 名字|编号]。")
    pet = named_pet(ctx, who, "镶嵌符印") if who else ctx.pet()
    sigil = named(ctx.content.sigils, body)
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
    note_prep_change(ctx, pet)
    return Reply("镶嵌符印", (
        f"{pet.name}在 {slot} 号槽装备了{sigil.name}：{bonus_text(ctx, sigil)}。",
        f"符印槽 {len(filled) + 1}/{SLOTS}；符印不消耗材料，可随时卸下换给其他伙伴。",
    ), ("灵宠符印", "我的灵宠"))


def unequip(ctx: Context, arg: str) -> Reply:
    body, who = split_selector(arg)
    if not body.strip():
        raise GameError("格式：灵宠符印 卸下 <符印> [伙伴 名字|编号]。")
    pet = named_pet(ctx, who, "卸下符印") if who else ctx.pet()
    sigil = named(ctx.content.sigils, body)
    filled = equipped(ctx, pet.pet_id)
    slots = [slot for slot, sigil_id in filled.items() if sigil_id == sigil.id]
    if not slots:
        raise GameError(f"{pet.name}没有装备{sigil.name}。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{PREFIX}{pet.pet_id}_{slots[0]}_{sigil.id}"),
    )
    note_prep_change(ctx, pet)
    return Reply("卸下符印", (
        f"{pet.name}卸下了{sigil.name}，{slots[0]} 号槽空出。",
        "符印仍在，解锁状态不会消失。",
    ), ("灵宠符印", "我的灵宠"))


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _cost_text(ctx: Context, level: int) -> str:
    stones, items = REFINE_COSTS[level]
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in items.items()
    )
    return "，".join(parts)


def refine(ctx: Context, arg: str) -> Reply:
    """Spend stones and materials to raise one sigil's rank, one step at a time."""
    body, who = split_selector(arg)
    if not body.strip():
        raise GameError("格式：灵宠符印 精炼 <符印> [伙伴 名字|编号]。")
    pet = named_pet(ctx, who, "精炼符印") if who else ctx.pet()
    sigil = named(ctx.content.sigils, body)
    if not unlocked(ctx, sigil, pet):
        raise GameError(f"{sigil.name}尚未解锁：需要 {requirement_text(ctx, sigil, pet)}。")
    level = rank(ctx, sigil.id)
    if level >= RANKS:
        raise GameError(f"{sigil.name}已精炼到 {RANKS} 阶，无法再提升。")
    target = level + 1
    stones, items = REFINE_COSTS[target]
    player = ctx.player()
    if player.stones < stones:
        raise GameError(
            f"灵石不足：精炼到 {target} 阶需要 {stones}，当前 {player.stones}。"
        )
    missing = [
        f"{ctx.content.items[item_id].name} {_owned(ctx, item_id)}/{amount}"
        for item_id, amount in items.items()
        if _owned(ctx, item_id) < amount
    ]
    if missing:
        raise GameError(f"材料不足：{'、'.join(missing)}。")
    player.stones -= stones
    for item_id, amount in items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (ctx.user_id, f"{RANK_PREFIX}{sigil.id}", target),
    )
    note_prep_change(ctx, pet)
    return Reply("符印精炼", (
        f"{sigil.name}精炼到 {target} 阶：{bonus_text(ctx, sigil)}。",
        f"花费 {_cost_text(ctx, target)}。加成对装备它的伙伴生效。",
    ), ("灵宠符印", "我的灵宠", "灵宠背包"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "装备":
        return equip(ctx, " ".join(parts[1:]))
    if parts[0] == "卸下":
        return unequip(ctx, " ".join(parts[1:]))
    if parts[0] == "总览":
        return overview(ctx, " ".join(parts[1:]))
    if parts[0] == "精炼":
        return refine(ctx, " ".join(parts[1:]))
    body, who = split_selector(arg)
    if not body and who:
        ctx.player()
        return _detail(ctx, named_pet(ctx, who, "查看符印"))
    raise GameError("格式：灵宠符印 [装备 <符印>|卸下 <符印>|精炼 <符印>|总览|伙伴 <名字|编号>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None or player.active_pet_id is None:
        return "符印：尚未选择主战灵宠"
    filled = equipped(ctx, player.active_pet_id, user_id)
    return f"符印：已装备 {len(filled)}/{SLOTS}"
