"""Monotonic per-player counters for systems that leave no other trace.

Hybridisation, alchemy, contracts and difficulty tiers complete instantly and store nothing, so
achievements had no way to see them. Each one bumps a ``stat_<metric>`` row instead, which keeps a
single storage pattern (``quest_progress``) and lets ``achievements._metric`` read them without a new
table. Counters only ever increase, and a replayed operation never reaches the bump because the reply
cache short-circuits the command.
"""

from ..application.context import Context
from ..utils.time import beijing_day, beijing_week

PREFIX = "stat_"


def key(metric: str) -> str:
    return f"{PREFIX}{metric}"


def day_key(metric: str, now: int) -> str:
    return f"{PREFIX}{metric}_day_{beijing_day(now)}"


def bump(ctx: Context, metric: str, amount: int = 1, user_id: str | None = None) -> int:
    """Increase one counter and return the new total."""
    if amount <= 0:
        raise ValueError("counter increments must be positive")
    owner = user_id or ctx.user_id
    for quest_id in (key(metric), day_key(metric, ctx.now)):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
            (owner, quest_id, amount),
        )
    return value(ctx, metric, owner)


def today_value(ctx: Context, metric: str, user_id: str | None = None) -> int:
    """Work done on this metric since the Beijing day started."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, day_key(metric, ctx.now)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def value(ctx: Context, metric: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key(metric)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def week_value(ctx: Context, metric: str, user_id: str | None = None) -> int:
    """Work done on this metric since the Beijing week started.

    Reads the same per-day rows `bump` writes, so a weekly goal never needs a
    second storage shape; the ISO date inside the key is enough to window it.
    """
    start = beijing_week(ctx.now)[0]
    first, last = beijing_day(start), beijing_day(start + 6 * 86_400)
    prefix = f"{PREFIX}{metric}_day_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{prefix}%"),
    ).fetchall()
    total = 0
    for row in rows:
        day = row["quest_id"][len(prefix):]
        if first <= day <= last:
            total += int(row["progress"])
    return total
