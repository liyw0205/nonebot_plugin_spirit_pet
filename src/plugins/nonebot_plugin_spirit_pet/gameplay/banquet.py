"""Weekly household banquet: one kitchen occasion per Beijing natural week.

The kitchen could only ever cook a dish on demand — there was no occasion that
made the whole household sit down together, and 厨艺 stopped mattering once the
top dish was reachable. A banquet is that occasion: once per week it spends
灵粮, 灵石 and 灶火, serves every owned pet that is not out on an expedition,
and pays a fixed weekly reward.

State lives in the existing ``quest_progress`` table:

* ``banquet_<week start>`` — held this week (``progress`` is the served count)
* ``stat_banquets_held`` — monotonic counter, written by ``counters.bump``

No new currency, no schema change; cooking single dishes still goes through
``gameplay/cuisine.py``.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import add_energy
from ..utils.time import beijing_day, beijing_week
from . import counters, cuisine
from .rewards import grant

WEEK_PREFIX = "banquet_"
PAGE_SIZE = 6


def rule(ctx: Context):
    return ctx.content.rules.banquet


def week_key(now: int) -> str:
    return f"{WEEK_PREFIX}{beijing_week(now)[0]}"


def held(ctx: Context, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, week_key(ctx.now)),
    ).fetchone()
    return row is not None


def held_count(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, week_key(ctx.now)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _reward_text(ctx: Context) -> str:
    entry = rule(ctx).reward
    parts = [f"灵石 {entry.stones.minimum}"] if entry.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in entry.items.items()
    )
    return " · ".join(parts) if parts else "无奖励"


def _effect_text(ctx: Context) -> str:
    entry = rule(ctx)
    parts = []
    if entry.energy:
        parts.append(f"精力 +{entry.energy}")
    if entry.exp:
        parts.append(f"修为 +{entry.exp}")
    if entry.affinity:
        parts.append(f"亲密 +{entry.affinity}")
    return " · ".join(parts)


def _shortage(ctx: Context) -> str | None:
    entry = rule(ctx)
    player = ctx.player()
    if player.stones < entry.stones:
        return f"灵石不足：开席需要 {entry.stones}，当前 {player.stones}。"
    owned = cuisine.owned_item(ctx, ctx.user_id, "spirit_food")
    if owned < entry.spirit_food:
        return f"灵粮不足：开席需要 {entry.spirit_food}，当前 {owned}。"
    if cuisine.heat_left(ctx) < entry.heat:
        return (
            f"今日灶火不足：开席需要 {entry.heat} 点，今日只剩 {cuisine.heat_left(ctx)} 点。"
        )
    return None


def _archive(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    page = 1
    if len(parts) > 1:
        try:
            page = int(parts[1])
        except ValueError as exc:
            raise GameError("格式：灵宠家宴 往期 [页码]。") from exc
    if page < 1:
        raise GameError("页码必须从 1 开始。")
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ? "
        "ORDER BY quest_id DESC",
        (ctx.user_id, f"{WEEK_PREFIX}%"),
    ).fetchall()
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"家宴往期只有 {pages} 页。")
    lines = [f"家宴往期（第 {page}/{pages} 页，每页 {PAGE_SIZE} 周）："]
    links = []
    if not rows:
        lines.append("还没有办过家宴；满足条件后发送 灵宠家宴 开席。")
    for row in rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        week = row["quest_id"][len(WEEK_PREFIX):]
        lines.append(f"{beijing_day(int(week))} 起 · 已开席 · 宴请 {int(row['progress'])} 位")
    if pages > 1:
        navigation = []
        if page > 1:
            navigation.append(f"灵宠家宴 往期 {page - 1}")
        if page < pages:
            navigation.append(f"灵宠家宴 往期 {page + 1}")
        lines.append("翻页：" + " / ".join(navigation))
        if page > 1:
            links.append(InlineCommand(len(lines) - 2, "上一页", f"灵宠家宴 往期 {page - 1}"))
        if page < pages:
            links.append(InlineCommand(len(lines) - 2, "下一页", f"灵宠家宴 往期 {page + 1}"))
    return Reply("灵宠家宴 · 往期", tuple(lines), ("灵宠家宴", "灵宠膳房", "灵宠目标"), tuple(links))


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠家宴 [开席 | 往期 [页码]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠家宴",
            (
                "尚未结契，先完成领养，才能摆家宴。",
                "每周可办一次家宴，宴请全部在册伙伴并领取一份固定奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = rule(ctx)
    current = cuisine.level(ctx)
    diners = len(cuisine.eligible_pets(ctx))
    lines = [
        f"本周家宴：{'已开席（宴请 %d 位）' % held_count(ctx) if held(ctx) else '未开席'}。",
        f"开席条件：厨艺 {current}/{entry.min_level} 级 · 灵粮 {entry.spirit_food}"
        f" · 灵石 {entry.stones} · 灶火 {entry.heat}。",
        f"今日灶火 {cuisine.heat_left(ctx)}/{ctx.content.rules.cuisine.daily_heat} · 可宴请 {diners} 位伙伴。",
        f"效果：{_effect_text(ctx)}（全体在册伙伴）。",
        f"周奖励：{_reward_text(ctx)}。",
    ]
    links = []
    if not held(ctx) and current >= entry.min_level and diners and _shortage(ctx) is None:
        links.append(InlineCommand(1, "开席", "灵宠家宴 开席"))
    shortage = _shortage(ctx)
    if held(ctx):
        lines.append("本周已办过，下周一 00:00（北京时间）后可再开席。")
    elif shortage:
        lines.append(shortage)
    elif current < entry.min_level:
        lines.append(f"厨艺未到 {entry.min_level} 级，先多学几道菜。")
    elif not diners:
        lines.append("全部在册伙伴都在外出派遣，先等他们归来。")
    links.append(InlineCommand(len(lines) - 1, "往期家宴", "灵宠家宴 往期"))
    return Reply("灵宠家宴", tuple(lines), ("灵宠家宴", "灵宠膳房", "灵宠目标"), tuple(links))


def hold(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠家宴 开席。")
    player = ctx.player()
    entry = rule(ctx)
    if held(ctx):
        raise GameError("本周家宴已经办过，下周一 00:00（北京时间）后可再开席。")
    current = cuisine.level(ctx)
    if current < entry.min_level:
        raise GameError(f"厨艺不足：家宴需要厨艺 {entry.min_level} 级，当前 {current} 级。")
    diners = cuisine.eligible_pets(ctx)
    if not diners:
        raise GameError("没有可宴请的伙伴：全部在册伙伴都在外出派遣。")
    shortage = _shortage(ctx)
    if shortage:
        raise GameError(shortage)

    player.stones -= entry.stones
    ctx.repo.consume_item(ctx.user_id, "spirit_food", entry.spirit_food)
    cuisine.spend_heat(ctx, entry.heat)
    for pet in diners:
        add_energy(pet, entry.energy, ctx.now)
        pet.exp += entry.exp
        pet.affinity = min(100, pet.affinity + entry.affinity)
    ctx.repo.invalidate_ready(ctx.user_id)
    result = grant(ctx, entry.reward)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (ctx.user_id, week_key(ctx.now), len(diners)),
    )
    total = counters.bump(ctx, "banquets_held")
    return Reply("灵宠家宴", (
        f"家宴开席：{len(diners)} 位伙伴 {_effect_text(ctx)}。",
        f"灵石 -{entry.stones}，灵粮 -{entry.spirit_food}，灶火 -{entry.heat}"
        f"（今日剩 {cuisine.heat_left(ctx)}）。",
        f"本周家宴奖励：{'，'.join(result)}。",
        f"累计举办 {total} 次 · 下周一 00:00 后可再开席。",
    ), ("灵宠家宴", "灵宠膳房", "灵宠目标"))


def ready(ctx: Context, user_id: str | None = None) -> bool:
    """Whether this week's banquet can be held right now (no side effects)."""
    entry = rule(ctx)
    return (
        not held(ctx, user_id)
        and cuisine.level(ctx, user_id) >= entry.min_level
        and bool(cuisine.eligible_pets(ctx))
        and _shortage(ctx) is None
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "开席":
        return hold(ctx, " ".join(parts[1:]))
    if parts[0] == "往期":
        return _archive(ctx, arg)
    raise GameError("格式：灵宠家宴 [开席 | 往期 [页码]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "家宴：尚未结契"
    if held(ctx, user_id):
        return f"家宴：本周已开席（宴请 {held_count(ctx, user_id)} 位）"
    return f"家宴：本周未开席 · 厨艺 {cuisine.level(ctx, user_id)}/{rule(ctx).min_level} 级"


__all__ = ["PAGE_SIZE", "WEEK_PREFIX", "dispatch", "held", "hold", "objective_line", "page"]
