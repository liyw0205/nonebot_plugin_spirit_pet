"""灵宠签到全勤: a per-month reward for signing in every day of a finished month.

The sign-in system pays *streak* milestones (3/7/14/30 consecutive days) and the
month calendar draws 签/今/漏 cells, but nothing ever rewards a perfect month.
The two axes differ: missing the 31st still leaves a 30-day streak, while a short
month signed end to end is a perfect month with a modest streak.

A month counts as 全勤 when every calendar day of that *completed* month has a
``signin_day_<date>`` row. The current month is never eligible, because it has not
finished yet. Claims are vouchers ``signin_full_<YYYY-MM>`` in ``quest_progress``.
"""

import calendar as _calendar
import re
from datetime import date, timedelta

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from . import checkin_rewards
from .rewards import grant

MONTH_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}")
PREFIX = "signin_full_"
STONES = 800
ITEMS = {"spirit_food": 2, "forge_ore": 2}
MONTHS_SHOWN = 3


def month_days(year: int, month: int) -> list[date]:
    return [date(year, month, day) for day in range(1, _calendar.monthrange(year, month)[1] + 1)]


def completed_months(today: date, count: int = MONTHS_SHOWN) -> list[tuple[int, int]]:
    """The last ``count`` finished months, newest first; the current month is excluded."""
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        months.append((year, month))
    return months


def claim_id(year: int, month: int) -> str:
    return f"{PREFIX}{year:04d}-{month:02d}"


def signed_in_month(ctx: Context, user_id: str, year: int, month: int) -> int:
    days = checkin_rewards.stored_days(ctx, user_id)
    return sum(1 for day in month_days(year, month) if day in days)


def is_full(ctx: Context, user_id: str, year: int, month: int) -> bool:
    return signed_in_month(ctx, user_id, year, month) == len(month_days(year, month))


def _claimed(ctx: Context, user_id: str, year: int, month: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(year, month)),
    ).fetchone()
    return bool(row and row["claimed"])


def _label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _reward() -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=STONES, maximum=STONES),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in ITEMS.items()},
    )


def _reward_text(ctx: Context) -> str:
    parts = [f"灵石 {STONES}"]
    parts.extend(
        f"{ctx.content.items[item].name if item in ctx.content.items else item} {amount}"
        for item, amount in ITEMS.items()
    )
    return "，".join(parts)


def _parse_month(value: str, today: date) -> tuple[int, int]:
    text = value.strip()
    if not MONTH_PATTERN.fullmatch(text):
        raise GameError("格式：灵宠签到全勤 领奖 YYYY-MM，例如 灵宠签到全勤 领奖 2026-10。")
    year, month = (int(part) for part in text.split("-"))
    if not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise GameError("月份超出日历范围，请检查年月。")
    if (year, month) >= (today.year, today.month):
        raise GameError("该月尚未结束，全勤奖励要等下个月领取。")
    return year, month


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠签到全勤 [领奖 YYYY-MM]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "签到全勤",
            (
                "签满一整月（每一天都签到）可在下个月领取全勤奖励。",
                f"奖励：{_reward_text(ctx)}。",
                "尚未结契，先完成领养。",
            ),
            ("灵宠帮助", "灵宠签到"),
            (InlineCommand(2, "开始领养", "灵宠领养 "),),
        )
    today = date.fromisoformat(beijing_day(ctx.now))
    lines = [f"全勤奖励：{_reward_text(ctx)}。"]
    links = []
    for year, month in completed_months(today):
        signed = signed_in_month(ctx, player.user_id, year, month)
        total = len(month_days(year, month))
        if _claimed(ctx, player.user_id, year, month):
            state = "已领取"
        elif signed == total:
            state = "可领取"
        else:
            state = "未全勤"
        lines.append(f"{_label(year, month)} · 已签 {signed}/{total} 天 · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取全勤", f"灵宠签到全勤 领奖 {_label(year, month)}",
            ))
    lines.append("当月尚未结束，不计入全勤；漏签一天即无法补领。")
    return Reply(
        "签到全勤", tuple(lines), ("灵宠签到", "灵宠签到月历", "灵宠签到奖励", "灵宠目标"), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    today = date.fromisoformat(beijing_day(ctx.now))
    text = arg.strip()
    if text.startswith("领奖"):
        text = text[2:].strip()
    if text:
        year, month = _parse_month(text, today)
    else:
        year, month = _newest_claimable(ctx, player.user_id, today)
    if _claimed(ctx, player.user_id, year, month):
        raise GameError(f"{_label(year, month)} 全勤奖励已领取。")
    signed = signed_in_month(ctx, player.user_id, year, month)
    total = len(month_days(year, month))
    if signed < total:
        raise GameError(f"{_label(year, month)} 尚未全勤：已签 {signed}/{total} 天。")
    reward = _reward()
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"全勤奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(year, month), signed),
    )
    return Reply("签到全勤", (
        f"{_label(year, month)} 全勤（{signed}/{total} 天）奖励已领取。",
        *result,
        f"灵石 {player.stones} · 下个月继续签满一整月可再领。",
    ), ("灵宠签到全勤", "灵宠签到", "灵宠目标"))


def _newest_claimable(ctx: Context, user_id: str, today: date) -> tuple[int, int]:
    for year, month in completed_months(today):
        if not _claimed(ctx, user_id, year, month) and is_full(ctx, user_id, year, month):
            return year, month
    raise GameError("最近三个月没有可领取的全勤奖励：签满一整月后，下个月再来。")


def dispatch(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value.startswith("领奖"):
        return claim(ctx, value)
    return page(ctx, value)


__all__ = [
    "ITEMS", "MONTHS_SHOWN", "PREFIX", "STONES", "claim", "claim_id", "completed_months",
    "dispatch", "is_full", "month_days", "page", "signed_in_month",
]
