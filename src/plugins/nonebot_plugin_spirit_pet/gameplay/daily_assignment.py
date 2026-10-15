from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from .rewards import grant

OFFERED = 3
CLAIM = "daily_assignment"
# Today's records are found by scanning recent rows, so the window only bounds
# the query; the Beijing day filter below is what defines "today".
SCAN_WINDOW = 172800


def day_ordinal(now: int) -> int:
    return date.fromisoformat(beijing_day(now)).toordinal()


def todays(ctx: Context) -> tuple:
    """Today's assignments: a pure function of the Beijing day."""
    pool = tuple(ctx.content.daily_assignments.values())
    ordinal = day_ordinal(ctx.now)
    return tuple(pool[(ordinal * OFFERED + index) % len(pool)] for index in range(OFFERED))


def _chosen(ctx: Context, user_id: str):
    """The assignment claimed today, if any."""
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, CLAIM),
    ).fetchone()
    if not row or not row["claimed"]:
        return None
    stored = int(row["progress"])
    if stored // 10 != day_ordinal(ctx.now):
        return None
    offered = todays(ctx)
    index = stored % 10
    if not 1 <= index <= len(offered):
        return None
    return offered[index - 1]


def _today_rows(ctx: Context, query: str, params: tuple, column: str) -> int:
    today = beijing_day(ctx.now)
    rows = ctx.repo.conn.execute(query, params)
    return sum(1 for row in rows if row[column] is not None and beijing_day(row[column]) == today)


def _value(ctx: Context, user_id: str, assignment) -> int:
    """Assignment progress, always scoped to today."""
    if assignment.metric == "daily_pve":
        return _today_rows(
            ctx,
            "SELECT b.played_at AS stamp FROM battle_records b "
            "JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind IN ('pve','pve_stage') AND b.winner_side=p.side "
            "AND b.played_at>=?",
            (user_id, ctx.now - SCAN_WINDOW), "stamp",
        )
    if assignment.metric == "daily_pvp":
        return _today_rows(
            ctx,
            "SELECT played_at AS stamp FROM pvp_results "
            "WHERE (challenger_id=? OR target_id=?) AND played_at>=?",
            (user_id, user_id, ctx.now - SCAN_WINDOW), "stamp",
        )
    if assignment.metric == "daily_discovery":
        return _today_rows(
            ctx,
            "SELECT discovered_at AS stamp FROM adventure_discoveries "
            "WHERE user_id=? AND discovered_at>=?",
            (user_id, ctx.now - SCAN_WINDOW), "stamp",
        )
    if assignment.metric == "daily_expedition":
        return _today_rows(
            ctx,
            "SELECT settled_at AS stamp FROM expeditions "
            "WHERE user_id=? AND state='claimed' AND settled_at>=?",
            (user_id, ctx.now - SCAN_WINDOW), "stamp",
        )
    if assignment.metric == "daily_claim":
        return _today_rows(
            ctx,
            "SELECT claimed_at AS stamp FROM achievement_claims "
            "WHERE user_id=? AND claimed_at>=?",
            (user_id, ctx.now - SCAN_WINDOW), "stamp",
        )
    row = ctx.repo.conn.execute(
        "SELECT last_train FROM players WHERE user_id=?", (user_id,),
    ).fetchone()
    today = beijing_day(ctx.now)
    return 1 if row and row["last_train"] is not None and beijing_day(row["last_train"]) == today else 0


def _state(ctx: Context, user_id: str, assignment, chosen) -> str:
    if chosen is not None:
        return "今日已选" if chosen.id == assignment.id else "今日已错过"
    value = _value(ctx, user_id, assignment)
    if value >= assignment.target:
        return "可领取"
    return f"进行中（{value}/{assignment.target}）"


def _summary(ctx: Context, assignment) -> str:
    parts = [f"灵石 {assignment.reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}"
        for item, bounds in assignment.reward.items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠课题 不接受参数，直接发送即可。")
    offered = todays(ctx)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("今日课题", (
            f"每天轮换 {OFFERED} 项课题，任选其一完成后领取奖励，当日只能领取一项。",
            "课题按北京时间日期轮换，次日 00:00 换新，未领取不累积。",
            "尚未结契，先完成领养，再来查看今日课题。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    chosen = _chosen(ctx, player.user_id)
    lines = []
    links = []
    for assignment in offered:
        state = _state(ctx, player.user_id, assignment, chosen)
        lines.append(f"{assignment.name} · {_summary(ctx, assignment)} · {state}")
        lines.append(assignment.description)
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 2, "领取课题奖励", f"灵宠课题领奖 {assignment.name}",
            ))
    if chosen is None:
        lines.append("今日尚未领取；三项任选其一，其余两项当日作废。")
    else:
        lines.append(f"今日已选「{chosen.name}」；次日 00:00 换新。")
    return Reply("今日课题", tuple(lines), ("灵宠任务", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    assignment = named(ctx.content.daily_assignments, arg)
    offered = todays(ctx)
    if all(entry.id != assignment.id for entry in offered):
        names = "、".join(entry.name for entry in offered)
        raise GameError(f"今日课题没有「{assignment.name}」；今日可选：{names}。")
    chosen = _chosen(ctx, player.user_id)
    if chosen is not None:
        raise GameError(f"今日已选「{chosen.name}」，明日再来。")
    value = _value(ctx, player.user_id, assignment)
    if value < assignment.target:
        raise GameError(f"今日尚未完成：{assignment.description}（{value}/{assignment.target}）。")
    result = grant(ctx, assignment.reward, player.user_id)
    index = next(index for index, entry in enumerate(offered, start=1) if entry.id == assignment.id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, CLAIM, day_ordinal(ctx.now) * 10 + index),
    )
    return Reply("今日课题奖励", (
        f"{assignment.name} · {assignment.description}", *result,
        "今日其余课题已作废，次日 00:00 换新。",
    ), ("灵宠课题", "灵宠任务", "灵宠目标"))
