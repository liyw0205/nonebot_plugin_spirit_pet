"""灵宠约战: an asynchronous spar request, settled when the other side answers.

``灵宠切磋 <UID>`` needs both players in the same room at the same time: it fights
immediately with whatever lineups both have right now. In practice two friends are
rarely online together, so in practice nobody spars.

A request is a one-row handshake in ``quest_progress`` — on the *target's* row,
``spar_req_<challenger user_id>`` whose ``progress`` is the expiry timestamp. Nothing
about either lineup is copied or frozen: when the target answers, the fight uses both
lineups as they stand at that moment, exactly like ``灵宠切磋``. That keeps the promise
of the synchronous version (a live mirror match, no resources spent, no season points)
while removing the requirement that both players be present.

Refusals — nobody home, expired, no lineup, pets away — never write. An expired request
is simply ignored by every read, so no cleanup job is needed.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .arena.battles import spar_fight

PREFIX = "spar_req_"
TITLE = "灵宠约战"


def rule(ctx: Context):
    return ctx.content.rules.spar_request


def _key(user_id: str) -> str:
    return f"{PREFIX}{user_id}"


def _set(ctx: Context, owner: str, from_id: str, until: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (owner, _key(from_id), until),
    )


def _drop(ctx: Context, owner: str, from_id: str) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?", (owner, _key(from_id)),
    )


def _uid(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return str(player.uid) if player is not None else "已离去的修士"


def _hours(seconds: int) -> str:
    if seconds <= 0:
        return "已过期"
    hours = seconds // 3600
    return f"{hours} 小时" if hours else "不足 1 小时"


def incoming(ctx: Context, user_id: str | None = None) -> list[tuple[str, int]]:
    """``(challenger user_id, expiry)`` for every live request aimed at this player."""
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{PREFIX}%"),
    ).fetchall()
    found = []
    for row in rows:
        until = int(row["progress"])
        if until <= ctx.now:
            continue
        found.append((row["quest_id"][len(PREFIX):], until))
    return sorted(found, key=lambda item: item[1])


def outgoing(ctx: Context, user_id: str | None = None) -> list[tuple[str, int]]:
    """``(target user_id, expiry)`` for every live request this player has sent."""
    me = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT user_id, progress FROM quest_progress WHERE quest_id=? AND progress>?",
        (_key(me), ctx.now),
    ).fetchall()
    return sorted(((row["user_id"], int(row["progress"])) for row in rows), key=lambda item: item[1])


def _other(ctx: Context, arg: str):
    text = arg.strip()
    if not text:
        raise GameError(f"格式：{TITLE} <UID>，或 {TITLE} 应战|撤回 <UID>。")
    target = ctx.repo.player_by_uid(text)
    if target is None:
        raise GameError("没有找到这位玩家，请填写有效的 UID。")
    if target.user_id == ctx.user_id:
        raise GameError("不能向自己发起对战。")
    return target


def send(ctx: Context, arg: str) -> Reply:
    ctx.player()
    target = _other(ctx, arg)
    if not ctx.repo.active_pets(ctx.user_id):
        raise GameError("尚未选择出战灵宠。")
    if not ctx.repo.active_pets(target.user_id):
        raise GameError("对方尚未选择出战灵宠。")
    until = ctx.now + rule(ctx).expires_hours * 3600
    _set(ctx, target.user_id, ctx.user_id, until)
    return Reply(TITLE, (
        f"已向 {target.uid_label} 发出约战，{rule(ctx).expires_hours} 小时内有效。",
        "对方发 灵宠约战 应战 你的 UID 即可开打；届时用的是双方当下的阵容。",
        "约战不消耗精力，也不计赛季积分与熟练度。",
    ), (TITLE, "灵宠切磋", "我的灵宠"))


def accept(ctx: Context, arg: str) -> Reply:
    me = ctx.player()
    text = arg.strip()
    other = ctx.repo.player_by_uid(text) if text else None
    if other is None:
        raise GameError("没有找到这位玩家，请填写有效的 UID。")
    if other.user_id == ctx.user_id:
        raise GameError("不能向自己发起对战。")
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _key(other.user_id)),
    ).fetchone()
    if row is None:
        raise GameError(f"{other.uid_label}没有向你发出约战。")
    if int(row["progress"]) <= ctx.now:
        raise GameError("这次约战已经过期，请让对方重新发起。")
    attacker_pets = ctx.repo.active_pets(other.user_id)
    if not attacker_pets:
        raise GameError("对方已经撤下出战灵宠，无法应战。")
    if not ctx.repo.active_pets(ctx.user_id):
        raise GameError("请先选择出战灵宠。")
    for pet in attacker_pets:
        ctx.require_idle_pet(pet)
    reply = spar_fight(
        ctx, attacker=other.user_id, defender=me.user_id,
        title="约战结算", tail="约战不消耗资源，不计赛季积分和熟练度。",
    )
    _drop(ctx, ctx.user_id, other.user_id)
    return reply


def withdraw(ctx: Context, arg: str) -> Reply:
    ctx.player()
    target = _other(ctx, arg)
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (target.user_id, _key(ctx.user_id)),
    ).fetchone()
    if row is None:
        raise GameError("你与对方之间没有待应战的约战。")
    _drop(ctx, target.user_id, ctx.user_id)
    return Reply(TITLE, (
        f"已撤回对 {target.uid_label} 的约战。",
        "对方页面上不会再出现这次约战。",
    ), (TITLE, "我的灵宠"))


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [应战|撤回 <UID>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能与人约战。",
                "约战是异步切磋：发出后对方随时应战，届时不消耗精力、不计积分。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pending = incoming(ctx)
    sent = outgoing(ctx)
    lines = [f"待我应战 {len(pending)} 条 · 我发出 {len(sent)} 条。"]
    links = []
    for from_id, until in pending:
        lines.append(f"{_uid(ctx, from_id)} 约战 · 剩 {_hours(until - ctx.now)}")
        links.append(InlineCommand(
            len(lines) - 1, "应战", f"{TITLE} 应战 {_uid(ctx, from_id)}",
        ))
    for to_id, until in sent:
        lines.append(f"已约 {_uid(ctx, to_id)} · 剩 {_hours(until - ctx.now)}")
        links.append(InlineCommand(
            len(lines) - 1, "撤回", f"{TITLE} 撤回 {_uid(ctx, to_id)}",
        ))
    if not pending and not sent:
        lines.append("目前没有待处理的约战。")
    lines.append("发约战：灵宠约战 <UID>；约战只在对方应战时结算，双方都用当下阵容。")
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠切磋", "我的灵宠"), tuple(links[:8]))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head, rest = parts[0], " ".join(parts[1:])
    if head == "应战":
        return accept(ctx, rest)
    if head == "撤回":
        return withdraw(ctx, rest)
    if head.isdecimal() or head.upper().startswith("UID"):
        return send(ctx, " ".join(parts))
    raise GameError(f"格式：{TITLE} [<UID>|应战 <UID>|撤回 <UID>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    """Not surfaced: a pending challenge is a message, not a progression track."""
    return ""


__all__ = [
    "PREFIX", "TITLE", "accept", "dispatch", "incoming", "outgoing", "page", "send", "withdraw",
]
