"""Weekly race settlement: last week's top three, their rewards, and the archive.

``race.enter`` already persists every week's best time as
``quest_progress.race_best_<week start>``. Until now only the current week key
was read, so a completed week's rows were write-only history. This module adds
the missing read and settlement path without touching the race itself:

* ``race_prize_<week start>`` — claim marker (``progress`` is the final rank)
* the top three of the previous Beijing week claim once during the current week
* older weeks stay readable, but their claim window is over

No new table or column: the archive is the existing race-best rows.
"""

from datetime import date, datetime

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING, beijing_day, beijing_week
from .race import time_text
from .rewards import grant

WEEK_SECONDS = 7 * 86_400
PAGE_SIZE = 6
CLAIM_PREFIX = "race_prize_"
BEST_PREFIX = "race_best_"


def week_start_of(now: int) -> int:
    return beijing_week(now)[0]


def week_label(start: int) -> str:
    return beijing_day(start)


def current_start(ctx: Context) -> int:
    return week_start_of(ctx.now)


def last_start(ctx: Context) -> int:
    return current_start(ctx) - WEEK_SECONDS


def claim_key(start: int) -> str:
    return f"{CLAIM_PREFIX}{start}"


def parse_week(value: str) -> int:
    """Accept only a Beijing Monday date; the label is also the command argument."""
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise GameError("周编号格式：灵宠竞速奖励 2026-10-26（必须是周一日期）。") from exc
    start = int(datetime(day.year, day.month, day.day, tzinfo=BEIJING).timestamp())
    if beijing_week(start)[0] != start:
        raise GameError("周编号必须是周一的日期，例如 2026-10-26。")
    return start


def _rows(ctx: Context, start: int) -> list:
    return ctx.repo.conn.execute(
        "SELECT identity.id + 9999 AS uid, progress.progress AS time, "
        "progress.user_id AS user_id "
        "FROM quest_progress progress JOIN player_identity identity USING(user_id) "
        "WHERE progress.quest_id=? ORDER BY progress.progress ASC, identity.id ASC",
        (f"{BEST_PREFIX}{start}",),
    ).fetchall()


def top(ctx: Context, start: int, limit: int = 3) -> list[dict]:
    return [
        {"rank": index, "uid": row["uid"], "time": row["time"], "user_id": row["user_id"]}
        for index, row in enumerate(_rows(ctx, start)[:limit], 1)
    ]


def my_time(ctx: Context, user_id: str, start: int) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, f"{BEST_PREFIX}{start}"),
    ).fetchone()
    return None if row is None else int(row["progress"])


def rank_of(ctx: Context, user_id: str, start: int) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT ranked FROM ("
        "SELECT progress.user_id AS user_id,"
        " ROW_NUMBER() OVER (ORDER BY progress.progress ASC, identity.id ASC) AS ranked"
        " FROM quest_progress progress JOIN player_identity identity USING(user_id)"
        " WHERE progress.quest_id=?"
        ") WHERE user_id=?",
        (f"{BEST_PREFIX}{start}", user_id),
    ).fetchone()
    return int(row["ranked"]) if row is not None else None


def archived_weeks(ctx: Context) -> list[int]:
    rows = ctx.repo.conn.execute(
        "SELECT DISTINCT quest_id FROM quest_progress WHERE quest_id LIKE ?",
        (f"{BEST_PREFIX}%",),
    ).fetchall()
    current = current_start(ctx)
    weeks = []
    for row in rows:
        suffix = row["quest_id"][len(BEST_PREFIX):]
        try:
            start = int(suffix)
        except ValueError:
            continue
        if start < current:
            weeks.append(start)
    return sorted(set(weeks), reverse=True)


def _claim_record(ctx: Context, user_id: str, start: int):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_key(start)),
    ).fetchone()


def claimed(ctx: Context, user_id: str, start: int) -> bool:
    record = _claim_record(ctx, user_id, start)
    return bool(record and record["claimed"])


def _prize(ctx: Context, rank: int):
    return ctx.content.race_prizes.get(rank)


def _prize_text(ctx: Context, rank: int) -> str:
    prize = _prize(ctx, rank)
    if prize is None:
        return "奖励待修复"
    parts = [f"灵石 {prize.stones}"] if prize.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in prize.items.items()
    )
    return "，".join(parts) if parts else "奖励待修复"


def _reward(prize) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=prize.stones, maximum=prize.stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in prize.items.items()
        },
    )


def _state(ctx: Context, user_id: str, start: int, rank: int | None) -> str:
    if claimed(ctx, user_id, start):
        return "已领取"
    if rank is None:
        return "未参赛"
    if rank <= 3:
        return "可领取"
    return f"第 {rank} 名 · 未进入前三"


def _unregistered(ctx: Context, argument: str) -> Reply:
    if argument.strip() and argument.strip() != "往期":
        raise GameError("尚未结契，先完成领养，才能查看自己的竞速记录。")
    start = last_start(ctx)
    lines = [
        "每周一 00:00（北京时间）结算上一自然周，前三名可在本周领取一次固定奖励。",
        f"上周（{week_label(start)} 起）前三名：",
    ]
    rows = top(ctx, start)
    if rows:
        lines.extend(
            f"{row['rank']}. UID {row['uid']} · {time_text(row['time'])}"
            for row in rows
        )
    else:
        lines.append("还没有已结算的成绩。")
    lines.extend(
        f"第 {rank} 名 · {_prize_text(ctx, rank)}" for rank in (1, 2, 3)
    )
    lines.append("尚未结契，先完成领养；上周的榜单仍可公开查看。")
    return Reply(
        "灵宠竞速奖励", tuple(lines), ("灵宠帮助",),
        (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),),
    )


def _settlement(ctx: Context, argument: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return _unregistered(ctx, argument)
    start = last_start(ctx)
    rows = top(ctx, start)
    lines = [
        "每周一 00:00（北京时间）结算上一自然周，前三名可在本周领取一次固定奖励，过期不补。",
        f"上周（{week_label(start)} 起）前三名：",
    ]
    if rows:
        lines.extend(
            f"{row['rank']}. UID {row['uid']} · {time_text(row['time'])}"
            for row in rows
        )
    else:
        lines.append("还没有已结算的成绩。")
    rank = rank_of(ctx, player.user_id, start)
    mine = my_time(ctx, player.user_id, start)
    links = []
    if mine is not None and rank is not None:
        state = _state(ctx, player.user_id, start, rank)
        lines.append(f"你的上周成绩：第 {rank} 名 · {time_text(mine)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取上周奖励", "灵宠竞速领奖"))
    else:
        lines.append("你上周没有参赛。")
    lines.append(
        f"本周（{week_label(current_start(ctx))} 起）进行中，周一 00:00 结算。"
    )
    lines.append(
        "奖励：" + "；".join(
            f"第 {rank} 名 {_prize_text(ctx, rank)}" for rank in (1, 2, 3)
        ) + "。"
    )
    weeks = archived_weeks(ctx)
    if weeks:
        lines.append(f"往期周榜：{len(weeks)} 周可回顾。")
        links.append(InlineCommand(len(lines) - 1, "查看往期", "灵宠竞速奖励 往期"))
    else:
        lines.append("还没有更早的已结算周。")
    return Reply("灵宠竞速奖励", tuple(lines), ("灵宠竞速", "灵宠竞速榜", "灵宠帮助"), tuple(links))


def _archive(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if len(parts) > 2:
        raise GameError("格式：灵宠竞速奖励 往期 [页码]。")
    page = 1
    if len(parts) > 1:
        try:
            page = int(parts[1])
        except ValueError as exc:
            raise GameError("格式：灵宠竞速奖励 往期 [页码]。") from exc
    if page < 1:
        raise GameError("页码必须从 1 开始。")
    weeks = archived_weeks(ctx)
    pages = max(1, (len(weeks) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"往期周榜只有 {pages} 页。")
    lines = [f"往期竞速周榜（第 {page}/{pages} 页，每页 {PAGE_SIZE} 周）："]
    links = []
    if not weeks:
        lines.append("还没有已结算的周。")
    for start in weeks[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        rows = top(ctx, start, 1)
        if rows:
            winner = rows[0]
            lines.append(
                f"{week_label(start)} 起 · 冠军 UID {winner['uid']} · "
                f"{time_text(winner['time'])} · 共 {len(_rows(ctx, start))} 人"
            )
        else:
            lines.append(f"{week_label(start)} 起 · 无人参赛")
        links.append(
            InlineCommand(len(lines) - 1, "查看该周", f"灵宠竞速奖励 {week_label(start)}")
        )
    if pages > 1:
        navigation = []
        if page > 1:
            navigation.append(f"灵宠竞速奖励 往期 {page - 1}")
        if page < pages:
            navigation.append(f"灵宠竞速奖励 往期 {page + 1}")
        lines.append("翻页：" + " / ".join(navigation))
        if page > 1:
            links.append(InlineCommand(len(lines) - 1, "上一页", f"灵宠竞速奖励 往期 {page - 1}"))
        if page < pages:
            links.append(InlineCommand(len(lines) - 1, "下一页", f"灵宠竞速奖励 往期 {page + 1}"))
    return Reply("灵宠竞速奖励 · 往期", tuple(lines), ("灵宠竞速奖励", "灵宠竞速", "灵宠帮助"), tuple(links))


def _detail(ctx: Context, argument: str) -> Reply:
    start = parse_week(argument)
    if start >= current_start(ctx):
        raise GameError("本周尚未结算，只能查看上一自然周及更早的周榜。")
    rows = top(ctx, start)
    lines = [f"竞速周榜 · {week_label(start)} 起（已结算）："]
    if rows:
        lines.extend(
            f"{row['rank']}. UID {row['uid']} · {time_text(row['time'])}"
            for row in rows
        )
    else:
        lines.append("该周无人参赛。")
    player = ctx.repo.player(ctx.user_id)
    links = []
    if player is not None:
        mine = my_time(ctx, player.user_id, start)
        rank = rank_of(ctx, player.user_id, start)
        if mine is None or rank is None:
            lines.append("你该周没有参赛。")
        else:
            state = _state(ctx, player.user_id, start, rank)
            if start != last_start(ctx):
                state = "已归档 · 领取期已过" if not claimed(ctx, player.user_id, start) else "已领取"
            lines.append(f"你的成绩：第 {rank} 名 · {time_text(mine)} · {state}")
            if start == last_start(ctx) and state == "可领取":
                links.append(InlineCommand(len(lines) - 1, "领取上周奖励", "灵宠竞速领奖"))
    lines.append("奖励：" + "；".join(
        f"第 {rank} 名 {_prize_text(ctx, rank)}" for rank in (1, 2, 3)
    ) + "。")
    lines.append("返回本周结算页或查看往期周榜。")
    links.append(InlineCommand(len(lines) - 1, "返回结算", "灵宠竞速奖励"))
    links.append(InlineCommand(len(lines) - 1, "查看往期", "灵宠竞速奖励 往期"))
    return Reply("灵宠竞速奖励", tuple(lines), ("灵宠竞速", "灵宠竞速榜", "灵宠帮助"), tuple(links))


def catalog(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value == "往期" or value.startswith("往期 "):
        return _archive(ctx, value)
    if value:
        return _detail(ctx, value)
    return _settlement(ctx, value)


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    start = last_start(ctx)
    if value and value != "上周":
        parsed = parse_week(value)
        if parsed != start:
            raise GameError("只能领取上一自然周的竞速奖励；更早的周已归档，不能补领。")
    player = ctx.player()
    record = _claim_record(ctx, player.user_id, start)
    if record is not None and record["claimed"]:
        raise GameError("上周的竞速奖励已经领取。")
    if record is not None:
        raise GameError("竞速奖励领取记录异常，请联系管理员检查存档。")
    rank = rank_of(ctx, player.user_id, start)
    if rank is None:
        raise GameError("你上周没有参赛，没有可领取的竞速奖励。")
    if rank > 3:
        raise GameError(f"你上周第 {rank} 名，未进入前三，没有可领取的竞速奖励。")
    prize = _prize(ctx, rank)
    if prize is None or any(item_id not in ctx.content.items for item_id in prize.items):
        raise GameError("竞速奖励物品定义缺失；尚未领取。")
    mine = my_time(ctx, player.user_id, start)
    if mine is None:
        raise GameError("你上周没有参赛，没有可领取的竞速奖励。")
    result = grant(ctx, _reward(prize), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_key(start), rank),
    )
    return Reply("竞速周奖励", (
        f"{week_label(start)} 起 · 第 {rank} 名 · {time_text(mine)}。",
        *result,
        "奖励已领取；下周榜单从周一 00:00 重新开始。",
    ), ("灵宠竞速奖励", "灵宠竞速榜", "灵宠目标"))


def objective_line(ctx: Context, user_id: str) -> str | None:
    """Only overrides the objective line when last week's prize is claimable."""
    player = ctx.repo.player(user_id)
    if player is None:
        return None
    start = last_start(ctx)
    rank = rank_of(ctx, user_id, start)
    if rank is not None and rank <= 3 and not claimed(ctx, user_id, start):
        return f"竞速：上周第 {rank} 名，奖励可领"
    return None


__all__ = [
    "PAGE_SIZE", "catalog", "claim", "claimed", "objective_line",
    "rank_of", "top", "week_label",
]
