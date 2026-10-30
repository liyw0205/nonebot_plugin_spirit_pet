"""Skill study: grow one equipped skill's proficiency outside of battle.

Combat is the only place proficiency used to move, which left 灵术专精 (needs level 3) and 灵宠传功
(hands over a level-1, 0-proficiency copy) stuck behind a long grind. Studying spends energy and
灵粮 to gain proficiency under two caps — per day and per pet per day — so it complements battles
rather than replacing them.

State lives in ``quest_progress``: ``research_day_<beijing date>`` counts studies used today and
``research_<beijing date>_<pet_id>`` counts the studies that pet used today. Both carry the date in
the key, so both caps reset by themselves when Beijing day changes. Both are integers, so no schema
change is needed and both reset on their own when Beijing day changes.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from .mastery import progress, progress_text, study
from .skills import learned

DAY_KEY = "research_day_"
PET_KEY = "research_"


def rule(ctx: Context):
    return ctx.content.rules.research


def _counter(ctx: Context, quest_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, quest_id),
    ).fetchone()
    return int(row["progress"]) if row else 0


def used_today(ctx: Context, user_id: str | None = None) -> int:
    return _counter(ctx, f"{DAY_KEY}{beijing_day(ctx.now)}", user_id)


def used_today_by_pet(ctx: Context, pet_id: int, user_id: str | None = None) -> int:
    return _counter(ctx, f"{PET_KEY}{beijing_day(ctx.now)}_{pet_id}", user_id)


def left_today(ctx: Context, user_id: str | None = None) -> int:
    return max(0, rule(ctx).daily_limit - used_today(ctx, user_id))


def left_today_for_pet(ctx: Context, pet_id: int, user_id: str | None = None) -> int:
    return max(0, rule(ctx).pet_daily_limit - used_today_by_pet(ctx, pet_id, user_id))


def _owned(ctx: Context, item_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (user_id or ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _next_level(ctx: Context, level: int, proficiency: int, gain: int) -> int:
    """The level this skill would reach after one study, using the game's own thresholds."""
    level_now, proficiency_now = level, proficiency + gain
    while (required := ctx.content.skill_levels[level_now].required_proficiency) is not None:
        if proficiency_now < required:
            break
        proficiency_now -= required
        level_now += 1
    return level_now


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠研习 [<灵术>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠研习",
            (
                "尚未结契，先完成领养，才能与伙伴一起研习灵术。",
                "研习消耗精力与灵粮，为已携带的灵术积累熟练度，不用打一场也能升阶。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.pet()
    entry = rule(ctx)
    item = ctx.content.items["spirit_food"]
    held = _owned(ctx, "spirit_food")
    proficiency = progress(ctx, pet.pet_id)
    equipped = [skill_id for skill_id, active in learned(ctx, pet.pet_id).items() if active]
    left = left_today(ctx)
    pet_left = left_today_for_pet(ctx, pet.pet_id)
    lines = [
        f"{pet.name}研习：每次消耗 {entry.energy} 精力与 {item.name} {entry.food} 份，熟练度 +{entry.gain}。",
        f"今日剩余 {left}/{entry.daily_limit} 次，{pet.name}今日可研习 {pet_left}/{entry.pet_daily_limit} 次。",
    ]
    links = []
    for skill_id in equipped:
        skill = ctx.content.skills[skill_id]
        level, current = proficiency[skill_id]
        maxed = ctx.content.skill_levels[level].required_proficiency is None
        if maxed:
            state = "已满级"
        elif left <= 0:
            state = "今日次数已用尽"
        elif pet_left <= 0:
            state = f"{pet.name}今日次数已用尽"
        elif pet.energy < entry.energy:
            state = f"精力不足（{pet.energy}/{entry.energy}）"
        elif held < entry.food:
            state = f"{item.name}不足（{held}/{entry.food}）"
        else:
            after = _next_level(ctx, level, current, entry.gain)
            state = "可研习" + (f"，可升至 {after} 级" if after > level else "")
        lines.append(f"{skill.name} · {progress_text(ctx, level, current)} · {state}")
        if state.startswith("可研习"):
            links.append(InlineCommand(len(lines) - 1, "研习", f"灵宠研习 {skill.name}"))
    if not equipped:
        lines.append("当前没有携带中的灵术，先到 灵宠技能 携带一门。")
    lines.append("格式：灵宠研习 <灵术>；只研习已携带的灵术，每次立即结算。")
    return Reply("灵宠研习", tuple(lines), ("灵宠研习", "灵宠技能", "我的灵宠"), tuple(links))


def do_study(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠研习 <灵术>。")
    pet = ctx.pet()
    skill = named(ctx.content.skills, arg)
    learned_now = learned(ctx, pet.pet_id)
    if skill.id not in learned_now:
        raise GameError(f"{pet.name}尚未学会{skill.name}。")
    if not learned_now[skill.id]:
        raise GameError(f"{skill.name}未携带，请先在灵宠技能里携带后再研习。")
    ctx.require_idle_pet(pet)

    entry = rule(ctx)
    level, current = progress(ctx, pet.pet_id)[skill.id]
    if ctx.content.skill_levels[level].required_proficiency is None:
        raise GameError(f"{skill.name}已经满级，无需继续研习。")
    if left_today(ctx) <= 0:
        raise GameError(f"今日研习次数已用尽（每日 {entry.daily_limit} 次，北京时间 00:00 刷新）。")
    if left_today_for_pet(ctx, pet.pet_id) <= 0:
        raise GameError(
            f"{pet.name}今日已研习 {entry.pet_daily_limit} 次，换一只伙伴或明日再来。"
        )
    if pet.energy < entry.energy:
        raise GameError(f"{pet.name}精力不足：研习需要 {entry.energy} 点，当前 {pet.energy} 点。")
    item = ctx.content.items["spirit_food"]
    held = _owned(ctx, "spirit_food")
    if held < entry.food:
        raise GameError(f"{item.name}不足：研习需要 {entry.food} 份，当前 {held} 份。")

    pet.energy -= entry.energy
    if entry.food:
        ctx.repo.consume_item(ctx.user_id, "spirit_food", entry.food)
    after, after_proficiency, upgraded = study(ctx, pet.pet_id, skill.id, entry.gain)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{DAY_KEY}{beijing_day(ctx.now)}", used_today(ctx) + 1),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{PET_KEY}{beijing_day(ctx.now)}_{pet.pet_id}", used_today_by_pet(ctx, pet.pet_id) + 1),
    )
    if upgraded:
        ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"{pet.name}研习{skill.name}：熟练度 +{entry.gain}（{progress_text(ctx, level, current)}"
        f" → {progress_text(ctx, after, after_proficiency)}）。",
        f"消耗 {entry.energy} 精力与 {item.name} {entry.food} 份（精力 {pet.energy}，{item.name} {held - entry.food}）。",
        f"今日剩余 {left_today(ctx)} 次，{pet.name}今日剩余 {left_today_for_pet(ctx, pet.pet_id)} 次。",
    ]
    if upgraded:
        lines.append(f"{skill.name}提升到 {after} 级，战斗中的威力倍率随之提高。")
    if after >= 3 and upgraded:
        lines.append("达到 3 级即可在 灵宠专精 里选定这门灵术。")
    return Reply("研习灵术", tuple(lines), ("灵宠研习", "灵宠技能", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, "") if not arg.strip() else do_study(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "研习：尚未结契"
    left = left_today(ctx, user_id)
    return f"研习：今日可用 {left} 次" if left else "研习：今日已用尽"
