"""Daily bounties: three rotating goals over the new systems, each claimable on its own.

The daily assignment board offers one choice out of three and covers only the original systems. A
bounty board offers three goals per Beijing day, derived from the pool by the day ordinal, and every
one of them can be claimed independently — so the counters added for hybridisation, alchemy, contracts
and hard clears finally have a daily outlet.

Progress is scoped to today: ``counters.bump`` also maintains a ``stat_<metric>_day_<date>`` row, so
yesterday's work never counts toward today's bounty and no per-player snapshot is needed.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from . import counters
from .rewards import grant

OFFERED = 3
CLAIM_PREFIX = "bounty_"
STAT_NAMES = {
    "hybrid_brews": "杂交",
    "alchemy_brews": "炼丹",
    "contracts_met": "契约",
    "hard_clears": "强化通关",
}


def pool(ctx: Context):
    return sorted(ctx.content.bounties.values(), key=lambda entry: entry.id)


def day_ordinal(now: int) -> int:
    from datetime import date

    return date.fromisoformat(beijing_day(now)).toordinal()


def todays(ctx: Context):
    """The window of bounties offered today, stable within the day and rotating next day."""
    entries = pool(ctx)
    start = day_ordinal(ctx.now) % len(entries)
    return [entries[(start + index) % len(entries)] for index in range(min(OFFERED, len(entries)))]


def claim_key(bounty, now: int) -> str:
    return f"{CLAIM_PREFIX}{beijing_day(now)}_{bounty.id}"


def progress(ctx: Context, bounty, user_id: str | None = None) -> int:
    return counters.today_value(ctx, bounty.metric, user_id)


def claimed(ctx: Context, bounty, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, claim_key(bounty, ctx.now)),
    ).fetchone()
    return row is not None


def reward_text(ctx: Context, bounty) -> str:
    parts = [f"灵石 {bounty.reward.stones.minimum}"] if bounty.reward.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in bounty.reward.items.items()
    )
    return " · ".join(parts) or "无奖励"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠赏金 [领取 <名称>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠赏金",
            (
                "尚未结契，先完成领养，才能接取赏金。",
                "赏金每日轮换三份，各自独立领取，进度只算当天。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = ["今日赏金各自独立领取，进度只计当天；明天换另外三份。"]
    links = []
    for bounty in todays(ctx):
        value = progress(ctx, bounty)
        done = claimed(ctx, bounty)
        state = "已领取" if done else ("可领取" if value >= bounty.target else "进行中")
        lines.append(
            f"{bounty.name} · {STAT_NAMES[bounty.metric]} {value}/{bounty.target}"
            f" · {reward_text(ctx, bounty)} · {state}"
        )
        if not done and value >= bounty.target:
            links.append(InlineCommand(len(lines) - 1, "领取", f"灵宠赏金 领取 {bounty.name}"))
    lines.append(f"今日可选：{'、'.join(entry.name for entry in todays(ctx))}。")
    return Reply("灵宠赏金", tuple(lines), ("灵宠赏金", "灵宠目标", "灵宠炼丹"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    ctx.player()
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠赏金 领取 <名称>。")
    bounty = named(ctx.content.bounties, text)
    offered = todays(ctx)
    if all(entry.id != bounty.id for entry in offered):
        names = "、".join(entry.name for entry in offered)
        raise GameError(f"今日赏金没有「{bounty.name}」；今日可选：{names}。")
    if claimed(ctx, bounty):
        raise GameError(f"「{bounty.name}」今日已领取，明日再来。")
    value = progress(ctx, bounty)
    if value < bounty.target:
        raise GameError(f"尚未达成：{bounty.description}（{value}/{bounty.target}）。")

    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, claim_key(bounty, ctx.now)),
    )
    lines = [f"「{bounty.name}」已完成：{reward_text(ctx, bounty)}。"]
    lines.extend(grant(ctx, bounty.reward))
    lines.append("今日其余赏金仍可继续完成。")
    return Reply("赏金已领", tuple(lines), ("灵宠赏金", "灵宠目标", "灵宠背包"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "领取":
        return claim(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠赏金 [领取 <名称>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "赏金：尚未结契"
    offered = todays(ctx)
    ready = sum(
        1 for bounty in offered
        if not claimed(ctx, bounty, user_id) and progress(ctx, bounty, user_id) >= bounty.target
    )
    done = sum(1 for bounty in offered if claimed(ctx, bounty, user_id))
    if ready:
        return f"赏金：{ready} 份可领取"
    return f"赏金：今日已领 {done}/{len(offered)}"
