"""灵宠好友: a player-managed friendship edge with a request handshake.

Explicit friendships coexist with the shared-battle and shared-team eligibility
used by gifting, fostering and mail:

* ``friend_requests`` holds a pending one-sided handshake (``from_id`` →
  ``to_id``) that expires on read, exactly like ``team_requests``;
* ``friend_links`` holds the accepted relationship as **one normalized row per
  pair** (``user_low < user_high``), so "A and B are friends" cannot be recorded
  twice or half-recorded;
* ``linked()`` is the single membership predicate, and ``gifting.are_friends``
  accepts either an accepted link or the legacy derived edge.

Neither table carries progress, rewards or battle state: 结交 moves no stones
and no items, writes no battle record and advances no quest, achievement, daily
or weekly counter. Every write resolves both players before touching a row, so a
refused action leaves the database byte-for-byte unchanged.
"""

import re

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from ..utils.time import beijing_day

PAGE_SIZE = 4


def rule(ctx: Context):
    return ctx.content.rules.friend


def _pair(first: str, second: str) -> tuple[str, str]:
    """Normalized key for a friendship: the two ids in a fixed order."""
    return (first, second) if first < second else (second, first)


def linked(ctx: Context, first: str, second: str) -> bool:
    """True when the two players have an accepted friendship."""
    if first == second:
        return False
    low, high = _pair(first, second)
    return ctx.repo.conn.execute(
        "SELECT 1 FROM friend_links WHERE user_low=? AND user_high=? LIMIT 1",
        (low, high),
    ).fetchone() is not None


def friends(ctx: Context, user_id: str | None = None) -> list:
    """Accepted friends of the player, oldest first."""
    owner = user_id or ctx.user_id
    return ctx.repo.conn.execute(
        "SELECT * FROM friend_links WHERE user_low=? OR user_high=? ORDER BY created_at, user_high",
        (owner, owner),
    ).fetchall()


def friend_count(ctx: Context, user_id: str) -> int:
    """Both columns must be counted, or half the roster goes uncharged."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM friend_links WHERE user_low=? OR user_high=?",
        (user_id, user_id),
    ).fetchone()
    return int(row["n"])


def other_side(row, user_id: str) -> str:
    """The friend's id inside a normalized link row."""
    return row["user_high"] if row["user_low"] == user_id else row["user_low"]


def sweep_expired(ctx: Context) -> int:
    """Drop every overdue request; a stale request never blocks a fresh one."""
    cursor = ctx.repo.conn.execute(
        "DELETE FROM friend_requests WHERE expires_at<=?", (ctx.now,),
    )
    return cursor.rowcount if cursor.rowcount > 0 else 0


def incoming(ctx: Context, user_id: str | None = None) -> list:
    owner = user_id or ctx.user_id
    return ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE to_id=? AND expires_at>? ORDER BY created_at, from_id",
        (owner, ctx.now),
    ).fetchall()


def outgoing(ctx: Context, user_id: str | None = None) -> list:
    owner = user_id or ctx.user_id
    return ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE from_id=? AND expires_at>? ORDER BY created_at, to_id",
        (owner, ctx.now),
    ).fetchall()


def _uid_label(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return player.uid_label if player is not None else "已离去的修士"


def _uid(ctx: Context, user_id: str) -> str:
    """The public UID of a player, as typed back into a command."""
    player = ctx.repo.player(user_id)
    return str(player.uid) if player is not None else ""


def _target(ctx: Context, arg: str, player):
    """Resolve the other player, rejecting self and unknown UIDs."""
    text = arg.strip()
    if not text:
        raise GameError("请填写对方的 UID。")
    if " " in text.split("UID")[-1].strip():
        raise GameError("请只填写一个 UID，例如 灵宠好友 添加 10001。")
    target = ctx.repo.player_by_uid(text)
    if target is None:
        raise GameError("未找到该 UID 对应的修士。")
    if target.user_id == player.user_id:
        raise GameError("不能把自己加为好友。")
    return target


def _pending(ctx: Context, first: str, second: str):
    """A pending request in either direction, or None."""
    return ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE expires_at>? AND"
        " ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?)) LIMIT 1",
        (ctx.now, first, second, second, first),
    ).fetchone()


def _hours(ctx: Context) -> int:
    return rule(ctx).request_hours


def page(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠好友",
            (
                "尚未结契，先完成领养，才能结交道友。",
                "好友之间可以赠送灵石与材料、寄养灵宠，也可以互通书信。",
                "成为好友需要一方发起、一方同意，双方都可见。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sweep_expired(ctx)
    player = ctx.player()
    rules = rule(ctx)
    roster = friends(ctx)
    asks = incoming(ctx)
    sent = outgoing(ctx)
    paged = paginate(roster, arg, "灵宠好友", "灵宠好友", PAGE_SIZE)
    lines = [
        f"好友 {len(roster)}/{rules.max_friends} 位 · 第 {paged.number}/{paged.total} 页"
        f" · 待我处理 {len(asks)} 条 · 我发出的 {len(sent)} 条"
        f" · 申请 {rules.request_hours} 小时内有效。",
    ]
    links = []
    if roster:
        for row in paged.entries:
            other = other_side(row, player.user_id)
            days = max(0, (ctx.now - int(row["created_at"])) // 86400)
            lines.append(f"{_uid_label(ctx, other)} · 结交于 {beijing_day(int(row['created_at']))}（{days} 天前）")
            links.append(InlineCommand(len(lines) - 1, "解除", f"灵宠好友 解除 {_uid(ctx, other)}"))
    else:
        lines.append("暂时还没有好友。用 灵宠好友 添加 <UID> 向其他修士发起结交。")
    lines.append("添加好友：灵宠好友 添加 <UID>。")
    return Reply(
        "灵宠好友",
        tuple(lines),
        (*paged.navigation, "灵宠好友 申请", "灵宠目标")[:4],
        tuple(links),
    )


def requests_page(ctx: Context, arg: str = "") -> Reply:
    """The handshake inbox: who wants in, and who I am still waiting on."""
    sweep_expired(ctx)
    player = ctx.player()
    rules = rule(ctx)
    asks = incoming(ctx)
    sent = outgoing(ctx)
    entries = [("in", row) for row in asks] + [("out", row) for row in sent]
    paged = paginate(entries, arg, "灵宠好友 申请", "灵宠好友 申请", PAGE_SIZE)
    lines = [
        f"待我处理 {len(asks)} 条 · 我发出的 {len(sent)} 条 · 第 {paged.number}/{paged.total} 页"
        f" · 申请 {rules.request_hours} 小时内有效。",
    ]
    links = []
    for direction, row in paged.entries:
        other_id = row["from_id"] if direction == "in" else row["to_id"]
        if direction == "in":
            lines.append(f"{_uid_label(ctx, other_id)} 想与你结交")
            index = len(lines) - 1
            links.append(InlineCommand(index, "同意", f"灵宠好友 同意 {_uid(ctx, other_id)}"))
            links.append(InlineCommand(index, "拒绝", f"灵宠好友 拒绝 {_uid(ctx, other_id)}"))
        else:
            lines.append(f"等待 {_uid_label(ctx, other_id)} 回应")
            links.append(InlineCommand(len(lines) - 1, "撤回", f"灵宠好友 撤回 {_uid(ctx, other_id)}"))
    if not entries:
        lines.append("没有待处理的结交申请。")
    lines.append("发起结交：灵宠好友 添加 <UID>。")
    return Reply(
        "灵宠好友 申请",
        tuple(lines),
        (*paged.navigation, "灵宠好友", "灵宠目标")[:4],
        tuple(links),
    )


def add(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    target = _target(ctx, arg, player)
    rules = rule(ctx)
    sweep_expired(ctx)
    if linked(ctx, player.user_id, target.user_id):
        raise GameError(f"{target.uid_label} 已经是你的好友了。")
    pending = _pending(ctx, player.user_id, target.user_id)
    if pending is not None:
        if pending["from_id"] == player.user_id:
            raise GameError("已有一条等待对方回应的结交申请，撤回后才能重发。")
        raise GameError(f"{target.uid_label} 已经向你发起结交，请在 灵宠好友 里同意或拒绝。")
    if friend_count(ctx, player.user_id) >= rules.max_friends:
        raise GameError(f"好友已达 {rules.max_friends} 位上限，请先解除部分好友。")
    if friend_count(ctx, target.user_id) >= rules.max_friends:
        raise GameError(f"{target.uid_label} 的好友已满，无法再接受结交。")
    ctx.repo.conn.execute(
        "INSERT INTO friend_requests(from_id, to_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (player.user_id, target.user_id, ctx.now, ctx.now + rules.request_hours * 3600),
    )
    return Reply("结交申请已发出", (
        f"已向 {target.uid_label} 发起好友申请。",
        f"{rules.request_hours} 小时内对方可在 灵宠好友 里同意或拒绝。",
        "对方同意后，你们就能互相赠送、寄养与寄信。",
    ), ("灵宠好友", "灵宠目标"))


def accept(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    target = _target(ctx, arg, player)
    rules = rule(ctx)
    sweep_expired(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE from_id=? AND to_id=? AND expires_at>?",
        (target.user_id, player.user_id, ctx.now),
    ).fetchone()
    if row is None:
        raise GameError("没有来自该道友的结交申请，请查看 灵宠好友。")
    if linked(ctx, player.user_id, target.user_id):
        raise GameError("你们已经是好友了。")
    if friend_count(ctx, player.user_id) >= rules.max_friends:
        raise GameError(f"好友已达 {rules.max_friends} 位上限，请先解除部分好友。")
    if friend_count(ctx, target.user_id) >= rules.max_friends:
        raise GameError(f"{target.uid_label} 的好友已满，无法再结交。")
    low, high = _pair(player.user_id, target.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO friend_links(user_low, user_high, created_at) VALUES (?, ?, ?)",
        (low, high, ctx.now),
    )
    ctx.repo.conn.execute(
        "DELETE FROM friend_requests WHERE from_id=? AND to_id=?",
        (target.user_id, player.user_id),
    )
    return Reply("已是好友", (
        f"你与 {target.uid_label} 结为好友。",
        "现在可以互相赠送灵石与材料、寄养灵宠、互通书信。",
        f"好友 {friend_count(ctx, player.user_id)}/{rules.max_friends} 位。",
    ), ("灵宠好友", "灵宠赠送", "灵宠信箱"))


def reject(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    target = _target(ctx, arg, player)
    sweep_expired(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE from_id=? AND to_id=? AND expires_at>?",
        (target.user_id, player.user_id, ctx.now),
    ).fetchone()
    if row is None:
        raise GameError("没有来自该道友的结交申请，请查看 灵宠好友。")
    ctx.repo.conn.execute(
        "DELETE FROM friend_requests WHERE from_id=? AND to_id=?",
        (target.user_id, player.user_id),
    )
    return Reply("已拒绝结交", (
        f"已拒绝 {target.uid_label} 的结交申请。",
        "对方之后仍可再次发起，你也可以主动添加他人。",
    ), ("灵宠好友", "灵宠目标"))


def withdraw(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    target = _target(ctx, arg, player)
    sweep_expired(ctx)
    row = ctx.repo.conn.execute(
        "SELECT * FROM friend_requests WHERE from_id=? AND to_id=? AND expires_at>?",
        (player.user_id, target.user_id, ctx.now),
    ).fetchone()
    if row is None:
        raise GameError("没有发给该道友的待回应申请，请查看 灵宠好友。")
    ctx.repo.conn.execute(
        "DELETE FROM friend_requests WHERE from_id=? AND to_id=?",
        (player.user_id, target.user_id),
    )
    return Reply("申请已撤回", (
        f"已撤回发给 {target.uid_label} 的结交申请。",
    ), ("灵宠好友", "灵宠目标"))


def remove(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    target = _target(ctx, arg, player)
    if not linked(ctx, player.user_id, target.user_id):
        raise GameError("你们还不是好友，请查看 灵宠好友。")
    low, high = _pair(player.user_id, target.user_id)
    ctx.repo.conn.execute(
        "DELETE FROM friend_links WHERE user_low=? AND user_high=?", (low, high),
    )
    return Reply("已解除好友", (
        f"你与 {target.uid_label} 解除了好友关系。",
        "双方名册同步移除，之前的战绩与队伍不受影响。",
    ), ("灵宠好友", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if head == "申请":
        return requests_page(ctx, rest)
    if head == "添加":
        return add(ctx, rest)
    if head == "同意":
        return accept(ctx, rest)
    if head == "拒绝":
        return reject(ctx, rest)
    if head == "撤回":
        return withdraw(ctx, rest)
    if head == "解除":
        return remove(ctx, rest)
    if re.fullmatch(r"[0-9]+", head):
        return page(ctx, head)
    raise GameError(
        "格式：灵宠好友 [页码|申请 [页码]|添加 <UID>|同意 <UID>|拒绝 <UID>|撤回 <UID>|解除 <UID>]。"
    )


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "好友：尚未结契"
    rules = rule(ctx)
    return (
        f"好友：{friend_count(ctx, user_id)}/{rules.max_friends} 位"
        f" · 待处理 {len(incoming(ctx, user_id))} 条"
    )


__all__ = [
    "accept", "add", "dispatch", "friend_count", "friends", "incoming", "linked", "objective_line",
    "other_side", "outgoing", "page", "reject", "remove", "requests_page", "sweep_expired", "withdraw",
]
