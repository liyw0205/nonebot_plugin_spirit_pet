"""Weekly milestones derived only from the existing weekly quest claims."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import beijing_day, beijing_week
from . import weekly_quests
from .rewards import grant

TITLE = "灵宠周常赏"
PREFIX = "weekly_reward_"


def entries(ctx: Context):
    return sorted(ctx.content.weekly_rewards.values(), key=lambda entry: entry.threshold)


def completed(ctx: Context, user_id: str | None = None) -> list[str]:
    return [quest.id for quest in ctx.content.weekly_quests.values()
            if weekly_quests.claimed_this_week(ctx, user_id or ctx.user_id, quest.id)]


def _key(start: int, threshold: int) -> str:
    return f"{PREFIX}{start}_{threshold}"


def _record(ctx: Context, start: int, threshold: int, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress,claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(start, threshold)),
    ).fetchone()


def _available(ctx: Context, entry) -> bool:
    return all(item in ctx.content.items for item in entry.items)


def _reward_text(ctx: Context, entry) -> str:
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(f"{ctx.content.items[item].name} {amount}" for item, amount in entry.items.items())
    return "，".join(parts)


def _state(ctx: Context, entry, count: int, start: int) -> str:
    record = _record(ctx, start, entry.threshold)
    if record is not None:
        return "已领取" if record["claimed"] else "领取记录异常"
    if not _available(ctx, entry):
        return "奖励暂不可用"
    return "可领取" if count >= entry.threshold else f"还差 {entry.threshold - count} 项"


def catalog(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠周常赏 [领奖 档位]。")
    start, end = beijing_week(ctx.now)
    player = ctx.repo.player(ctx.user_id)
    count = len(completed(ctx)) if player else 0
    lines = [f"本周：{beijing_day(start)} ~ {beijing_day(end - 1)} · 已领取 {count}/{len(ctx.content.weekly_quests)} 项周常。",
             "领取单项周常奖励后累计；每档每周可领一次，周一00:00重新累计，旧周未领档不补发。"]
    links = []
    for entry in entries(ctx):
        state = _state(ctx, entry, count, start) if player else "尚未结契"
        reward = _reward_text(ctx, entry) if _available(ctx, entry) else "奖励暂不可用"
        lines.append(f"{entry.threshold} 项 · {entry.name} · {reward} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取奖励",
                         f"{TITLE} 领奖 {entry.threshold} 周 {beijing_day(start)}"))
    if player is None:
        lines.append("尚未结契，先完成领养再参加周常。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), ("灵宠周常", "灵宠背包", "灵宠目标") if player else ("灵宠帮助",), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) not in (1, 3) or (len(parts) == 3 and parts[1] != "周"):
        raise GameError("格式：灵宠周常赏 领奖 档位，例如 灵宠周常赏 领奖 2。")
    threshold = quantity(parts[0], len(ctx.content.weekly_quests))
    entry = next((entry for entry in entries(ctx) if entry.threshold == threshold), None)
    if entry is None:
        options = "、".join(str(item.threshold) for item in entries(ctx))
        raise GameError(f"周常赏档位为 {options} 项。")
    start, end = beijing_week(ctx.now)
    if len(parts) == 3 and parts[2] != beijing_day(start):
        raise GameError("这条周常赏领取入口已经跨周，请重新查看灵宠周常赏。")
    player = ctx.player()
    # A permanent receipt also prevents an expired message from claiming a later week's reward.
    record = _record(ctx, start, threshold)
    if record is not None:
        if record["claimed"]:
            raise GameError("本周该档周常赏已领取，下周再来。")
        raise GameError("周常赏领取记录异常，请联系管理员检查存档。")
    future = ctx.repo.conn.execute(
        "SELECT 1 FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')='weekly_reward' "
        "AND json_extract(snapshot,'$.week_start')>? LIMIT 1", (player.user_id, start),
    ).fetchone()
    if future:
        raise GameError("系统日期早于周常赏记录，请等待日期恢复。")
    claimed = completed(ctx)
    if len(claimed) < threshold:
        raise GameError(f"本周仅领取 {len(claimed)} 项周常，还未达到 {threshold} 项。")
    if not _available(ctx, entry):
        raise GameError("周常赏奖励定义暂不可用，本次未领奖。")
    reward = Reward(exp=Range(minimum=0, maximum=0),
                    stones=Range(minimum=entry.stones, maximum=entry.stones),
                    items={item: Range(minimum=amount, maximum=amount) for item, amount in entry.items.items()})
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1)",
        (player.user_id, _key(start, threshold), len(claimed)),
    )
    reply = Reply(TITLE, (f"{entry.name}已领取 · 本周已领 {len(claimed)} 项周常。", *result,
                         f"周期至 {beijing_day(end - 1)}；其他已达成档位可分别领取。"),
                  (TITLE, "灵宠周常", "灵宠背包"))
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now,
        {"kind": "weekly_reward", "week_start": start, "threshold": threshold,
         "quests": claimed, "reward": entry.model_dump()}, reply)
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "领奖":
        return claim(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠周常赏 [领奖 档位]。")


def objective_line(ctx: Context, user_id: str) -> str:
    count = len(completed(ctx, user_id))
    start, _ = beijing_week(ctx.now)
    pending = sum(count >= entry.threshold and _available(ctx, entry)
                  and _record(ctx, start, entry.threshold, user_id) is None for entry in entries(ctx))
    return f"周常赏：本周已领 {count} 项周常 · 可领 {pending} 档"
