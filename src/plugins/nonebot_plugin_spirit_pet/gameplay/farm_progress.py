"""Farm ladder: 农事 levels earned by harvesting, and their one-time rewards.

Levels use the lifetime ``stat_farm_harvests`` counter written at harvest:

* the level is derived from ``data/farm_levels.json`` thresholds — no stored
  level that could drift from the counter;
* plots 5 and 6 ask for levels 2 and 3 (``farming.PLOT_LEVEL``);
* each reached level pays once, keyed ``farm_level_claim_<level>`` in the
  existing ``quest_progress`` table, in the same transaction as the reward.

Nothing here grows the farm or harvests a crop; ``灵宠灵田`` and ``灵宠收获``
stay the only writers of crop state.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from . import farming
from .rewards import grant

CLAIM_PREFIX = "farm_level_claim_"


def levels(ctx: Context):
    return [ctx.content.farm_levels[level] for level in sorted(ctx.content.farm_levels)]


def claimed(ctx: Context, level: int, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{CLAIM_PREFIX}{level}"),
    ).fetchone()
    return bool(row and row["claimed"])


def claimable(ctx: Context, user_id: str | None = None) -> list:
    reached = farming.level(ctx, user_id)
    return [
        entry for entry in levels(ctx)
        if entry.level > 1 and entry.level <= reached and not claimed(ctx, entry.level, user_id)
    ]


def next_level(ctx: Context, user_id: str | None = None):
    reached = farming.level(ctx, user_id)
    return next((entry for entry in levels(ctx) if entry.level > reached), None)


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in entry.items.items()
    )
    return " · ".join(parts) if parts else "无奖励"


def _reward(entry) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in entry.items.items()
        },
    )


def _state(ctx: Context, entry) -> str:
    if entry.level == 1:
        return "起始等级"
    if claimed(ctx, entry.level):
        return "已领取"
    if entry.level <= farming.level(ctx):
        return "可领取"
    return "未达成"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠农事 [领奖 [等级]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠农事",
            (
                "尚未结契，先完成领养，才能积累农事经验。",
                "每次真正收获作物都会推进农事等级；等级解锁更多田位并发放一次性奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    total = farming.harvests(ctx)
    current = farming.level_entry(ctx)
    following = next_level(ctx)
    lines = [
        f"农事 {current.level} 级 · 累计收获 {total} 次。",
        (
            f"下一等级：{following.level} 级，累计收获 {following.harvests} 次"
            f"（还差 {max(0, following.harvests - total)} 次）。"
            if following is not None
            else "农事已满级，收获继续计入累计次数。"
        ),
        f"田位 5 需农事 {farming.plot_requirement(5)} 级，田位 6 需农事 {farming.plot_requirement(6)} 级。",
    ]
    opened = sum(1 for plot in range(1, farming.PLOT_COUNT + 1) if farming._plot_state(ctx, plot)[0])
    lines.append(f"已开垦 {opened}/{farming.PLOT_COUNT} 块田位。")
    links = []
    for entry in levels(ctx):
        if entry.level == 1:
            continue
        state = _state(ctx, entry)
        lines.append(f"{entry.level} 级 · {_reward_text(ctx, entry)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取奖励", f"灵宠农事 领奖 {entry.level}"))
    pending = claimable(ctx)
    if pending:
        lines.append(f"可领 {len(pending)} 档农事奖励，也可一次全部领取。")
        links.append(InlineCommand(len(lines) - 1, "全部领取", "灵宠农事 领奖"))
    return Reply(
        "灵宠农事", tuple(lines),
        ("灵宠农事", "灵宠灵田", "灵宠目标", "灵宠帮助"), tuple(links),
    )


def _grant(ctx: Context, entries: list) -> tuple[str, ...]:
    lines = []
    for entry in entries:
        result = grant(ctx, _reward(entry))
        lines.append(f"{entry.level} 级：{'，'.join(result)}。")
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
            (ctx.user_id, f"{CLAIM_PREFIX}{entry.level}", entry.level),
        )
    return tuple(lines)


def claim(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    ctx.player()
    if text:
        level = quantity(text, max(ctx.content.farm_levels))
        if level not in ctx.content.farm_levels:
            raise GameError(f"农事等级只有 {len(ctx.content.farm_levels)} 级。")
        entry = ctx.content.farm_levels[level]
        if level == 1:
            raise GameError("农事 1 级是起始等级，没有奖励。")
        if claimed(ctx, level):
            raise GameError(f"农事 {level} 级奖励已经领取。")
        if level > farming.level(ctx):
            raise GameError(
                f"农事尚未达到 {level} 级：累计收获 {farming.harvests(ctx)}/{entry.harvests} 次。"
            )
        lines = _grant(ctx, [entry])
    else:
        pending = claimable(ctx)
        if not pending:
            raise GameError("暂无可领的农事奖励；继续收获作物提升等级。")
        lines = _grant(ctx, pending)
    return Reply("灵宠农事", (
        *lines,
        f"农事 {farming.level(ctx)} 级 · 累计收获 {farming.harvests(ctx)} 次。",
        f"已开垦 {sum(1 for plot in range(1, farming.PLOT_COUNT + 1) if farming._plot_state(ctx, plot)[0])}"
        f"/{farming.PLOT_COUNT} 块田位。",
    ), ("灵宠农事", "灵宠灵田", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "领奖":
        return claim(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠农事 [领奖 [等级]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "农事：尚未结契"
    total = farming.harvests(ctx, user_id)
    current = farming.level_entry(ctx, user_id)
    pending = claimable(ctx, user_id)
    following = next_level(ctx, user_id)
    progress = (
        f" · 下一等级 {total}/{following.harvests}" if following is not None else " · 已满级"
    )
    if pending:
        return f"农事：{current.level} 级 · 可领 {len(pending)} 档奖励{progress}"
    return f"农事：{current.level} 级 · 累计 {total} 次{progress}"


__all__ = ["CLAIM_PREFIX", "claim", "claimable", "dispatch", "levels", "objective_line", "page"]
