"""One-time rewards for successful, persisted friend visits."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from .rewards import grant
from .visits import VISIT_PREFIX

TITLE = "灵宠串门礼"
CLAIM_PREFIX = "visit_reward_"


def entries(ctx: Context):
    return sorted(ctx.content.visit_rewards.values(), key=lambda entry: entry.threshold)


def _key(threshold: int) -> str:
    return f"{CLAIM_PREFIX}{threshold}"


def _record(ctx: Context, threshold: int, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(threshold)),
    ).fetchone()


def total_visits(ctx: Context, user_id: str | None = None) -> int:
    """Count only successful per-friend visit receipts, never daily counters."""
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM quest_progress "
        "WHERE user_id=? AND progress>0 AND quest_id GLOB ? "
        "AND quest_id NOT LIKE ? AND quest_id NOT LIKE ?",
        (owner, f"{VISIT_PREFIX}[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*",
         "visit_day_%", f"{CLAIM_PREFIX}%"),
    ).fetchone()
    return int(row["total"])


def _available(ctx: Context, entry) -> bool:
    return all(item_id in ctx.content.items for item_id in entry.items)


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in entry.items.items()
    )
    return "，".join(parts) if parts else "奖励暂不可用"


def _state(ctx: Context, entry, total: int, user_id: str | None = None) -> str:
    record = _record(ctx, entry.threshold, user_id)
    if record is not None:
        return "已领取" if record["claimed"] else "领取记录异常"
    if not _available(ctx, entry):
        return "奖励暂不可用"
    return "可领取" if total >= entry.threshold else f"还差 {entry.threshold - total} 次"


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("灵宠串门礼 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    total = total_visits(ctx) if player else 0
    lines = [
        f"累计串门：{total} 次。只统计成功拜访好友的持久回执，不含每日计数、预览或重复拜访。",
        "累计礼永久保留；串门原有羁绊经验与灵石奖励仍按每次成功拜访结算。",
    ]
    links = []
    for entry in entries(ctx):
        state = _state(ctx, entry, total) if player else "尚未结契"
        reward = _reward_text(ctx, entry) if _available(ctx, entry) else "奖励暂不可用"
        lines.append(f"{entry.threshold} 次 · {entry.name} · {reward} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取串门礼", f"灵宠串门领奖 {entry.threshold}",
            ))
    if player is None:
        lines.append("尚未结契，先完成领养再去好友家串门。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), ("灵宠串门", "灵宠目标") if player else ("灵宠帮助",), tuple(links))


def _reward(entry) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={item_id: Range(minimum=amount, maximum=amount)
               for item_id, amount in entry.items.items()},
    )


def claim(ctx: Context, arg: str) -> Reply:
    threshold = quantity(arg.strip(), 1000)
    entry = next((item for item in entries(ctx) if item.threshold == threshold), None)
    if entry is None:
        raise GameError("串门礼仅有 3、10、30 次三档。")
    player = ctx.player()
    record = _record(ctx, threshold, player.user_id)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"{threshold} 次串门礼已领取。")
        raise GameError("串门礼领取记录异常，请联系管理员检查存档。")
    total = total_visits(ctx, player.user_id)
    if total < threshold:
        raise GameError(f"累计串门仅 {total} 次，还未达到 {threshold} 次。")
    if not _available(ctx, entry):
        raise GameError("串门礼奖励定义暂不可用，本次未领奖。")
    result = grant(ctx, _reward(entry), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, _key(threshold), total),
    )
    return Reply(
        TITLE,
        (f"{entry.name}已领取 · 累计串门 {total} 次。", *result),
        (TITLE, "灵宠串门", "灵宠背包"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        return catalog(ctx)
    parts = arg.split()
    if parts[0] == "领奖":
        if len(parts) != 2:
            raise GameError("格式：灵宠串门礼 [领奖 档位]。")
        return claim(ctx, parts[1])
    if len(parts) == 1:
        return claim(ctx, parts[0])
    raise GameError("格式：灵宠串门礼 [领奖 档位]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "串门礼：尚未结契"
    total = total_visits(ctx, user_id)
    claimable = sum(
        total >= entry.threshold and _record(ctx, entry.threshold, user_id) is None
        for entry in entries(ctx)
    )
    return f"串门礼：累计 {total} 次 · 可领 {claimable} 档" if claimable else f"串门礼：累计 {total} 次"


__all__ = ["CLAIM_PREFIX", "TITLE", "catalog", "claim", "dispatch", "objective_line", "total_visits"]
