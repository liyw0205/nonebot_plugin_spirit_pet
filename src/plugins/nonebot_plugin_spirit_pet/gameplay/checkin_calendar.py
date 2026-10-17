import calendar
import re
from datetime import date, timedelta

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING, beijing_day
from . import checkin_rewards

MONTH_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}")


def _parse_month(value: str, today: date) -> tuple[int, int]:
    text = value.strip()
    if not text:
        return today.year, today.month
    if not MONTH_PATTERN.fullmatch(text):
        raise GameError("格式：灵宠签到月历 YYYY-MM，例如 灵宠签到月历 2026-10；不填查看当月。")
    year, month = (int(part) for part in text.split("-"))
    if not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise GameError("月份超出日历范围，请检查年月。")
    if (year, month) > (today.year, today.month):
        raise GameError("该月尚未到来，暂无签到记录可回顾。")
    return year, month


def _month_days(year: int, month: int) -> list[date]:
    return [date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]


def _longest_run(days: set[date], boundary: tuple[date, date] | None = None) -> int:
    longest = run = 0
    previous = None
    for day in sorted(days):
        if boundary and not boundary[0] <= day <= boundary[1]:
            previous = day
            continue
        run = run + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return longest


def calendar_reply(ctx: Context, arg: str) -> Reply:
    today = date.fromisoformat(beijing_day(ctx.now))
    year, month = _parse_month(arg, today)
    player = ctx.repo.player(ctx.user_id)
    title = f"签到月历 {year:04d}-{month:02d}"
    if player is None:
        return Reply(title, (
            "签到月历按北京时间自然月回顾每天的签到记录。",
            "尚未结契，先完成领养；签到记录从此版本开始累计。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    known = checkin_rewards.known_days(ctx, player)
    month_days = _month_days(year, month)
    month_first, month_last = month_days[0], month_days[-1]
    signed = {day for day in month_days if day in known}
    lines = [
        f"当前连续 {checkin_rewards.current_streak(ctx, player)} 天"
        f" · 历史最佳 {checkin_rewards.best_streak(ctx, player)} 天。",
        f"本月已签 {len(signed)}/{len(month_days)} 天"
        f" · 本月最长连续 {_longest_run(signed, (month_first, month_last))} 天。",
    ]
    links = []
    for day in month_days:
        if day in signed:
            mark = "已签到"
        elif day > today:
            mark = "未到"
        else:
            mark = "未签"
        lines.append(f"{day.month}月{day.day}日 · {mark}")
    if not signed:
        lines.append("这个月还没有签到记录。")
    commands = ["灵宠签到奖励"]
    if (year, month) < (today.year, today.month):
        commands.insert(0, f"灵宠签到月历 {today.year:04d}-{today.month:02d}")
    else:
        earliest = min(known) if known else None
        if earliest is not None and (earliest.year, earliest.month) < (year, month):
            commands.insert(0, f"灵宠签到月历 {year - int(month == 1):04d}-{12 if month == 1 else month - 1:02d}")
    return Reply(title, tuple(lines), tuple(commands), tuple(links))
