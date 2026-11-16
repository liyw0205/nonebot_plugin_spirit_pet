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
    if metric in {"weekly_daily_claims", "weekly_active_days"}:
        rows = conn.execute(
            "SELECT json_extract(snapshot,'$.day') AS day, json_extract(snapshot,'$.quest_id') AS quest_id "
            "FROM duel_actions WHERE user_id=? AND created_at>=? AND created_at<? "
            "AND json_extract(snapshot,'$.kind')='daily_quest_claim'", (user_id, start, end),
        )
        claims = {(row["day"], row["quest_id"]) for row in rows if row["quest_id"] in ctx.content.quests}
        return len(claims) if metric == "weekly_daily_claims" else len({day for day, _ in claims})
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
    elif metric == "weekly_cuisine_orders":
        week = beijing_day(start)
        prefix = f"cuisine_order_{week}_"
        rows = conn.execute(
            "SELECT quest_id, claimed FROM quest_progress WHERE user_id=? AND substr(quest_id,1,?)=?",
            (user_id, len(prefix), prefix),
        ).fetchall()
        delivered = {
            row["quest_id"][len(prefix):]
            for row in rows
            if row["claimed"] and row["quest_id"][len(prefix):] in ctx.content.cuisine_orders
        }
        return len(delivered)
    elif metric == "weekly_cuisine_practice":
        query = (
            "SELECT COUNT(*) FROM duel_actions WHERE user_id=? AND created_at>=? AND created_at<? "
            "AND json_extract(snapshot,'$.kind')='cuisine_practice' "
            "AND json_extract(snapshot,'$.status')='finished'"
        )
        params = (user_id, start, end)
    elif metric == "weekly_banquets":
        week_key = f"banquet_{start}"
        query = (
            "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1"
        )
        params = (user_id, week_key)
    else:
        raise ValueError(f"unknown weekly metric: {metric}")
    return conn.execute(query, params).fetchone()[0]


def claimed_this_week(ctx: Context, user_id: str, quest_id: str) -> bool:
    """A claim counts for this week only when its stored week start matches."""
    start, _ = beijing_week(ctx.now)
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND ((quest_id=? AND progress=?) OR quest_id=?)",
        (user_id, quest_id, start, f"weekly_claim_{start}_{quest_id}"),
    ).fetchone() is not None


def require_current_week(ctx: Context, quest_id: str, requested: str = "") -> None:
    start, _ = beijing_week(ctx.now)
    if requested and requested != beijing_day(start):
        raise GameError("这条领取入口已经跨周，请重新查看本周页面。")
    latest = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, quest_id),
    ).fetchone()
    if latest and latest["progress"] > start:
        raise GameError("系统日期早于领取记录，请等待日期恢复。")


def record_claim(ctx: Context, quest_id: str) -> None:
    start, _ = beijing_week(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1)",
        (ctx.user_id, f"weekly_claim_{start}_{quest_id}", start),
    )
    # Keep the latest-period row for existing readers and pre-upgrade saves.
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress,claimed=1",
        (ctx.user_id, quest_id, start),
    )


def _next_command(quest) -> str:
    return {
        "weekly_pve_wins": "灵宠秘境", "weekly_pvp_wins": "灵宠论剑榜",
        "weekly_expedition_claims": "灵宠行程", "weekly_adventures": "灵宠历练",
        "weekly_stage_clears": "灵宠关卡", "weekly_achievement_claims": "灵宠成就",
        "weekly_cuisine_orders": "灵宠膳房订单", "weekly_cuisine_practice": "灵宠膳房研修",
        "weekly_banquets": "灵宠家宴", "weekly_daily_claims": "灵宠任务",
        "weekly_active_days": "灵宠任务",
    }[quest.metric]


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
                len(lines) - 1, "领取奖励", f"灵宠周常领奖 {quest.name} 周 {beijing_day(start)}",
            ))
        elif state == "未达成":
            command = _next_command(quest)
            if command not in {link.command for link in links}:
                links.append(InlineCommand(len(lines) - 1, "继续目标", command))
    return Reply(
        f"灵宠周常 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "灵宠任务", "灵宠周常赏"), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    name, separator, week = arg.rpartition(" 周 ")
    quest = named(ctx.content.weekly_quests, name if separator else arg)
    require_current_week(ctx, quest.id, week if separator else "")
    if claimed_this_week(ctx, player.user_id, quest.id):
        raise GameError("本周这项奖励已领取，下周再来。")
    value = _metric(ctx, player.user_id, quest.metric)
    if value < quest.target:
        raise GameError(f"本周尚未达成：{quest.description}（进度 {value}/{quest.target}）")
    result = grant(ctx, quest.reward, player.user_id)
    record_claim(ctx, quest.id)
    reply = Reply("周常奖励已领取", (
        f"{quest.name}已完成。", *result, "下周一 00:00（北京时间）重置。",
    ), ("灵宠周常", "灵宠任务", "灵宠周常赏"))
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now,
        {"kind": "weekly_quest_claim", "week_start": beijing_week(ctx.now)[0], "quest_id": quest.id}, reply)
    return reply
