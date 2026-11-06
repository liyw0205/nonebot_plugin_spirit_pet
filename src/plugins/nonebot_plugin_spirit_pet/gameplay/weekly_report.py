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
        f"信箱：收到 {received} 封 · 已领取 {claimed} 封。",
        "周报只读，不补发奖励；跨周后统计窗口自动切换。",
    ))
    return Reply(TITLE, tuple(lines), ("灵宠签到", "灵宠战报", "灵宠任务", "灵宠信箱"))


__all__ = ["report"]
