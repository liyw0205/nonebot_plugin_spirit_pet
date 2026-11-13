"""One-time rewards for bringing real materials back from each herb route."""

from collections import defaultdict

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity, named
from .rewards import grant

CLAIM_PREFIX = "herbalism_reward_"


def _entries(ctx: Context, route_id: str | None = None):
    entries = [entry for entry in ctx.content.herbalism_rewards.values()
               if route_id is None or entry.route == route_id]
    return sorted(entries, key=lambda entry: (entry.route, entry.threshold))


def _record(ctx: Context, route_id: str, threshold: int, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{CLAIM_PREFIX}{route_id}_{threshold}"),
    ).fetchone()


def _seen(ctx: Context, route_id: str, user_id: str | None = None) -> int:
    user_id = user_id or ctx.user_id
    route = ctx.content.herb_routes[route_id]
    site_keys = {
        f"herbalism_seen_{route_id}_{index}"
        for index, site in enumerate(route.sites, 1)
        if site.item_id is not None
    }
    if not site_keys:
        return 0
    placeholders = ",".join("?" for _ in site_keys)
    return int(ctx.repo.conn.execute(
        f"SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND progress>0 AND quest_id IN ({placeholders})",
        (user_id, *sorted(site_keys)),
    ).fetchone()[0])


def _reward(entry) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={item_id: Range(minimum=amount, maximum=amount)
               for item_id, amount in entry.items.items()},
    )


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in entry.items.items())
    return "，".join(parts)


def _state(ctx: Context, entry, count: int, user_id: str | None = None) -> str:
    if _record(ctx, entry.route, entry.threshold, user_id) is not None:
        return "已领取"
    return "可领取" if count >= entry.threshold else f"还差 {entry.threshold - count} 处"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠采药赏 不接受参数，直接发送即可。")
    user_id = ctx.user_id
    if ctx.repo.player(user_id) is None:
        lines = ["采药赏按每条药山实际带回的采集点累计，达成每档可领一次。"]
        for route in ctx.content.herb_routes.values():
            lines.append(f"{route.name} · 0/{sum(site.item_id is not None for site in route.sites)} 处")
            lines.extend(f"  {entry.threshold} 处 · {entry.name} · {_reward_text(ctx, entry)}"
                         for entry in _entries(ctx, route.id))
        lines.append("尚未结契，先完成领养；预览不会写入进度。")
        return Reply("灵宠采药赏", tuple(lines), ("灵宠帮助",),
                     (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),))
    lines = ["只统计返程时实际带回的采集点；每档奖励只能领取一次。"]
    links = []
    for route in ctx.content.herb_routes.values():
        total = sum(site.item_id is not None for site in route.sites)
        count = _seen(ctx, route.id)
        lines.append(f"{route.name} · {count}/{total} 处")
        for entry in _entries(ctx, route.id):
            state = _state(ctx, entry, count)
            lines.append(f"{entry.threshold} 处 · {entry.name} · {_reward_text(ctx, entry)} · {state}")
            if state == "可领取":
                links.append(InlineCommand(len(lines) - 1, "领取奖励",
                                           f"灵宠采药领奖 {route.name} {entry.threshold}"))
    return Reply("灵宠采药赏", tuple(lines), ("灵宠采药", "灵宠目标", "灵宠帮助"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠采药领奖 药山名 档位，例如 灵宠采药领奖 溪谷药坡 1。")
    route = named(ctx.content.herb_routes, parts[0])
    threshold = quantity(parts[1], 9)
    entry = next((item for item in _entries(ctx, route.id) if item.threshold == threshold), None)
    if entry is None:
        raise GameError("该药山没有此档采药奖励。")
    player = ctx.player()
    record = _record(ctx, route.id, threshold, player.user_id)
    if record is not None and record["claimed"]:
        raise GameError(f"{route.name} {threshold} 处奖励已经领取。")
    if record is not None:
        raise GameError("采药奖励领取记录异常，请联系管理员检查存档。")
    count = _seen(ctx, route.id, player.user_id)
    if count < threshold:
        raise GameError(f"{route.name} 仅带回 {count} 处，还未达到 {threshold} 处。")
    result = grant(ctx, _reward(entry), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, f"{CLAIM_PREFIX}{route.id}_{threshold}", count),
    )
    return Reply("灵宠采药赏", (f"{route.name}「{entry.name}」已领取（带回 {count} 处）。", *result),
                 ("灵宠采药赏", "灵宠采药", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        return catalog(ctx, "")
    parts = arg.split()
    if parts[0] == "领奖":
        return claim(ctx, " ".join(parts[1:]))
    # The parser removes the alias suffix for ``灵宠采药领奖``; accepting the
    # direct two-argument form keeps native buttons and text commands identical.
    if len(parts) == 2:
        return claim(ctx, arg)
    raise GameError("格式：灵宠采药赏 [领奖 药山名 档位]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "采药赏：尚未结契"
    pending = []
    for route in ctx.content.herb_routes.values():
        count = _seen(ctx, route.id, user_id)
        pending.extend(entry for entry in _entries(ctx, route.id)
                       if count >= entry.threshold and _record(ctx, entry.route, entry.threshold, user_id) is None)
    return f"采药赏：可领 {len(pending)} 档" if pending else "采药赏：按三条药山带回点数累计"


__all__ = ["CLAIM_PREFIX", "catalog", "claim", "dispatch", "objective_line"]
