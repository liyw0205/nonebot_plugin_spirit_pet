from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .equipment import active_sets
from .rewards import grant

CLAIM_PREFIX = "equipment_set_reward_"
SET_REWARDS = {
    "sky_wind": (180, {"spirit_food": 1}),
    "stone_guard": (240, {"forge_ore": 1}),
    "venom_edge": (300, {"bloodline_essence": 1}),
    "root_silk": (300, {"bloodline_essence": 1}),
}


def claim_id(set_id: str) -> str:
    return CLAIM_PREFIX + set_id


def claimed(ctx: Context, user_id: str, set_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(set_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def active_set_ids(ctx: Context, user_id: str) -> set[str]:
    player = ctx.repo.player(user_id)
    if player is None or player.active_pet_id is None:
        return set()
    return {entry.id for entry in active_sets(ctx, player.active_pet_id)}


def state(ctx: Context, user_id: str, set_id: str, active: set[str], has_player: bool) -> str:
    if not has_player:
        return "尚未结契"
    if claimed(ctx, user_id, set_id):
        return "已领取"
    if set_id not in SET_REWARDS:
        return "奖励待配置"
    return "可领取" if set_id in active else "未完成"


def claimable(ctx: Context, user_id: str):
    active = active_set_ids(ctx, user_id)
    return tuple(
        equipment_set for equipment_set in ctx.content.equipment_sets.values()
        if equipment_set.id in SET_REWARDS
        and equipment_set.id in active
        and not claimed(ctx, user_id, equipment_set.id)
    )


def reward_text(ctx: Context, set_id: str) -> str:
    reward_config = SET_REWARDS.get(set_id)
    if reward_config is None:
        return "奖励待配置"
    stones, items = reward_config
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in items.items()
    )
    return "，".join(parts)


def _reward(set_id: str) -> Reward:
    stones, items = SET_REWARDS[set_id]
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        raise GameError("格式：灵宠套装领奖 套装名。")
    equipment_set = named(ctx.content.equipment_sets, value)
    reward_config = SET_REWARDS.get(equipment_set.id)
    if reward_config is None:
        raise GameError(f"套装「{equipment_set.name}」的完成奖励尚未配置。")

    player = ctx.player()
    if claimed(ctx, player.user_id, equipment_set.id):
        raise GameError(f"套装「{equipment_set.name}」的完成奖励已领取。")
    if player.active_pet_id is None:
        raise ctx.missing_pet()
    if equipment_set.id not in active_set_ids(ctx, player.user_id):
        raise GameError(f"须由同一只出战灵宠同时装备「{equipment_set.name}」的全部部件后领奖。")

    reward = _reward(equipment_set.id)
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"套装完成奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1, claimed=1",
        (player.user_id, claim_id(equipment_set.id)),
    )
    return Reply("套装完成奖励", (
        f"「{equipment_set.name}」完成奖励已领取。", *result,
    ), ("灵宠套装", "灵宠目标"))
