"""Two-season farming contracts backed by append-only duel action snapshots."""

import sqlite3

from pydantic import ValidationError

from ..application.context import Context
from ..domain.farm_contract_snapshot import FarmContractSnapshot
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from . import farming

TITLE = "灵宠农契"
SEQUENCE_KEY = "farm_contract_sequence"
RULE_VERSION = 1
PAGE_SIZE = 5


def _validate(ctx: Context, payload: dict) -> dict:
    try:
        run = FarmContractSnapshot.model_validate(payload).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError) as exc:
        raise GameError("农契快照损坏，灵田与资源未变；请联系管理员核对存档。") from exc
    if set(run["crops"]) - set(ctx.content.crops):
        raise GameError("农契作物快照缺少当前目录引用，进度保留且未结算。")
    referenced = set(run["delivery"]) | set(run["reward_items"])
    if referenced - set(ctx.content.items):
        raise GameError("农契物品快照缺少当前目录引用，进度保留且未结算。")
    return run


def _latest(ctx: Context, user_id: str | None = None) -> dict | None:
    try:
        row = ctx.repo.latest_farm_contract(user_id or ctx.user_id)
    except (sqlite3.DatabaseError, TypeError, ValueError, KeyError) as exc:
        raise GameError("农契记录损坏，未写入任何状态；请联系管理员核对存档。") from exc
    if row is None:
        return None
    return _validate(ctx, row["snapshot"])


def active(ctx: Context, user_id: str | None = None) -> dict | None:
    run = _latest(ctx, user_id)
    return run if run is not None and run["status"] == "active" else None


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_farm_contract_action(
        ctx.operation_id, ctx.user_id, ctx.now, run, reply,
    )
    return reply


def _plan_by_name(ctx: Context, query: str):
    return named(ctx.content.farm_contracts, query)


def _item_text(ctx: Context, values: dict[str, int]) -> str:
    return "、".join(f"{ctx.content.items[item_id].name} ×{amount}" for item_id, amount in values.items())


def _reward_text(ctx: Context, plan: dict) -> str:
    parts = [f"灵石 {plan['reward_stones']}"] if plan["reward_stones"] else []
    if plan["reward_items"]:
        parts.append(_item_text(ctx, plan["reward_items"]))
    return "、".join(parts)


def _available_plots(ctx: Context) -> list[int]:
    return [
        plot for plot in range(1, farming.PLOT_COUNT + 1)
        if farming._open_row(ctx, plot) is not None and farming._crop_row(ctx, plot) is None
    ]


def _contract_lines(ctx: Context, run: dict) -> list[str]:
    order = " → ".join(ctx.content.crops[crop_id].name for crop_id in run["crops"])
    seasons = run["seasons"]
    lines = [
        f"契约 {run['contract_id']} · {run['plan_name']} · 田位 {run['plot']} · 已完成 {len(seasons)}/2 季",
        f"轮作顺序：{order}",
    ]
    for season in seasons:
        crop = ctx.content.crops[season["crop_id"]]
        lines.append(f"第 {season['number']} 季 · {crop.name} · 已真实成熟收获")
    if len(seasons) < 2:
        crop = ctx.content.crops[run["crops"][len(seasons)]]
        lines.append(f"下一季：田位 {run['plot']} 播种{crop.name}并成熟收获。")
    else:
        lines.append(f"可交付：{_item_text(ctx, run['delivery'])}。")
    lines.append(f"押金 {run['deposit']} 灵石 · 完成奖励：{_reward_text(ctx, run)}")
    return lines


def catalog(ctx: Context) -> Reply:
    run = active(ctx)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = ["三份农契都需在本人已开垦、空闲的灵田上签订；每人同时只能进行一份。"]
        for plan in ctx.content.farm_contracts.values():
            crops = " → ".join(ctx.content.crops[crop_id].name for crop_id in plan.crops)
            lines.append(
                f"{plan.name} · 农事 {plan.min_farm_level} 级 · 押金 {plan.deposit} · "
                f"{crops} · 交付 {_item_text(ctx, plan.delivery)} · 奖励 {_reward_text(ctx, plan.model_dump(mode='json'))}"
            )
        return Reply(TITLE, tuple(lines), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    if run is not None:
        lines = _contract_lines(ctx, run)
        links = []
        if len(run["seasons"]) == 2:
            links.append(InlineCommand(0, "交付农契", f"{TITLE} 交付 {run['contract_id']}"))
        links.append(InlineCommand(0, "放弃农契", f"{TITLE} 放弃 {run['contract_id']}"))
        return Reply(TITLE, tuple(lines), (TITLE + " 记录", "灵宠灵田", "灵宠背包", "灵宠目标"), tuple(links))

    lines = [f"农事 {farming.level(ctx)} 级 · 同时限一份；签约只接受已开垦且空闲的田位。"]
    links = []
    plots = _available_plots(ctx)
    for plan in ctx.content.farm_contracts.values():
        crops = " → ".join(ctx.content.crops[crop_id].name for crop_id in plan.crops)
        line = (
            f"{plan.name} · 农事 {plan.min_farm_level} 级 · 押金 {plan.deposit} · {crops} · "
            f"交付 {_item_text(ctx, plan.delivery)} · 完成奖励 {_reward_text(ctx, plan.model_dump(mode='json'))}"
        )
        lines.append(line)
        if farming.level(ctx) < plan.min_farm_level:
            lines.append(f"  尚需农事 {plan.min_farm_level} 级。")
        elif player.stones < plan.deposit:
            lines.append(f"  押金不足，当前 {player.stones} 灵石。")
        elif plots:
            plot = plots[0]
            lines.append(f"  可用空闲田位：{'、'.join(map(str, plots))}。")
            links.append(InlineCommand(len(lines) - 1, "签订契约", f"{TITLE} 签订 {plan.name} {plot}"))
        else:
            lines.append("  暂无已开垦的空闲田位。")
    lines.append("只有签约后在指定田位种下、按顺序成熟收获的作物才计入两季。")
    return Reply(TITLE, tuple(lines), (TITLE + " 记录", "灵宠灵田", "灵宠背包", "灵宠目标"), tuple(links))


def check_plant_time(ctx: Context, plot: int) -> None:
    run = active(ctx)
    if run is not None and run["plot"] == plot and ctx.now < run["updated_at"]:
        raise GameError("当前时间早于农契最近一次推进，请等待时钟恢复。")


def sign(ctx: Context, plan_name: str, plot: int) -> Reply:
    player = ctx.player()
    plan = _plan_by_name(ctx, plan_name)
    if active(ctx) is not None:
        raise GameError("已有进行中的农契，请先完成交付或主动放弃。")
    latest = _latest(ctx)
    if latest is not None and ctx.now < latest["updated_at"]:
        raise GameError("当前时间早于上次农契记录，请等待时钟恢复。")
    if farming.level(ctx) < plan.min_farm_level:
        raise GameError(f"{plan.name}需要农事 {plan.min_farm_level} 级，当前 {farming.level(ctx)} 级。")
    if not 1 <= plot <= farming.PLOT_COUNT:
        raise GameError(f"田位编号是 1-{farming.PLOT_COUNT}。")
    opened, crop_row, _ = farming._plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦。")
    if crop_row is not None:
        raise GameError(f"田位 {plot} 已有作物，农契只可绑定空闲田位。")
    if player.stones < plan.deposit:
        raise GameError(f"签订{plan.name}需要押金 {plan.deposit} 灵石，当前不足。")
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, SEQUENCE_KEY),
    ).fetchone()
    contract_id = int(row["progress"] if row else 0) + 1
    if contract_id > 9_223_372_036_854_775_807:
        raise GameError("农契编号已达上限，未扣除押金。")
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress, claimed=0",
        (ctx.user_id, SEQUENCE_KEY, contract_id),
    )
    player.stones -= plan.deposit
    run = FarmContractSnapshot(
        snapshot_version=1, contract_id=contract_id, plan_id=plan.id, plan_name=plan.name,
        status="active", plot=plot, deposit=plan.deposit, crops=plan.crops,
        delivery=plan.delivery, reward_stones=plan.reward_stones,
        reward_items=plan.reward_items, rule_version=RULE_VERSION,
        signed_at=ctx.now, updated_at=ctx.now, seasons=[],
    ).model_dump(mode="json")
    reply = Reply(TITLE + " · 已签订", (
        f"契约 {contract_id}「{plan.name}」已绑定田位 {plot}，托管押金 {plan.deposit} 灵石。",
        f"两季顺序：{' → '.join(ctx.content.crops[crop_id].name for crop_id in run['crops'])}。",
        "按顺序播种并真实成熟收获；完成两季后交付指定材料，押金与奖励同事务结算。",
    ), (TITLE, "灵宠灵田", "灵宠商店"))
    return _record(ctx, run, reply)


def advance_on_harvest(
    ctx: Context, plot: int, crop_id: str, cycle: int, planted_at: int,
    harvested_at: int, *, wilted: bool, reply: Reply,
) -> tuple[Reply, dict | None]:
    run = active(ctx)
    if run is None:
        return reply, None
    if ctx.now < run["updated_at"]:
        raise GameError("当前时间早于农契最近一次推进，请等待时钟恢复。")
    # Even non-qualifying harvests need a permanent receipt to protect later crops.
    run["updated_at"] = ctx.now
    if run["plot"] != plot or wilted or len(run["seasons"]) >= 2:
        return reply, run
    next_number = len(run["seasons"]) + 1
    expected = run["crops"][next_number - 1]
    if crop_id != expected or planted_at < run["signed_at"]:
        return reply, run
    if cycle <= 0 or harvested_at < planted_at:
        raise GameError("本季种植记录无效，农契进度未变。")
    run["seasons"].append({
        "number": next_number, "crop_id": crop_id, "cycle": cycle,
        "planted_at": planted_at, "harvested_at": harvested_at,
    })
    run["updated_at"] = ctx.now
    run = _validate(ctx, run)
    progress = f"农契 {run['contract_id']} · 第 {next_number}/2 季达成。"
    updated_reply = Reply(reply.title, (*reply.lines, progress), reply.commands, reply.inline_commands)
    return updated_reply, run


def _active_contract(ctx: Context, contract_id: int) -> dict:
    run = active(ctx)
    if run is None:
        raise GameError("当前没有进行中的农契。")
    if run["contract_id"] != contract_id:
        raise GameError("这是旧农契编号，请重新查看 灵宠农契。")
    if ctx.now < run["updated_at"]:
        raise GameError("当前时间早于农契最近一次推进，请等待时钟恢复。")
    return run


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def deliver(ctx: Context, contract_id: int) -> Reply:
    run = _active_contract(ctx, contract_id)
    if len(run["seasons"]) != 2:
        raise GameError("两季作物尚未全部成熟收获，不能交付。")
    missing = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, item_id)}/{amount}"
        for item_id, amount in run["delivery"].items()
        if _owned(ctx, item_id) < amount
    ]
    if missing:
        raise GameError(f"交付材料不足：{'、'.join(missing)}。农契与押金保持不变。")
    for item_id, amount in run["delivery"].items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    player = ctx.player()
    payout = run["deposit"] + run["reward_stones"]
    player.stones += payout
    for item_id, amount in run["reward_items"].items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    run["status"] = "completed"
    run["updated_at"] = ctx.now
    lines = [
        f"契约 {contract_id} 已交付 {_item_text(ctx, run['delivery'])}。",
        f"押金退还 {run['deposit']} 灵石 · 完成奖励灵石 {run['reward_stones']} · 总计 +{payout}。",
    ]
    if run["reward_items"]:
        lines.append(f"额外奖励：{_item_text(ctx, run['reward_items'])}。")
    lines.append("两季收获、交付凭证、押金退还与奖励已一并结算。")
    reply = Reply(TITLE + " · 已交付", tuple(lines), (TITLE, "灵宠背包", "灵宠目标"))
    return _record(ctx, _validate(ctx, run), reply)


def abandon(ctx: Context, contract_id: int) -> Reply:
    run = _active_contract(ctx, contract_id)
    run["status"] = "abandoned"
    run["updated_at"] = ctx.now
    reply = Reply(TITLE + " · 已放弃", (
        f"契约 {contract_id} 已放弃；绑定田位与已收获产物保留，押金 {run['deposit']} 灵石不退。",
        "契约记录已保存，可继续使用灵田。",
    ), (TITLE, "灵宠灵田", "灵宠目标"))
    return _record(ctx, _validate(ctx, run), reply)


def history(ctx: Context, argument: str) -> Reply:
    try:
        entries = ctx.repo.farm_contract_history(ctx.user_id)
        entries = [{"snapshot": _validate(ctx, entry["snapshot"])} for entry in entries]
    except (sqlite3.DatabaseError, TypeError, ValueError, KeyError) as exc:
        raise GameError("农契历史损坏，未修改任何资源；请联系管理员核对存档。") from exc
    page = paginate(entries, argument, TITLE + "记录", f"{TITLE} 记录", PAGE_SIZE)
    lines = [f"第 {page.number}/{page.total} 页 · 共 {len(entries)} 份农契。"]
    for entry in page.entries:
        run = entry["snapshot"]
        status = {"active": "进行中", "completed": "已交付", "abandoned": "已放弃"}[run["status"]]
        crops = " → ".join(ctx.content.crops[crop_id].name for crop_id in run["crops"])
        actual = "、".join(
            f"第{season['number']}季{ctx.content.crops[season['crop_id']].name}"
            for season in run["seasons"]
        ) or "尚无成熟收获"
        lines.extend((
            f"契约 {run['contract_id']} · {run['plan_name']} · {status} · 田位 {run['plot']}",
            f"计划：{crops} · 实收：{actual}",
            f"押金 {run['deposit']} · 交付 {_item_text(ctx, run['delivery'])}",
        ))
    return Reply(f"{TITLE}记录 {page.number}/{page.total}", tuple(lines), (*page.navigation, TITLE))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "签订" and len(parts) == 3:
        plan = _plan_by_name(ctx, parts[1])
        plot = quantity(parts[2], farming.PLOT_COUNT)
        return sign(ctx, plan.name, plot)
    if parts[0] == "交付" and len(parts) == 2:
        return deliver(ctx, quantity(parts[1], 9_223_372_036_854_775_807))
    if parts[0] == "放弃" and len(parts) == 2:
        return abandon(ctx, quantity(parts[1], 9_223_372_036_854_775_807))
    if parts[0] == "记录" and len(parts) <= 2:
        return history(ctx, parts[1] if len(parts) == 2 else "")
    raise GameError(f"格式：{TITLE} [签订 契约名 田位|交付 契约号|放弃 契约号|记录 页码]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = active(ctx, user_id)
    if run is None:
        latest = _latest(ctx, user_id)
        if latest is None:
            return "农契：暂无进行中的两季轮作"
        status = "已交付" if latest["status"] == "completed" else "已放弃"
        return f"农契：最近契约 {latest['contract_id']} {status}"
    if len(run["seasons"]) == 2:
        return f"农契：契约 {run['contract_id']} 两季完成 · 可交付"
    return f"农契：契约 {run['contract_id']} · 已完成 {len(run['seasons'])}/2 季"


__all__ = ["TITLE", "active", "advance_on_harvest", "catalog", "dispatch", "objective_line"]
