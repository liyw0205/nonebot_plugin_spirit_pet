"""Gear words: random stat affixes stored per equipment stack.

Words attach to a stack keyed by ``(item_id, enhancement)`` because the
inventory collapses identical stacks into a quantity. Each word is one row in
``quest_progress``:

- ``gear_words_<item_id>_<enh>_<index>_<word_id>`` with ``progress`` holding
  the rolled value.

Reading collects and sorts those rows; generation rolls 1-3 words based on the
enhancement level (``1 + level // 4``, capped at 3); reforge rerolls every word
of a stack without reducing the count. Schema 20 stays untouched.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from .equipment_inventory import highest_enhancement
from .rewards import grant

WORD_PREFIX = "gear_words_"
MAX_WORDS = 3
REFORGE_STONES = 300
REFORGE_GRAIN = 5  # spirit_food, farm output


def stack_key(item_id: str, enhancement: int, index: int, word_id: str) -> str:
    return f"{WORD_PREFIX}{item_id}_{enhancement}_{index}_{word_id}"


def _prefix(item_id: str, enhancement: int) -> str:
    return f"{WORD_PREFIX}{item_id}_{enhancement}_"


def rows(ctx: Context, item_id: str, enhancement: int) -> list[tuple[str, int]]:
    """Sorted [(word_id, value)] for the stack, oldest word first."""
    prefix = _prefix(item_id, enhancement)
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    ).fetchall()
    entries = []
    for row in rows:
        remainder = row["quest_id"][len(prefix):]
        try:
            index, word_id = remainder.split("_", 1)
            entries.append((int(index), word_id, row["progress"]))
        except ValueError:
            continue
    return [(word_id, value) for _, word_id, value in sorted(entries)]


def describe(ctx: Context, item_id: str, enhancement: int) -> str:
    """Human summary of a stack's words, or an empty string when none exist."""
    words = rows(ctx, item_id, enhancement)
    if not words:
        return ""
    return "词条：" + "、".join(
        f"{ctx.content.gear_words[word_id].name} +{value}" for word_id, value in words
    )


def _clear(ctx: Context, item_id: str, enhancement: int) -> None:
    prefix = _prefix(item_id, enhancement)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    )


def roll(ctx: Context, item_id: str, enhancement: int) -> int:
    """Generate words for a fresh stack; returns the number of words rolled."""
    count = min(MAX_WORDS, 1 + enhancement // 4)
    for index in range(count):
        word = ctx.content.gear_words[list(ctx.content.gear_words)[
            ctx.rng.randint(0, len(ctx.content.gear_words) - 1)
        ]]
        value = ctx.rng.randint(word.low, word.high)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
            (ctx.user_id, stack_key(item_id, enhancement, index, word.id), value),
        )
    return count


def reroll(ctx: Context, item_id: str, enhancement: int) -> None:
    """Reroll a stack's words in place, never reducing the count."""
    words = rows(ctx, item_id, enhancement)
    current = len(words)
    _clear(ctx, item_id, enhancement)
    count = max(current, min(MAX_WORDS, 1 + enhancement // 4))
    for index in range(count):
        word = ctx.content.gear_words[list(ctx.content.gear_words)[
            ctx.rng.randint(0, len(ctx.content.gear_words) - 1)
        ]]
        value = ctx.rng.randint(word.low, word.high)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (ctx.user_id, stack_key(item_id, enhancement, index, word.id), value),
        )


def word_reforge(ctx: Context, arg: str) -> Reply:
    item = named(ctx.content.items, arg.strip())
    gear = ctx.content.equipment.get(item.id) if item.kind == "equipment" else None
    if gear is None:
        raise GameError("未找到该装备，请检查名称。")
    player = ctx.player()
    enhancement = highest_enhancement(ctx, item.id)
    current = len(rows(ctx, item.id, enhancement))
    if current == 0:
        raise GameError("这件装备还没有词条，先打造或获得新的装备。")
    if player.stones < REFORGE_STONES:
        raise GameError(f"词条重铸需要 {REFORGE_STONES} 灵石，当前不足。")
    grain = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'",
        (player.user_id,),
    ).fetchone()
    if grain is None or grain["quantity"] < REFORGE_GRAIN:
        raise GameError(f"词条重铸需要 {REFORGE_GRAIN} 份灵粮，当前不足。")
    player.stones -= REFORGE_STONES
    ctx.repo.conn.execute(
        "UPDATE inventory SET quantity=quantity-? WHERE user_id=? AND item_id='spirit_food'",
        (REFORGE_GRAIN, player.user_id),
    )
    reroll(ctx, item.id, enhancement)
    return Reply("词条重铸", (
        f"{item.name} +{enhancement} 的词条已重铸。",
        describe(ctx, item.id, enhancement),
        f"花费灵石 {REFORGE_STONES}、灵粮 {REFORGE_GRAIN}。",
    ), ("灵宠背包", "灵宠装备", "灵宠工坊"))