"""Milestones derived from successful three-stage cooking pot receipts."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.cooking_reward_content import CookingReward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from .rewards import grant

TITLE = "灵宠掌勺成品赏"
CLAIM_PREFIX = "cooking_reward_"


def entries(ctx: Context):
    return sorted(ctx.content.cooking_rewards.values(), key=lambda entry: entry.threshold)


def completed(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM duel_actions "
        "WHERE user_id=? AND json_extract(snapshot,'$.kind')='cooking' "
        "AND json_extract(snapshot,'$.status')='finished' "
        "AND json_type(snapshot,'$.portions')='integer' "
        "AND json_extract(snapshot,'$.portions')>0",
        (user_id or ctx.user_id,),
    ).fetchone()
    return int(row["total"])


def claim_id(threshold: int) -> str:
    return f"{CLAIM_PREFIX}{threshold}"


def _records(ctx: Context, user_id: str | None = None):
    return {row["quest_id"]: row for row in ctx.repo.conn.execute(
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE user_id=? AND quest_id GLOB ?",
        (user_id or ctx.user_id, CLAIM_PREFIX + "*"),
    )}


def _available(ctx: Context, entry: CookingReward) -> bool:
    try:
        CookingReward.model_validate(entry.model_dump())
    except ValueError:
        return False
    return all(item_id in ctx.content.items for item_id in entry.items)


def _reward_text(ctx: Context, entry: CookingReward) -> str:
    if not _available(ctx, entry):
        return "奖励暂不可用"
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in entry.items.items())
    return "、".join(parts)


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠掌勺成品赏；领取请用 灵宠掌勺成品领奖 档位。")
    registered = ctx.repo.player(ctx.user_id) is not None
    total = completed(ctx) if registered else 0
    records = _records(ctx) if registered else {}
    lines = [
        f"成功成膳：{total} 锅。只统计三段掌勺完成且有产物的锅，焦糊、收灶和膳房即时烹饪不计。",
        "奖励永久保留；成品入袋与掌勺熟练另行结算。",
    ]
    links = []
    for entry in entries(ctx):
        record = records.get(claim_id(entry.threshold))
        if record is not None:
            status = "已领取" if record["claimed"] else "领取记录异常"
        elif not registered:
            status = "尚未结契"
        elif total < entry.threshold:
            status = f"还差 {entry.threshold - total} 锅"
        elif not _available(ctx, entry):
            status = "奖励暂不可用"
        else:
            status = "可领取"
        lines.append(f"{entry.threshold} 锅 · {entry.name} · {_reward_text(ctx, entry)} · {status}")
        if status == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取成品赏", f"灵宠掌勺成品领奖 {entry.threshold}",
            ))
    if not registered:
        lines.append("尚未结契，先领养伙伴，再开锅掌勺。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), ("灵宠掌勺", "灵宠膳房", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    threshold = quantity(arg.strip(), 1000)
    entry = next((item for item in entries(ctx) if item.threshold == threshold), None)
    if entry is None:
        raise GameError("掌勺成品赏仅有 1、3、6 锅三档。")
    player = ctx.player()
    key = claim_id(threshold)
    record = _records(ctx, player.user_id).get(key)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"{threshold} 锅掌勺成品赏已领取。")
        raise GameError("掌勺成品赏领取记录异常，请联系管理员检查存档。")
    total = completed(ctx, player.user_id)
    if total < threshold:
        raise GameError(f"成功成膳仅 {total} 锅，还未达到 {threshold} 锅。")
    if not _available(ctx, entry):
        raise GameError("奖励定义暂不可用，本次未领取；请稍后再试。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={item_id: Range(minimum=amount, maximum=amount)
               for item_id, amount in entry.items.items()},
    )
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, key, total),
    )
    return Reply(
        TITLE, (f"{entry.name}已领取 · 成功成膳 {total} 锅。", *result),
        (TITLE, "灵宠掌勺", "灵宠背包"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    total = completed(ctx, user_id)
    records = _records(ctx, user_id)
    pending = sum(
        total >= entry.threshold
        and claim_id(entry.threshold) not in records
        and _available(ctx, entry)
        for entry in entries(ctx)
    )
    return f"掌勺成品赏：成功 {total} 锅 · 可领 {pending} 档"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "领奖" and len(parts) == 2:
        return claim(ctx, parts[1])
    if len(parts) == 1 and parts[0].isdecimal():
        return claim(ctx, parts[0])
    raise GameError("格式：灵宠掌勺成品赏 [领奖 档位]。")


__all__ = ["CLAIM_PREFIX", "catalog", "claim", "claim_id", "completed", "dispatch", "entries", "objective_line"]
