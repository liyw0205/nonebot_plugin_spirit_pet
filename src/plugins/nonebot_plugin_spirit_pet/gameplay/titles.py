from ..application.context import Context
from ..domain.models import Reply
from ..utils.pagination import paginate
from .achievements import _metric as _achievement_metric
from .skill_mastery_rewards import claim_count as _skill_mastery_claim_count

TITLE_PAGE_SIZE = 5


def _claim_count(ctx: Context, user_id: str, ids) -> int:
    values = tuple(ids)
    if not values:
        return 0
    placeholders = ",".join("?" for _ in values)
    return ctx.repo.conn.execute(
        f"SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 "
        f"AND quest_id IN ({placeholders})",
        (user_id, *values),
    ).fetchone()[0]


def _metric(ctx: Context, user_id: str, metric: str) -> int:
    """Titles reuse the achievement metrics plus the two claim-count metrics."""
    if metric == "main_quest_claims":
        return _claim_count(ctx, user_id, ctx.content.main_quests)
    if metric == "weekly_claims":
        return _claim_count(ctx, user_id, ctx.content.weekly_quests)
    if metric == "skill_mastery_rewards":
        return _skill_mastery_claim_count(ctx, user_id)
    return _achievement_metric(ctx, user_id, metric)


def _ordered(ctx: Context) -> list:
    return sorted(ctx.content.titles.values(), key=lambda title: title.order)


def earned(ctx: Context, user_id: str) -> list[tuple]:
    """Every title the current save satisfies, in priority order."""
    held = []
    for title in _ordered(ctx):
        value = _metric(ctx, user_id, title.metric)
        if value >= title.target:
            held.append((title, value))
    return held


def current(ctx: Context, user_id: str):
    """The held title with the highest order, or None."""
    held = earned(ctx, user_id)
    return held[-1][0] if held else None


def catalog(ctx: Context, arg: str) -> Reply:
    titles = _ordered(ctx)
    page = paginate(titles, arg, "灵宠称号", "灵宠称号", page_size=TITLE_PAGE_SIZE)
    player = ctx.repo.player(ctx.user_id)
    lines = []
    if player is None:
        lines.append("尚未结契，先完成领养，再收集称号。")
        for title in page.entries:
            lines.append(f"{title.order}. {title.name} · 未获得 · {title.description}")
        return Reply(
            f"灵宠称号 {page.number}/{page.total}", tuple(lines),
            (*page.navigation, "灵宠帮助"), (),
        )

    held = earned(ctx, player.user_id)
    held_ids = {title.id for title, _ in held}
    holder = held[-1][0] if held else None
    lines.append(
        f"当前称号：{holder.name} · 已获得 {len(held)}/{len(titles)} 项"
        if holder else f"当前称号：尚无 · 已获得 0/{len(titles)} 项"
    )
    for title in page.entries:
        value = _metric(ctx, player.user_id, title.metric)
        state = "已获得" if title.id in held_ids else f"进度 {value}/{title.target}"
        lines.append(f"{title.order}. {title.name} · {state} · {title.description}")
    return Reply(
        f"灵宠称号 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "我的信息"), (),
    )
