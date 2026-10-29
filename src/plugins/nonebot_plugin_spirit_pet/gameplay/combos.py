"""Skill combos: two equipped skills on one pet grant a small stat bonus.

Nothing is stored: a combo is matched directly from ``learned_skills`` every time it is read, so
equipping or unequipping a skill changes the page and the battle stats immediately.
"""

from ..application.context import Context
from ..domain.combo_content import Combo
from ..domain.models import GameError, InlineCommand, Reply
from .skills import learned


def matched(ctx: Context, skill_ids) -> list[Combo]:
    present = set(skill_ids)
    return [
        combo for combo in ctx.content.combos.values()
        if all(skill_id in present for skill_id in combo.skills)
    ]


def apply(ctx: Context, stats: dict, skill_ids) -> dict:
    """Multiply the final stats by every matched combo, in content order."""
    for combo in matched(ctx, skill_ids):
        for key, rate in combo.bonuses.model_dump().items():
            if rate:
                stats[key] = int(stats[key] * (1 + rate) + 0.5)
    return stats


def equipped(ctx: Context, pet_id: int) -> set[str]:
    return {skill_id for skill_id, active in learned(ctx, pet_id).items() if active}


STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def _bonus_text(ctx: Context, combo: Combo) -> str:
    parts = []
    for key, rate in combo.bonuses.model_dump().items():
        if rate:
            parts.append(f"{STAT_LABELS[key]} +{round(rate * 100)}%")
    return "，".join(parts)


def _pair_text(ctx: Context, combo: Combo) -> str:
    return " + ".join(ctx.content.skills[skill_id].name for skill_id in combo.skills)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠连携。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠连携",
            (
                "尚未结契，先完成领养，才能查看灵术连携。",
                "两门指定技能同时装备在同一只灵宠身上，会额外获得一份属性加成。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.repo.pet(player.active_pet_id) if player.active_pet_id is not None else None
    if pet is None:
        return Reply(
            "灵宠连携",
            ("还没有主战灵宠，先在「我的灵宠」里选择一只。",),
            ("灵宠连携", "我的灵宠"),
        )
    active = equipped(ctx, pet.pet_id)
    total = len(ctx.content.combos)
    hit = matched(ctx, active)
    lines = [f"{pet.name}：已连携 {len(hit)}/{total} 组。"]
    for combo in ctx.content.combos.values():
        missing = [sid for sid in combo.skills if sid not in active]
        state = "已连携" if not missing else "未集齐（缺 " + "、".join(
            ctx.content.skills[sid].name for sid in missing
        ) + "）"
        lines.append(f"{combo.name}：{_pair_text(ctx, combo)} → {_bonus_text(ctx, combo)} · {state}")
    lines.append("连携只按当前装备的技能判定，换下技能立即失效；不额外占用精力或存档。")
    return Reply("灵宠连携", tuple(lines), ("灵宠连携", "灵宠技能", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    pet = ctx.repo.pet(player.active_pet_id) if player is not None and player.active_pet_id is not None else None
    if pet is None:
        return "连携：尚未选择主战灵宠"
    hit = matched(ctx, equipped(ctx, pet.pet_id))
    return f"连携：已连携 {len(hit)}/{len(ctx.content.combos)}"
