from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from .rewards import grant

CLAIM_PREFIX = "adventure_collection_"
MILESTONES = (
    (3, "初见山海", 120, {"spirit_food": 1}),
    (7, "寻幽探胜", 300, {"forge_ore": 2}),
    (14, "博闻强识", 700, {"affinity_pill": 2}),
    (21, "尽览山海", 1800, {"bloodline_essence": 4}),
)


def claim_id(threshold: int) -> str:
    return f"{CLAIM_PREFIX}{threshold}"


def discovered(ctx: Context, user_id: str) -> set[str]:
    """Return only current catalog entries; retired discovery rows stay harmless."""
    ids = tuple(ctx.content.encounters)
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    rows = ctx.repo.conn.execute(
        f"SELECT encounter_id FROM adventure_discoveries WHERE user_id=? "
        f"AND encounter_id IN ({placeholders})",
        (user_id, *ids),
    ).fetchall()
    return {row["encounter_id"] for row in rows}


def count(ctx: Context, user_id: str) -> int:
    return len(discovered(ctx, user_id))


def claimed(ctx: Context, user_id: str, threshold: int) -> bool:
    return claim_state(ctx, user_id, threshold) == "已领取"


def claim_state(ctx: Context, user_id: str, threshold: int) -> str | None:
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(threshold)),
    ).fetchone()
    if row is None:
        return None
    if row["claimed"] == 1 and type(row["progress"]) is int and row["progress"] >= threshold:
        return "已领取"
    return "领取记录异常"


def _reward(ctx: Context, milestone) -> Reward | None:
    _, _, stones, item_amounts = milestone
    for item_id in item_amounts:
        item = ctx.content.items.get(item_id)
        if item is None or item.kind not in {"consumable", "material"}:
            return None
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in item_amounts.items()
        },
    )


def _reward_text(ctx: Context, milestone) -> str:
    _, _, stones, item_amounts = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in item_amounts.items()
    )
    return "，".join(parts)


def summary(ctx: Context, user_id: str) -> str:
    total = count(ctx, user_id)
    claimable = []
    for milestone in MILESTONES:
        threshold = milestone[0]
        if (total >= threshold and claim_state(ctx, user_id, threshold) is None
                and _reward(ctx, milestone) is not None):
            claimable.append(threshold)
    if claimable:
        names = "、".join(f"{threshold} 条" for threshold in claimable)
        return f"奇闻收集：可领 {len(claimable)} 档（{names}）· 已发现 {total}/{len(ctx.content.encounters)} 条"
    return f"奇闻收集：暂无可领 · 已发现 {total}/{len(ctx.content.encounters)} 条"


def milestone_lines(ctx: Context, user_id: str) -> tuple[list[str], list[InlineCommand]]:
    total = count(ctx, user_id)
    lines = [f"当前独立奇闻：{total}/{len(ctx.content.encounters)} 条。"]
    links = []
    for milestone in MILESTONES:
        threshold, name, _, _ = milestone
        state = claim_state(ctx, user_id, threshold)
        if state is None:
            state = f"还差 {threshold - total} 条" if total < threshold else (
                "可领取" if _reward(ctx, milestone) is not None else "奖励待修复"
            )
        lines.append(f"{threshold} 条 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取收集奖励", f"灵宠奇闻领奖 {threshold}",
            ))
    return lines, links


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠奇闻奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            f"{milestone[0]} 条 · {milestone[1]} · {_reward_text(ctx, milestone)}"
            for milestone in MILESTONES
        ]
        lines.append("尚未结契，先完成领养；奇闻发现会从历练记录中永久累计。")
        return Reply("奇闻收集奖励", tuple(lines), ("灵宠奇闻榜", "灵宠帮助"), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))
    lines, links = milestone_lines(ctx, player.user_id)
    return Reply("奇闻收集奖励", tuple(lines), ("灵宠奇闻榜", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        raise GameError("格式：灵宠奇闻领奖 <数量>，可选 3、7、14、21。")
    player = ctx.player()
    threshold, name, _, _ = milestone
    status = claim_state(ctx, player.user_id, threshold)
    if status == "已领取":
        raise GameError(f"{threshold} 条奇闻收集奖励已领取。")
    if status == "领取记录异常":
        raise GameError(f"{threshold} 条奇闻收集奖励领取记录异常，请联系管理员检查存档。")
    total = count(ctx, player.user_id)
    if total < threshold:
        raise GameError(f"独立奇闻不足：当前 {total} 条，需要 {threshold} 条。")
    reward = _reward(ctx, milestone)
    if reward is None:
        raise GameError("奇闻收集奖励物品定义缺失或类型错误；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(threshold), total),
    )
    return Reply("奇闻收集奖励", (
        f"{threshold} 条里程碑「{name}」已领取。", *result,
        f"当前独立奇闻：{total}/{len(ctx.content.encounters)} 条。",
    ), ("灵宠奇闻奖励", "灵宠奇闻榜", "灵宠目标"))
