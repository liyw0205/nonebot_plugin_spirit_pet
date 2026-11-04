"""Public ranking of share owners by de-duplicated readers."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .shares import READER_PREFIX

PAGE_SIZE = 10


def ranking(ctx: Context) -> list[dict]:
    return [
        dict(row)
        for row in ctx.repo.conn.execute(
            "SELECT q.user_id AS user_id, identity.id + 9999 AS uid, COUNT(*) AS readers "
            "FROM quest_progress q JOIN players p ON p.user_id = q.user_id "
            "JOIN player_identity identity USING(user_id) "
            "WHERE q.quest_id LIKE ? "
            "GROUP BY q.user_id, identity.id "
            "ORDER BY readers DESC, q.user_id ASC",
            (f"{READER_PREFIX}%",),
        ).fetchall()
    ]


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠分享榜 不接受参数，直接发送即可。")
    rows = ranking(ctx)
    total = len(rows)
    lines = ["按分享被多少位不同玩家读过排名；同一读者重复阅读只算一位。"]
    if not rows:
        lines.append("还没有人分享过被阅读的战报。")
    else:
        for rank, row in enumerate(rows[:PAGE_SIZE], start=1):
            lines.append(f"{rank}. UID {row['uid']} · {row['readers']} 位读者")
        player = ctx.repo.player(ctx.user_id)
        if player is not None:
            own_rank = next(
                (index for index, row in enumerate(rows, start=1)
                 if row["user_id"] == player.user_id),
                None,
            )
            if own_rank is not None and own_rank > PAGE_SIZE:
                lines.append(f"你的名次：第 {own_rank} 名（共 {total} 位分享者）。")
            elif own_rank is None:
                lines.append(f"你还没有被阅读的分享（共 {total} 位分享者）。")
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先完成领养；榜单对所有人公开。")
        return Reply("灵宠分享榜", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))
    return Reply("灵宠分享榜", tuple(lines), (
        "灵宠分享", "灵宠分享榜奖励", "灵宠分享奖励", "灵宠战报",
    ), ())


__all__ = ["PAGE_SIZE", "catalog", "ranking"]
