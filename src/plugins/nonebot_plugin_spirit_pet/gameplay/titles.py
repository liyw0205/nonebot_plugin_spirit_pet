from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from .achievements import _metric as _achievement_metric
from .skill_mastery_rewards import claim_count as _skill_mastery_claim_count

TITLE_PAGE_SIZE = 5
SELECTION_ID = "title_equipped"


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


def selected(ctx: Context, user_id: str):
    """Return a valid explicit choice; malformed or stale rows are ignored."""
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, SELECTION_ID),
    ).fetchone()
    if row is None or row["claimed"] != 1 or type(row["progress"]) is not int:
        return None
    title = next((title for title in _ordered(ctx) if title.order == row["progress"]), None)
    if title is None or _metric(ctx, user_id, title.metric) < title.target:
        return None
    return title


def current(ctx: Context, user_id: str):
    """The valid explicit choice, or the legacy highest-order fallback."""
    held = earned(ctx, user_id)
    choice = selected(ctx, user_id)
    if choice is not None and any(title.id == choice.id for title, _ in held):
        return choice
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
    holder = current(ctx, player.user_id)
    choice = selected(ctx, player.user_id)
    lines.append(
        f"当前称号：{holder.name} · 已获得 {len(held)}/{len(titles)} 项"
        + (" · 主动佩戴" if choice is not None and choice.id == holder.id else "")
        if holder else f"当前称号：尚无 · 已获得 0/{len(titles)} 项"
    )
    links = []
    for title in page.entries:
        value = _metric(ctx, player.user_id, title.metric)
        state = "已获得" if title.id in held_ids else f"进度 {value}/{title.target}"
        suffix = " · 当前佩戴" if choice is not None and choice.id == title.id else ""
        lines.append(f"{title.order}. {title.name} · {state} · {title.description}{suffix}")
        if title.id in held_ids and not suffix:
            links.append(InlineCommand(
                len(lines) - 1, "佩戴", f"灵宠称号佩戴 {title.name}",
            ))
    return Reply(
        f"灵宠称号 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "我的信息"), tuple(links),
    )


def equip(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    title = named(ctx.content.titles, arg)
    value = _metric(ctx, player.user_id, title.metric)
    if value < title.target:
        raise GameError(f"称号「{title.name}」尚未获得，当前进度 {value}/{title.target}。")
    choice = selected(ctx, player.user_id)
    if choice is not None and choice.id == title.id:
        return Reply(f"已佩戴称号：{title.name}", ("称号未改变。",), ("灵宠称号", "我的信息"))
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, SELECTION_ID, title.order),
    )
    return Reply(
        f"已佩戴称号：{title.name}",
        ("称号已切换。",),
        ("灵宠称号", "我的信息"),
    )
