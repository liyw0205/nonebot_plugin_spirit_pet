"""Ascension state shared by combat, skills, titles and the trial command.

Ascension is permanent per pet and stored in `quest_progress` (schema 20 stays
frozen): `ascended_<pet_id>` marks the pet, `rebirth_count` counts full-roster
cycles, `ascension_week_<pet_id>` enforces one repeat trial per pet per week and
`ascension_repeat_<pet_id>` counts completed repeat trials.

A cycle is recorded on every successful trial once the whole roster is
ascended, so ascending the last partner and each later weekly repeat both count
toward the three-cycle title without minting extra currency.
"""

from ..domain.state import ASCENDED_PREFIX
from ..utils.time import beijing_week

REBIRTH_ID = "rebirth_count"
REPEAT_WEEK_PREFIX = "ascension_week_"
REPEAT_COUNT_PREFIX = "ascension_repeat_"
STAT_BONUS = 0.10
SKILL_SLOTS = 5


def ascended_count(ctx, user_id: str) -> int:
    return int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 AND quest_id LIKE ?",
        (user_id, f"{ASCENDED_PREFIX}%"),
    ).fetchone()[0])


def rebirth_count(ctx, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, REBIRTH_ID),
    ).fetchone()
    return int(row["progress"]) if row else 0


def week_start(now: int) -> int:
    return beijing_week(now)[0]


def mark_ascended(ctx, pet) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (pet.user_id, f"{ASCENDED_PREFIX}{pet.pet_id}", ctx.now),
    )
    pet.ascended = True


def record_cycle(ctx, user_id: str) -> int:
    """Record one full-roster ascension cycle and return the new count."""
    count = rebirth_count(ctx, user_id) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (user_id, REBIRTH_ID, count),
    )
    return count


def repeat_week(ctx, pet_id: int) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{REPEAT_WEEK_PREFIX}{pet_id}"),
    ).fetchone()
    return int(row["progress"]) if row else None


def mark_repeat(ctx, pet_id: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (ctx.user_id, f"{REPEAT_WEEK_PREFIX}{pet_id}", week_start(ctx.now)),
    )


def repeat_count(ctx, user_id: str, pet_id: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, f"{REPEAT_COUNT_PREFIX}{pet_id}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def add_repeat(ctx, user_id: str, pet_id: int) -> int:
    count = repeat_count(ctx, user_id, pet_id) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (user_id, f"{REPEAT_COUNT_PREFIX}{pet_id}", count),
    )
    return count


def skill_slots(ctx, pet) -> int:
    """Ascended pets open the exclusive fifth slot; others keep the base rule."""
    return SKILL_SLOTS if pet.ascended else ctx.content.rules.max_skill_slots
