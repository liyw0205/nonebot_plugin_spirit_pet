"""Cumulative rewards for real weekly household banquets."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from .rewards import grant

TITLE = "灵宠家宴赏"
PREFIX = "banquet_reward_"
BANQUET_PREFIX = "banquet_"


def entries(ctx: Context):
    return sorted(ctx.content.banquet_rewards.values(), key=lambda entry: entry.threshold)


def total_held(ctx: Context, user_id: str | None = None) -> int:
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM quest_progress "
        "WHERE user_id=? AND quest_id LIKE ? AND quest_id NOT LIKE ? AND claimed=1",
        (owner, f"{BANQUET_PREFIX}%", f"{PREFIX}%"),
    ).fetchone()
    return int(row["total"])


def _key(threshold: int) -> str:
    return f"{PREFIX}{threshold}"


def _record(ctx: Context, threshold: int, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(threshold)),
    ).fetchone()


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
    return "可领取" if total >= entry.threshold else f"还差 {entry.threshold - total} 席"


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠家宴赏 [领奖 档位]。")
    player = ctx.repo.player(ctx.user_id)
    total = total_held(ctx) if player else 0
    lines = [
        f"累计家宴：{total} 席。只统计每周成功开席的持久回执，不含预览、拒绝或重复开席。",
        "累计奖励永久保留；家宴每周固定奖励与本页里程奖励分别计算。",
    ]
    links = []
    for entry in entries(ctx):
        state = _state(ctx, entry, total) if player else "尚未结契"
        reward = _reward_text(ctx, entry) if _available(ctx, entry) else "奖励暂不可用"
        lines.append(f"{entry.threshold} 席 · {entry.name} · {reward} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取家宴赏", f"灵宠家宴领奖 {entry.threshold}",
            ))
    if player is None:
        lines.append("尚未结契，先完成领养再参加家宴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(
        TITLE,
        tuple(lines),
        ("灵宠家宴", "灵宠目标") if player else ("灵宠帮助",),
        tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    threshold = quantity(value, 1000)
    entry = next((item for item in entries(ctx) if item.threshold == threshold), None)
    if entry is None:
        raise GameError("家宴赏仅有 2、4、8 席三档。")
    player = ctx.player()
    record = _record(ctx, threshold, player.user_id)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"{threshold} 席家宴赏已领取。")
        raise GameError("家宴赏领取记录异常，请联系管理员检查存档。")
    total = total_held(ctx, player.user_id)
    if total < threshold:
        raise GameError(f"累计家宴仅 {total} 席，还未达到 {threshold} 席。")
    if not _available(ctx, entry):
        raise GameError("家宴赏奖励定义暂不可用，本次未领奖。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={item_id: Range(minimum=amount, maximum=amount)
               for item_id, amount in entry.items.items()},
    )
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, _key(threshold), total),
    )
    return Reply(
        TITLE,
        (f"{entry.name}已领取 · 累计家宴 {total} 席。", *result),
        (TITLE, "灵宠家宴", "灵宠背包"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "家宴赏：尚未结契"
    total = total_held(ctx, user_id)
    claimable = sum(
        total >= entry.threshold and _record(ctx, entry.threshold, user_id) is None
        for entry in entries(ctx)
    )
    if claimable:
        return f"家宴赏：累计 {total} 席 · 可领 {claimable} 档"
    return f"家宴赏：累计 {total} 席"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "领奖" and len(parts) == 2:
        return claim(ctx, parts[1])
    if len(parts) == 1 and parts[0].isdecimal():
        return claim(ctx, parts[0])
    raise GameError("格式：灵宠家宴赏 [领奖 档位]。")


__all__ = ["BANQUET_PREFIX", "PREFIX", "catalog", "dispatch", "entries", "objective_line", "total_held"]
