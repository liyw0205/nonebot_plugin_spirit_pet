"""Weekly non-combat activity summary built from existing permanent records."""

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.time import beijing_day, beijing_week

TITLE = "灵宠周报"
KIND_NAMES = {"pvp": "论剑", "spar": "切磋", "pve": "秘境", "pve_stage": "关卡"}


def _battles(ctx: Context, user_id: str, start: int, end: int) -> tuple[int, int, dict]:
    rows = ctx.repo.conn.execute(
        "SELECT b.kind AS kind, COUNT(*) AS fights, "
        "SUM(b.winner_side=p.side) AS wins "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.played_at>=? AND b.played_at<? "
        "GROUP BY b.kind",
        (user_id, start, end),
    ).fetchall()
    fights = sum(int(row["fights"]) for row in rows)
    wins = sum(int(row["wins"] or 0) for row in rows)
    return fights, wins, {row["kind"]: int(row["fights"]) for row in rows}


def _signins(ctx: Context, user_id: str, start: int, end: int) -> int:
    first, last = beijing_day(start), beijing_day(end - 1)
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE 'signin_day_%'",
        (user_id,),
    ).fetchall()
    return sum(
        1 for row in rows
        if first <= row["quest_id"][len("signin_day_"):] <= last
    )


def _expeditions(ctx: Context, user_id: str, start: int, end: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM expeditions "
        "WHERE user_id=? AND started_at>=? AND started_at<?",
        (user_id, start, end),
    ).fetchone()
    return int(row["n"])


def _mail(ctx: Context, user_id: str, start: int, end: int) -> tuple[int, int]:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n, "
        "SUM(CASE WHEN state='claimed' THEN 1 ELSE 0 END) AS claimed "
        "FROM mail_messages WHERE recipient_id=? AND created_at>=? AND created_at<?",
        (user_id, start, end),
    ).fetchone()
    return int(row["n"]), int(row["claimed"] or 0)


def _arc_choices(ctx: Context, user_id: str, start: int, end: int) -> int:
    """This week's fate-arc choices, summed from the per-day counter rows.

    `counters.bump` already writes one ``stat_<metric>_day_<date>`` row per Beijing day, so
    the week's total is a read of existing rows: no new table, no back-fill, no reward.
    """
    first, last = beijing_day(start), beijing_day(end - 1)
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress "
        "WHERE user_id=? AND quest_id LIKE 'stat_arc_choices_day_%'",
        (user_id,),
    ).fetchall()
    return sum(
        int(row["progress"]) for row in rows
        if first <= row["quest_id"][len("stat_arc_choices_day_"):] <= last
    )


def _duel_wins(ctx: Context, user_id: str, start: int) -> int:
    """Guardians beaten this week: the `duel_week_<week start>_<id>` markers."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress "
        "WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (user_id, f"duel_week_{start}_*"),
    ).fetchone()
    return int(row["n"])


def _drill_attempts(ctx: Context, user_id: str, start: int, end: int) -> int:
    """Drill attempts this week, summed from the per-day `drill_<day>` rows."""
    first, last = beijing_day(start), beijing_day(end - 1)
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress "
        "WHERE user_id=? AND quest_id LIKE 'drill_%'",
        (user_id,),
    ).fetchall()
    total = 0
    for row in rows:
        day = row["quest_id"][len("drill_"):]
        # The day suffix is an ISO date (YYYY-MM-DD); compare it as text, in range.
        if first <= day <= last:
            total += int(row["progress"])
    return total


def _glob_count(ctx: Context, user_id: str, pattern: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, pattern),
    ).fetchone()
    return int(row["n"])


def _week_grades(ctx: Context, user_id: str, start: int) -> tuple[int, int]:
    """This week's escort clears and full clears, from the `escort_<week>_<mission>` rows."""
    rows = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, f"escort_{start}_*"),
    ).fetchall()
    grades = [int(row["progress"]) for row in rows]
    return sum(1 for value in grades if value > 0), sum(1 for value in grades if value >= 2)


def _forbidden_depths(ctx: Context, user_id: str, start: int) -> int:
    """Forbidden depths cleared this week (the `_all` bonus marker is not a depth)."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND quest_id GLOB ?"
        " AND quest_id NOT GLOB ?",
        (user_id, f"forbidden_{start}_*", f"forbidden_{start}_all"),
    ).fetchone()
    return int(row["n"])


def _tribulation_slots(ctx: Context, user_id: str, start: int) -> int:
    """Tribulation contracts cleared this week (the `_all` sweep marker is not a slot)."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND quest_id GLOB ?"
        " AND quest_id NOT GLOB ?",
        (user_id, f"trib_{start}_*", f"trib_{start}_all"),
    ).fetchone()
    return int(row["n"])


def _codex_week_slots(ctx: Context, user_id: str, start: int) -> int:
    """Weekly codex trials cleared this week (`codex_week_<week>_<slot>` rows)."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, f"codex_week_{start}_*"),
    ).fetchone()
    return int(row["n"])


def _gauntlet_rounds(ctx: Context, user_id: str, start: int) -> int:
    """Round markers cleared this week across every shipped ladder.

    Keys are `gauntlet_<week>_<round>` for the shipped ladder and
    `gauntlet_<ladder>_<week>_<round>` for the others, so the week segment is found
    by scanning rather than by one glob; the `_all` markers are not rounds.
    """
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB 'gauntlet_*'",
        (user_id,),
    ).fetchall()
    total = 0
    for row in rows:
        parts = str(row["quest_id"]).split("_")
        if len(parts) >= 3 and parts[-2] == str(start) and parts[-1].isdigit():
            total += 1
    return total


def report(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠周报 不接受参数，直接发送即可。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, (
            "周报按北京时间自然周汇总签到、战斗、委托与收到信件，只读不写。",
            "尚未结契，先完成领养；周报不会补发奖励。",
        ), ("灵宠帮助",), ())
    start, end = beijing_week(ctx.now)
    fights, wins, by_kind = _battles(ctx, ctx.user_id, start, end)
    signins = _signins(ctx, ctx.user_id, start, end)
    expeditions = _expeditions(ctx, ctx.user_id, start, end)
    received, claimed = _mail(ctx, ctx.user_id, start, end)
    chooser = _arc_choices(ctx, ctx.user_id, start, end)
    duels = _duel_wins(ctx, ctx.user_id, start)
    drills = _drill_attempts(ctx, ctx.user_id, start, end)
    trials = _glob_count(ctx, ctx.user_id, f"team_trial_{start}_*")
    gauntlets = _gauntlet_rounds(ctx, ctx.user_id, start)
    escorts, escorts_full = _week_grades(ctx, ctx.user_id, start)
    forbidden_depths = _forbidden_depths(ctx, ctx.user_id, start)
    tribulation_slots = _tribulation_slots(ctx, ctx.user_id, start)
    codex_slots = _codex_week_slots(ctx, ctx.user_id, start)
    lines = [
        f"统计区间：{beijing_day(start)} 至 {beijing_day(end - 1)}（北京时间）。",
        f"签到：{signins} 天。",
        f"战斗：{fights} 场 · {wins} 胜。",
    ]
    detail = " · ".join(
        f"{KIND_NAMES.get(kind, kind)} {count} 场"
        for kind, count in sorted(by_kind.items())
    )
    if detail:
        lines.append(f"分类：{detail}。")
    lines.extend((
        f"委托：本周出发 {expeditions} 次。",
        f"斗法：本周胜 {duels} 位护法。",
        f"演武：本周出手 {drills} 次。",
        f"团队试炼：本周通关 {trials} 场。",
        f"擂台：本周通过 {gauntlets} 关。",
        f"护送：本周通关 {escorts} 条 · 满评 {escorts_full} 条。",
        f"禁地：本周通关 {forbidden_depths} 层。",
        f"劫境：本周清掉 {tribulation_slots} 份契约。",
        f"图鉴试炼：本周通关 {codex_slots} 场。",
        f"奇缘：本周做出 {chooser} 次抉择。",
        f"信箱：收到 {received} 封 · 已领取 {claimed} 封。",
        "周报只读，不补发奖励；跨周后统计窗口自动切换。",
    ))
    return Reply(TITLE, tuple(lines), ("灵宠签到", "灵宠战报", "灵宠任务", "灵宠信箱"))


__all__ = ["report"]
