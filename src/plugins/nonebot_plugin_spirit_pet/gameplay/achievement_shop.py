"""Achievement point shop: claimed achievements earn points, points buy chosen material.

Points are derived, not stored twice: ``earned`` counts the player's rows in
``achievement_claims`` times ``rules.achievement_points.per_claim``, and ``spent`` is the
``ach_points_spent`` row in ``quest_progress``. The balance is the difference, so a claim made
in any earlier session counts exactly once and no migration is needed.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from .achievements import claimed_count

SPENT_KEY = "ach_points_spent"


def rule(ctx: Context):
    return ctx.content.rules.achievement_points


def earned(ctx: Context, user_id: str | None = None) -> int:
    return claimed_count(ctx, user_id or ctx.user_id) * rule(ctx).per_claim


def spent(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, SPENT_KEY),
    ).fetchone()
    return int(row["progress"]) if row else 0


def balance(ctx: Context, user_id: str | None = None) -> int:
    return earned(ctx, user_id) - spent(ctx, user_id)


def offers(ctx: Context):
    return sorted(ctx.content.achievement_shop.values(), key=lambda offer: offer.cost)


def payout_text(ctx: Context, offer) -> str:
    parts = []
    if offer.reward.stones:
        parts.append(f"灵石 {offer.reward.stones}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in offer.reward.items.items()
    )
    return " + ".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠成就商店 [兑换 <序号|名称>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠成就商店",
            (
                "尚未结契，先完成领养，才能用成就点兑换物品。",
                f"每领取一个成就奖励可获得 {rule(ctx).per_claim} 点成就点，点数可在本店兑换材料。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    available = balance(ctx)
    lines = [
        f"成就点：可用 {available}（累计 {earned(ctx)}，已用 {spent(ctx)}）。",
        f"每领取一个成就奖励 +{rule(ctx).per_claim} 点；兑换即时入账，可重复兑换。",
    ]
    links = []
    for index, offer in enumerate(offers(ctx), 1):
        state = "可兑换" if available >= offer.cost else f"还差 {offer.cost - available} 点"
        lines.append(f"{index}. {offer.name} · {offer.cost} 点 · {payout_text(ctx, offer)} · {state}")
        if available >= offer.cost:
            links.append(InlineCommand(len(lines) - 1, "兑换", f"灵宠成就商店 兑换 {index}"))
    lines.append("格式：灵宠成就商店 兑换 <序号|名称>。")
    return Reply("灵宠成就商店", tuple(lines), ("灵宠成就商店", "灵宠成就", "灵宠目标"), tuple(links))


def _offer(ctx: Context, text: str):
    token = text.strip()
    if not token:
        raise GameError("格式：灵宠成就商店 兑换 <序号|名称>。")
    if token.isdecimal():
        index = int(token)
        listed = offers(ctx)
        if index < 1 or index > len(listed):
            raise GameError(f"成就商店共有 {len(listed)} 项，序号需在 1-{len(listed)} 之间。")
        return listed[index - 1]
    return named(ctx.content.achievement_shop, token)


def redeem(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠成就商店 兑换 <序号|名称>。")
    offer = _offer(ctx, arg)
    player = ctx.player()
    available = balance(ctx)
    missing = set(offer.reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"兑换物品定义缺失：{', '.join(sorted(missing))}；本次未扣除点数。")
    if available < offer.cost:
        raise GameError(f"成就点不足：{offer.name}需要 {offer.cost} 点，当前可用 {available} 点。")

    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, SPENT_KEY, spent(ctx) + offer.cost),
    )
    player.stones += offer.reward.stones
    for item_id, amount in offer.reward.items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"兑换成功：{offer.name}，消耗 {offer.cost} 点成就点。",
        f"获得 {payout_text(ctx, offer)}。",
        f"成就点：可用 {balance(ctx)}（累计 {earned(ctx)}，已用 {spent(ctx)}）。",
    ]
    return Reply("成就点兑换", tuple(lines), ("灵宠成就商店", "灵宠背包", "灵宠成就"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "兑换":
        return redeem(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠成就商店 [兑换 <序号|名称>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    return f"成就点：可用 {balance(ctx, user_id)}（累计 {earned(ctx, user_id)}）"
