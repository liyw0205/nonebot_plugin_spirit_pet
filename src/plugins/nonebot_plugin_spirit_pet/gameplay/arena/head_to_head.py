from ...application.context import Context
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.time import BEIJING
from datetime import datetime


def _opponent(ctx: Context, uid: str):
    text = uid.strip()
    target = ctx.repo.player_by_uid(text)
    if target is None:
        raise GameError("没有找到这位玩家，请填写有效的 UID，例如 灵宠论剑交锋 10001。")
    if target.user_id == ctx.user_id:
        raise GameError("不能查看与自己的交锋，请填写对方 UID。")
    return target


def _rows(ctx: Context, other_id: str):
    return ctx.repo.conn.execute(
        "SELECT season_id, challenger_id, target_id, winner_id, played_at "
        "FROM pvp_results WHERE (challenger_id=? AND target_id=?) "
        "OR (challenger_id=? AND target_id=?) ORDER BY played_at DESC, result_id DESC",
        (ctx.user_id, other_id, other_id, ctx.user_id),
    ).fetchall()


def head_to_head(ctx: Context, arg: str) -> Reply:
    ctx.player()
    target = _opponent(ctx, arg)
    rows = _rows(ctx, target.user_id)
    if not rows:
        return Reply(f"论剑交锋 · {target.uid_label}", (
            f"你与{target.uid_label}还没有论剑交锋记录。",
            "在论剑榜或匹配中挑战该修士后，这里会汇总历史战绩。",
        ), ("灵宠论剑榜", "灵宠匹配"), (
            InlineCommand(1, "查看匹配对手", "灵宠匹配"),
        ))

    wins = losses = draws = 0
    by_season: dict[str, list[int]] = {}
    for row in rows:
        if row["winner_id"] is None:
            outcome = 2
        elif row["winner_id"] == ctx.user_id:
            outcome = 0
        else:
            outcome = 1
        wins += outcome == 0
        losses += outcome == 1
        draws += outcome == 2
        bucket = by_season.setdefault(row["season_id"], [0, 0, 0])
        bucket[outcome] += 1

    last = rows[0]
    last_time = datetime.fromtimestamp(last["played_at"], BEIJING).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"与{target.uid_label}交锋 {len(rows)} 场 · {wins} 胜 {losses} 负 {draws} 平。",
        f"最近一场：{last['season_id']} 赛季 · {last_time}（北京时间）。",
        "按赛季分布（最近在前）：",
    ]
    for season_id, (season_wins, season_losses, season_draws) in sorted(
        by_season.items(), reverse=True,
    ):
        lines.append(f"{season_id} · {season_wins + season_losses + season_draws} 场"
                     f" · {season_wins} 胜 {season_losses} 负 {season_draws} 平")
    lines.append("具体战斗过程可在战报中查看；切磋不计入论剑交锋。")
    return Reply(
        f"论剑交锋 · {target.uid_label}", tuple(lines),
        ("灵宠战报", "灵宠论剑榜", "灵宠赛季"),
        (
            InlineCommand(len(lines) - 1, "查看战报列表", "灵宠战报"),
            InlineCommand(0, "再次挑战", f"灵宠论剑 {target.uid}"),
        ),
    )
