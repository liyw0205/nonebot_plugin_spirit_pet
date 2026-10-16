import json
from datetime import datetime

from ...application.context import Context
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import quantity
from ...utils.time import BEIJING

PAGE_SIZE = 4
_CORRUPT = "该赛季奖励快照暂不可回顾，请联系管理员检查存档。"


def _snapshot(row) -> dict:
    try:
        data = json.loads(row["reward_snapshot"])
        if not isinstance(data, dict):
            raise ValueError
        if not isinstance(data.get("tier_id"), str) or not data["tier_id"]:
            raise ValueError
        if not isinstance(data.get("tier_name"), str) or not data["tier_name"]:
            raise ValueError
        if type(data.get("rating")) is not int or data["rating"] < 0:
            raise ValueError
        if type(data.get("stones")) is not int or data["stones"] < 0:
            raise ValueError
        items = data.get("items")
        if not isinstance(items, dict) or any(
            not isinstance(item_id, str) or type(amount) is not int or amount < 0
            for item_id, amount in items.items()
        ):
            raise ValueError
        return data
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GameError(_CORRUPT) from exc


def _time(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(timestamp, BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        raise GameError("该赛季的时间记录异常，请联系管理员检查存档。") from exc


def _reward_text(ctx: Context, snapshot: dict) -> str:
    parts = [f"灵石 +{snapshot['stones']}"]
    parts.extend(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else f'物品 {item_id}'} +{amount}"
        for item_id, amount in snapshot["items"].items() if amount
    )
    return "、".join(parts)


def _rows(ctx: Context):
    return ctx.repo.conn.execute(
        "SELECT c.season_id, c.user_id, c.reward_snapshot, c.claimed_at, "
        "s.starts_at, s.ends_at FROM season_claims c "
        "JOIN seasons s ON s.season_id=c.season_id "
        "WHERE c.user_id=? ORDER BY s.starts_at DESC, c.season_id DESC",
        (ctx.user_id,),
    ).fetchall()


def _summary(ctx: Context, row) -> str:
    try:
        snapshot = _snapshot(row)
        reward = _reward_text(ctx, snapshot)
        claimed_at = _time(row["claimed_at"])
    except GameError as exc:
        label = "奖励快照异常" if str(exc) == _CORRUPT else "时间记录异常"
        return f"{row['season_id']} · {label}"
    return f"{row['season_id']} · 最终积分 {snapshot['rating']} · {snapshot['tier_name']} · 领取于 {claimed_at} · {reward}"


def catalog(ctx: Context, arg: str) -> Reply:
    """List claimed season rewards or open one season's persistent snapshot."""
    value = arg.strip()
    if value and "-" in value:
        return detail(ctx, value)
    if value:
        page = quantity(value, 999999)
    else:
        page = 1
    rows = _rows(ctx)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"赛季奖励回顾共 {pages} 页。")
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    if not selected:
        return Reply("赛季奖励回顾 1/1", ("尚无已领取的赛季奖励。",), ("灵宠赛季奖励", "灵宠帮助"))
    lines = tuple(_summary(ctx, row) for row in selected)
    links = tuple(
        InlineCommand(index, "查看详情", f"灵宠赛季奖励回顾 {row['season_id']}")
        for index, row in enumerate(selected)
    )
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠赛季奖励回顾 {page - 1}")
    if page < pages:
        commands.append(f"灵宠赛季奖励回顾 {page + 1}")
    commands.extend(("灵宠赛季奖励", "灵宠赛季"))
    return Reply(f"赛季奖励回顾 {page}/{pages}", lines, tuple(commands), links)


def detail(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 1 or "-" not in parts[0]:
        raise GameError("格式：灵宠赛季奖励回顾 YYYY-MM。")
    season_id = parts[0]
    row = ctx.repo.conn.execute(
        "SELECT c.season_id, c.user_id, c.reward_snapshot, c.claimed_at, "
        "s.starts_at, s.ends_at FROM season_claims c "
        "JOIN seasons s ON s.season_id=c.season_id "
        "WHERE c.season_id=? AND c.user_id=?",
        (season_id, ctx.user_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的该赛季奖励回顾。")
    if ctx.now < row["ends_at"]:
        raise GameError("该赛季尚未结束，尚无结算回顾。")
    snapshot = _snapshot(row)
    return Reply(f"赛季奖励回顾 · {season_id}", (
        f"最终积分：{snapshot['rating']}。",
        f"结算档位：{snapshot['tier_name']}。",
        f"领取时间：{_time(row['claimed_at'])}（北京时间）。",
        f"实际发放：{_reward_text(ctx, snapshot)}。",
        "领取凭证：已永久保存；本页读取领取时的奖励快照。",
    ), ("灵宠赛季奖励回顾", "灵宠赛季奖励", f"灵宠赛季 {season_id}", "灵宠背包"))
