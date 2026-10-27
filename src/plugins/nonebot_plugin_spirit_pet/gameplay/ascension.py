"""Ascension trial: three consecutive fights, then a permanent ascended state.

The trial is free and atomic: one command runs 雷劫, 心魔 and 天道 in order, each
starting from full health, and stops at the first defeat. A defeat costs nothing
and keeps no marker, so the player can try again. A full win writes
`ascended_<pet_id>` and counts this week's cycle in `rebirth_count` (at most one
cycle per Beijing week).

An ascended pet may repeat the same trial once per week (`ascension_week_<id>`)
to advance later cycles; repeats grant no currency or items. The ascended flag
is derived from `quest_progress` by `Repository.pet()`, adds 10% to every stat in
`pet_stats`, opens the fifth skill slot and appears in battle snapshots.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from . import ascension_rules
from .combat import enemy_fighter, fight
from .loadout import combatant
from .pet_targets import selected_pet

PAGE_SIZE = 5


def _stages(ctx: Context):
    return sorted(ctx.content.ascension.values(), key=lambda stage: stage.order)


def _final_realm(ctx: Context) -> int:
    return len(ctx.content.realms) - 1


def _can_start(ctx: Context, pet) -> bool:
    return not pet.ascended and pet.realm == _final_realm(ctx) and pet.layer == 10


def _week_used(ctx: Context, pet) -> bool:
    return ascension_rules.repeat_week(ctx, pet.pet_id) == ascension_rules.week_start(ctx.now)


def _state(ctx: Context, pet) -> str:
    if pet.ascended:
        return "本周轮回试炼已挑战" if _week_used(ctx, pet) else "可挑战轮回试炼"
    if _can_start(ctx, pet):
        return "可挑战飞升"
    return "未达渡劫十层"


def _page_argument(ctx: Context, arg: str) -> int:
    parts = arg.split()
    if not parts:
        return 1
    if len(parts) != 2 or parts[0] != "分页":
        raise GameError("格式：灵宠飞升 [宠物编号] 或 灵宠飞升 分页 N。")
    return quantity(parts[1], 999)


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    stages = _stages(ctx)
    rule_lines = (
        "飞升试炼共三段：" + "、".join(stage.name for stage in stages)
        + "；每段满血开始，三段连续全胜才能飞升。",
        "试炼不消耗灵石、灵粮或精力；失败不回收任何资源，可再次挑战。",
    )
    if player is None:
        return Reply("灵宠飞升", (
            "尚未结契，先完成领养，才能挑战飞升试炼。",
            *rule_lines,
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    page_number = _page_argument(ctx, arg)
    pets = ctx.repo.owned_pets(player.user_id)
    pages = max(1, (len(pets) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page_number > pages:
        raise GameError(f"灵宠飞升共 {pages} 页。")
    selected = pets[(page_number - 1) * PAGE_SIZE:page_number * PAGE_SIZE]
    ascended = ascension_rules.ascended_count(ctx, player.user_id)
    cycles = ascension_rules.rebirth_count(ctx, player.user_id)
    lines = [
        f"轮回：{cycles} 周目 · 已飞升 {ascended} 只",
        *rule_lines,
    ]
    links = []
    if not pets:
        lines.append("名册里还没有伙伴，先去领养或召唤一位吧。")
        links.append(InlineCommand(len(lines) - 1, "查看灵宠名册", "灵宠列表"))
        return Reply("灵宠飞升", tuple(lines), ("灵宠列表", "灵宠帮助"), tuple(links))
    for pet in selected:
        state = _state(ctx, pet)
        lines.append(
            f"编号 {pet.pet_id}：{pet.name} · {ctx.content.realms[pet.realm].name} {pet.layer}层"
            f" · {state}"
        )
        if state == "可挑战飞升":
            links.append(InlineCommand(len(lines) - 1, "挑战飞升", f"灵宠飞升 {pet.pet_id}"))
        elif state == "可挑战轮回试炼":
            links.append(InlineCommand(len(lines) - 1, "轮回试炼", f"灵宠飞升 {pet.pet_id}"))
    commands = []
    if page_number > 1:
        commands.append(f"灵宠飞升 分页 {page_number - 1}")
    if page_number < pages:
        commands.append(f"灵宠飞升 分页 {page_number + 1}")
    commands.extend(("灵宠目标", "灵宠称号"))
    return Reply(f"灵宠飞升 {page_number}/{pages}", tuple(lines), tuple(commands), tuple(links))


def _summary(stage, battle) -> str:
    outcome = "胜" if battle.winner == 0 else ("平" if battle.winner == -1 else "败")
    return f"第{stage.order}段 {stage.name}：{outcome} · {battle.rounds} 回合"


def _run(ctx: Context, pet) -> list[tuple]:
    """Fight every stage with a fresh fighter so each starts at full health."""
    results = []
    for stage in _stages(ctx):
        ally = combatant(ctx, ctx.user_id, pet_id=pet.pet_id)
        enemy = enemy_fighter(ctx.content.enemies[stage.enemy], ctx.content.skills)
        battle = fight([ally], [enemy], ctx.rng, ctx.content.elements)
        results.append((stage, battle))
        if battle.winner != 0:
            break
    return results


def _reply_commands() -> tuple[str, ...]:
    return ("灵宠飞升", "灵宠称号", "灵宠目标", "我的灵宠")


def trial(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = selected_pet(ctx, arg, "飞升")
    ctx.require_idle_pet(pet)

    repeat = pet.ascended
    if repeat:
        if _week_used(ctx, pet):
            raise GameError(f"{pet.name}本周已经完成轮回试炼，下周再来。")
    elif not _can_start(ctx, pet):
        raise GameError(f"{pet.name}尚未达到渡劫十层，无法开启飞升试炼。")

    results = _run(ctx, pet)
    lines = [_summary(stage, battle) for stage, battle in results]
    won = len(results) == len(_stages(ctx)) and all(battle.winner == 0 for _, battle in results)

    if not won:
        if repeat:
            ascension_rules.mark_repeat(ctx, pet.pet_id)
        failed = results[-1][0]
        lines.append(f"第{failed.order}段{failed.name}未通过，本次{'轮回试炼' if repeat else '飞升'}未成。")
        lines.append("三段必须连续全胜；本次未消耗任何资源。")
        if repeat:
            lines.append("本周轮回试炼已结束，下周可再来。")
        else:
            lines.append("准备好后可再次发送 灵宠飞升 编号。")
        return Reply("轮回试炼未成" if repeat else "飞升未成", tuple(lines), _reply_commands())

    cycles_before = ascension_rules.rebirth_count(ctx, player.user_id)
    ascended_before = ascension_rules.ascended_count(ctx, player.user_id)
    if repeat:
        ascension_rules.mark_repeat(ctx, pet.pet_id)
        ascension_rules.add_repeat(ctx, player.user_id, pet.pet_id)
        lines.append(f"{pet.name}重走雷劫、心魔、天道，本轮轮回试炼完成。")
        title = "轮回试炼完成"
    else:
        ascension_rules.mark_ascended(ctx, pet)
        ascension_rules.mark_repeat(ctx, pet.pet_id)
        lines.append(f"{pet.name}走完三段试炼，飞升成功！")
        lines.append("全属性 +10%，并解锁专属第五技能栏位。")
        title = "飞升成功"
    cycles = cycles_before
    roster = ctx.repo.owned_pets(player.user_id)
    if all(member.ascended for member in roster):
        cycles = ascension_rules.record_cycle(ctx, player.user_id)
        lines.append(f"周目：{cycles} · 全队飞升已记录新周目。")
    else:
        lines.append(f"周目：{cycles} · 队伍尚有伙伴未飞升，全队飞升后才记录新周目。")
    if not repeat and ascended_before == 0:
        lines.append("获得称号「破界者」，可在 灵宠称号 查看。")
    if cycles == 3 and cycles_before < 3:
        lines.append("获得称号「轮回行者」，三轮轮回已走过。")
    return Reply(title, tuple(lines), _reply_commands())


def dispatch(ctx: Context, arg: str) -> Reply:
    """Bare command opens the roster page; 分页 navigates; a pet number runs."""
    text = arg.strip()
    if not text or text.startswith("分页"):
        return catalog(ctx, text)
    return trial(ctx, text)
