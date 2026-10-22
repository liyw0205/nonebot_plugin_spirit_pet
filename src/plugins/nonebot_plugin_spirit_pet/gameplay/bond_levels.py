"""Bond levels: per-pet experience from interaction, outing and mini-games.

Experience thresholds for levels 1-5: [50, 150, 350, 650, 1000]. Each level
grants a passive combat bonus that applies in every real battle (PVE and PVP).
Bonuses are applied as stat bonuses in the combatant pipeline, so historical
battle records capture the effective stats.

Storage: ``bond_exp_<pet_id>`` row in ``quest_progress`` (progress=accumulated
exp, claimed=0 since this is a pure accumulator). Level 1 grants no bonus.
Schema 20 stays untouched.
"""

from ..application.context import Context
from ..domain.models import GameError, Reply

BOND_PREFIX = "bond_exp_"
THRESHOLDS = (50, 150, 350, 650, 1000)  # exp needed to REACH levels 2..5


def key(pet_id: int) -> str:
    return f"{BOND_PREFIX}{pet_id}"


def exp(ctx: Context, pet_id: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, key(pet_id)),
    ).fetchone()
    return row["progress"] if row else 0


def level(exp_value: int) -> int:
    """Bond level 1..5 for an experience total."""
    reached = 1
    for threshold in THRESHOLDS:
        if exp_value >= threshold:
            reached += 1
    return min(reached, 5)


def current_level(ctx: Context, pet_id: int) -> int:
    return level(exp(ctx, pet_id))


def _bonuses(pet_level: int) -> dict[str, int]:
    """Flat stat bonuses granted per bond level (added on top of base)."""
    table = {
        1: {},
        2: {"hp": 30, "attack": 5},
        3: {"hp": 60, "attack": 10, "defense": 8},
        4: {"hp": 100, "attack": 15, "defense": 14, "speed": 6},
        5: {"hp": 160, "attack": 22, "defense": 20, "speed": 10},
    }
    return table[pet_level]


def apply_bonus(pet_level: int, stats: dict[str, int]) -> None:
    """Add bond-level flat bonuses to *stats* in place."""
    for stat, bonus in _bonuses(pet_level).items():
        stats[stat] += bonus


def add_exp(ctx: Context, pet_id: int, amount: int) -> int:
    """Add experience for a pet; returns the new total."""
    new = exp(ctx, pet_id) + amount
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key(pet_id), new),
    )
    return new


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if arg.strip():
        raise GameError("灵宠羁绊 不接受参数，直接发送即可。")
    lines = []
    for row in ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id",
        (player.user_id,),
    ):
        pet = ctx.repo.pet(row["pet_id"])
        total = exp(ctx, pet.pet_id)
        lvl = level(total)
        if lvl < 5:
            next_threshold = THRESHOLDS[lvl - 1]
            lines.append(
                f"{pet.name}（编号 {pet.pet_id}）· 羁绊等级 {lvl} · 经验 {total}/{next_threshold}"
            )
        else:
            lines.append(f"{pet.name}（编号 {pet.pet_id}）· 羁绊等级 MAX · 经验 {total}")
    if not lines:
        lines.append("尚无在册灵宠。")
    return Reply("灵宠羁绊", tuple(lines), ("我的灵宠", "灵宠帮助"))