from datetime import date, timedelta

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.state import Player
from ..utils.time import beijing_day
from .rewards import grant

DAY_PREFIX = "signin_day_"
CLAIM_PREFIX = "signin_reward_"
MILESTONES = (
    (3, "三日相伴", 100, {"spirit_food": 1}),
    (7, "七日相守", 300, {"forge_ore": 2}),
    (14, "半月同行", 650, {"bloodline_essence": 2}),
    (30, "月满仙缘", 1400, {"bloodline_essence": 5}),
)


def _stored_days(ctx: Context, user_id: str) -> set[date]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? "
        "AND substr(quest_id, 1, ?) = ? AND claimed=1",
        (user_id, len(DAY_PREFIX), DAY_PREFIX),
    )
    days = set()
    for row in rows:
        try:
            days.add(date.fromisoformat(row["quest_id"][len(DAY_PREFIX):]))
        except ValueError:
            continue
    return days


def _days(ctx: Context, player: Player) -> set[date]:
    today = date.fromisoformat(beijing_day(ctx.now))
    days = {day for day in _stored_days(ctx, player.user_id) if day <= today}
    # Existing accounts retain only their latest sign-in date; do not invent older history.
    try:
        previous = date.fromisoformat(player.sign_day)
    except ValueError:
        previous = None
    if previous is not None and previous <= today:
        days.add(previous)
    return days


def current_streak(ctx: Context, player: Player) -> int:
    today = date.fromisoformat(beijing_day(ctx.now))
    days = _days(ctx, player)
    end = today if today in days else today - timedelta(days=1)
    if end not in days:
        return 0
    count = 0
    while end in days:
        count += 1
        end -= timedelta(days=1)
    return count


def best_streak(ctx: Context, player: Player) -> int:
    longest = run = 0
    previous = None
    for day in sorted(_days(ctx, player)):
        run = run + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return longest


def record_sign(ctx: Context, player: Player, previous_sign_day: str) -> tuple[int, int]:
    """Persist this sign-in and the known prior day in the same transaction as its reward."""
    today = date.fromisoformat(beijing_day(ctx.now))
    try:
        previous = date.fromisoformat(previous_sign_day)
    except ValueError:
        previous = None
    if previous == today - timedelta(days=1):
        _record_day(ctx, player.user_id, previous)
    _record_day(ctx, player.user_id, today)
    return current_streak(ctx, player), best_streak(ctx, player)


def _record_day(ctx: Context, user_id: str, day: date) -> None:
    ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (user_id, DAY_PREFIX + day.isoformat()),
    )


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
        raise GameError("灵宠签到奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = []
        for milestone in MILESTONES:
            days, name, _, _ = milestone
            lines.append(f"{days} 天 · {name} · {_reward_text(ctx, milestone)}")
        lines.append("尚未结契，先完成领养；签到记录从此版本开始累计。")
        return Reply("连续签到奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    streak = current_streak(ctx, player)
    best = best_streak(ctx, player)
    lines = [f"当前连续 {streak} 天 · 历史最佳 {best} 天。"]
    links = []
    for milestone in MILESTONES:
        days, name, _, _ = milestone
        state = "已领取" if _claimed(ctx, player.user_id, days) else (
            "可领取" if best >= days else f"未达成（历史最佳 {best}/{days} 天）"
        )
        lines.append(f"{days} 天 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取奖励", f"灵宠签到领奖 {days}"))
    return Reply("连续签到奖励", tuple(lines), ("灵宠签到", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        allowed = "、".join(str(entry[0]) for entry in MILESTONES)
        raise GameError(f"格式：灵宠签到领奖 <天数>，可选 {allowed}。")
    days, name, _, _ = milestone
    if _claimed(ctx, player.user_id, days):
        raise GameError(f"{days} 天连续签到奖励已领取。")
    best = best_streak(ctx, player)
    if best < days:
        raise GameError(f"历史最佳连续签到为 {best} 天，尚未达成 {days} 天里程碑。")
    reward = _reward(milestone)
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"连续签到奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(days), best),
    )
    return Reply("连续签到奖励", (
        f"{days} 天里程碑「{name}」已领取。", *result,
        f"当前连续 {current_streak(ctx, player)} 天 · 历史最佳 {best} 天。",
    ), ("灵宠签到奖励", "灵宠签到", "灵宠目标"))
