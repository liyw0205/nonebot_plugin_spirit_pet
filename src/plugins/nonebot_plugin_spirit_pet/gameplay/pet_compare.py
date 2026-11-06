"""Side-by-side comparison of two owned pets without changing either one."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .bond_levels import current_level as bond_level
from .equipment import loadout
from .loadout import combatant
from .mastery import progress
from .mood import level as mood_level, value as mood_value
from .specialization import current as specialization
from .skills import learned


def _pet(ctx: Context, token: str):
    if not token.isdecimal():
        raise GameError("格式：灵宠对比 <编号A> <编号B>。")
    pet = ctx.repo.pet(int(token))
    if pet.user_id != ctx.user_id:
        raise GameError(f"编号 {pet.pet_id} 不属于你。")
    if pet.archived:
        raise GameError(f"{pet.name}在封存库中，请先复原再对比。")
    return pet


def _skill_text(ctx: Context, pet) -> str:
    learned_rows = progress(ctx, pet.pet_id)
    names = [
        ctx.content.skills[skill_id].name
        for skill_id in learned_rows
        if skill_id in ctx.content.skills
    ]
    if not names:
        return "未学灵术"
    shown = "、".join(names[:3])
    return f"{len(names)} 门（{shown}{'…' if len(names) > 3 else ''}）"


def _gear_text(ctx: Context, pet) -> str:
    equipped = loadout(ctx, pet.pet_id)
    if not equipped:
        return "未装备"
    names = [
        ctx.content.items[item_id].name
        for item_id, _ in equipped.values()
        if item_id in ctx.content.items
    ]
    return f"{len(names)} 件（{'、'.join(names)}）" if names else "未装备"


def _specialization_text(ctx: Context, pet) -> str:
    chosen = specialization(ctx, pet.pet_id)
    if chosen is None:
        return "未选择专精"
    skill = ctx.content.skills.get(chosen)
    return f"专精 {skill.name}" if skill is not None else f"专精已失效（{chosen}）"


def _summary(ctx: Context, pet) -> dict:
    fighter = combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)
    stats = fighter.stats
    return {
        "pet": pet,
        "stats": stats,
        "skills": _skill_text(ctx, pet),
        "gear": _gear_text(ctx, pet),
        "bond": bond_level(ctx, pet.pet_id),
        "mood": mood_level(ctx, pet),
        "mood_value": mood_value(ctx, pet),
        "specialization": _specialization_text(ctx, pet),
    }


def _delta(a: int, b: int) -> str:
    diff = b - a
    return f"+{diff}" if diff > 0 else str(diff)


def compare(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠对比", (
            "尚未结契，先完成领养，才能并排比较两只伙伴。",
            "对比只读，不会切换出战、消耗资源或改变装备。",
        ), ("灵宠领养", "灵宠帮助"), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠对比 <编号A> <编号B>。")
    first, second = _pet(ctx, parts[0]), _pet(ctx, parts[1])
    if first.pet_id == second.pet_id:
        raise GameError("需要两只不同的伙伴才能对比。")
    left, right = _summary(ctx, first), _summary(ctx, second)
    a, b = left["stats"], right["stats"]
    lines = [
        f"{first.name}（{first.pet_id}） vs {second.name}（{second.pet_id}）",
        f"气血 {a.hp} vs {b.hp}（{_delta(a.hp, b.hp)}）",
        f"攻击 {a.attack} vs {b.attack}（{_delta(a.attack, b.attack)}）",
        f"防御 {a.defense} vs {b.defense}（{_delta(a.defense, b.defense)}）",
        f"速度 {a.speed} vs {b.speed}（{_delta(a.speed, b.speed)}）",
        f"技能：{left['skills']} vs {right['skills']}",
        f"装备：{left['gear']} vs {right['gear']}",
        f"羁绊：Lv{left['bond']} vs Lv{right['bond']} · "
        f"心境：{left['mood'].name} {left['mood_value']} vs "
        f"{right['mood'].name} {right['mood_value']}",
        f"专精：{left['specialization']} vs {right['specialization']}",
    ]
    return Reply("灵宠对比", tuple(lines), ("灵宠列表", "灵宠装备", "我的灵宠"))


__all__ = ["compare"]
