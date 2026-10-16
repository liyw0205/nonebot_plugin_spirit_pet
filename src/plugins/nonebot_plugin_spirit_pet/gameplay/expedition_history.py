from datetime import datetime

from pydantic import ValidationError

from ..application.context import Context
from ..domain.expedition_state import RewardSnapshot
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from ..utils.time import BEIJING

PAGE_SIZE = 5


def _snapshot(row) -> RewardSnapshot:
    try:
        return RewardSnapshot.model_validate_json(row["reward_snapshot"])
    except (TypeError, ValueError, ValidationError) as exc:
        raise GameError("该行程的奖励快照暂不可回顾，请联系管理员检查存档。") from exc


def _resource_text(snapshot: RewardSnapshot) -> str:
    parts = []
    if snapshot.exp:
        parts.append(f"修为 +{snapshot.exp}")
    if snapshot.stones:
        parts.append(f"灵石 +{snapshot.stones}")
    return "、".join(parts) or "无"


def _item_text(ctx: Context, snapshot: RewardSnapshot) -> str:
    parts = []
    for item_id, amount in snapshot.items.items():
        if amount:
            name = ctx.content.items[item_id].name if item_id in ctx.content.items else f"物品 {item_id}"
            parts.append(f"{name} +{amount}")
    return "、".join(parts) or "无"


def _reward_text(ctx: Context, snapshot: RewardSnapshot) -> str:
    parts = [
        value for value in (_resource_text(snapshot), _item_text(ctx, snapshot)) if value != "无"
    ]
    return "、".join(parts) or "无"


def _state(ctx: Context, row) -> tuple[str, str | None, str | None]:
    job_id = row["job_id"]
    if row["state"] == "running":
        if ctx.now >= row["finishes_at"]:
            return "已完成，待归来领取", "领取归来奖励", f"灵宠归来 {job_id}"
        return f"外出中，剩余 {row['finishes_at'] - ctx.now} 秒", "提前召回", f"灵宠召回 {job_id}"
    if row["state"] == "cancelled":
        return "已提前召回，无奖励", None, None
    return "奖励已领取", None, None


def catalog(ctx: Context, arg: str) -> Reply:
    rows = ctx.repo.conn.execute(
        "SELECT e.*, p.name AS pet_name FROM expeditions e "
        "JOIN pets p ON p.user_id=e.user_id AND p.pet_id=e.pet_id "
        "WHERE e.user_id=? ORDER BY e.job_id DESC",
        (ctx.user_id,),
    ).fetchall()
    page = paginate(rows, arg, "灵宠行程记录", "灵宠行程记录", PAGE_SIZE)
    if not page.entries:
        commands = ["灵宠委托", "灵宠帮助"]
        if ctx.repo.player(ctx.user_id) is not None:
            commands.insert(0, "灵宠行程")
        return Reply("灵宠行程记录 1/1", ("尚无委托行程记录。",), (
            *commands,
        ))

    lines, commands, links = [], [], []
    for row in page.entries:
        status = _state_for_list(ctx, row)
        line = len(lines)
        lines.extend((
            f"行程 {row['job_id']} · {row['task_name']} · 灵宠：{row['pet_name']}",
            f"{status} · 出发于 {_time(row['started_at'])}",
        ))
        command = f"灵宠行程回顾 {row['job_id']}"
        commands.append(command)
        links.append(InlineCommand(line, "查看详情", command))
    commands.extend((*page.navigation, "灵宠行程", "灵宠委托"))
    return Reply(f"灵宠行程记录 {page.number}/{page.total}", tuple(lines), tuple(commands), tuple(links))


def _state_for_list(ctx: Context, row) -> str:
    if row["state"] == "claimed":
        try:
            reward = f"实际发放：{_reward_text(ctx, _snapshot(row))}"
        except GameError:
            reward = "奖励快照异常，可查看详情"
        return f"奖励已领取 · {reward}"
    state, _, _ = _state(ctx, row)
    if row["state"] == "running" and ctx.now >= row["finishes_at"]:
        try:
            state += f" · 待领取预览：{_reward_text(ctx, _snapshot(row))}"
        except GameError:
            state += " · 奖励快照异常"
    return state


def _time(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(timestamp, BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError) as exc:
        raise GameError("该行程的时间记录异常，请联系管理员检查存档。") from exc


def detail(ctx: Context, arg: str) -> Reply:
    job_id = quantity(arg, 9_223_372_036_854_775_807)
    row = ctx.repo.conn.execute(
        "SELECT e.*, p.name AS pet_name FROM expeditions e "
        "JOIN pets p ON p.user_id=e.user_id AND p.pet_id=e.pet_id "
        "WHERE e.job_id=? AND e.user_id=?",
        (job_id, ctx.user_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的这项行程。")

    state, label, command = _state(ctx, row)
    lines = [
        f"行程 {job_id} · {row['task_name']} · 灵宠：{row['pet_name']}",
        state,
        f"出发时间：{_time(row['started_at'])}（北京时间）",
    ]
    newer_count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM expeditions WHERE user_id=? AND job_id>?",
        (ctx.user_id, job_id),
    ).fetchone()[0]
    commands = [f"灵宠行程记录 {newer_count // PAGE_SIZE + 1}", "灵宠委托"]
    links = ()
    if row["state"] == "running":
        if ctx.now >= row["finishes_at"]:
            snapshot = _snapshot(row)
            lines.append(f"待领取预览：{_reward_text(ctx, snapshot)}")
        else:
            lines.append(f"预计归来：{_time(row['finishes_at'])}（北京时间）")
        commands.insert(0, f"灵宠行程 {job_id}")
        links = (InlineCommand(1, label, command),)
    elif row["state"] == "claimed":
        snapshot = _snapshot(row)
        lines.extend((
            f"领取时间：{_time(row['settled_at'])}（北京时间）",
            f"实际发放：{_resource_text(snapshot)}",
            f"实际道具：{_item_text(ctx, snapshot)}",
            "领取凭证：已永久保存",
        ))
    else:
        lines.append(f"召回时间：{_time(row['settled_at'])}（北京时间）；出发精力不退。")
    return Reply(f"行程回顾 {job_id}", tuple(lines), tuple(commands), links)
