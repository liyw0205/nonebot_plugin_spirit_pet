"""One-time milestones for distinct readers of a player's shared reports."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from .rewards import grant
from .shares import readers

CLAIM_PREFIX = "share_read_reward_"


def thresholds(ctx: Context) -> list[int]:
    return sorted(ctx.content.share_rewards)


def claim_id(readers_count: int) -> str:
    return f"{CLAIM_PREFIX}{readers_count}"


def _record(ctx: Context, user_id: str, readers_count: int):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(readers_count)),
    ).fetchone()


def claimed(ctx: Context, user_id: str, readers_count: int) -> bool:
    record = _record(ctx, user_id, readers_count)
    return bool(record and record["claimed"])


def _reward(entry) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in entry.items.items()
        },
    )


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in entry.items.items()
    )
    return "，".join(parts) if parts else "奖励待修复"


def _state(ctx: Context, user_id: str, count: int, entry) -> str:
    if claimed(ctx, user_id, entry.readers):
        return "已领取"
    if count >= entry.readers:
        return "可领取"
    return f"还差 {entry.readers - count} 位读者"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠分享奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "分享码被不同玩家打开时会计入读者里程碑；同一读者重复阅读只算一位。",
            *(
                f"{entry.readers} 位读者 · {entry.name} · {_reward_text(ctx, entry)}"
                for entry in (ctx.content.share_rewards[n] for n in thresholds(ctx))
            ),
            "尚未结契，先完成领养；分享与奖励均可公开查看。",
        ]
        return Reply("灵宠分享奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    count = readers(ctx, player.user_id)
    lines = [f"分享的去重读者：{count} 位。"]
    links = []
    for threshold in thresholds(ctx):
        entry = ctx.content.share_rewards[threshold]
        state = _state(ctx, player.user_id, count, entry)
        lines.append(f"{entry.readers} 位读者 · {entry.name} · {_reward_text(ctx, entry)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取分享奖励", f"灵宠分享领奖 {entry.readers}",
            ))
    lines.append("同一读者重复阅读同一分享码、或分享者自己阅读，都不增加读者数。")
    return Reply("灵宠分享奖励", tuple(lines), ("灵宠分享", "灵宠战报", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value.isdigit():
        raise GameError("格式：灵宠分享领奖 <读者数>，可选 3、10、30。")
    threshold = int(value)
    entry = ctx.content.share_rewards.get(threshold)
    if entry is None:
        raise GameError("格式：灵宠分享领奖 <读者数>，可选 3、10、30。")
    player = ctx.player()
    record = _record(ctx, player.user_id, threshold)
    if record is not None and record["claimed"]:
        raise GameError(f"{threshold} 位读者的分享奖励已经领取。")
    if record is not None:
        raise GameError("分享奖励领取记录异常，请联系管理员检查存档。")
    count = readers(ctx, player.user_id)
    if count < threshold:
        raise GameError(f"去重读者不足：当前 {count} 位，需要 {threshold} 位。")
    if any(item_id not in ctx.content.items for item_id in entry.items):
        raise GameError("分享奖励物品定义缺失；尚未领取。")
    result = grant(ctx, _reward(entry), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(threshold), count),
    )
    return Reply("分享奖励", (
        f"{threshold} 位读者「{entry.name}」已领取（当前 {count} 位）。", *result,
    ), ("灵宠分享奖励", "灵宠分享", "灵宠战报"))


__all__ = [
    "CLAIM_PREFIX", "catalog", "claim", "claim_id", "claimed", "thresholds",
]
