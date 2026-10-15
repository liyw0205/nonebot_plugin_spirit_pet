from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, beijing_week
from .rewards import grant

WEEKLY_PAGE_SIZE = 5


def _metric(ctx: Context, user_id: str, metric: str) -> int:
    """Count this week's progress from records that are already permanent."""
    conn = ctx.repo.conn
    start, end = beijing_week(ctx.now)
    if metric == "weekly_pve_wins":
        query = (
            "SELECT COUNT(*) FROM battle_records b JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind IN ('pve', 'pve_stage') AND b.winner_side=p.side "
            "AND b.played_at>=? AND b.played_at<?"
        )
        params = (user_id, start, end)
    elif metric == "weekly_pvp_wins":
        query = "SELECT COUNT(*) FROM pvp_results WHERE winner_id=? AND played_at>=? AND played_at<?"
        params = (user_id, start, end)
    elif metric == "weekly_expedition_claims":
        query = (
            "SELECT COUNT(*) FROM expeditions WHERE user_id=? AND state='claimed' "
            "AND settled_at>=? AND settled_at<?"
        )
        params = (user_id, start, end)
    elif metric == "weekly_adventures":
        encounter_ids = tuple(ctx.content.encounters)
        placeholders = ",".join("?" for _ in encounter_ids)
        query = (
            "SELECT COUNT(*) FROM adventure_discoveries WHERE user_id=? AND discovered_at>=? "
            f"AND discovered_at<? AND encounter_id IN ({placeholders})"
        )
        params = (user_id, start, end, *encounter_ids)
    elif metric == "weekly_stage_clears":
        query = (
            "SELECT COUNT(*) FROM pve_stage_progress WHERE user_id=? AND stage_id NOT LIKE 'tower_%' "
            "AND first_cleared_at>=? AND first_cleared_at<?"
        )
        params = (user_id, start, end)
    elif metric == "weekly_achievement_claims":
        query = "SELECT COUNT(*) FROM achievement_claims WHERE user_id=? AND claimed_at>=? AND claimed_at<?"
        params = (user_id, start, end)
    else:
        raise ValueError(f"unknown weekly metric: {metric}")
    return conn.execute(query, params).fetchone()[0]


def claimed_this_week(ctx: Context, user_id: str, quest_id: str) -> bool:
    """A claim counts for this week only when its stored week start matches."""
    start, _ = beijing_week(ctx.now)
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, quest_id),
    ).fetchone()
    return bool(row and row["claimed"] and row["progress"] == start)


def _reward_summary(ctx: Context, quest) -> str:
    parts = [f"灵石 {quest.reward.stones.minimum}-{quest.reward.stones.maximum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}-{bounds.maximum}"
        for item, bounds in quest.reward.items.items()
    )
    return "，".join(parts)


def _state(ctx: Context, user_id: str, quest, value: int) -> str:
    if claimed_this_week(ctx, user_id, quest.id):
        return "已领取"
    return "可领取" if value >= quest.target else "未达成"


def catalog(ctx: Context, arg: str) -> Reply:
    start, end = beijing_week(ctx.now)
    lines = [
        f"本周周期：{beijing_day(start)} ~ {beijing_day(end - 1)}（北京时间，周一 00:00 重置）"
    ]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再查看本周目标。")
        return Reply("灵宠周常", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    page = paginate(
        list(ctx.content.weekly_quests.values()), arg, "灵宠周常", "灵宠周常",
        page_size=WEEKLY_PAGE_SIZE,
    )
    links = []
    for quest in page.entries:
        value = _metric(ctx, player.user_id, quest.metric)
        state = _state(ctx, player.user_id, quest, value)
        lines.append(
            f"{quest.name}：{value}/{quest.target}（{state}） · {_reward_summary(ctx, quest)}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励", f"灵宠周常领奖 {quest.name}",
            ))
    return Reply(
        f"灵宠周常 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "灵宠任务"), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    quest = named(ctx.content.weekly_quests, arg)
    if claimed_this_week(ctx, player.user_id, quest.id):
        raise GameError("本周这项奖励已领取，下周再来。")
    value = _metric(ctx, player.user_id, quest.metric)
    if value < quest.target:
        raise GameError(f"本周尚未达成：{quest.description}（进度 {value}/{quest.target}）")
    result = grant(ctx, quest.reward, player.user_id)
    start, _ = beijing_week(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, quest.id, start),
    )
    return Reply("周常奖励已领取", (
        f"{quest.name}已完成。", *result, "下周一 00:00（北京时间）重置。",
    ), ("灵宠周常", "灵宠任务"))
