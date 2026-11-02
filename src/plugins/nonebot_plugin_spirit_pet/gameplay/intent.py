"""Battle intent: a posture that trades outgoing damage against incoming damage.

Formation edits the four base stats per pet, mood and bonds scale them; intent is the first layer
that leaves stats alone and moves the two damage multipliers instead, so it stays meaningful for a
team whose stats are already saturated. One posture applies to the whole side, persists between
sessions, and can be cleared back to neutral.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named

KEY = "intent_"


def _prefix(user_id: str) -> str:
    # One row per posture, `intent_<user>_<intent id>`, so the flag stays an integer counter and
    # switching is a delete-then-insert instead of an overloaded string value.
    return f"{KEY}{user_id}_"


def current(ctx: Context, user_id: str | None = None) -> object | None:
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{_prefix(owner)}%"),
    ).fetchall()
    for row in rows:
        intent = ctx.content.intents.get(row["quest_id"][len(_prefix(owner)):])
        if intent is not None:
            return intent
    return None


def rates(ctx: Context, user_id: str | None = None) -> tuple[float, float]:
    intent = current(ctx, user_id)
    return (intent.dealt, intent.taken) if intent else (1.0, 1.0)


def _set(ctx: Context, user_id: str, intent_id: str | None) -> None:
    conn = ctx.repo.conn
    conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id, f"{_prefix(user_id)}%"),
    )
    if intent_id is not None:
        conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1",
            (user_id, f"{_prefix(user_id)}{intent_id}"),
        )


def _percent(rate: float) -> str:
    return f"{'+' if rate >= 1 else ''}{int(round((rate - 1) * 100))}%"


def _line(intent) -> str:
    return f"{intent.name}：输出 {_percent(intent.dealt)} · 承伤 {_percent(intent.taken)}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠战意 [选择 <战意> | 清除]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠战意",
            ("尚未结契，先完成领养，才能选择战意。",),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    active = current(ctx)
    lines = []
    if active is None:
        lines.append("当前战意：无（输出与承伤均为原值）")
    else:
        lines.append(f"当前战意：{active.name}（{_line(active)}）")
    lines.append("战意只作用于我方出战灵宠，不改四维，可随时切换或清除。")
    links = []
    for intent in sorted(ctx.content.intents.values(), key=lambda entry: entry.dealt, reverse=True):
        mark = "（当前）" if active is not None and active.id == intent.id else ""
        lines.append(f"{_line(intent)}{mark}")
        if active is None or active.id != intent.id:
            links.append(InlineCommand(len(lines) - 1, "选择", f"灵宠战意 选择 {intent.name}"))
    if active is not None:
        links.append(InlineCommand(0, "清除", "灵宠战意 清除"))
    return Reply("灵宠战意", tuple(lines), ("灵宠战意", "灵宠目标", "灵宠帮助"), tuple(links))


def choose(ctx: Context, arg: str) -> Reply:
    name = arg.strip()
    if not name:
        raise GameError("格式：灵宠战意 选择 <战意>。")
    ctx.player()
    intent = named({entry.name: entry for entry in ctx.content.intents.values()}, name)
    if current(ctx) is not None and current(ctx).id == intent.id:
        # Re-selecting the posture already in force is a no-op, not an error, and writes nothing.
        return Reply(
            "灵宠战意",
            (f"当前已是{intent.name}（{_line(intent)}）。",),
            ("灵宠战意", "灵宠目标"),
        )
    _set(ctx, ctx.user_id, intent.id)
    return Reply(
        "战意已定",
        (f"改以{intent.name}出战（{_line(intent)}）。", "下一场战斗起对我方出战灵宠生效。"),
        ("灵宠战意", "灵宠目标", "灵宠帮助"),
    )


def clear(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠战意 清除。")
    ctx.player()
    if current(ctx) is None:
        raise GameError("当前没有设置战意。")
    _set(ctx, ctx.user_id, None)
    return Reply(
        "战意已清除",
        ("恢复常规交战姿势，输出与承伤不再有增减。",),
        ("灵宠战意", "灵宠目标"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "选择":
        return choose(ctx, " ".join(parts[1:]))
    if parts[0] == "清除":
        return clear(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠战意 [选择 <战意> | 清除]。")


def objective_line(ctx: Context, user_id: str) -> str:
    intent = current(ctx, user_id)
    return f"战意：{intent.name}" if intent else "战意：未选择"
