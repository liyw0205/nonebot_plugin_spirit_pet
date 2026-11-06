"""战报复盘: turn one stored battle into concrete, priced next steps.

The log only keeps rendered lines, so the analysis uses the immutable snapshot
(stats, elements, skills, equipment) plus the player's CURRENT growth state. It
never writes: every line is a diagnosis or a link to the command that would help.
"""

import json

from ..application.context import Context
from ..domain.models import InlineCommand, Reply
from . import equipment, sigils, support
from .combat import effectiveness
from .effects import BOND_GUARD_AFFINITY

STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
MAX_ACTIONS = 4


def _team(snapshot: dict, side: int) -> list[dict]:
    for team in snapshot.get("teams", []):
        if team.get("side") == side:
            return list(team.get("members", []))
    return []


def _other_side(snapshot: dict, side: int) -> int:
    sides = [team.get("side") for team in snapshot.get("teams", [])]
    return next((value for value in sides if value != side), 1 - side)


def _totals(members: list[dict]) -> dict[str, int]:
    totals = {key: 0 for key in STAT_LABELS}
    for member in members:
        stats = member.get("stats") or {}
        for key in totals:
            totals[key] += int(stats.get(key, 0))
    return totals


def _stat_text(totals: dict[str, int]) -> str:
    return " ".join(f"{STAT_LABELS[key]} {totals[key]}" for key in STAT_LABELS)


def _primary(members: list[dict]) -> str | None:
    for member in members:
        value = member.get("primary_element")
        if value:
            return value
    return None


def _element_text(ctx: Context, mine: list[dict], theirs: list[dict]) -> str:
    own, other = _primary(mine), _primary(theirs)
    if not own or not other:
        return "元素：战报未记录双方主属性。"
    forward = effectiveness(own, other, ctx.content.elements)
    backward = effectiveness(other, own, ctx.content.elements)
    own_name = ctx.content.elements[own].name if own in ctx.content.elements else own
    other_name = ctx.content.elements[other].name if other in ctx.content.elements else other
    verdict = ""
    if forward > backward:
        verdict = " · 我方克制对方"
    elif forward < backward:
        verdict = " · 我方被对方克制"
    return f"元素：我方主属性 {own_name} 对 {other_name} ×{forward:g}，反向 ×{backward:g}{verdict}。"


def _enhancement_action(ctx: Context) -> tuple[str, str] | None:
    """The cheapest next enhancement across the current roster, with its real price."""
    cheapest = None
    for pet in ctx.repo.active_pets(ctx.user_id):
        for slot, label in equipment.SLOTS.items():
            worn = equipment.loadout(ctx, pet.pet_id)
            if slot not in worn:
                continue
            item_id, level = worn[slot]
            forge = ctx.content.forge_levels.get(level)
            if forge is None or forge.upgrade_stones is None:
                continue
            costs = [f"{forge.upgrade_stones} 灵石"]
            costs.extend(
                f"{ctx.content.items[key].name} {amount}"
                for key, amount in forge.upgrade_items.items()
            )
            candidate = (
                forge.upgrade_stones,
                f"{pet.name}的{ctx.content.items[item_id].name} +{level} 可强化：{'、'.join(costs)}",
                f"灵宠强化 {label} 伙伴 {pet.pet_id}",
            )
            if cheapest is None or candidate[0] < cheapest[0]:
                cheapest = candidate
    return (cheapest[1], cheapest[2]) if cheapest is not None else None


def _gear_action(ctx: Context) -> tuple[str, str] | None:
    for pet in ctx.repo.active_pets(ctx.user_id):
        worn = equipment.loadout(ctx, pet.pet_id)
        for slot, label in equipment.SLOTS.items():
            if slot not in worn:
                return (f"{pet.name}的{label}位还空着", f"灵宠整备 {pet.pet_id}")
    return None


def _sigil_action(ctx: Context) -> tuple[str, str] | None:
    for pet in ctx.repo.active_pets(ctx.user_id):
        filled = sigils.equipped(ctx, pet.pet_id)
        if len(filled) >= sigils.SLOTS:
            continue
        ready = next(
            (
                sigil for sigil in ctx.content.sigils.values()
                if sigil.id not in filled.values() and sigils.unlocked(ctx, sigil, pet)
            ),
            None,
        )
        if ready is not None:
            return (
                f"{pet.name}还能镶{ready.name}：{sigils.bonus_text(ctx, ready)}",
                f"灵宠符印 装备 {ready.name} 伙伴 {pet.pet_id}",
            )
    return None


def _support_action(ctx: Context) -> tuple[str, str] | None:
    if len(support.assigned(ctx)) >= support.max_slots(ctx):
        return None
    return ("助战席还空着，可借后备伙伴的基础四维", "灵宠助战")


def _affinity_action(ctx: Context) -> tuple[str, str] | None:
    for pet in ctx.repo.active_pets(ctx.user_id):
        if pet.affinity < BOND_GUARD_AFFINITY:
            return (
                f"{pet.name}亲密 {pet.affinity}/{BOND_GUARD_AFFINITY}，未满时无心契护佑",
                "灵宠互动",
            )
    return None


def review(ctx: Context, row) -> Reply:
    snapshot = json.loads(row["snapshot"])
    side = int(row["side"])
    mine = _team(snapshot, side)
    theirs = _team(snapshot, _other_side(snapshot, side))
    result = "平局" if row["winner_side"] == -1 else ("胜利" if row["winner_side"] == side else "败北")

    lines = [
        f"战报 #{row['battle_id']} · 复盘 · {result} · {row['rounds']} 回合",
        f"我方四维 {_stat_text(_totals(mine))}",
        f"对方四维 {_stat_text(_totals(theirs))}",
        _element_text(ctx, mine, theirs),
    ]
    own_skills = sum(len(member.get("skills") or []) for member in mine)
    own_gear = sum(len(member.get("equipment") or []) for member in mine)
    own_level = sum(
        int(item.get("enhancement", 0))
        for member in mine for item in (member.get("equipment") or [])
    )
    lines.append(f"我方阵容：灵术 {own_skills} 门 · 装备 {own_gear} 件 · 强化合计 +{own_level}")

    actions = [
        action for action in (
            _enhancement_action(ctx),
            _gear_action(ctx),
            _sigil_action(ctx),
            _support_action(ctx),
            _affinity_action(ctx),
        ) if action is not None
    ][:MAX_ACTIONS]
    links = []
    if actions:
        lines.append("下一步：")
        for text, command in actions:
            lines.append(f"  {text}")
            links.append(InlineCommand(len(lines) - 1, "前往", command))
    else:
        lines.append("下一步：当前养成已无短板，去灵宠目标看看还能领什么。")
    lines.append("复盘只读：不改装备、灵术、符印与阵容。")
    return Reply(
        f"战报 #{row['battle_id']} 复盘",
        tuple(lines),
        ("灵宠战报", "我的灵宠", "灵宠整备"),
        tuple(links),
    )
