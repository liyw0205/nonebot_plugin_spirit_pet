"""One-time rewards for reaching the share leaderboard's top ranks."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from . import share_board
from .rewards import grant

CLAIM_PREFIX = "share_rank_reward_"


def thresholds(ctx: Context) -> list[int]:
    return sorted(ctx.content.share_rank_rewards)


def claim_id(rank: int) -> str:
    return f"{CLAIM_PREFIX}{rank}"


def _record(ctx: Context, user_id: str, rank: int):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(rank)),
    ).fetchone()


def claimed(ctx: Context, user_id: str, rank: int) -> bool:
    record = _record(ctx, user_id, rank)
    return bool(record and record["claimed"])


def rank_of(ctx: Context, user_id: str) -> int | None:
    for index, row in enumerate(share_board.ranking(ctx), start=1):
        if row["user_id"] == user_id:
            return index
    return None


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


def _state(ctx: Context, user_id: str, rank: int | None, entry) -> str:
    if claimed(ctx, user_id, entry.rank):
        return "已领取"
    if rank is None:
        return "尚未上榜"
    if rank <= entry.rank:
        return "可领取"
    return f"还差至前 {entry.rank} 名 {rank - entry.rank} 名"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠分享榜奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "分享榜按去重读者数排名，达到前 1/3/10 名可各领一次奖励。",
            *(
                f"前 {entry.rank} 名 · {entry.name} · {_reward_text(ctx, entry)}"
                for entry in (ctx.content.share_rank_rewards[rank] for rank in thresholds(ctx))
            ),
            "尚未结契，先完成领养；分享榜与奖励均可公开查看。",
        ]
        return Reply("灵宠分享榜奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    rank = rank_of(ctx, player.user_id)
    lines = [
        f"当前分享榜名次：第 {rank} 名。" if rank is not None else "当前分享榜名次：尚未上榜。",
    ]
    links = []
    for threshold in thresholds(ctx):
        entry = ctx.content.share_rank_rewards[threshold]
        state = _state(ctx, player.user_id, rank, entry)
        lines.append(f"前 {entry.rank} 名 · {entry.name} · {_reward_text(ctx, entry)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取分享榜奖励", f"灵宠分享榜领奖 {entry.rank}",
            ))
    lines.append("奖励为一次性，领取后掉出榜单不会撤回。")
    return Reply("灵宠分享榜奖励", tuple(lines), ("灵宠分享榜", "灵宠分享", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value.isdigit():
        raise GameError("格式：灵宠分享榜领奖 <名次>，可选 1、3、10。")
    threshold = int(value)
    entry = ctx.content.share_rank_rewards.get(threshold)
    if entry is None:
        raise GameError("格式：灵宠分享榜领奖 <名次>，可选 1、3、10。")
    player = ctx.player()
    record = _record(ctx, player.user_id, threshold)
    if record is not None and record["claimed"]:
        raise GameError(f"前 {threshold} 名的分享榜奖励已经领取。")
    if record is not None:
        raise GameError("分享榜奖励领取记录异常，请联系管理员检查存档。")
    rank = rank_of(ctx, player.user_id)
    if rank is None:
        raise GameError("你尚未进入分享榜，需先有被不同玩家读过的分享。")
    if rank > threshold:
        raise GameError(f"当前第 {rank} 名，尚未进入前 {threshold} 名。")
    if any(item_id not in ctx.content.items for item_id in entry.items):
        raise GameError("分享榜奖励物品定义缺失；尚未领取。")
    result = grant(ctx, _reward(entry), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(threshold), rank),
    )
    return Reply("分享榜奖励", (
        f"前 {threshold} 名「{entry.name}」已领取（第 {rank} 名）。", *result,
    ), ("灵宠分享榜奖励", "灵宠分享榜", "灵宠目标"))


__all__ = [
    "CLAIM_PREFIX", "catalog", "claim", "claim_id", "claimed", "rank_of", "thresholds",
]
