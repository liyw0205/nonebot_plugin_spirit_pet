"""灵宠切磋周目标: three weekly goals fed by real mirror battles.

``arena.battles.spar_fight`` already records every 切磋/约战, but nothing in the
spar surface accumulates: 战绩 and 榜 only read history, and the closing line
says so ("切磋不消耗资源，不计赛季积分和熟练度"). This module hangs a week-scoped
goal board off that same transaction.

Every key carries the Monday timestamp from ``beijing_week``, so progress and
vouchers reset by themselves when the week turns. All of it lives in
``quest_progress``; there is no schema change.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from .rewards import grant as _grant

BATTLES_KEY = "spar_wk_battles_"
WINS_KEY = "spar_wk_wins_"
OPPONENT_KEY = "spar_wk_opp_"
CLAIM_PREFIX = "spar_goal_claim_"

# (id, 名称, 目标值, 灵石, 物品)
GOALS = (
    ("battles", "交手", 2, 120, {"spirit_food": 1}),
    ("wins", "胜场", 3, 260, {"forge_ore": 1}),
    ("opponents", "对手", 2, 180, {"energy_pill": 1}),
)


def week(ctx: Context, now: int | None = None) -> int:
    start, _ = beijing_week(ctx.now if now is None else now)
    return start


def _progress_row(ctx: Context, quest_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, quest_id),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _bump(ctx: Context, quest_id: str, user_id: str) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
        (user_id, quest_id),
    )


def value(ctx: Context, goal_id: str, user_id: str | None = None) -> int:
    owner = user_id or ctx.user_id
    start = week(ctx)
    if goal_id == "battles":
        return _progress_row(ctx, f"{BATTLES_KEY}{start}", owner)
    if goal_id == "wins":
        return _progress_row(ctx, f"{WINS_KEY}{start}", owner)
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{OPPONENT_KEY}{start}_%"),
    ).fetchone()
    return int(row[0]) if row else 0


def record(ctx: Context, first: str, second: str, winner: int) -> None:
    """Count one spar for both sides; only the winner gains a win."""
    start = week(ctx)
    for owner, rival in ((first, second), (second, first)):
        _bump(ctx, f"{BATTLES_KEY}{start}", owner)
        ctx.repo.conn.execute(
            "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed)"
            " VALUES (?, ?, 1, 0)",
            (owner, f"{OPPONENT_KEY}{start}_{rival}"),
        )
    if winner in (0, 1):
        _bump(ctx, f"{WINS_KEY}{start}", (first, second)[winner])


def claimed(ctx: Context, goal_id: str, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{CLAIM_PREFIX}{week(ctx)}_{goal_id}"),
    ).fetchone()
    return bool(row and row["claimed"])


def claimable(ctx: Context, user_id: str | None = None) -> list[tuple]:
    owner = user_id or ctx.user_id
    return [
        goal for goal in GOALS
        if value(ctx, goal[0], owner) >= goal[2] and not claimed(ctx, goal[0], owner)
    ]


def _goal(name: str):
    target = name.strip()
    goal = next(
        (entry for entry in GOALS if entry[0] == target or entry[1] == target), None,
    )
    if goal is None:
        choices = "、".join(entry[1] for entry in GOALS)
        raise GameError(f"目标可选：{choices}。")
    return goal


def _reward_text(ctx: Context, goal) -> str:
    _, _, _, stones, items = goal
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in items.items()
    )
    return " · ".join(parts)


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠切磋目标。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠切磋目标",
            (
                "每周切磋有三个目标：交手 2 场、取胜 3 场、与 2 位不同对手交手。",
                "尚未结契，先完成领养，再找人切磋。",
            ),
            ("灵宠帮助",),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    lines = ["本周切磋（周一 00:00 重置）："]
    links = []
    for goal in GOALS:
        goal_id, name, target, _, _ = goal
        current = value(ctx, goal_id, player.user_id)
        done = claimed(ctx, goal_id, player.user_id)
        state = "已领取" if done else ("可领取" if current >= target else f"{current}/{target}")
        lines.append(f"{name} {state} · {_reward_text(ctx, goal)}")
        if not done and current >= target:
            links.append(InlineCommand(
                len(lines) - 1, "领取切磋奖励", f"灵宠切磋领奖 {goal[1]}",
            ))
    lines.append("切磋不消耗资源，胜负只影响切磋战绩，不影响赛季积分。")
    return Reply("灵宠切磋目标", tuple(lines), ("灵宠切磋", "灵宠切磋榜", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠切磋领奖 <交手|胜场|对手>。")
    goal = _goal(text)
    goal_id, name, target, stones, items = goal
    current = value(ctx, goal_id, player.user_id)
    if current < target:
        raise GameError(f"「{name}」尚未达成：{current}/{target}。")
    if claimed(ctx, goal_id, player.user_id):
        raise GameError(f"「{name}」本周奖励已经领取。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in items.items()
        },
    )
    result = _grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, f"{CLAIM_PREFIX}{week(ctx)}_{goal_id}", current),
    )
    return Reply(
        "切磋周目标",
        (f"「{name}」本周奖励已领取。", *result),
        ("灵宠切磋目标", "灵宠切磋", "灵宠背包"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "切磋：尚未结契"
    battles = value(ctx, "battles", user_id)
    wins = value(ctx, "wins", user_id)
    pending = len(claimable(ctx, user_id))
    if pending:
        return f"切磋：{pending} 项可领 · 本周 {battles} 场 {wins} 胜"
    return f"切磋：本周 {battles} 场 · {wins} 胜"


__all__ = [
    "BATTLES_KEY", "CLAIM_PREFIX", "GOALS", "OPPONENT_KEY", "WINS_KEY",
    "claim", "claimable", "claimed", "objective_line", "page", "record", "value", "week",
]
