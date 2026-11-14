"""Weekly contribution-rank rewards derived from the world-boss threat ledger."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from . import world_boss
from .rewards import grant

PREFIX = "world_boss_rank_reward_"
PAGE_LIMIT = 10


def entries(ctx: Context):
    return [ctx.content.world_boss_rank_rewards[rank] for rank in (1, 3, 10)]


def claim_id(week: int, rank: int) -> str:
    return f"{PREFIX}{week}_{rank}"


def _rows(ctx: Context, week: int):
    return ctx.repo.conn.execute(
        "SELECT identity.id + 9999 AS uid, progress.user_id AS user_id, "
        "progress.progress AS contribution "
        "FROM quest_progress progress JOIN player_identity identity USING(user_id) "
        "WHERE progress.quest_id=? AND progress.claimed=0 "
        "ORDER BY progress.progress DESC, identity.id ASC LIMIT ?",
        (f"{world_boss.THREAT_PREFIX}{week}", PAGE_LIMIT),
    ).fetchall()


def _rank(ctx: Context, user_id: str, week: int) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT ranked FROM ("
        "SELECT progress.user_id AS user_id, ROW_NUMBER() OVER ("
        "ORDER BY progress.progress DESC, identity.id ASC) AS ranked "
        "FROM quest_progress progress JOIN player_identity identity USING(user_id) "
        "WHERE progress.quest_id=? AND progress.claimed=0"
        ") WHERE user_id=?",
        (f"{world_boss.THREAT_PREFIX}{week}", user_id),
    ).fetchone()
    return int(row["ranked"]) if row is not None else None


def _contribution(ctx: Context, user_id: str, week: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=0",
        (user_id, f"{world_boss.THREAT_PREFIX}{week}"),
    ).fetchone()
    return int(row["progress"]) if row is not None else 0


def _record(ctx: Context, user_id: str, week: int, threshold: int):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(week, threshold)),
    ).fetchone()


def claimed(ctx: Context, user_id: str, week: int, threshold: int) -> bool:
    record = _record(ctx, user_id, week, threshold)
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
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in entry.items.items()
    )
    return "、".join(parts)


def _state(ctx: Context, user_id: str, week: int, entry, rank: int | None) -> str:
    record = _record(ctx, user_id, week, entry.rank)
    if record is not None:
        return "已领取" if record["claimed"] else "领取记录异常"
    if rank is None:
        return "尚无贡献"
    if rank <= entry.rank:
        return "可领取"
    return f"还差至前 {entry.rank} 名 {rank - entry.rank} 名"


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("灵宠首领榜不接受参数，直接发送即可。")
    week = world_boss.week_ordinal(ctx.now)
    rows = _rows(ctx, week)
    lines = [
        f"本周首领贡献榜（{beijing_day(ctx.now)} 所在周）：按真实威胁贡献排名。",
        "同贡献按 UID 先后，贡献只来自本周真实首领挑战，个人胜败档位另行计算。",
    ]
    if rows:
        lines.extend(
            f"{index}. UID {row['uid']} · 威胁贡献 {row['contribution']}"
            for index, row in enumerate(rows, 1)
        )
    else:
        lines.append("本周还没有首领贡献，先去挑战首领吧。")

    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养；榜单和奖励规则可先只读查看。")
        return Reply("首领贡献榜", tuple(lines), ("灵宠首领", "灵宠帮助"), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    rank = _rank(ctx, player.user_id, week)
    contribution = _contribution(ctx, player.user_id, week)
    lines.append(
        f"你的本周贡献：{contribution} · 当前第 {rank} 名。"
        if rank is not None else "你的本周贡献：0 · 尚未入榜。"
    )
    links = []
    for entry in entries(ctx):
        state = _state(ctx, player.user_id, week, entry, rank)
        lines.append(f"前 {entry.rank} 名 · {entry.name} · {_reward_text(ctx, entry)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取榜赏", f"灵宠首领榜领奖 {entry.rank}",
            ))
    return Reply("首领贡献榜", tuple(lines), ("灵宠首领", "灵宠目标", "灵宠帮助"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value.isdecimal():
        raise GameError("格式：灵宠首领榜领奖 <名次>，可选 1、3、10。")
    threshold = int(value)
    entry = ctx.content.world_boss_rank_rewards.get(threshold)
    if entry is None:
        raise GameError("首领榜赏仅有前 1、3、10 名三档。")

    player = ctx.player()
    week = world_boss.week_ordinal(ctx.now)
    record = _record(ctx, player.user_id, week, threshold)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"本周前 {threshold} 名首领榜赏已领取。")
        raise GameError("首领榜赏领取记录异常，请联系管理员检查存档。")
    rank = _rank(ctx, player.user_id, week)
    if rank is None:
        raise GameError("本周尚无首领贡献，先完成一次真实挑战。")
    if rank > threshold:
        raise GameError(f"当前第 {rank} 名，尚未进入前 {threshold} 名。")
    missing = set(entry.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"首领榜赏物品定义缺失：{', '.join(sorted(missing))}；本次未领奖。")

    # Claim marker and payout share the outer Store transaction; either failure rolls back both.
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, claim_id(week, threshold), rank),
    )
    result = grant(ctx, _reward(entry), player.user_id)
    return Reply(
        "首领榜赏",
        (f"本周第 {rank} 名「{entry.name}」已领取。", *result),
        ("灵宠首领榜", "灵宠首领", "灵宠背包"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    week = world_boss.week_ordinal(ctx.now)
    rank = _rank(ctx, user_id, week)
    pending = sum(
        rank is not None and rank <= entry.rank and not claimed(ctx, user_id, week, entry.rank)
        for entry in entries(ctx)
    )
    return (
        f"首领榜赏：本周第 {rank} 名 · 可领 {pending} 档"
        if rank is not None else "首领榜赏：本周尚未入榜"
    )


def dispatch(ctx: Context, arg: str = "") -> Reply:
    value = arg.strip()
    if not value:
        return catalog(ctx)
    if value.startswith("领奖"):
        value = value[2:].strip()
    return claim(ctx, value)


__all__ = ["catalog", "claim", "claim_id", "dispatch", "objective_line"]
