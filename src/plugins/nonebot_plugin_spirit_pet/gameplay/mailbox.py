"""灵宠信箱: asynchronous cross-player mail with escrowed attachments.

灵宠赠送 moves items only while both players are online and is capped at three
gifts a day; the market escrows items but trades them for stones. A mailbox is the
missing shape: hand a stack or some stones to another修士 together with a short
message, and let them pick it up whenever they next open the game.

Escrow follows the market convention: the attachment leaves the sender's bag the
moment the mail is written, and exactly one guarded transition can pay it out.

* ``active`` — held in escrow, claimable by the recipient, recallable by the sender
* ``claimed`` — paid into the recipient's bag; the row is the permanent receipt
* ``recalled`` — the sender took it back before it was claimed
* ``returned`` — it expired unclaimed and went back to the sender

Every transition is guarded by ``state='active'``, so one escrow can never be paid
twice. Expiry is lazy: whichever mailbox is opened next returns overdue mail, which
keeps the feature independent of a background job. The same friendship edge that
gates 灵宠赠送 gates posting (a shared battle or team history).
"""

import re

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .gifting import are_friends

PAGE_SIZE = 5
OUTBOX_PAGE_SIZE = 5
MAX_BODY = 60
STONES_LABEL = "灵石"


def rule(ctx: Context):
    return ctx.content.rules.mail


def _today(ctx: Context) -> str:
    return beijing_day(ctx.now)


def _sent_today(ctx: Context, user_id: str) -> int:
    rows = ctx.repo.conn.execute(
        "SELECT created_at FROM mail_messages WHERE sender_id=?", (user_id,),
    )
    today = _today(ctx)
    return sum(1 for row in rows if beijing_day(row["created_at"]) == today)


def inbox(ctx: Context, user_id: str | None = None) -> list:
    """Active mail addressed to the player, oldest first."""
    return ctx.repo.conn.execute(
        "SELECT * FROM mail_messages WHERE recipient_id=? AND state='active'"
        " ORDER BY message_id",
        (user_id or ctx.user_id,),
    ).fetchall()


def outbox(ctx: Context, user_id: str | None = None) -> list:
    """Active mail the player sent and can still recall."""
    return ctx.repo.conn.execute(
        "SELECT * FROM mail_messages WHERE sender_id=? AND state='active'"
        " ORDER BY message_id DESC",
        (user_id or ctx.user_id,),
    ).fetchall()


def sweep_expired(ctx: Context) -> int:
    """Return every overdue unclaimed mail to its sender; pay each row once."""
    rows = ctx.repo.conn.execute(
        "SELECT * FROM mail_messages WHERE state='active' AND expires_at<=?", (ctx.now,),
    ).fetchall()
    for row in rows:
        closed = ctx.repo.conn.execute(
            "UPDATE mail_messages SET state='returned', closed_at=? WHERE message_id=? AND state='active'",
            (ctx.now, row["message_id"]),
        )
        if closed.rowcount != 1:
            continue
        _pay(ctx, row["sender_id"], row)
    return len(rows)


def _pay(ctx: Context, user_id: str, row) -> None:
    """Deliver one escrowed attachment, bypassing `grant` (no exp, no idle pet)."""
    if row["kind"] == "stones":
        player = ctx.repo.player(user_id)
        if player is not None:
            player.stones += int(row["stones"])
        return
    ctx.repo.add_item(user_id, row["item_id"], int(row["quantity"]))


def _attachment_text(ctx: Context, row) -> str:
    if row["kind"] == "stones":
        return f"{STONES_LABEL} {row['stones']}"
    item = ctx.content.items.get(row["item_id"])
    name = item.name if item is not None else row["item_id"]
    return f"{name} ×{row['quantity']}"


def _uid_label(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return player.uid_label if player is not None else "已注销的修士"


def _remaining_days(ctx: Context, row) -> int:
    return max(0, (int(row["expires_at"]) - ctx.now + 86399) // 86400)


def _parse_send(ctx: Context, arg: str) -> tuple:
    parts = arg.split(maxsplit=3)
    if len(parts) < 4:
        raise GameError("格式：灵宠信箱 邮寄 <UID> <物品名|灵石> <数量> <留言>。")
    uid_text, name, amount_text, body = parts
    body = body.strip()
    if not body:
        raise GameError("请写下留言内容。")
    if len(body) > MAX_BODY:
        raise GameError(f"留言最多 {MAX_BODY} 个字。")
    return uid_text, name, amount_text, body


def send(ctx: Context, arg: str) -> Reply:
    uid_text, name, amount_text, body = _parse_send(ctx, arg)
    player = ctx.player()
    target = ctx.repo.player_by_uid(quantity(uid_text, 9_223_372_036_854_775_807))
    if target is None or target.user_id == player.user_id:
        raise GameError("请填写其他玩家的 UID。")
    if not are_friends(ctx, player.user_id, target.user_id):
        raise GameError("只能寄给好友、论剑或同队出现过的玩家，可用 灵宠好友 结交。")
    rules = rule(ctx)
    if _sent_today(ctx, player.user_id) >= rules.daily_limit:
        raise GameError(f"今日寄信已达 {rules.daily_limit} 封，明日 00:00（北京时间）再寄。")
    if len(inbox(ctx, target.user_id)) >= rules.inbox_capacity:
        raise GameError("对方信箱已满，请稍后再寄或提醒对方领取。")

    if name == STONES_LABEL:
        amount = quantity(amount_text, rules.max_stones)
        if player.stones < amount:
            raise GameError("灵石不足。")
        player.stones -= amount
        kind, stones, item_id, item_quantity = "stones", amount, None, 0
        attachment = f"{STONES_LABEL} {amount}"
    else:
        item = next((entry for entry in ctx.content.items.values() if entry.name == name), None)
        if item is None:
            raise GameError("未找到该物品，请检查名称。")
        if item.kind not in rules.kinds:
            raise GameError("信箱只能寄送材料与消耗品；装备、灵卵与秘笈不可邮寄。")
        amount = quantity(amount_text, rules.max_items)
        ctx.repo.consume_item(player.user_id, item.id, amount)
        kind, stones, item_id, item_quantity = "item", 0, item.id, amount
        attachment = f"{item.name} ×{amount}"

    cursor = ctx.repo.conn.execute(
        "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity, body,"
        " created_at, expires_at, state, closed_at, claimed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL)",
        (
            player.user_id, target.user_id, kind, stones, item_id, item_quantity, body,
            ctx.now, ctx.now + rules.days * 86400,
        ),
    )
    return Reply("信件已寄出", (
        f"已寄给 {target.uid_label}：{attachment}。",
        f"留言：{body}",
        f"{rules.days} 天内未领取会自动退回；在此之前可以收回。",
        f"今日已寄 {_sent_today(ctx, player.user_id)}/{rules.daily_limit} 封。",
    ), ("灵宠信箱", "灵宠信箱 寄件", "灵宠背包"))


def page(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠信箱",
            (
                "尚未结契，先完成领养，才能收寄信件。",
                "信箱把材料或灵石寄给好友或同队出现过的修士，对方上线后自取。",
                "没人领取的信件到期会自动退回寄件人。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sweep_expired(ctx)
    rows = inbox(ctx)
    rules = rule(ctx)
    paged = paginate(rows, arg, "灵宠信箱", "灵宠信箱", PAGE_SIZE)
    lines = [
        f"收件 {len(rows)}/{rules.inbox_capacity} 封 · 第 {paged.number}/{paged.total} 页"
        f" · 信件保存 {rules.days} 天。",
    ]
    links = []
    for row in paged.entries:
        lines.append(
            f"#{row['message_id']} {_uid_label(ctx, row['sender_id'])}：{_attachment_text(ctx, row)}"
            f" · 剩 {_remaining_days(ctx, row)} 天"
        )
        label = f"{row['body']}"
        lines.append(f"   留言：{label}")
        links.append(InlineCommand(
            len(lines) - 2, "领取", f"灵宠信箱 领取 {row['message_id']}",
        ))
    if not rows:
        lines.append("暂时没有未领取的信件。")
    else:
        links.append(InlineCommand(0, "全部领取", "灵宠信箱 一键领取"))
    lines.append("写一封信：灵宠信箱 邮寄 <UID> <物品名|灵石> <数量> <留言>。")
    return Reply("灵宠信箱", tuple(lines), (*paged.navigation, "灵宠信箱 寄件", "灵宠目标")[:4], tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise GameError("格式：灵宠信箱 领取 <信件编号>。")
    sweep_expired(ctx)
    message_id = int(text)
    row = ctx.repo.conn.execute(
        "SELECT * FROM mail_messages WHERE message_id=?", (message_id,),
    ).fetchone()
    if row is None or row["recipient_id"] != player.user_id or row["state"] != "active":
        raise GameError("没有可领取的信件，请查看 灵宠信箱。")
    closed = ctx.repo.conn.execute(
        "UPDATE mail_messages SET state='claimed', closed_at=?, claimed_at=? "
        "WHERE message_id=? AND state='active'",
        (ctx.now, ctx.now, message_id),
    )
    if closed.rowcount != 1:
        raise GameError("这封信刚刚已被领取或退回。")
    _pay(ctx, player.user_id, row)
    return Reply("信件已领取", (
        f"来自 {_uid_label(ctx, row['sender_id'])}：{_attachment_text(ctx, row)}。",
        f"留言：{row['body']}",
    ), ("灵宠信箱", "灵宠背包", "灵宠目标"))


def claim_all(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠信箱 一键领取。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠信箱", (
            "尚未结契，先完成领养，才能领取信件。",
            "一键领取只处理当前可领信件，不会补发已过期的附件。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    player = ctx.player()
    swept = sweep_expired(ctx)
    rows = inbox(ctx)
    if not rows:
        lines = ["没有可领取的信件，请查看 灵宠信箱。"]
        if swept:
            lines.append(f"本次已将 {swept} 封过期信件退回寄件人。")
        return Reply("灵宠信箱", tuple(lines), ("灵宠信箱", "灵宠背包"))
    paid, stones, item_count = [], 0, 0
    for row in rows:
        closed = ctx.repo.conn.execute(
            "UPDATE mail_messages SET state='claimed', closed_at=?, claimed_at=? "
            "WHERE message_id=? AND state='active'",
            (ctx.now, ctx.now, row["message_id"]),
        )
        if closed.rowcount != 1:
            continue
        _pay(ctx, player.user_id, row)
        paid.append(row)
        if row["kind"] == "stones":
            stones += int(row["stones"])
        else:
            item_count += int(row["quantity"])
    if not paid:
        return Reply("灵宠信箱", ("这些信件刚刚已被领取或退回，请刷新 灵宠信箱。",), ("灵宠信箱",))
    lines = [f"已领取 {len(paid)} 封。"]
    for row in paid[:8]:
        lines.append(
            f"#{row['message_id']} 来自 {_uid_label(ctx, row['sender_id'])}："
            f"{_attachment_text(ctx, row)}"
        )
    if len(paid) > 8:
        lines.append(f"另有 {len(paid) - 8} 封已一并领取。")
    lines.append(f"合计：灵石 +{stones} · 物品 {item_count} 件。")
    return Reply("信件已领取", tuple(lines), ("灵宠信箱", "灵宠背包", "灵宠目标"))


def outbox_page(ctx: Context, arg: str = "") -> Reply:
    ctx.player()
    sweep_expired(ctx)
    rows = outbox(ctx)
    paged = paginate(rows, arg, "灵宠信箱 寄件", "灵宠信箱 寄件", OUTBOX_PAGE_SIZE)
    lines = [f"未领取的信件 {len(rows)} 封 · 第 {paged.number}/{paged.total} 页。"]
    links = []
    for row in paged.entries:
        lines.append(
            f"#{row['message_id']} 致 {_uid_label(ctx, row['recipient_id'])}：{_attachment_text(ctx, row)}"
            f" · 剩 {_remaining_days(ctx, row)} 天"
        )
        lines.append(f"   留言：{row['body']}")
        links.append(InlineCommand(
            len(lines) - 2, "收回", f"灵宠信箱 收回 {row['message_id']}",
        ))
    if not rows:
        lines.append("寄出的信件都已被领取或退回。")
    return Reply("灵宠信箱 寄件", tuple(lines), (*paged.navigation, "灵宠信箱", "灵宠背包")[:4], tuple(links))


def recall(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise GameError("格式：灵宠信箱 收回 <信件编号>。")
    sweep_expired(ctx)
    message_id = int(text)
    row = ctx.repo.conn.execute(
        "SELECT * FROM mail_messages WHERE message_id=?", (message_id,),
    ).fetchone()
    if row is None or row["sender_id"] != player.user_id or row["state"] != "active":
        raise GameError("没有可收回的信件，请查看 灵宠信箱 寄件。")
    closed = ctx.repo.conn.execute(
        "UPDATE mail_messages SET state='recalled', closed_at=? "
        "WHERE message_id=? AND state='active'",
        (ctx.now, message_id),
    )
    if closed.rowcount != 1:
        raise GameError("这封信刚刚已被领取，无法收回。")
    _pay(ctx, player.user_id, row)
    return Reply("信件已收回", (
        f"已从 {_uid_label(ctx, row['recipient_id'])} 的信箱收回：{_attachment_text(ctx, row)}。",
        "留言随信件一并作废。",
    ), ("灵宠信箱", "灵宠背包", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if re.fullmatch(r"[0-9]+", head):
        return page(ctx, head)
    if head == "邮寄":
        return send(ctx, rest)
    if head == "领取":
        return claim(ctx, rest)
    if head == "一键领取":
        return claim_all(ctx, rest)
    if head == "寄件":
        return outbox_page(ctx, rest)
    if head == "收回":
        return recall(ctx, rest)
    raise GameError("格式：灵宠信箱 [页码|邮寄 <UID> <物品名|灵石> <数量> <留言>|领取 <编号>|一键领取|寄件|收回 <编号>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "信箱：尚未结契"
    rows = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM mail_messages WHERE recipient_id=? AND state='active'",
        (user_id,),
    ).fetchone()
    waiting = int(rows["n"])
    sent = len(outbox(ctx, user_id))
    return f"信箱：待领 {waiting} 封 · 寄出未领 {sent} 封"


__all__ = [
    "claim", "claim_all", "dispatch", "inbox", "objective_line", "outbox", "outbox_page", "page", "recall",
    "send", "sweep_expired",
]
