from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from .companionship import active_bond_streak
from .rewards import grant

MILESTONES = (
    (3, "初识相伴", 80, {"spirit_food": 1}),
    (7, "心意渐深", 180, {"affinity_pill": 1}),
    (14, "朝夕相守", 420, {"forge_ore": 2}),
    (30, "心契相依", 1000, {"bloodline_essence": 3}),
)
CLAIM_PREFIX = "bond_streak_reward_"


def claim_id(days: int) -> str:
    return f"{CLAIM_PREFIX}{days}"


def _claimed(ctx: Context, user_id: str, days: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(days)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(milestone) -> Reward:
    days, _, stones, items = milestone
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def _reward_text(ctx: Context, milestone) -> str:
    _, _, stones, items = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item].name if item in ctx.content.items else item} {amount}"
        for item, amount in items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠陪伴奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = []
        for milestone in MILESTONES:
            days, name, _, _ = milestone
            lines.append(f"{days} 天 · {name} · {_reward_text(ctx, milestone)} · 未达成")
        lines.append("尚未结契；每日与灵宠互动会累计连续陪伴天数。")
        return Reply("连续陪伴奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    current = active_bond_streak(player, ctx.now)
    best = player.best_bond_streak
    lines = [f"当前连续 {current} 天 · 历史最佳 {best} 天。"]
    links = []
    for milestone in MILESTONES:
        days, name, _, _ = milestone
        state = "已领取" if _claimed(ctx, player.user_id, days) else (
            "可领取" if best >= days else f"未达成（历史最佳 {best}/{days} 天）"
        )
        lines.append(f"{days} 天 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取奖励", f"灵宠陪伴领奖 {days}"))
    return Reply("连续陪伴奖励", tuple(lines), ("灵宠互动", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        allowed = "、".join(str(entry[0]) for entry in MILESTONES)
        raise GameError(f"格式：灵宠陪伴领奖 <天数>，可选 {allowed}。")
    days, name, _, _ = milestone
    if _claimed(ctx, player.user_id, days):
        raise GameError(f"{days} 天连续陪伴奖励已领取。")
    best = player.best_bond_streak
    if best < days:
        raise GameError(f"历史最佳连续陪伴为 {best} 天，尚未达成 {days} 天里程碑。")
    reward = _reward(milestone)
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"连续陪伴奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(days), best),
    )
    return Reply("连续陪伴奖励", (
        f"{days} 天里程碑「{name}」已领取。", *result,
        f"当前连续 {active_bond_streak(player, ctx.now)} 天 · 历史最佳 {best} 天。",
    ), ("灵宠陪伴奖励", "灵宠互动", "灵宠目标"))
