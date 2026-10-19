from ...application.context import Context
from ...domain.content import Range, Reward
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import quantity
from ..rewards import grant

CLAIM_PREFIX = "pvp_streak_"
MILESTONES = (
    (3, "初露锋芒", 150, {"spirit_food": 1}),
    (5, "连战连捷", 350, {"forge_ore": 2}),
    (10, "势如破竹", 800, {"bloodline_essence": 2}),
    (20, "威震论剑", 1800, {"bloodline_essence": 4, "breakthrough_pill": 1}),
)


def _rows(ctx: Context, user_id: str):
    """All ranked matches involving the player, oldest first."""
    return ctx.repo.conn.execute(
        "SELECT challenger_id, target_id, winner_id "
        "FROM pvp_results WHERE challenger_id=? OR target_id=? "
        "ORDER BY played_at ASC, result_id ASC",
        (user_id, user_id),
    ).fetchall()


def _outcome(row, user_id: str) -> int:
    """0 win, 1 loss, 2 draw from this player's perspective."""
    if row["winner_id"] is None:
        return 2
    return 0 if row["winner_id"] == user_id else 1


def best_streak(ctx: Context, user_id: str) -> int:
    best = run = 0
    for row in _rows(ctx, user_id):
        outcome = _outcome(row, user_id)
        if outcome == 0:
            run += 1
            best = max(best, run)
        elif outcome == 1:
            run = 0
        # Draws pause the streak without reducing the historical best.
    return best


def momentum(ctx: Context, user_id: str) -> tuple[int, int]:
    """(kind, count): kind 1 win streak, -1 loss streak, 0 none."""
    kind, count = 0, 0
    for row in _rows(ctx, user_id):
        outcome = _outcome(row, user_id)
        if outcome == 2:
            kind, count = 0, 0
        elif kind == 0:
            kind = 1 if outcome == 0 else -1
            count = 1
        elif (outcome == 0) == (kind == 1):
            count += 1
        else:
            kind = 1 if outcome == 0 else -1
            count = 1
    return kind, count


def momentum_text(ctx: Context, user_id: str) -> str:
    kind, count = momentum(ctx, user_id)
    if kind == 1:
        return f"当前 {count} 连胜"
    if kind == -1:
        return f"当前 {count} 连败"
    return "当前无连胜"


def claim_id(streak: int) -> str:
    return f"{CLAIM_PREFIX}{streak}"


def claimed(ctx: Context, user_id: str, streak: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(streak)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(milestone) -> Reward:
    _, _, stones, items = milestone
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def _reward_text(ctx: Context, milestone) -> str:
    _, _, stones, items = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in items.items()
    )
    return "，".join(parts)


def _reward_valid(ctx: Context, milestone) -> bool:
    for item_id, _ in milestone[3].items():
        item = ctx.content.items.get(item_id)
        if item is None or item.kind not in {"consumable", "material", "breakthrough"}:
            return False
    return True


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠连胜奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            f"{streak} 连胜 · {name} · {_reward_text(ctx, (streak, name, stones, items))}"
            for streak, name, stones, items in MILESTONES
        ]
        lines.append("尚未结契，先完成领养；连胜记录来自论剑对战，切磋不计入。")
        return Reply("论剑连胜奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    best = best_streak(ctx, player.user_id)
    lines = [f"{momentum_text(ctx, player.user_id)} · 历史最佳 {best} 连胜。"]
    links = []
    for milestone in MILESTONES:
        streak, name, _, _ = milestone
        valid = _reward_valid(ctx, milestone)
        if claimed(ctx, player.user_id, streak):
            state = "已领取"
        elif best >= streak and valid:
            state = "可领取"
        elif not valid:
            state = "奖励待修复"
        else:
            state = f"未达成（历史最佳 {best}/{streak} 连胜）"
        lines.append(f"{streak} 连胜 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取连胜奖励", f"灵宠连胜领奖 {streak}",
            ))
    return Reply("论剑连胜奖励", tuple(lines), ("灵宠赛季", "灵宠论剑榜", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        allowed = "、".join(str(entry[0]) for entry in MILESTONES)
        raise GameError(f"格式：灵宠连胜领奖 <连胜数>，可选 {allowed}。")
    player = ctx.player()
    streak, name, _, _ = milestone
    if claimed(ctx, player.user_id, streak):
        raise GameError(f"{streak} 连胜奖励已领取。")
    best = best_streak(ctx, player.user_id)
    if best < streak:
        raise GameError(f"历史最佳连胜为 {best}，尚未达成 {streak} 连胜。")
    reward = _reward(milestone)
    missing = set(reward.items) - set(ctx.content.items)
    if missing or not _reward_valid(ctx, milestone):
        raise GameError("连胜奖励物品定义缺失或类型错误；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(streak), best),
    )
    return Reply("论剑连胜奖励", (
        f"{streak} 连胜里程碑「{name}」已领取。", *result,
        f"{momentum_text(ctx, player.user_id)} · 历史最佳 {best} 连胜。",
    ), ("灵宠连胜奖励", "灵宠赛季", "灵宠目标"))
