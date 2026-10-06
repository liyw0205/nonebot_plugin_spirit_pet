from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def beijing_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, BEIJING).date().isoformat()


def cooldown_left(previous: int | None, now: int, seconds: int) -> int:
    if previous is None:
        return 0
    return max(0, previous + seconds - now)
