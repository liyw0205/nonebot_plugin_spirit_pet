from ..application.context import Context
from ..domain.models import GameError


def highest_enhancement(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT MAX(enhancement) AS enhancement FROM unequipped_equipment "
        "WHERE user_id=? AND item_id=? AND quantity>0", (ctx.user_id, item_id),
    ).fetchone()
    return row["enhancement"] or 0


def _check(ctx: Context, item_id: str, enhancement: int, amount: int) -> None:
    item = ctx.content.items.get(item_id)
    if item is None or item.kind != "equipment":
        raise ValueError("equipment inventory requires an equipment item")
    if type(enhancement) is not int or enhancement not in ctx.content.forge_levels:
        raise ValueError("unsupported equipment enhancement")
    if type(amount) is not int or amount <= 0:
        raise ValueError("equipment amount must be a positive integer")


def take(ctx: Context, item_id: str, enhancement: int, amount: int = 1) -> None:
    _check(ctx, item_id, enhancement, amount)
    if not enhancement:
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
        return
    updated = ctx.repo.conn.execute(
        "UPDATE unequipped_equipment SET quantity=quantity-? "
        "WHERE user_id=? AND item_id=? AND enhancement=? AND quantity>=?",
        (amount, ctx.user_id, item_id, enhancement, amount),
    )
    if updated.rowcount != 1:
        raise GameError("背包内该强化等级的装备数量不足。")


def put(ctx: Context, item_id: str, enhancement: int, amount: int = 1) -> None:
    _check(ctx, item_id, enhancement, amount)
    if not enhancement:
        ctx.repo.add_item(ctx.user_id, item_id, amount)
        return
    ctx.repo.conn.execute(
        "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, item_id, enhancement) DO UPDATE SET quantity=quantity+excluded.quantity",
        (ctx.user_id, item_id, enhancement, amount),
    )
