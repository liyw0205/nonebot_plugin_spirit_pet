"""Merchant contracts: a staged trade commitment with a deadline and a deposit.

The daily board in ``merchant.py`` is a one-message hand-off. A contract asks the
player to hold stock across days and deliver in order, with the deposit at risk
if they abandon or run out of time — the long-commitment half of the merchant
loop.

State lives in ``quest_progress`` (no schema change):

* ``mc_id_<contract id>`` — the accepted contract (presence is the marker)
* ``mc_stage`` — index of the next undelivered stage (1-based)
* ``mc_deadline`` — epoch the contract must be finished by
* ``mc_done_<stamp>_<id>`` / ``mc_abandon_<stamp>_<id>`` /
  ``mc_expire_<stamp>_<id>`` — one row per finished contract, ``progress`` is the
  number of stages actually delivered
"""

from ..application.context import Context
from ..domain.merchant_contract_content import MerchantContract
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from . import merchant
from .rewards import grant

ID_PREFIX = "mc_id_"
STAGE = "mc_stage"
DEADLINE = "mc_deadline"
DONE = "mc_done_"
ABANDON = "mc_abandon_"
EXPIRE = "mc_expire_"
HISTORY_PAGE = 6


def contracts(ctx: Context) -> list[MerchantContract]:
    return sorted(
        ctx.content.merchant_contracts.values(), key=lambda entry: (entry.min_rep, entry.id),
    )


def _row(ctx: Context, key: str, user_id: str | None = None):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()


def _set(ctx: Context, key: str, value: int, claimed: int = 0, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=excluded.claimed",
        (user_id or ctx.user_id, key, value, claimed),
    )


def _clear(ctx: Context, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND (quest_id IN (?, ?) OR quest_id LIKE ?)",
        (user_id or ctx.user_id, STAGE, DEADLINE, f"{ID_PREFIX}%"),
    )


def current_id(ctx: Context, user_id: str | None = None) -> str | None:
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ? LIMIT 1",
        (user_id or ctx.user_id, f"{ID_PREFIX}%"),
    ).fetchone()
    return row["quest_id"][len(ID_PREFIX):] if row else None


def active(ctx: Context, user_id: str | None = None) -> MerchantContract | None:
    contract_id = current_id(ctx, user_id)
    if contract_id is None:
        return None
    return ctx.content.merchant_contracts.get(contract_id)


def stage_index(ctx: Context, user_id: str | None = None) -> int:
    row = _row(ctx, STAGE, user_id)
    return int(row["progress"]) if row else 0


def deadline(ctx: Context, user_id: str | None = None) -> int:
    row = _row(ctx, DEADLINE, user_id)
    return int(row["progress"]) if row else 0


def _record(ctx: Context, prefix: str, contract, stages: int, user_id: str | None = None) -> None:
    _set(ctx, f"{prefix}{ctx.now}_{contract.id}", stages, 1, user_id)


def _expire_if_due(ctx: Context, user_id: str | None = None) -> None:
    """A contract past its deadline fails lazily, on the next read."""
    contract = active(ctx, user_id)
    if contract is None:
        return
    if ctx.now <= deadline(ctx, user_id):
        return
    stages = max(0, stage_index(ctx, user_id) - 1)
    _record(ctx, EXPIRE, contract, stages, user_id)
    _clear(ctx, user_id)


def _owned(ctx: Context, item_id: str, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _reward_text(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}"] if reward.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts) if parts else "无"


def _demand_text(ctx: Context, contract, index: int) -> str:
    stage = contract.stages[index - 1]
    return "、".join(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in stage.items.items()
    )


def _remaining_text(ctx: Context, contract) -> str:
    left = deadline(ctx) - ctx.now
    if left <= 0:
        return "已到期"
    days = left // 86_400
    return f"剩 {days} 天" if days else f"剩 {left} 秒"


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠商会 大单。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠商会 · 大单",
            (
                "尚未结契，先完成领养，才能替商会跑大单。",
                "大单分三段交货，接单要付定金；按期交齐有额外奖励，弃单或误期定金不退。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    _expire_if_due(ctx)
    player = ctx.player()
    current = merchant.rep(ctx, player.user_id)
    lines = [f"商会声望：{current}（大单按声望解锁）。"]
    links = []
    running = active(ctx)
    if running is not None:
        index = stage_index(ctx)
        lines.append(
            f"进行中：{running.name} · 第 {index}/{len(running.stages)} 段"
            f" · {_remaining_text(ctx, running)}。"
        )
        lines.append(f"下一段需求：{_demand_text(ctx, running, index)}。")
        links.append(InlineCommand(len(lines) - 1, "交货", "灵宠商会 交货"))
        links.append(InlineCommand(len(lines) - 2, "弃单", "灵宠商会 弃单"))
    else:
        lines.append("当前没有进行中的大单。")
    for contract in contracts(ctx):
        if running is not None:
            state = "进行中" if running.id == contract.id else "已有大单"
        elif current >= contract.min_rep:
            state = "可接"
        else:
            state = f"声望不足（{contract.min_rep}）"
        lines.append(
            f"{contract.name} · 声望 {contract.min_rep} · 定金 {contract.deposit}"
            f" · {len(contract.stages)} 段 · 限 {contract.days} 天"
            f" · 分段货款 {sum(stage.stones for stage in contract.stages)} 灵石"
            f" · 完成奖 {_reward_text(ctx, contract.bonus)} + 声望 {contract.rep} · {state}"
        )
        if state == "可接":
            links.append(InlineCommand(len(lines) - 1, "接单", f"灵宠商会 接单 {contract.name}"))
    lines.append("每日看板与 灵宠商会 兑换 不变；同一时间只能接一份大单，定金接单时扣除、交齐后返还。")
    links.append(InlineCommand(len(lines) - 1, "大单记录", "灵宠商会 大单记录"))
    return Reply("灵宠商会 · 大单", tuple(lines), ("灵宠商会", "灵宠商会 大单", "灵宠目标"), tuple(links))


def _contract_arg(ctx: Context, value: str) -> MerchantContract:
    if value.isdigit():
        listed = contracts(ctx)
        index = int(value)
        if not 1 <= index <= len(listed):
            raise GameError(f"大单只有 {len(listed)} 种，序号超出范围。")
        return listed[index - 1]
    for contract in contracts(ctx):
        if value in (contract.id, contract.name):
            return contract
    raise GameError("未找到该大单，请检查名称或序号。")


def accept(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        raise GameError("格式：灵宠商会 接单 <大单名|序号>。")
    player = ctx.player()
    _expire_if_due(ctx)
    if active(ctx) is not None:
        raise GameError("已经有一份进行中的大单，先 交货 或 弃单。")
    contract = _contract_arg(ctx, value)
    current = merchant.rep(ctx, player.user_id)
    if current < contract.min_rep:
        raise GameError(f"{contract.name}需要商会声望 {contract.min_rep}，当前 {current}。")
    if player.stones < contract.deposit:
        raise GameError(f"接单定金 {contract.deposit} 灵石，当前 {player.stones}。")
    player.stones -= contract.deposit
    _set(ctx, f"{ID_PREFIX}{contract.id}", 1, 1)
    _set(ctx, STAGE, 1)
    _set(ctx, DEADLINE, ctx.now + contract.days * 86_400)
    return Reply("灵宠商会 · 接单", (
        f"接下{contract.name}：扣定金 {contract.deposit} 灵石，限 {contract.days} 天。",
        f"第一段需求：{_demand_text(ctx, contract, 1)}。",
        "按期交齐三段可拿额外奖励并退回定金；弃单或误期定金不退。",
    ), ("灵宠商会 大单", "灵宠商会 交货", "灵宠背包"))


def deliver(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠商会 交货。")
    player = ctx.player()
    _expire_if_due(ctx)
    contract = active(ctx)
    if contract is None:
        raise GameError("当前没有进行中的大单，先 灵宠商会 接单。")
    index = stage_index(ctx)
    if not 1 <= index <= len(contract.stages):
        raise GameError("大单进度异常，请联系管理员检查存档。")
    stage = contract.stages[index - 1]
    short = [
        f"{ctx.content.items[item_id].name} 缺 {amount - _owned(ctx, item_id, player.user_id)}"
        for item_id, amount in stage.items.items()
        if _owned(ctx, item_id, player.user_id) < amount
    ]
    if short:
        raise GameError(f"交货物品不足：{'、'.join(short)}。")
    demand = _demand_text(ctx, contract, index)
    for item_id, amount in stage.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    if stage.stones:
        player.stones += stage.stones
    lines = [f"{contract.name} 第 {index}/{len(contract.stages)} 段已交货：{demand}。"]
    if stage.stones:
        lines.append(f"本段货款：灵石 +{stage.stones}。")
    if index < len(contract.stages):
        _set(ctx, STAGE, index + 1)
        lines.append(f"下一段需求：{_demand_text(ctx, contract, index + 1)}。")
        lines.append(f"{_remaining_text(ctx, contract)}。")
        return Reply("灵宠商会 · 交货", tuple(lines), ("灵宠商会 大单", "灵宠商会 交货", "灵宠背包"))

    result = grant(ctx, contract.bonus)
    player.stones += contract.deposit
    total_rep = merchant.rep(ctx, player.user_id) + contract.rep
    merchant._write_progress(ctx, merchant.REP_KEY, total_rep, 1)
    _record(ctx, DONE, contract, len(contract.stages))
    _clear(ctx)
    lines.extend((
        f"三段交齐：定金 {contract.deposit} 灵石已退回。",
        f"完成奖励：{'，'.join(result)} · 声望 +{contract.rep}（{total_rep}）。",
    ))
    return Reply("灵宠商会 · 大单完成", tuple(lines), ("灵宠商会", "灵宠商会 大单", "灵宠目标"))


def abandon(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠商会 弃单。")
    ctx.player()
    _expire_if_due(ctx)
    contract = active(ctx)
    if contract is None:
        raise GameError("当前没有进行中的大单。")
    stages = max(0, stage_index(ctx) - 1)
    _record(ctx, ABANDON, contract, stages)
    _clear(ctx)
    return Reply("灵宠商会 · 弃单", (
        f"已放弃{contract.name}，定金 {contract.deposit} 灵石不退。",
        f"已交付 {stages}/{len(contract.stages)} 段。",
        "可重新接单；弃单记录保留在 灵宠商会 大单记录。",
    ), ("灵宠商会 大单", "灵宠商会", "灵宠背包"))


def _records(ctx: Context, user_id: str | None = None) -> list[dict]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND ("
        "quest_id LIKE ? OR quest_id LIKE ? OR quest_id LIKE ?)",
        (user_id or ctx.user_id, f"{DONE}%", f"{ABANDON}%", f"{EXPIRE}%"),
    ).fetchall()
    found = []
    for row in rows:
        key = row["quest_id"]
        for prefix, label in ((DONE, "完成"), (ABANDON, "弃单"), (EXPIRE, "误期")):
            if not key.startswith(prefix):
                continue
            stamp, _, contract_id = key[len(prefix):].partition("_")
            if not stamp.isdigit():
                break
            contract = ctx.content.merchant_contracts.get(contract_id)
            found.append({
                "stamp": int(stamp), "outcome": label,
                "name": contract.name if contract else contract_id,
                "stages": int(row["progress"]),
                "total": len(contract.stages) if contract else 0,
            })
            break
    return sorted(found, key=lambda entry: (entry["stamp"], entry["name"]), reverse=True)


def history(ctx: Context, arg: str) -> Reply:
    if arg.strip() and not arg.strip().isdigit():
        raise GameError("格式：灵宠商会 大单记录 [页码]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠商会 · 大单记录",
            ("尚未结契，先完成领养，才有大单记录。",),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    records = _records(ctx)
    pages = max(1, (len(records) + HISTORY_PAGE - 1) // HISTORY_PAGE)
    page = int(arg) if arg.strip() else 1
    if page < 1 or page > pages:
        raise GameError(f"大单记录共 {pages} 页。")
    lines = [f"大单记录（第 {page}/{pages} 页，每页 {HISTORY_PAGE} 条）："]
    if not records:
        lines.append("还没有完成或中止的大单。")
    for record in records[(page - 1) * HISTORY_PAGE:page * HISTORY_PAGE]:
        lines.append(
            f"{beijing_day(record['stamp'])} · {record['name']} · {record['outcome']}"
            f" · 交付 {record['stages']}/{record['total']} 段"
        )
    links = []
    if pages > 1:
        if page > 1:
            links.append(InlineCommand(len(lines) - 1, "上一页", f"灵宠商会 大单记录 {page - 1}"))
        if page < pages:
            links.append(InlineCommand(len(lines) - 1, "下一页", f"灵宠商会 大单记录 {page + 1}"))
    return Reply("灵宠商会 · 大单记录", tuple(lines), ("灵宠商会 大单", "灵宠商会", "灵宠目标"), tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    # `灵宠商会 大单` arrives with its own verb; the sub-verbs arrive without it.
    if parts and parts[0] == "大单":
        parts = parts[1:]
    if not parts:
        return page(ctx, "")
    if parts[0] == "接单":
        return accept(ctx, " ".join(parts[1:]))
    if parts[0] == "交货":
        return deliver(ctx, " ".join(parts[1:]))
    if parts[0] == "弃单":
        return abandon(ctx, " ".join(parts[1:]))
    if parts[0] == "记录":
        return history(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠商会 大单 [接单 <名>|交货|弃单|记录 [页]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "大单：尚未结契"
    contract = active(ctx, user_id)
    if contract is None:
        open_now = [
            entry for entry in contracts(ctx) if entry.min_rep <= merchant.rep(ctx, user_id)
        ]
        return f"大单：未接单 · 可接 {len(open_now)} 种" if open_now else "大单：未接单"
    index = stage_index(ctx, user_id)
    return f"大单：{contract.name} {index}/{len(contract.stages)} 段"


__all__ = [
    "accept", "abandon", "active", "contracts", "current_id", "deliver", "dispatch",
    "history", "objective_line", "page", "stage_index",
]
