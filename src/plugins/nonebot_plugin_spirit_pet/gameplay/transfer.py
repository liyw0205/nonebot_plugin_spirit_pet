"""Skill transfer: one pet teaches a learned skill to another pet for stones and essence.

The teacher keeps its own copy; the student gains the skill at level 1 with no proficiency.
Cost is derived from the skill book's price, so transfer is always a discount on buying a fresh
book but never free. Nothing is stored beyond the new ``learned_skills`` row.
"""

import math

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from .ascension_rules import skill_slots
from .compatibility import check_requirements, requirement_text
from .mastery import progress, progress_text
from .skills import learned


def rule(ctx: Context):
    return ctx.content.rules.transfer


def cost(ctx: Context, skill) -> tuple[int, int]:
    price = ctx.content.items[skill.book_item].price or 0
    stones = max(rule(ctx).min_stones, math.ceil(price * rule(ctx).price_rate))
    return stones, rule(ctx).bloodline_essence


def _cost_text(ctx: Context, skill) -> str:
    stones, essence = cost(ctx, skill)
    parts = [f"灵石 {stones}"]
    if essence:
        parts.append(f"血脉精华 {essence}")
    return " + ".join(parts)


def _pets(ctx: Context):
    return sorted(ctx.repo.owned_pets(ctx.user_id), key=lambda pet: pet.pet_id)


def _pet(ctx: Context, token: str):
    matches = [pet for pet in _pets(ctx) if pet.name == token or str(pet.pet_id) == token]
    if not matches:
        raise GameError(f"没有找到名为 {token} 的伙伴。")
    if len(matches) > 1:
        raise GameError(f"有 {len(matches)} 只伙伴都叫 {token}，请改用伙伴编号。")
    return matches[0]


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _eligible(ctx: Context, student, skill_id: str) -> bool:
    if skill_id in learned(ctx, student.pet_id):
        return False
    try:
        check_requirements(ctx, student, ctx.content.skills[skill_id].requirements)
    except GameError:
        return False
    return True


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠传功 [<师父> <徒弟> <灵术>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠传功",
            (
                "尚未结契，先完成领养，才能让伙伴互相传授灵术。",
                "师父须已学会该灵术；徒弟须满足属性、类别与境界条件，且尚未学会。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    teacher = ctx.pet()
    learned_skills = learned(ctx, teacher.pet_id)
    lines = [
        "传功让一门已学会的灵术复制给另一只伙伴：师父保留原技能，徒弟从第 1 层、0 熟练度开始。",
        f"费用按秘笈价格的 {rule(ctx).price_rate:.0%} 计算，至少 {rule(ctx).min_stones} 灵石"
        + (f"，另耗血脉精华 {rule(ctx).bloodline_essence}。" if rule(ctx).bloodline_essence else "。"),
        f"师父：{teacher.name}（编号 {teacher.pet_id}）· 已学 {len(learned_skills)} 门。",
    ]
    if not learned_skills:
        lines.append("尚未学会灵术，没有可传授的内容。")
    mastery = progress(ctx, teacher.pet_id)
    others = [pet for pet in _pets(ctx) if pet.pet_id != teacher.pet_id]
    for skill_id in learned_skills:
        skill = ctx.content.skills[skill_id]
        candidates = [pet.name for pet in others if _eligible(ctx, pet, skill_id)]
        state = "可传：" + "、".join(candidates) if candidates else "暂无可传对象"
        lines.append(
            f"{skill.name} · {progress_text(ctx, *mastery[skill_id])} · {_cost_text(ctx, skill)} · {state}"
        )
    lines.append("格式：灵宠传功 <师父> <徒弟> <灵术>。徒弟携带位已满时仍会学会，但不会自动携带。")
    return Reply("灵宠传功", tuple(lines), ("灵宠传功", "灵宠技能", "我的灵宠"))


def teach(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 3:
        raise GameError("格式：灵宠传功 <师父> <徒弟> <灵术>。")
    teacher = _pet(ctx, parts[0])
    student = _pet(ctx, parts[1])
    if teacher.pet_id == student.pet_id:
        raise GameError("师父与徒弟不能是同一只伙伴。")
    skill = named(ctx.content.skills, parts[2])
    if skill.id not in learned(ctx, teacher.pet_id):
        raise GameError(f"{teacher.name}尚未学会{skill.name}，无法传授。")
    if skill.id in learned(ctx, student.pet_id):
        raise GameError(f"{student.name}已经学会{skill.name}，无需传功。")
    check_requirements(ctx, student, skill.requirements)
    ctx.require_idle_pet(teacher)
    ctx.require_idle_pet(student)

    stones, essence = cost(ctx, skill)
    player = ctx.player()
    item = ctx.content.items["bloodline_essence"]
    held = _owned(ctx, "bloodline_essence")
    if player.stones < stones:
        raise GameError(f"灵石不足：传功需要 {stones}，当前 {player.stones}。")
    if held < essence:
        raise GameError(f"{item.name}不足：传功需要 {essence}，当前 {held}。")

    player.stones -= stones
    if essence:
        ctx.repo.consume_item(ctx.user_id, "bloodline_essence", essence)
    equipped = int(sum(learned(ctx, student.pet_id).values()) < skill_slots(ctx, student))
    ctx.repo.conn.execute(
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, ?, 1, 0)",
        (student.pet_id, skill.id, equipped),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"{teacher.name}把{skill.name}传给了{student.name}，徒弟从第 1 层、0 熟练度开始。",
        f"消耗 " + _cost_text(ctx, skill) + (f"（剩余 {held - essence}）" if essence else ""),
        "已自动携带。" if equipped else "携带位已满，已学会但未携带；可在灵宠技能里调整。",
        f"适用条件：{requirement_text(ctx, skill.requirements)}。",
    ]
    return Reply("传授灵术", tuple(lines), ("灵宠传功", "灵宠技能", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, "") if not arg.strip() else teach(ctx, arg)
