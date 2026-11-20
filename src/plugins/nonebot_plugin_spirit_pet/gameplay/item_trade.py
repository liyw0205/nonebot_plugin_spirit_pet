"""Friend-only bilateral exchanges with durable escrow and atomic settlement."""

import sqlite3
from datetime import datetime
from hashlib import sha256

from pydantic import ValidationError

from ..application.context import Context
from ..domain.item_trade_state import (
    ItemTrade, MAX_TRADE_ITEMS, MAX_TRADE_STONES, TRADE_SECONDS, TradeAsset,
)
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import BEIJING
from . import friends
from .gifting import GIFTABLE_KINDS

TITLE = "灵宠换物"
PAGE_SIZE = 5
STATES = {
    "pending": "待对方确认", "finished": "已成交", "cancelled": "已取消并退款",
    "rejected": "已拒绝并退款", "expired": "已过期并退款",
}
FORMAT = "灵宠换物 预览 好友UID 付出物品 数量 索取物品 数量"


def _validate(ctx: Context, data: dict | None) -> ItemTrade | None:
    if data is None:
        return None
    try:
        run = ItemTrade.model_validate(data)
    except (ValidationError, TypeError, ValueError) as exc:
        raise GameError("换物快照损坏，资源与进度保留；请联系管理员核对存档。") from exc
    if any(asset.item is not None and asset.item not in ctx.content.items for asset in (run.offer, run.request)):
        raise GameError("换物快照中的物品内容缺失，托管保留；请联系管理员核对存档。")
    return run


def _load(ctx: Context, owner: str, trade_id: int | None = None) -> ItemTrade | None:
    try:
        data = ctx.repo.item_trade(owner, trade_id)
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("换物记录损坏，资源与进度保留；请联系管理员核对存档。") from exc
    return _validate(ctx, data)


def active(ctx: Context, user_id: str | None = None) -> ItemTrade | None:
    run = _load(ctx, user_id or ctx.user_id)
    return run if run is not None and run.status == "pending" else None


def _text(asset: TradeAsset) -> str:
    return f"{asset.name} ×{asset.amount}"


def _asset(ctx: Context, name: str, amount: str) -> TradeAsset:
    if name == "灵石":
        return TradeAsset(item=None, name=name, amount=quantity(amount, MAX_TRADE_STONES))
    item = named(ctx.content.items, name)
    if item.kind not in GIFTABLE_KINDS:
        raise GameError("换物仅限消耗品、材料或灵石，不能交换宠物、装备、灵卵、秘笈与破境丹。")
    return TradeAsset(item=item.id, name=item.name, amount=quantity(amount, MAX_TRADE_ITEMS))


def _stock(ctx: Context, owner: str, asset: TradeAsset) -> int:
    if asset.item is None:
        return ctx.player(owner).stones
    return ctx.repo.inventory(owner).get(asset.item, 0)


def _require_stock(ctx: Context, owner: str, asset: TradeAsset) -> None:
    if asset.item is not None and ctx.content.items[asset.item].kind not in GIFTABLE_KINDS:
        raise GameError("该物品当前不可换物，资源保留；发起者可取消退款。")
    if _stock(ctx, owner, asset) < asset.amount:
        raise GameError(f"{asset.name}不足：需要 {asset.amount}，当前 {_stock(ctx, owner, asset)}。")


def _take(ctx: Context, owner: str, asset: TradeAsset) -> None:
    _require_stock(ctx, owner, asset)
    if asset.item is None:
        ctx.player(owner).stones -= asset.amount
    else:
        ctx.repo.consume_item(owner, asset.item, asset.amount)


def _give(ctx: Context, owner: str, asset: TradeAsset) -> None:
    ctx.player(owner)
    if asset.item is None:
        ctx.player(owner).stones += asset.amount
    else:
        ctx.repo.add_item(owner, asset.item, asset.amount)


def _record(ctx: Context, run: ItemTrade, reply: Reply) -> Reply:
    ctx.repo.record_item_trade(ctx.operation_id, ctx.user_id, ctx.now, run.model_dump(), reply)
    return reply


def _terms(ctx: Context, parts: list[str]):
    if len(parts) != 5:
        raise GameError(f"格式：{FORMAT}；确认后使用相同参数的 发起。")
    ctx.player()
    target = friends._target(ctx, parts[0], ctx.player())
    if not friends.linked(ctx, ctx.user_id, target.user_id):
        raise GameError("换物需要双方已经成为好友，请先完成结交。")
    offer, request = _asset(ctx, *parts[1:3]), _asset(ctx, *parts[3:5])
    if offer.item == request.item:
        raise GameError("付出与索取必须是不同资产，请勿用相同物品换物。")
    for owner in (ctx.user_id, target.user_id):
        if active(ctx, owner):
            raise GameError("你或对方已有待处理换物，请先成交、拒绝、取消或到期退款。")
        latest = _load(ctx, owner)
        if latest is not None and ctx.now < latest.updated_at:
            raise GameError("系统时间早于最近换物操作，请等待时钟恢复。")
    _require_stock(ctx, ctx.user_id, offer)
    return target, offer, request


def preview(ctx: Context, parts: list[str]) -> Reply:
    target, offer, request = _terms(ctx, parts)
    command = f"{TITLE} 发起 {target.uid} {offer.name} {offer.amount} {request.name} {request.amount}"
    return Reply(f"{TITLE} · 预览", (
        f"向 {target.uid_label} 付出 {_text(offer)}，索取 {_text(request)}。",
        "确认发起才托管你的付出；对方同意后双方一次成交。",
        "有效 24 小时；拒绝、取消或过期处理会全额退回托管，不收手续费。",
    ), (command, TITLE, "灵宠背包", "灵宠好友"))


def start(ctx: Context, parts: list[str]) -> Reply:
    target, offer, request = _terms(ctx, parts)
    trade_id = max(1, int(sha256(f"trade:{ctx.user_id}:{ctx.operation_id}".encode()).hexdigest()[:14], 16))
    run = ItemTrade(
        trade_id=trade_id, owner_id=ctx.user_id, target_id=target.user_id,
        offer=offer, request=request, status="pending", started_at=ctx.now,
        expires_at=ctx.now + TRADE_SECONDS, updated_at=ctx.now,
    )
    _take(ctx, ctx.user_id, offer)
    detail = _detail(ctx, run)
    return _record(ctx, run, Reply(detail.title, (
        f"邀约 {trade_id} 已发起，已托管 {_text(offer)}。", *detail.lines,
    ), detail.commands, detail.inline_commands))


def _detail(ctx: Context, run: ItemTrade) -> Reply:
    mine = run.owner_id == ctx.user_id
    give, receive = (run.offer, run.request) if mine else (run.request, run.offer)
    other = ctx.player(run.target_id if mine else run.owner_id)
    expired = run.status == "pending" and ctx.now >= run.expires_at
    status = "已到期，待退款" if expired else STATES[run.status]
    stamp = datetime.fromtimestamp(run.expires_at, BEIJING).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"邀约 {run.trade_id} · {status} · 对方 {other.uid_label}。",
        f"你的付出：{_text(give)}；你的所得：{_text(receive)}。",
        f"截止 {stamp}（北京时间）；发起者付出已托管，确认者同意时才扣款。",
    ]
    commands = []
    if run.status == "pending":
        if expired:
            commands.append(f"{TITLE} 退款 {run.trade_id}")
        elif mine:
            commands.append(f"{TITLE} 取消 {run.trade_id}")
            lines.append("等待对方本人确认；取消后已托管资产全额退回。")
        else:
            reason = "" if friends.linked(ctx, run.owner_id, run.target_id) else "双方已解除好友"
            if not reason and _stock(ctx, ctx.user_id, run.request) < run.request.amount:
                reason = f"{run.request.name}不足"
            if not reason:
                commands.append(f"{TITLE} 同意 {run.trade_id}")
            else:
                lines.append(f"暂不可同意：{reason}；可补齐资源或拒绝退款。")
            commands.append(f"{TITLE} 拒绝 {run.trade_id}")
    elif run.status == "finished":
        lines.append(f"已付出 {_text(give)}，已收到 {_text(receive)}；无额外奖励。")
    else:
        lines.append(f"已退回发起者 {_text(run.offer)}；受邀者没有扣款。")
    commands.extend((f"{TITLE} 记录", "灵宠背包", TITLE))
    return Reply(f"{TITLE} · 邀约 {run.trade_id}", tuple(lines), tuple(commands[:4]))


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("先领养伙伴，再与好友约定互换消耗品、材料或灵石。",),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = active(ctx)
    if run is not None:
        return _detail(ctx, run)
    return Reply(TITLE, (
        "当前没有待处理换物；每人同时只能参与一份邀约。",
        f"每边限一种资产：材料/消耗品 1-{MAX_TRADE_ITEMS} 件，灵石 1-{MAX_TRADE_STONES}。",
        "发起时托管付出，好友同意时一次交换；24 小时后可处理退款。",
        f"{FORMAT}。",
    ), (f"{TITLE} 预览 ", f"{TITLE} 记录", "灵宠好友", "灵宠背包"))


def history(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) > 1:
        raise GameError(f"格式：{TITLE} 记录 页码。")
    number = quantity(parts[0], 999) if parts else 1
    count, rows = ctx.repo.item_trade_history(ctx.user_id, number, PAGE_SIZE)
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    if number > pages:
        raise GameError(f"换物记录共 {pages} 页。")
    lines = [f"共 {count} 份已处理邀约 · 第 {number}/{pages} 页。"]
    links = []
    for data in rows:
        run = _validate(ctx, data)
        mine = ctx.user_id == run.owner_id
        give, receive = (run.offer, run.request) if mine else (run.request, run.offer)
        result = f"付出 {_text(give)}，得到 {_text(receive)}" if run.status == "finished" else (
            f"退回 {_text(run.offer)}" if mine else "未扣款"
        )
        lines.append(f"邀约 {run.trade_id} · {STATES[run.status]} · {result}。")
        links.append(InlineCommand(len(lines) - 1, "查看详情", f"{TITLE} 详情 {run.trade_id}"))
    commands = []
    if number > 1:
        commands.append(f"{TITLE} 记录 {number - 1}")
    if number < pages:
        commands.append(f"{TITLE} 记录 {number + 1}")
    return Reply(f"{TITLE} · 记录", tuple(lines), (*commands, TITLE, "灵宠背包"), tuple(links))


def resolve(ctx: Context, action: str, value: str) -> Reply:
    ctx.player()
    run = _load(ctx, ctx.user_id, quantity(value, 9_223_372_036_854_775_807))
    if run is None:
        raise GameError("未找到属于你的换物邀约。")
    if action == "详情":
        return _detail(ctx, run)
    if run.status != "pending":
        raise GameError("这份换物已经处理，请查看原邀约记录。")
    if action in {"同意", "拒绝"} and ctx.user_id != run.target_id:
        raise GameError("只有受邀好友本人可以同意或拒绝。")
    if action == "取消" and ctx.user_id != run.owner_id:
        raise GameError("只有发起者可以取消邀约。")
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近换物操作，请等待时钟恢复。")
    expired = ctx.now >= run.expires_at
    if action == "退款" and not expired:
        raise GameError("邀约尚未到期，发起者可取消，受邀者可拒绝。")
    if expired or action in {"拒绝", "取消", "退款"}:
        _give(ctx, run.owner_id, run.offer)
        status = "expired" if expired else ("rejected" if action == "拒绝" else "cancelled")
    else:
        if not friends.linked(ctx, run.owner_id, run.target_id):
            raise GameError("双方已解除好友，不能成交；可拒绝或取消退款。")
        _take(ctx, run.target_id, run.request)
        _give(ctx, run.target_id, run.offer)
        _give(ctx, run.owner_id, run.request)
        status = "finished"
    ended = ItemTrade.model_validate({**run.model_dump(), "status": status, "updated_at": ctx.now})
    return _record(ctx, ended, _detail(ctx, ended))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return page(ctx)
    action, rest = parts[0], parts[1:]
    if action == "记录":
        return history(ctx, rest)
    if action == "预览":
        return preview(ctx, rest)
    if action == "发起":
        return start(ctx, rest)
    if action in {"详情", "同意", "拒绝", "取消", "退款"} and len(rest) == 1:
        return resolve(ctx, action, rest[0])
    raise GameError(f"格式：{FORMAT}，或 {TITLE} 详情/同意/拒绝/取消/退款 邀约号，或 记录 页码。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = active(ctx, user_id)
    if run is None:
        return "换物：没有待处理邀约"
    status = "已到期，待退款" if ctx.now >= run.expires_at else (
        "等待好友确认" if run.owner_id == user_id else "待你确认"
    )
    return f"换物：邀约 {run.trade_id} · {status}"
