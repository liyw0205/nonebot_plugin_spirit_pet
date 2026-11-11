"""Persistent investment in an active equipment set.

Resonance is deliberately separate from the one-time set completion reward.  A
level is stored as a ``quest_progress`` row so old databases and the existing
transaction/idempotency layer remain unchanged.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from .equipment import active_sets

KEY = "equipment_set_resonance_"
MAX_LEVEL = 3
STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def _key(set_id: str) -> str:
    return f"{KEY}{set_id}"


def level(ctx: Context, set_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(set_id)),
    ).fetchone()
    return min(MAX_LEVEL, max(0, int(row["progress"]))) if row else 0


def _definition(ctx: Context, set_id: str):
    return ctx.content.equipment_sets[set_id]


def bonus(ctx: Context, set_id: str, user_id: str | None = None) -> dict[str, int]:
    current = level(ctx, set_id, user_id)
    if current == 0:
        return {}
    return _definition(ctx, set_id).resonance[current - 1].bonuses.model_dump()


def active_bonus(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, int]:
    result = {key: 0 for key in STAT_NAMES}
    for equipment_set in active_sets(ctx, pet_id):
        for key, value in bonus(ctx, equipment_set.id, user_id).items():
            result[key] += value
    return {key: value for key, value in result.items() if value}


def _bonus_text(bonuses: dict[str, int]) -> str:
    return " ".join(
        f"{STAT_NAMES[key]} +{value}" for key, value in bonuses.items() if value
    ) or "无"


def cost_text(ctx: Context, tier) -> str:
    parts = [f"灵石 {tier.cost.stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in tier.cost.items.items()
    )
    return "、".join(parts)


def _active_for_current(ctx: Context, set_id: str) -> bool:
    pet = ctx.pet()
    return any(entry.id == set_id for entry in active_sets(ctx, pet.pet_id))


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def resonate(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        raise GameError("格式：灵宠套装共鸣 套装名。")
    equipment_set = named(ctx.content.equipment_sets, value)
    player = ctx.player()
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    if not _active_for_current(ctx, equipment_set.id):
        raise GameError(
            f"当前出战伙伴必须同时装备「{equipment_set.name}」的全部部件，才能进行共鸣。"
        )
    current = level(ctx, equipment_set.id)
    if current >= MAX_LEVEL:
        raise GameError(f"「{equipment_set.name}」共鸣已达 {MAX_LEVEL} 阶。")
    tier = equipment_set.resonance[current]
    if player.stones < tier.cost.stones:
        raise GameError(
            f"共鸣 {current + 1} 阶需要 {tier.cost.stones} 灵石，当前灵石不足。"
        )
    missing = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, item_id)}"
        for item_id, amount in tier.cost.items.items()
        if _owned(ctx, item_id) < amount
    ]
    if missing:
        raise GameError("共鸣材料不足：还需" + "、".join(missing) + "。")

    player.stones -= tier.cost.stones
    for item_id, amount in tier.cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (ctx.user_id, _key(equipment_set.id), current + 1),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    after = tier.bonuses.model_dump()
    return Reply("套装共鸣", (
        f"「{equipment_set.name}」共鸣提升至 {current + 1}/{MAX_LEVEL} 阶。",
        f"消耗：{cost_text(ctx, tier)}。",
        f"新增套装共鸣：{_bonus_text(after)}。",
        f"{pet.name}当前已激活该套装，战斗属性立即生效。",
    ), ("灵宠套装", "灵宠装备", "我的灵宠"), (
        InlineCommand(0, "查看套装", f"灵宠套装 {equipment_set.name}"),
    ))


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "套装共鸣：尚未结契"
    levels = []
    for equipment_set in ctx.content.equipment_sets.values():
        current = level(ctx, equipment_set.id, user_id)
        if current:
            levels.append(current)
    active = sum(
        1 for pet in ctx.repo.active_pets(user_id)
        for equipment_set in active_sets(ctx, pet.pet_id)
        if level(ctx, equipment_set.id, user_id) < MAX_LEVEL
    )
    if not levels:
        return f"套装共鸣：尚未共鸣 · 可投入 {active} 套"
    return f"套装共鸣：已共鸣 {len(levels)} 套 · 最高 {max(levels)}/{MAX_LEVEL} 阶"


__all__ = ["KEY", "MAX_LEVEL", "active_bonus", "bonus", "cost_text", "level", "objective_line", "resonate"]
