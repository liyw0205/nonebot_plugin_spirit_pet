"""Seven-day streak layered on top of the daily assignment receipt.

The existing daily assignment remains the only way to make progress.  This
module records a small, optional streak in ``quest_progress`` and is called by
``daily_assignment.claim`` before that transaction returns, so the daily reward
and the streak reward can never commit separately.
"""

from datetime import date

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import beijing_day
from .rewards import grant

TITLE = "灵宠课题连章"
DAYS = 7
DEPOSIT = 300
FINAL_STONES = 700
FINAL_ITEMS = {"spirit_food": 7, "forge_ore": 2}

ACTIVE = "assignment_chain_active"
COUNT = "assignment_chain_count"
LAST = "assignment_chain_last"
DAY_PREFIX = "assignment_chain_day_"
RESULT_PREFIX = "assignment_chain_result_"
COMPLETE = 1
FAILED = 2
ABANDONED = 3
HISTORY_PAGE_SIZE = 6


def day_ordinal(now: int) -> int:
    return date.fromisoformat(beijing_day(now)).toordinal()


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    if row is None or not row["claimed"]:
        return None
    return int(row["progress"])


def _set(ctx: Context, key: str, value: int, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (user_id or ctx.user_id, key, value),
    )


def _active(ctx: Context, user_id: str | None = None) -> dict | None:
    owner = user_id or ctx.user_id
    start = _progress(ctx, ACTIVE, owner)
    if start is None:
        return None
    count = _progress(ctx, COUNT, owner)
    last = _progress(ctx, LAST, owner)
    if count is None or last is None or last < start - 1 or count < 0 or count >= DAYS:
        raise GameError("课题连章存档不完整，请联系管理员检查存档。")
    return {"start": start, "count": count, "last": last}


def active(ctx: Context, user_id: str | None = None) -> dict | None:
    """Read-only state used by objectives and the daily digest."""
    return _active(ctx, user_id)


def _clear(ctx: Context) -> None:
    ctx.repo.conn.executemany(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        [(ctx.user_id, ACTIVE), (ctx.user_id, COUNT), (ctx.user_id, LAST)],
    )


def _result_key(start: int) -> str:
    return f"{RESULT_PREFIX}{start}"


def _record_result(ctx: Context, start: int, status: int, count: int) -> None:
    _set(ctx, _result_key(start), status * 100 + count)


def _finish(ctx: Context, state: dict, status: int) -> None:
    _record_result(ctx, state["start"], status, state["count"])
    _clear(ctx)


def _fixed_reward() -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=FINAL_STONES, maximum=FINAL_STONES),
        items={item: Range(minimum=amount, maximum=amount) for item, amount in FINAL_ITEMS.items()},
    )


def _date_label(ordinal: int) -> str:
    return date.fromordinal(ordinal).isoformat()


def _status_text(value: int) -> tuple[str, int]:
    status, count = divmod(value, 100)
    return {COMPLETE: "完成", FAILED: "断档失败", ABANDONED: "主动放弃"}.get(status, "未知"), count


def _day_key(start: int, day: int, assignment_id: str) -> str:
    return f"{DAY_PREFIX}{start}_{day}_{assignment_id}"


def _record_day(ctx: Context, state: dict, day: int, assignment) -> None:
    _set(ctx, _day_key(state["start"], day, assignment.id), state["count"] + 1)


def _gap(state: dict, today: int) -> bool:
    return today > state["last"] + 1


def _final_lines(ctx: Context, state: dict) -> tuple[str, ...]:
    player = ctx.player()
    player.stones += DEPOSIT
    result = grant(ctx, _fixed_reward(), player.user_id)
    _record_result(ctx, state["start"], COMPLETE, DAYS)
    _clear(ctx)
    return (
        f"七日连章完成：押金 {DEPOSIT} 灵石已退回。",
        f"终章奖励：{'，'.join(result)}。",
        "连章记录已保存，可发送 灵宠课题连章 记录 回顾。",
    )


def record_claim(ctx: Context, assignment) -> tuple[str, ...]:
    """Advance an active run from a successful daily-assignment claim.

    The caller invokes this before returning its reply, inside the same Store
    transaction.  A missed day is a normal outcome of the daily claim, not a
    reason to roll back that day's unrelated assignment reward.
    """
    state = _active(ctx)
    if state is None:
        return ()
    today = day_ordinal(ctx.now)
    if today < state["start"] or today < state["last"]:
        raise GameError("系统日期早于课题连章记录，请等待日期恢复。")
    if today == state["last"]:
        raise GameError("今日课题已经计入连章，请勿重复提交。")
    if _gap(state, today):
        _finish(ctx, state, FAILED)
        return (
            f"课题连章已因漏过 {_date_label(state['last'] + 1)} 断档，押金不退；本次课题仍正常领取。",
        )
    if today != state["last"] + 1:
        raise GameError("课题连章日期不连续，请稍后重试。")
    _record_day(ctx, state, today, assignment)
    state["count"] += 1
    state["last"] = today
    if state["count"] == DAYS:
        return _final_lines(ctx, state)
    _set(ctx, COUNT, state["count"])
    _set(ctx, LAST, state["last"])
    return (
        f"课题连章第 {state['count']}/{DAYS} 日完成，还需 {DAYS - state['count']} 天。",
        f"下一日：{_date_label(today + 1)}；连续完成才会退回押金并发终章奖励。",
    )


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [开启|放弃|记录 [页码]]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能参加课题连章。",
                f"开启后连续 {DAYS} 个北京时间自然日领取每日课题；押金 {DEPOSIT} 灵石，完成后原额退回。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    state = _active(ctx)
    lines = [
        f"规则：连续 {DAYS} 日各领取一项每日课题；押金 {DEPOSIT} 灵石，终章固定奖励灵石 {FINAL_STONES}、灵粮 {FINAL_ITEMS['spirit_food']}、锻灵矿 {FINAL_ITEMS['forge_ore']}。",
    ]
    links = []
    if state is None:
        lines.append("当前未开启连章；今日课题尚未领取时可开启。")
        links.append(InlineCommand(len(lines) - 1, "开启连章", f"{TITLE} 开启"))
    else:
        today = day_ordinal(ctx.now)
        if _gap(state, today):
            lines.append(
                f"当前连章已断档：第 {state['count']}/{DAYS} 日，漏过 {_date_label(state['last'] + 1)}；下一次写操作会结算失败。"
            )
        else:
            next_day = state["last"] + 1
            lines.append(
                f"进行中：第 {state['count']}/{DAYS} 日 · 上次 {_date_label(state['last']) if state['count'] else '尚未开始'} · "
                f"下一次应在 {_date_label(next_day)} 领取课题。"
            )
            links.append(InlineCommand(len(lines) - 1, "查看今日课题", "灵宠课题"))
        links.append(InlineCommand(len(lines) - 1, "放弃连章", f"{TITLE} 放弃"))
    lines.append("课题奖励仍按原规则发放；连章只在每日课题成功领奖后推进，不会代领或补发漏日。")
    links.append(InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"))
    return Reply(TITLE, tuple(lines), ("灵宠目标", "灵宠帮助"), tuple(links))


def start(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} 开启。")
    player = ctx.player()
    today = day_ordinal(ctx.now)
    state = _active(ctx)
    if state is not None and _gap(state, today):
        _finish(ctx, state, FAILED)
        state = None
    if state is not None:
        raise GameError("已有进行中的课题连章，请先完成今日课题或主动放弃。")
    from . import daily_assignment

    if daily_assignment._chosen(ctx, player.user_id) is not None:
        raise GameError("今日课题已经领取，明日开始连章更稳妥。")
    if player.stones < DEPOSIT:
        raise GameError(f"开启课题连章需要押金 {DEPOSIT} 灵石，当前 {player.stones}。")
    player.stones -= DEPOSIT
    _set(ctx, ACTIVE, today)
    _set(ctx, COUNT, 0)
    _set(ctx, LAST, today - 1)
    return Reply(TITLE, (
        f"已开启七日课题连章：押金 {DEPOSIT} 灵石已托管。",
        f"今日为第 1/{DAYS} 日，请先完成任一今日课题并领取奖励。",
        "每日课题仍只可领取一项；漏过自然日押金不退。",
    ), (TITLE, "灵宠课题", "灵宠目标"))


def abandon(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} 放弃。")
    ctx.player()
    state = _active(ctx)
    if state is None:
        raise GameError("当前没有进行中的课题连章。")
    today = day_ordinal(ctx.now)
    if _gap(state, today):
        _finish(ctx, state, FAILED)
        return Reply(TITLE, (
            f"课题连章已因漏过 {_date_label(state['last'] + 1)} 断档，押金 {DEPOSIT} 灵石不退。",
            "可重新发送 灵宠课题连章 开启。",
        ), (TITLE, "灵宠课题", "灵宠目标"))
    _finish(ctx, state, ABANDONED)
    return Reply(TITLE, (
        f"已放弃第 {state['count']}/{DAYS} 日课题连章，押金 {DEPOSIT} 灵石不退。",
        "已完成的每日课题奖励保留；可重新发送 灵宠课题连章 开启。",
    ), (TITLE, "灵宠课题", "灵宠目标"))


def history(ctx: Context, arg: str = "") -> Reply:
    if arg.strip() and not arg.strip().isdigit():
        raise GameError(f"格式：{TITLE} 记录 [页码]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先完成领养，才有课题连章记录。",), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ? "
        "ORDER BY quest_id DESC LIMIT 60",
        (ctx.user_id, f"{RESULT_PREFIX}%"),
    ).fetchall()
    page_number = quantity(arg or "1", 999)
    pages = max(1, (len(rows) + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    if page_number > pages:
        raise GameError(f"课题连章记录共 {pages} 页。")
    selected = rows[(page_number - 1) * HISTORY_PAGE_SIZE:page_number * HISTORY_PAGE_SIZE]
    lines = [f"课题连章记录（第 {page_number}/{pages} 页，每页 {HISTORY_PAGE_SIZE} 条）："]
    if not selected:
        lines.append("还没有结束的课题连章。")
    for row in selected:
        start = int(row["quest_id"][len(RESULT_PREFIX):])
        status, count = _status_text(int(row["progress"]))
        lines.append(f"{_date_label(start)} 起 · {status} · 连续 {count}/{DAYS} 日 · 押金{'退回' if status == '完成' else '不退'}")
    links = []
    if page_number > 1:
        links.append(InlineCommand(len(lines) - 1, "上一页", f"{TITLE} 记录 {page_number - 1}"))
    if page_number < pages:
        links.append(InlineCommand(len(lines) - 1, "下一页", f"{TITLE} 记录 {page_number + 1}"))
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠课题", "灵宠目标"), tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts[0] == "开启":
        return start(ctx, " ".join(parts[1:]))
    if parts[0] == "放弃":
        return abandon(ctx, " ".join(parts[1:]))
    if parts[0] == "记录":
        return history(ctx, " ".join(parts[1:]))
    raise GameError(f"格式：{TITLE} [开启|放弃|记录 [页码]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "课题连章：尚未结契"
    state = _active(ctx, user_id)
    if state is None:
        return f"课题连章：未开启 · 押金 {DEPOSIT} 灵石"
    today = day_ordinal(ctx.now)
    if _gap(state, today):
        return f"课题连章：已断档 · 第 {state['count']}/{DAYS} 日"
    if state["count"] >= DAYS:
        return "课题连章：已完成"
    return f"课题连章：第 {state['count']}/{DAYS} 日 · 还需 {DAYS - state['count']} 天"


def pending_today(ctx: Context, user_id: str) -> bool:
    state = _active(ctx, user_id)
    return state is not None and not _gap(state, day_ordinal(ctx.now))


__all__ = [
    "ACTIVE", "COUNT", "DAYS", "DEPOSIT", "FINAL_ITEMS", "FINAL_STONES", "LAST", "TITLE",
    "abandon", "active", "day_ordinal", "dispatch", "history", "objective_line", "page",
    "pending_today", "record_claim", "start",
]
