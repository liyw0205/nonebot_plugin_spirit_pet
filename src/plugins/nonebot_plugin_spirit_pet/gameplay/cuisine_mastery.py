"""Per-recipe mastery rewards backed by the real cuisine portion ledger."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import cuisine
from .rewards import grant

PREFIX = "cuisine_mastery_"
THRESHOLDS = (1, 3, 6)


def rewards(ctx: Context, dish_id: str | None = None):
    entries = [
        entry for entry in ctx.content.cuisine_mastery_rewards.values()
        if dish_id is None or entry.dish_id == dish_id
    ]
    return sorted(entries, key=lambda entry: (entry.dish_id, entry.threshold))


def _key(dish_id: str, threshold: int) -> str:
    return f"{PREFIX}{dish_id}_{threshold}"


def _progress(ctx: Context, user_id: str | None = None) -> dict[str, tuple[int, int]]:
    owner = user_id or ctx.user_id
    try:
        rows = ctx.repo.cuisine_progress(owner)
    except (TypeError, ValueError) as exc:
        raise GameError("膳房精通进度损坏，请联系管理员检查存档。") from exc
    for key, (progress, claimed_value) in rows.items():
        if key.startswith(cuisine.DISH_PREFIX) and progress < 0:
            raise GameError(f"{key.removeprefix(cuisine.DISH_PREFIX)} 的膳房精通进度损坏，请联系管理员检查存档。")
        if key.startswith(PREFIX) and claimed_value not in (0, 1):
            raise GameError("膳房精通领取记录损坏，请联系管理员检查存档。")
    return rows


def cooked(ctx: Context, dish_id: str, user_id: str | None = None) -> int:
    return _progress(ctx, user_id).get(cuisine.DISH_PREFIX + dish_id, (0, 0))[0]


def _claim_row(ctx: Context, dish_id: str, threshold: int, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(dish_id, threshold)),
    ).fetchone()


def claimed(ctx: Context, dish_id: str, threshold: int, user_id: str | None = None) -> bool:
    return _progress(ctx, user_id).get(_key(dish_id, threshold), (0, 0))[1] == 1


def mastery_level(ctx: Context, dish_id: str, user_id: str | None = None) -> int:
    amount = cooked(ctx, dish_id, user_id)
    return sum(amount >= threshold for threshold in THRESHOLDS)


def claimable(ctx: Context, user_id: str | None = None) -> list:
    owner = user_id or ctx.user_id
    if ctx.repo.player(owner) is None:
        return []
    progress = _progress(ctx, owner)
    return [
        entry for entry in rewards(ctx)
        if progress.get(cuisine.DISH_PREFIX + entry.dish_id, (0, 0))[0] >= entry.threshold
        and progress.get(_key(entry.dish_id, entry.threshold), (0, 0))[1] != 1
    ]


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else item_id} {amount}"
        for item_id, amount in entry.items.items()
    )
    return "、".join(parts)


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("灵宠膳房精通 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    lines = []
    links = []
    progress: dict[str, tuple[int, int]] = {}
    reward_entries = {
        dish.id: rewards(ctx, dish.id) for dish in cuisine.dishes(ctx)
    }
    all_rewards = tuple(entry for entries in reward_entries.values() for entry in entries)
    if player is None:
        lines.append("尚未结契，先完成领养；膳房成功产出的单膳会累计对应菜谱精通。")
        links.append(InlineCommand(0, "开始领养", "灵宠领养 "))
    else:
        progress = _progress(ctx)
        ready = sum(
            progress.get(cuisine.DISH_PREFIX + entry.dish_id, (0, 0))[0] >= entry.threshold
            and progress.get(_key(entry.dish_id, entry.threshold), (0, 0))[1] != 1
            for entry in all_rewards
        )
        lines.append(f"共有 {ready} 档精通奖励可领取；即时烹饪与掌勺成膳都会计入，焦糊和宴席不计。")
    for dish in cuisine.dishes(ctx):
        entries = reward_entries[dish.id]
        if not entries:
            continue
        amount = progress.get(cuisine.DISH_PREFIX + dish.id, (0, 0))[0]
        level = sum(amount >= threshold for threshold in THRESHOLDS)
        lines.append(f"{dish.name} · 成功 {amount} 份 · 精通 {level}/{len(THRESHOLDS)} 级")
        for entry in entries:
            is_claimed = progress.get(_key(dish.id, entry.threshold), (0, 0))[1] == 1
            state = "已领取" if is_claimed else (
                "可领取" if player and amount >= entry.threshold else f"未达成（{amount}/{entry.threshold}）"
            )
            lines.append(f"  {entry.threshold} 份 · {entry.name} · {_reward_text(ctx, entry)} · {state}")
            if state == "可领取":
                links.append(InlineCommand(
                    len(lines) - 1, "领取精通奖励",
                    f"灵宠膳房精通领奖 {dish.name} {entry.threshold}",
                ))
    return Reply(
        "膳房菜谱精通", tuple(lines),
        (("灵宠帮助",) if player is None else
         ("灵宠膳房", "灵宠掌勺", "灵宠膳房订单", "灵宠目标")), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2 or parts[1] not in {str(value) for value in THRESHOLDS}:
        raise GameError("格式：灵宠膳房精通领奖 <菜名> <档位>，档位可选 1、3、6。")
    player = ctx.player()
    dish = named(ctx.content.cuisine, parts[0])
    threshold = int(parts[1])
    entry = next(
        (reward for reward in rewards(ctx, dish.id) if reward.threshold == threshold), None,
    )
    if entry is None:
        raise GameError("该菜谱没有这个精通档位。")
    row = _claim_row(ctx, dish.id, threshold)
    if row is not None:
        if row["claimed"] == 1:
            raise GameError(f"{dish.name} {threshold} 份精通奖励已领取。")
        if row["claimed"] not in (0, 1):
            raise GameError("膳房精通领取记录损坏，请联系管理员检查存档。")
        raise GameError("该菜谱精通领取记录异常，请联系管理员检查存档。")
    amount = cooked(ctx, dish.id)
    if amount < threshold:
        raise GameError(f"{dish.name} 尚未达到 {threshold} 份精通，目前成功 {amount} 份。")
    missing = set(entry.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"膳房精通奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=entry.stones, maximum=entry.stones),
        items={item_id: Range(minimum=count, maximum=count) for item_id, count in entry.items.items()},
    )
    payout = grant(ctx, reward)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, _key(dish.id, threshold), amount),
    )
    return Reply(
        "膳房精通奖励", (
            f"{dish.name} {threshold} 份精通「{entry.name}」已领取。",
            *payout,
            f"当前成功 {amount} 份 · 精通 {mastery_level(ctx, dish.id)}/{len(THRESHOLDS)} 级。",
        ), ("灵宠膳房精通", "灵宠膳房", "灵宠背包"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None:
        return "膳房精通：尚未结契"
    progress = _progress(ctx, user_id)
    entries = rewards(ctx)
    ready = sum(
        progress.get(cuisine.DISH_PREFIX + entry.dish_id, (0, 0))[0] >= entry.threshold
        and progress.get(_key(entry.dish_id, entry.threshold), (0, 0))[1] != 1
        for entry in entries
    )
    mastered = sum(
        progress.get(cuisine.DISH_PREFIX + dish.id, (0, 0))[0] >= threshold
        for dish in cuisine.dishes(ctx) for threshold in THRESHOLDS
    )
    total = len(entries)
    if ready:
        return f"膳房精通：可领 {ready} 档 · 已达 {mastered}/{total} 档"
    return f"膳房精通：已达 {mastered}/{total} 档"


def dispatch(ctx: Context, arg: str = "") -> Reply:
    return catalog(ctx, arg)
