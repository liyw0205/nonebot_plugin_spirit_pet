"""Monotonic per-player counters for systems that leave no other trace.

Hybridisation, alchemy, contracts and difficulty tiers complete instantly and store nothing, so
achievements had no way to see them. Each one bumps a ``stat_<metric>`` row instead, which keeps a
single storage pattern (``quest_progress``) and lets ``achievements._metric`` read them without a new
table. Counters only ever increase, and a replayed operation never reaches the bump because the reply
cache short-circuits the command.
"""

from ..application.context import Context

PREFIX = "stat_"


def key(metric: str) -> str:
    return f"{PREFIX}{metric}"


def bump(ctx: Context, metric: str, amount: int = 1, user_id: str | None = None) -> int:
    """Increase one counter and return the new total."""
    if amount <= 0:
        raise ValueError("counter increments must be positive")
    owner = user_id or ctx.user_id
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (owner, key(metric), amount),
    )
    return value(ctx, metric, owner)


def value(ctx: Context, metric: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key(metric)),
    ).fetchone()
    return int(row["progress"]) if row else 0
