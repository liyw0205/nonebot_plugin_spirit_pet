from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import season_bounds
from .rewards import grant

PAGE_SIZE = 5
CLAIM_PREFIX = "season_"


def claim_id(mission_id: str) -> str:
    return CLAIM_PREFIX + mission_id


def window(ctx: Context) -> tuple[str, int, int]:
    """The current arena season and its Beijing-month bounds."""
    return season_bounds(ctx.now)


def _claimed(ctx: Context, user_id: str, mission_id: str, start: int) -> bool:
    """A claim counts for this season only when its stored start matches."""
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(mission_id)),
    ).fetchone()
    return bool(row and row["claimed"] and row["progress"] == start)


def _value(ctx: Context, user_id: str, mission) -> int:
    """Season progress, always derived from timestamped records."""
    season_id, start, end = window(ctx)
    conn = ctx.repo.conn
    if mission.metric == "season_matches":
        row = conn.execute(
            "SELECT COUNT(*) AS amount FROM pvp_results "
            "WHERE season_id=? AND (challenger_id=? OR target_id=?)",
            (season_id, user_id, user_id),
        ).fetchone()
        return int(row["amount"])
    if mission.metric == "season_wins":
        row = conn.execute(
            "SELECT COUNT(*) AS amount FROM pvp_results WHERE season_id=? AND winner_id=?",
            (season_id, user_id),
        ).fetchone()
        return int(row["amount"])
    if mission.metric == "season_pve":
        row = conn.execute(
            "SELECT COUNT(*) AS amount FROM battle_records b "
            "JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind IN ('pve','pve_stage') AND b.winner_side=p.side "
            "AND b.played_at>=? AND b.played_at<?",
            (user_id, start, end),
        ).fetchone()
        return int(row["amount"])
    if mission.metric == "season_discoveries":
        row = conn.execute(
            "SELECT COUNT(*) AS amount FROM adventure_discoveries "
            "WHERE user_id=? AND discovered_at>=? AND discovered_at<?",
            (user_id, start, end),
        ).fetchone()
        return int(row["amount"])
    row = conn.execute(
        "SELECT COUNT(*) AS amount FROM achievement_claims "
        "WHERE user_id=? AND claimed_at>=? AND claimed_at<?",
        (user_id, start, end),
    ).fetchone()
    return int(row["amount"])


def _state(ctx: Context, user_id: str, mission, start: int) -> str:
    if _claimed(ctx, user_id, mission.id, start):
        return "已领取"
    value = _value(ctx, user_id, mission)
    if value >= mission.target:
        return "可领取"
    return f"进行中（{value}/{mission.target}）"


def _summary(ctx: Context, mission) -> str:
    parts = [f"灵石 {mission.reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}"
        for item, bounds in mission.reward.items.items()
    )
    return "，".join(parts)


def _remaining_days(ctx: Context) -> int:
    _, _, end = window(ctx)
    return max(0, (end - ctx.now + 86399) // 86400)


def catalog(ctx: Context, arg: str) -> Reply:
    entries = tuple(ctx.content.season_missions.values())
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠赛季任务共 {pages} 页。")
    season_id, start, _ = window(ctx)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("赛季任务", (
            f"赛季 {season_id} 共 {len(entries)} 项目标，达成后可在本赛季内领取一次性奖励。",
            "赛季按北京时间自然月切换，未领取不会累积到下一个赛季。",
            "尚未结契，先完成领养，再来查看赛季任务。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    selected = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = []
    links = []
    for mission in selected:
        state = _state(ctx, player.user_id, mission, start)
        lines.append(f"{mission.name} · {_summary(ctx, mission)} · {state}")
        lines.append(mission.description)
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 2, "领取赛季奖励", f"灵宠赛季任务领奖 {mission.name}",
            ))
    done = sum(1 for mission in entries if _claimed(ctx, player.user_id, mission.id, start))
    claimable = sum(1 for mission in entries if _state(ctx, player.user_id, mission, start) == "可领取")
    lines.append(
        f"赛季 {season_id} · 剩余 {_remaining_days(ctx)} 天 · 已领取 {done}/{len(entries)} 项，尚有 {claimable} 项可领取。"
    )
    commands = []
    if page > 1:
        commands.append(f"灵宠赛季任务 {page - 1}")
    if page < pages:
        commands.append(f"灵宠赛季任务 {page + 1}")
    commands.extend(("灵宠赛季", "灵宠目标"))
    return Reply(f"赛季任务 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    mission = named(ctx.content.season_missions, arg)
    season_id, start, _ = window(ctx)
    if _claimed(ctx, player.user_id, mission.id, start):
        raise GameError(f"{mission.name}的本赛季奖励已领取，下赛季再来。")
    value = _value(ctx, player.user_id, mission)
    if value < mission.target:
        raise GameError(f"本赛季尚未完成：{mission.description}（{value}/{mission.target}）。")
    result = grant(ctx, mission.reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(mission.id), start),
    )
    return Reply("赛季任务奖励", (
        f"{mission.name} · 赛季 {season_id}", *result,
    ), ("灵宠赛季任务", "灵宠赛季", "灵宠目标"))
