"""Skill specialisation: commit one pet to one learned skill for an archetype power bonus.

State is one ``quest_progress`` row per pet, keyed ``spec_<pet_id>_<skill_id>`` — the skill id
lives in the *key* because ``progress`` is an integer. The bonus reaches combat through
``loadout.combatant``, which multiplies the specialised skill's entry in ``skill_multipliers``;
``combat.py`` and ``effects.py`` already read that dict, so no battle-engine change is needed.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.specialization_content import skill_archetype
from ..utils.arguments import named
from .mastery import progress, progress_text
from .skills import learned

KEY_PREFIX = "spec_"


def rule(ctx: Context):
    return ctx.content.rules.specialization


def current(ctx: Context, pet_id: int, user_id: str | None = None) -> str | None:
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ? ORDER BY quest_id LIMIT 1",
        (user_id or ctx.user_id, f"{KEY_PREFIX}{pet_id}_%"),
    ).fetchone()
    return None if row is None else row["quest_id"][len(KEY_PREFIX) + len(str(pet_id)) + 1:]


def rate_for(ctx: Context, skill) -> float:
    return ctx.content.specializations[skill_archetype(skill)].rate


def archetype(ctx: Context, skill):
    return ctx.content.specializations[skill_archetype(skill)]


def bonus(ctx: Context, skill) -> str:
    return f"+{rate_for(ctx, skill):.0%}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠专精 [<灵术>|取消]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵术专精",
            (
                "尚未结契，先完成领养，才能为伙伴选定专精。",
                "每只伙伴只能专精一门已学灵术，威力按其流派加成；改投他术需要灵石，取消不返还。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.pet()
    chosen = current(ctx, pet.pet_id)
    mastery = progress(ctx, pet.pet_id)
    lines = [
        f"{pet.name}：{'专精 ' + ctx.content.skills[chosen].name if chosen else '尚未选择专精'}。",
        f"专精需要灵术达到 {rule(ctx).min_level} 级，改投他术消耗 {rule(ctx).switch_stones} 灵石，取消不返还。",
    ]
    links = []
    for skill_id in learned(ctx, pet.pet_id):
        skill = ctx.content.skills[skill_id]
        entry = archetype(ctx, skill)
        level = mastery[skill_id][0]
        state = "已专精" if skill_id == chosen else (
            f"可专精（{entry.name} {bonus(ctx, skill)}）"
            if level >= rule(ctx).min_level
            else f"需 {rule(ctx).min_level} 级（当前 {level} 级）"
        )
        lines.append(
            f"{skill.name} · {progress_text(ctx, *mastery[skill_id])} · {entry.name} {bonus(ctx, skill)} · {state}"
        )
        if skill_id != chosen and level >= rule(ctx).min_level:
            links.append(InlineCommand(len(lines) - 1, "专精", f"灵宠专精 {skill.name}"))
    if chosen:
        links.append(InlineCommand(0, "取消专精", "灵宠专精 取消"))
    if not learned(ctx, pet.pet_id):
        lines.append("尚未学会灵术，没有可专精的内容。")
    lines.append("格式：灵宠专精 <灵术>，或 灵宠专精 取消。")
    return Reply("灵术专精", tuple(lines), ("灵宠专精", "灵宠技能", "我的灵宠"), tuple(links))


def _skill(ctx: Context, pet_id: int, token: str):
    skill = named(ctx.content.skills, token)
    if skill.id not in learned(ctx, pet_id):
        raise GameError(f"{ctx.repo.pet(pet_id).name}尚未学会{skill.name}。")
    return skill


def choose(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠专精 <灵术>。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    skill = _skill(ctx, pet.pet_id, arg)
    chosen = current(ctx, pet.pet_id)
    if chosen == skill.id:
        raise GameError(f"{pet.name}已经专精{skill.name}，无需重复选择。")
    level = progress(ctx, pet.pet_id)[skill.id][0]
    if level < rule(ctx).min_level:
        raise GameError(f"{skill.name}仅为 {level} 级，专精需要 {rule(ctx).min_level} 级。")

    player = ctx.player()
    cost = 0 if chosen is None else rule(ctx).switch_stones
    if player.stones < cost:
        raise GameError(f"灵石不足：改投专精需要 {cost}，当前 {player.stones}。")
    player.stones -= cost
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{KEY_PREFIX}{pet.pet_id}_%"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1)",
        (ctx.user_id, f"{KEY_PREFIX}{pet.pet_id}_{skill.id}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    entry = archetype(ctx, skill)
    lines = [
        f"{pet.name}专精{skill.name}：{entry.name}，该灵术威力 {bonus(ctx, skill)}。",
        ("首次专精免费。" if not cost else f"改投消耗 {cost} 灵石（剩余 {player.stones}）。"),
        f"当前等级 {level} 级；取消专精随时可用，但不返还灵石。",
    ]
    return Reply("灵术专精", tuple(lines), ("灵宠专精", "灵宠技能", "我的灵宠"))


def cancel(ctx: Context, arg: str) -> Reply:
    if arg.strip() not in ("", "取消"):
        raise GameError("格式：灵宠专精 取消，不接受其他参数。")
    pet = ctx.pet()
    chosen = current(ctx, pet.pet_id)
    if chosen is None:
        raise GameError(f"{pet.name}当前没有专精，无需取消。")
    skill = ctx.content.skills[chosen]
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{KEY_PREFIX}{pet.pet_id}_{chosen}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("取消专精", (
        f"{pet.name}已取消专精{skill.name}，不再获得该灵术的威力加成。",
        "取消不返还灵石；随时可以重新专精，首次之后每次改投都会收费。",
    ), ("灵宠专精", "灵宠技能", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "取消":
        return cancel(ctx, arg[len("取消"):])
    return choose(ctx, " ".join(parts))


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None or player.active_pet_id is None:
        return "专精：尚未选择主战灵宠"
    pet = ctx.repo.pet(player.active_pet_id)
    chosen = current(ctx, pet.pet_id, user_id)
    if chosen is None:
        return "专精：未选择"
    skill = ctx.content.skills[chosen]
    return f"专精：{skill.name}（{bonus(ctx, skill)}）"
