import re
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def beijing_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, BEIJING).date().isoformat()


def cooldown_left(previous: int | None, now: int, seconds: int) -> int:
    if previous is None:
        return 0
    return max(0, previous + seconds - now)


def parse_season_id(value: str) -> tuple[int, int]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("season ID must use YYYY-MM")
    year, month = map(int, value.split("-"))
    if not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise ValueError("season ID outside supported calendar")
    return year, month


def season_bounds(timestamp: int) -> tuple[str, int, int]:
    current = datetime.fromtimestamp(timestamp, BEIJING)
    year, month = current.year, current.month
    start = datetime(year, month, 1, tzinfo=BEIJING)
    end = datetime(year + int(month == 12), 1 if month == 12 else month + 1, 1, tzinfo=BEIJING)
    return f"{year:04d}-{month:02d}", int(start.timestamp()), int(end.timestamp())
