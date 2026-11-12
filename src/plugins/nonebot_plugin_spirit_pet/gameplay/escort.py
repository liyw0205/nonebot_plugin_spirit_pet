"""Pet escort: an NPC fights beside the lineup and must survive every wave.

The escort is an ordinary ``Fighter`` placed on the player's side, so no engine change is needed.
Waves are fought in order against the same player-side fighters (hp carries over), and the run only
counts as a win when every wave is cleared **and** the escort is still standing. The payout is
graded by the escort's remaining health, so a messy win is worth less than a clean one.

State is one ``quest_progress`` row per mission per week whose ``progress`` is the best grade reached
(1 = partial, 2 = full). A first partial clear pays the partial reward; a later full clear pays only
the difference, so clearing early never costs the player anything.
"""

import re

from ..application.context import Context
from ..domain.content import Stats
from ..domain.escort_content import EscortMission
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import Fighter, enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

KEY = "escort_"
PARTIAL = 1
FULL = 2
CLEAN_RATIO = 0.5
HISTORY = frozenset({"战历", "战绩"})
HISTORY_PAGE_SIZE = 6
# `escort_<week start>_<mission id>`; mission ids carry no underscore.
WEEK_MARKER = re.compile(r"^escort_([0-9]+)_(.+)$")


def missions(ctx: Context):
    return sorted(ctx.content.escorts.values(), key=lambda mission: mission.energy)


def mission(ctx: Context, arg: str) -> EscortMission:
    return named(ctx.content.escorts, arg)


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _key(ctx: Context, mission_id: str) -> str:
    return f"{KEY}{week_start(ctx)}_{mission_id}"


def grade(ctx: Context, mission_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(ctx, mission_id)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def cleared_count(ctx: Context, user_id: str | None = None) -> int:
    return sum(1 for mission_ in missions(ctx) if grade(ctx, mission_.id, user_id) > 0)


def weeks_run(ctx: Context, user_id: str | None = None) -> list[tuple[int, int, int]]:
    """Every recorded escort week as ``(week start, missions cleared, full clears)``.

    The per-mission grade rows are permanent and only the current week is read, so a
    past week was unreachable. This groups exactly those rows, newest week first; a
    mission that has left the shipped content still counts by its row.
    """
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id or ctx.user_id, f"{KEY}*"),
    ).fetchall()
    weeks: dict[int, list[int]] = {}
    for row in rows:
        match = WEEK_MARKER.match(str(row["quest_id"]))
        if match is None:
            continue
        weeks.setdefault(int(match.group(1)), []).append(int(row["progress"]))
    return sorted(
        (
            (start, sum(1 for value in grades if value > 0), sum(1 for value in grades if value >= FULL))
            for start, grades in weeks.items()
        ),
        key=lambda item: item[0],
        reverse=True,
    )


def history(ctx: Context, arg: str) -> Reply:
    """Read-only record of past escort weeks; pays nothing, writes nothing."""
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "护送战历",
            (
                "尚未结契，先完成领养，才能留下护送记录。",
                "战历按周回顾通关与满评次数，只读，不补发奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    records = weeks_run(ctx)
    if not records:
        return Reply(
            "护送战历",
            (
                "还没有护送记录，先发送 灵宠护送 出发一次。",
                "每次通关会在本周留下一条评价，战历按周汇总。",
            ),
            ("灵宠护送", "灵宠目标", "我的灵宠"),
        )
    page = paginate(records, arg, "护送战历", "灵宠护送 战历", HISTORY_PAGE_SIZE)
    lines = [
        f"共 {len(records)} 周有记录 · 第 {page.number}/{page.total} 页（新的在前）。",
    ]
    for start, cleared, full in page.entries:
        lines.append(f"{beijing_day(start)} 起那一周 · 通关 {cleared} 条 · 满评 {full} 条")
    lines.append("战历只读：不重跑、不补发奖励，也不改变本周评价。")
    return Reply(
        "护送战历",
        tuple(lines),
        (*page.navigation, "灵宠护送", "灵宠目标")[:4],
    )


def _grade_text(value: int) -> str:
    return {FULL: "满评", PARTIAL: "部分评价"}.get(value, "未通关")


def escort_fighter(ctx: Context, mission_: EscortMission) -> Fighter:
    npc = mission_.npc
    return Fighter.create(
        npc.name,
        Stats(hp=npc.hp, attack=npc.attack, defense=npc.defense, speed=npc.speed),
    )


def payout_text(ctx: Context, reward) -> str:
    parts = [f"修为 {reward.exp.minimum}", f"灵石 {reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def _difference(ctx: Context, full, partial):
    """The extra payout for upgrading a partial clear to a full one."""
    from ..domain.content import Range

    items = {}
    for item_id, bounds in full.items.items():
        extra = bounds.minimum - partial.items[item_id].minimum if item_id in partial.items else bounds.minimum
        if extra > 0:
            items[item_id] = Range(minimum=extra, maximum=extra)
    return type(full)(
        exp=Range(minimum=full.exp.minimum - partial.exp.minimum, maximum=full.exp.maximum - partial.exp.maximum),
        stones=Range(minimum=full.stones.minimum - partial.stones.minimum, maximum=full.stones.maximum - partial.stones.maximum),
        items=items,
    )


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠护送 [出发 <任务>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠护送",
            (
                "尚未结契，先完成领养，才能接下护送任务。",
                "护送目标与你并肩作战，必须活着走完全部波次；它剩下的血越多，报酬越高。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = ["护送目标会加入我方参战，血量跨波延续；全波清完且目标存活才算通关。"]
    links = []
    for mission_ in missions(ctx):
        npc = mission_.npc
        enemies = "、".join(
            f"第{index}波 " + "、".join(ctx.content.enemies[enemy_id].name for enemy_id in wave)
            for index, wave in enumerate(mission_.waves, 1)
        )
        state = _grade_text(grade(ctx, mission_.id))
        lines.append(
            f"{mission_.name} · 目标 {npc.name} 气血 {npc.hp}/攻击 {npc.attack}"
            f" · {len(mission_.waves)} 波（{enemies}）· 精力 {mission_.energy} · {state}"
        )
        lines.append(
            f"   满评 {payout_text(ctx, mission_.rewards.full)}"
            f" · 部分 {payout_text(ctx, mission_.rewards.partial)}"
        )
        if grade(ctx, mission_.id) < FULL:
            links.append(InlineCommand(len(lines) - 2, "出发", f"灵宠护送 出发 {mission_.name}"))
    lines.append("每周一 00:00 重置；本周先拿部分评价、之后满评只补差额。")
    lines.append("也可带一位伙伴护航，途中自主择路、保护货物并消耗灵粮补给。")
    links.append(InlineCommand(len(lines) - 1, "前往护航", "灵宠护航"))
    return Reply("灵宠护送", tuple(lines), ("灵宠护送", "灵宠秘境", "灵宠战报"), tuple(links))


def start(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠护送 出发 <任务>。")
    mission_ = mission(ctx, arg)
    player = ctx.player()
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    checked = False
    for _, pet in selected:
        if not checked:
            ctx.check_action(player, pet, "pve", mission_.energy, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < mission_.energy:
                raise GameError(f"{pet.name}精力不足，护送需要 {mission_.energy} 点。")

    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    escort = escort_fighter(ctx, mission_)
    full_hp = escort.stats.hp
    team = [*allies, escort]
    for _, pet in selected:
        pet.energy -= mission_.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)

    lines = []
    survived = 0
    deciding = None
    for index, wave in enumerate(mission_.waves, 1):
        if escort.hp <= 0:
            break
        enemies = [enemy_fighter(ctx.content.enemies[enemy_id], ctx.content.skills) for enemy_id in wave]
        capture = capture_snapshot(ctx, (team, enemies), ([ctx.user_id], []))
        battle = fight(team, enemies, ctx.rng, ctx.content.elements)
        for user_id, pet in selected:
            lines.extend(award_mastery(
                ctx, user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
            ))
        escort_state = f"{escort.name} {max(0, escort.hp)}/{full_hp}"
        deciding = (battle, capture, enemies[0].name, index)
        if battle.winner != 0:
            lines.append(
                f"第 {index} 波："
                + ("平局" if battle.winner == -1 else "败")
                + f" · {battle.rounds} 回合 · {escort_state}。"
            )
            break
        survived += 1
        lines.append(f"第 {index} 波：胜 · {battle.rounds} 回合 · {escort_state}。")
        if escort.hp <= 0:
            lines.append(f"{escort.name}在混战中倒下，护送失败。")
            break

    won = survived == len(mission_.waves) and escort.hp > 0
    clean = won and escort.hp >= full_hp * CLEAN_RATIO
    new_grade = FULL if clean else (PARTIAL if won else 0)
    previous = grade(ctx, mission_.id)
    paid = 0
    if new_grade > previous:
        reward = mission_.rewards.full if new_grade == FULL and previous == 0 else (
            mission_.rewards.partial if new_grade == PARTIAL else _difference(ctx, mission_.rewards.full, mission_.rewards.partial)
        )
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (ctx.user_id, _key(ctx, mission_.id), new_grade),
        )
        lines.append(
            ("满评奖励：" if new_grade == FULL and previous == 0 else "部分奖励：" if new_grade == PARTIAL else "补足差额：")
            + "，".join(grant(ctx, reward))
        )
        paid = new_grade
    elif won:
        lines.append("本周该任务已达更高评价，本次不再重复发奖。")

    if deciding is not None:
        battle, capture, enemy_name, index = deciding
        record_battle(
            ctx, kind="pve_stage", battle=battle, capture=capture,
            reply=Reply("护送结果", tuple(lines)), battle_key=_key(ctx, mission_.id),
            battle_name=f"护送·{mission_.name}",
        )
    if won:
        advance(ctx, "pve")
    if clean:
        title = "护送满评"
    elif won:
        title = "护送达成"
    else:
        title = "护送失败"
    lines.append(
        f"本周该任务评价：{_grade_text(max(previous, new_grade))}；"
        f"每只出战伙伴精力 -{mission_.energy}。"
    )
    return Reply(title, tuple(lines), ("灵宠护送", "灵宠战报", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    if head in HISTORY:
        return history(ctx, " ".join(parts[1:]))
    if head == "出发":
        return start(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠护送 [战历|出发 <任务>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "护送：尚未结契"
    done = cleared_count(ctx, user_id)
    return f"护送：本周已通关 {done}/{len(missions(ctx))}" if done else "护送：本周尚未出发"
