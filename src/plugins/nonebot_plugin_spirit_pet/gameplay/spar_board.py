"""Weekly spar leaderboard derived from permanent spar battle records."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week

PAGE_SIZE = 10


def _rows(ctx: Context) -> list[dict]:
    start, end = beijing_week(ctx.now)
    return [
        dict(row)
        for row in ctx.repo.conn.execute(
            "SELECT p.user_id AS user_id, identity.id + 9999 AS uid, "
            "COUNT(*) AS fights, SUM(b.winner_side=p.side) AS wins, "
            "SUM(CASE WHEN b.winner_side=-1 THEN 1 ELSE 0 END) AS draws, "
            "SUM(CASE WHEN b.winner_side=1-p.side THEN 1 ELSE 0 END) AS losses, "
            "MAX(b.played_at) AS last_fight "
            "FROM battle_records b "
            "JOIN (SELECT DISTINCT battle_id, user_id, side FROM battle_participants) p "
            "ON p.battle_id=b.battle_id "
            "JOIN player_identity identity ON identity.user_id=p.user_id "
            "WHERE b.kind='spar' AND b.played_at>=? AND b.played_at<? "
            "GROUP BY p.user_id, identity.id",
            (start, end),
        ).fetchall()
    ]


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠切磋榜 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠切磋榜", (
            "切磋榜按北京时间自然周统计切磋胜场；周一切换后重新开始。",
            "尚未结契，先完成领养；切磋需要双方都选择出战灵宠。",
        ), ("灵宠切磋", "灵宠帮助"), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    rows = _rows(ctx)
    rows.sort(key=lambda row: (-row["wins"], -row["fights"], row["user_id"]))
    lines = ["按本周切磋胜场排名；同胜场先比场次，再按 UID 稳定排序。"]
    links = []
    if not rows:
        lines.append("本周还没有切磋记录。")
    else:
        for rank, row in enumerate(rows[:PAGE_SIZE], start=1):
            lines.append(
                f"{rank}. UID {row['uid']} · {row['wins']} 胜 {row['losses']} 负 "
                f"{row['draws']} 平 · {row['fights']} 场"
            )
            links.append(InlineCommand(
                len(lines) - 1, "查看战绩", f"灵宠切磋战绩 {row['uid']}",
            ))
        own_rank = next(
            (index for index, row in enumerate(rows, start=1) if row["user_id"] == player.user_id),
            None,
        )
        if own_rank is None:
            lines.append(f"你本周还没有切磋记录（共 {len(rows)} 位参与者）。")
        elif own_rank > PAGE_SIZE:
            lines.append(f"你的名次：第 {own_rank} 名（共 {len(rows)} 位参与者）。")
    commands = [link.command for link in links]
    commands.extend(("灵宠切磋", "灵宠切磋战绩", "灵宠战报"))
    return Reply("灵宠切磋榜", tuple(lines), tuple(commands), tuple(links))


__all__ = ["PAGE_SIZE", "catalog"]
