from ...application.context import Context
from ...domain.content import Range, Reward
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import quantity
from ..rewards import grant

CLAIM_PREFIX = "season_road_"
PAGE_SIZE = 7

# (tier, name, wins, distinct_opponents, stones, items)
MILESTONES = (
    (1, "初入征途", 5, 0, 300, {"spirit_food": 2}),
    (2, "小有名气", 15, 0, 600, {"forge_ore": 2}),
    (3, "崭露头角", 30, 0, 1000, {"bloodline_essence": 2}),
    (4, "剑指前列", 50, 0, 1500, {"forge_ore": 4, "bloodline_essence": 2}),
    (5, "名动一方", 80, 15, 2200, {"bloodline_essence": 4}),
    (6, "登峰造极", 120, 25, 3200, {"forge_ore": 8, "bloodline_essence": 6}),
    (7, "赛季传奇", 200, 40, 5000, {"bloodline_essence": 10, "breakthrough_pill": 2}),
)


def claim_id(tier: int) -> str:
    return f"{CLAIM_PREFIX}{tier}"


def _progress(ctx: Context, season_id: str, user_id: str) -> tuple[int, int]:
    """(challenger wins, distinct beaten opponents) within the season window."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS wins, COUNT(DISTINCT target_id) AS opponents "
        "FROM pvp_results WHERE season_id=? AND challenger_id=? AND winner_id=?",
        (season_id, user_id, user_id),
    ).fetchone()
    return int(row["wins"]), int(row["opponents"])


def _claimed(ctx: Context, user_id: str, tier: int, season_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(tier)),
    ).fetchone()
    # The credential stores the season ordinal (YYYYMM); a new season invalidates it.
    return bool(row and row["claimed"] and row["progress"] == _season_ordinal(season_id))


def _season_ordinal(season_id: str) -> int:
    return int(season_id.replace("-", ""))


def _reward(milestone) -> Reward:
    _, _, _, _, stones, items = milestone
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def _reward_valid(ctx: Context, milestone) -> bool:
    for item_id, _ in milestone[5].items():
        item = ctx.content.items.get(item_id)
        if item is None or item.kind not in {"consumable", "material", "breakthrough"}:
            return False
    return True


def _reward_text(ctx: Context, milestone) -> str:
    _, _, _, _, stones, items = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠赛季征途 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            f"第 {tier} 阶 · {name} · {_reward_text(ctx, (tier, name, 0, 0, stones, items))}"
            for tier, name, _, _, stones, items in MILESTONES
        ]
        lines.append("尚未结契，先完成领养；征途按当前赛季的挑战者胜场推进。")
        return Reply("论剑赛季征途", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    from .seasons import current_season
    season = current_season(ctx)
    wins, opponents = _progress(ctx, season.season_id, player.user_id)
    lines = [f"当前赛季 {season.season_id} · 挑战者胜场 {wins} · 战胜对手 {opponents} 位。"]
    links = []
    claimed_count = 0
    for milestone in MILESTONES:
        tier, name, need_wins, need_opponents, _, _ = milestone
        valid = _reward_valid(ctx, milestone)
        if _claimed(ctx, player.user_id, tier, season.season_id):
            state = "已领取"
            claimed_count += 1
        elif wins >= need_wins and opponents >= need_opponents and valid:
            state = "可领取"
        elif not valid:
            state = "奖励待修复"
        else:
            state = f"进行中 {min(wins, need_wins)}/{need_wins} 胜"
            if need_opponents:
                state += f" · 对手 {min(opponents, need_opponents)}/{need_opponents}"
        lines.append(f"第 {tier} 阶 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取征途奖励", f"灵宠征途领奖 {tier}",
            ))
    return Reply("论剑赛季征途", tuple(lines), ("灵宠赛季", "灵宠论剑榜", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        allowed = "、".join(str(entry[0]) for entry in MILESTONES)
        raise GameError(f"格式：灵宠征途领奖 <阶数>，可选 {allowed}。")
    player = ctx.player()
    tier, name, need_wins, need_opponents, _, _ = milestone
    from .seasons import current_season
    season = current_season(ctx)
    if _claimed(ctx, player.user_id, tier, season.season_id):
        raise GameError(f"第 {tier} 阶征途奖励本季已领取。")
    wins, opponents = _progress(ctx, season.season_id, player.user_id)
    if wins < need_wins or opponents < need_opponents:
        raise GameError(
            f"第 {tier} 阶需要本季胜 {need_wins} 场"
            + (f"且战胜 {need_opponents} 位不同对手" if need_opponents else "")
            + f"；当前 {wins} 胜 / {opponents} 位。"
        )
    reward = _reward(milestone)
    missing = set(reward.items) - set(ctx.content.items)
    if missing or not _reward_valid(ctx, milestone):
        raise GameError("征途奖励物品定义缺失或类型错误；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(tier), int(season.season_id.replace("-", ""))),
    )
    return Reply("论剑赛季征途", (
        f"第 {tier} 阶征途「{name}」已领取。", *result,
        f"当前赛季 {season.season_id} · 挑战者胜场 {wins}。",
    ), ("灵宠赛季征途", "灵宠赛季", "灵宠目标"))
