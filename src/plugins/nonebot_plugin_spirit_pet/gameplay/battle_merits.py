from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from .rewards import grant

CLAIM_PREFIX = "battle_merit_"
VALID_KINDS = ("pve", "pve_stage", "pvp")
MILESTONES = (
    (5, "初阵告捷", 180, {"forge_ore": 1}),
    (20, "百战渐勇", 600, {"bloodline_essence": 2}),
    (50, "战意凌云", 1500, {"forge_ore": 5, "bloodline_essence": 2}),
)


def claim_id(wins: int) -> str:
    return f"{CLAIM_PREFIX}{wins}"


def wins(ctx: Context, user_id: str) -> int:
    """Count each player's real PVE/PVP win once, independent of pet count."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS wins FROM battle_records AS b "
        "JOIN battle_participants AS p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind IN (?, ?, ?) AND b.winner_side=p.side",
        (user_id, *VALID_KINDS),
    ).fetchone()
    return int(row["wins"])


def claimed(ctx: Context, user_id: str, milestone: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(milestone)),
    ).fetchone()
    return bool(row and row["claimed"])


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


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠战斗功勋 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = ["有效胜场统计秘境、关卡和论剑，切磋、败北与平局不计。"]
        for milestone in MILESTONES:
            wins_needed, name, _, _ = milestone
            lines.append(f"{wins_needed} 胜 · {name} · {_reward_text(ctx, milestone)}")
        lines.append("尚未结契，先完成领养；战报会从此记录你的有效胜场。")
        return Reply("战斗功勋", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    total = wins(ctx, player.user_id)
    lines = [f"当前有效胜场：{total} 场（秘境、关卡、论剑；不含切磋）。"]
    links = []
    for milestone in MILESTONES:
        wins_needed, name, _, _ = milestone
        state = "已领取" if claimed(ctx, player.user_id, wins_needed) else (
            "可领取" if total >= wins_needed else f"还差 {wins_needed - total} 场"
        )
        lines.append(f"{wins_needed} 胜 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取功勋奖励", f"灵宠战斗功勋领奖 {wins_needed}",
            ))
    return Reply("战斗功勋", tuple(lines), ("灵宠战报", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        raise GameError("格式：灵宠战斗功勋领奖 <胜场>，可选 5、20、50。")
    player = ctx.player()
    wins_needed, name, _, _ = milestone
    if claimed(ctx, player.user_id, wins_needed):
        raise GameError(f"{wins_needed} 胜战斗功勋已领取。")
    total = wins(ctx, player.user_id)
    if total < wins_needed:
        raise GameError(f"有效胜场不足：当前 {total} 场，需要 {wins_needed} 场。")
    reward = _reward(ctx, milestone)
    if reward is None:
        raise GameError("战斗功勋奖励物品定义缺失或类型错误；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(wins_needed), total),
    )
    return Reply("战斗功勋奖励", (
        f"{wins_needed} 胜里程碑「{name}」已领取。", *result,
        f"当前有效胜场：{total} 场。",
    ), ("灵宠战斗功勋", "灵宠战报", "灵宠目标"))
