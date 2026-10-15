from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from . import daily_dungeon, main_quest, quests, titles, weekly_quests
from .achievements import _metric as achievement_metric

HUB_PAGES = (
    "灵宠任务", "灵宠今日秘境", "灵宠周常", "灵宠主线", "灵宠成就", "灵宠称号",
)


def _claim_line(name: str, claimable: list[str], total: int) -> str:
    if claimable:
        return f"{name}：可领 {len(claimable)} 项（{'、'.join(claimable)}）· 共 {total} 项"
    return f"{name}：暂无可领 · 共 {total} 项"


def _daily_line(ctx: Context, user_id: str) -> str:
    """Mirror `quests.quests`' claimable test over the shared progress table."""
    rows = {
        row["quest_id"]: row for row in ctx.repo.conn.execute(
            "SELECT * FROM quest_progress WHERE user_id=?", (user_id,),
        )
    }
    claimable = []
    for quest in ctx.content.quests.values():
        row = rows.get(quest.id)
        if row and row["claimed"]:
            continue
        if (row["progress"] if row else 0) >= quest.target:
            claimable.append(quest.name)
    return _claim_line("今日任务", claimable, len(ctx.content.quests))


def _weekly_line(ctx: Context, user_id: str) -> str:
    claimable = [
        quest.name for quest in ctx.content.weekly_quests.values()
        if not weekly_quests.claimed_this_week(ctx, user_id, quest.id)
        and weekly_quests._metric(ctx, user_id, quest.metric) >= quest.target
    ]
    return _claim_line("本周周常", claimable, len(ctx.content.weekly_quests))


def _main_quest_line(ctx: Context, user_id: str) -> str:
    claimed = main_quest._claimed(ctx, user_id)
    current = main_quest._current(ctx, user_id)
    if current is None:
        return f"主线：{len(ctx.content.main_quests)} 步全部完成"
    state, value = main_quest._state(ctx, user_id, current, claimed, current)
    return f"主线：下一步 {current.name} · {state}（{value}/{current.target}）"


def _achievement_line(ctx: Context, user_id: str) -> str:
    claims = {
        row["achievement_id"] for row in ctx.repo.conn.execute(
            "SELECT achievement_id FROM achievement_claims WHERE user_id=?", (user_id,),
        )
    }
    claimable = [
        entry.name for entry in ctx.content.achievements.values()
        if entry.id not in claims and achievement_metric(ctx, user_id, entry.metric) >= entry.target
    ]
    return _claim_line("成就", claimable, len(ctx.content.achievements))


def _dungeon_line(ctx: Context, user_id: str) -> str:
    dungeon = daily_dungeon.featured_dungeon(ctx.content, ctx.now)
    wins = daily_dungeon.wins_today(ctx, user_id, dungeon.id)
    states = " · ".join(
        f"{kind} {daily_dungeon._state(ctx, user_id, claim_id, wins)}"
        for kind, claim_id in daily_dungeon.CLAIM_KINDS.items()
    )
    return f"今日秘境：{dungeon.name} · {states}"


def _title_line(ctx: Context, user_id: str) -> str:
    held = titles.earned(ctx, user_id)
    holder = held[-1][0] if held else None
    return f"称号：{holder.name if holder else '尚无'} · 已获得 {len(held)}/{len(ctx.content.titles)} 项"


def objectives(ctx: Context, arg: str) -> Reply:
    """One read-only page summarising every objective system's claimable state."""
    if arg.strip():
        raise GameError("灵宠目标 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠目标", (
            "尚未结契，先完成领养，就能在这里看到所有可领奖励。",
            "这里汇总今日任务、今日秘境、本周周常、主线、成就与称号的领取状态。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    quests.refresh(ctx)
    lines = [
        _daily_line(ctx, player.user_id),
        _dungeon_line(ctx, player.user_id),
        _weekly_line(ctx, player.user_id),
        _main_quest_line(ctx, player.user_id),
        _achievement_line(ctx, player.user_id),
        _title_line(ctx, player.user_id),
    ]
    links = tuple(
        InlineCommand(index, "前往", command) for index, command in enumerate(HUB_PAGES)
    )
    return Reply("灵宠目标", tuple(lines), ("灵宠帮助", "我的灵宠"), links)
