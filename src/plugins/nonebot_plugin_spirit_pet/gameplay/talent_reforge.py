"""Talent reforge: reroll a pet's talent with a guaranteed non-downgrade.

Pet talents are static per species in the catalog, but a pet's own talent can
be overridden per instance. The override, the lock state and the reforge
history all live in `quest_progress` (no schema change):

- override  : `pet_talent_<pet_id>_<talent_id>` row with claimed=1
- lock      : `pet_talent_lock_<pet_id>` with claimed=1
- history   : `talent_reforge_<pet_id>_<ordinal>_<talent_id>` with claimed=1

Every caller that needs the pet's actual talent (status page, combat) goes
through :func:`current_talent`, which prefers an override row and falls back to
the species definition.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from .rewards import grant

TALENT_PREFIX = "pet_talent_"
LOCK_PREFIX = "pet_talent_lock_"
HISTORY_PREFIX = "talent_reforge_"
REFORGE_COST_STONES = 500
REFORGE_COST_ITEM = "bloodline_essence"
REFORGE_COST_ITEM_AMOUNT = 1
LOCK_COST_ITEM = "bloodline_essence"
LOCK_COST_AMOUNT = 2
HISTORY_WINDOW = 3


def override_key(pet_id: int, talent_id: str) -> str:
    return f"{TALENT_PREFIX}{pet_id}_{talent_id}"


def lock_key(pet_id: int) -> str:
    return f"{LOCK_PREFIX}{pet_id}"


def history_key(pet_id: int, ordinal: int, talent_id: str) -> str:
    return f"{HISTORY_PREFIX}{pet_id}_{ordinal}_{talent_id}"


def _override(ctx: Context, pet_id: int, talent_id: str) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1, claimed=1",
        (ctx.user_id, override_key(pet_id, talent_id)),
    )


def _clear_overrides(ctx: Context, pet_id: int) -> None:
    prefix = f"{TALENT_PREFIX}{pet_id}_"
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    )


def _has_lock(ctx: Context, pet_id: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, lock_key(pet_id)),
    ).fetchone()
    return row is not None


def _set_lock(ctx: Context, pet_id: int, locked: bool) -> None:
    if locked:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1, claimed=1",
            (ctx.user_id, lock_key(pet_id)),
        )
    else:
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
            (ctx.user_id, lock_key(pet_id)),
        )


def _charge(ctx: Context, stones: int, item_id: str, amount: int) -> None:
    player = ctx.player()
    held = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (player.user_id, item_id),
    ).fetchone()
    if player.stones < stones or (held is None or held["quantity"] < amount):
        raise GameError(
            f"材料不足：需要 {stones} 灵石与 {ctx.content.items[item_id].name} {amount}。",
        )
    player.stones -= stones
    ctx.repo.conn.execute(
        "UPDATE inventory SET quantity=quantity-? WHERE user_id=? AND item_id=?",
        (amount, player.user_id, item_id),
    )


def _pet(ctx: Context, arg: str):
    player = ctx.player()
    raw = arg.strip()
    if raw.startswith("编号 "):
        raw = raw[len("编号 "):]
    try:
        pet_id = int(raw) if raw else int(player.active_pet_id or 0)
    except ValueError:
        raise GameError("请填写在册灵宠编号，例如 灵宠洗练 3。")
    pet = ctx.repo.pet(pet_id) if pet_id else None
    if pet is None or pet.user_id != player.user_id:
        raise GameError(f"没有编号 {pet_id} 的灵宠。")
    return pet


def current_talent(ctx: Context, pet) -> str:
    """The pet's effective talent id: an override row wins, else the species."""
    prefix = f"{TALENT_PREFIX}{pet.pet_id}_"
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND substr(quest_id, 1, ?)=? LIMIT 1",
        (ctx.user_id, len(prefix), prefix),
    ).fetchone()
    if row is not None:
        return row["quest_id"][len(prefix):]
    return ctx.content.species[pet.species_id].talent


def _history(ctx: Context, pet_id: int) -> list[str]:
    prefix = f"{HISTORY_PREFIX}{pet_id}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND substr(quest_id, 1, ?)=? ORDER BY quest_id",
        (ctx.user_id, len(prefix), prefix),
    ).fetchall()
    entries = []
    for row in rows:
        remainder = row["quest_id"][len(prefix):]
        try:
            ordinal, talent_id = remainder.split("_", 1)
            entries.append((int(ordinal), talent_id))
        except ValueError:
            continue
    return [talent_id for _, talent_id in sorted(entries)[-HISTORY_WINDOW:]]


def _next_ordinal(ctx: Context, pet_id: int) -> int:
    prefix = f"{HISTORY_PREFIX}{pet_id}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    ).fetchall()
    maximum = 0
    for row in rows:
        remainder = row["quest_id"][len(prefix):]
        try:
            maximum = max(maximum, int(remainder.split("_", 1)[0]))
        except (ValueError, IndexError):
            continue
    return maximum + 1


def reforge(ctx: Context, arg: str) -> Reply:
    pet = _pet(ctx, arg)
    current_id = current_talent(ctx, pet)
    if _has_lock(ctx, pet.pet_id):
        current = ctx.content.talents[current_id]
        raise GameError(
            f"{pet.name}的天赋已被锁定（{current.name}），先发送 灵宠解锁天赋 {pet.pet_id} 再洗练。",
        )
    _charge(ctx, REFORGE_COST_STONES, REFORGE_COST_ITEM, REFORGE_COST_ITEM_AMOUNT)
    definition = ctx.content.talents[current_id]
    pool = [
        talent for talent in ctx.content.talents.values()
        if talent.id != current_id and talent.power >= definition.power
    ]
    if not pool:
        raise GameError("当前天赋已是最高威力，无可提升的天赋。")
    chosen = pool[ctx.rng.randint(0, len(pool) - 1)]
    _clear_overrides(ctx, pet.pet_id)
    _override(ctx, pet.pet_id, chosen.id)
    ordinal = _next_ordinal(ctx, pet.pet_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, history_key(pet.pet_id, ordinal, chosen.id)),
    )
    return Reply("天赋洗练", (
        f"{pet.name}洗练天赋：{definition.name} → {chosen.name}",
        f"新天赋：{chosen.description}",
    ), ("灵宠洗练记录", "我的灵宠"))


def set_lock(ctx: Context, arg: str) -> Reply:
    pet = _pet(ctx, arg)
    current = ctx.content.talents[current_talent(ctx, pet)]
    _charge(ctx, 0, LOCK_COST_ITEM, LOCK_COST_AMOUNT)
    _set_lock(ctx, pet.pet_id, True)
    return Reply("锁定天赋", (
        f"{pet.name}已锁定当前天赋「{current.name}」，洗练前需先解锁。",
    ), (f"灵宠解锁天赋 {pet.pet_id}", "我的灵宠"))


def clear_lock(ctx: Context, arg: str) -> Reply:
    pet = _pet(ctx, arg)
    if not _has_lock(ctx, pet.pet_id):
        raise GameError(f"{pet.name}当前没有锁定天赋。")
    _set_lock(ctx, pet.pet_id, False)
    return Reply("解锁天赋", (
        f"{pet.name}已解锁天赋，可以再次洗练了。",
    ), (f"灵宠洗练 {pet.pet_id}", "我的灵宠"))


def history(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if arg.strip():
        raise GameError("灵宠洗练记录 不接受参数，直接发送即可。")
    lines = []
    for row in ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id", (player.user_id,),
    ):
        pet = ctx.repo.pet(row["pet_id"])
        current_id = current_talent(ctx, pet)
        current = ctx.content.talents[current_id]
        prefix = f"{HISTORY_PREFIX}{pet.pet_id}_"
        count = ctx.repo.conn.execute(
            "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
            (ctx.user_id, len(prefix), prefix),
        ).fetchone()["n"]
        lines.append(f"{pet.name}（{pet.pet_id}）· 当前天赋：{current.name} · 已洗练 {count} 次")
        for talent_id in _history(ctx, pet.pet_id):
            talent = ctx.content.talents[talent_id]
            lines.append(f"曾得 · {talent.name}：{talent.description}")
    if not lines:
        lines.append("尚无在册灵宠。")
    return Reply("洗练历史", tuple(lines), ("我的灵宠", "灵宠帮助"))