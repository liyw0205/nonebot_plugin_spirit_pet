"""灵宠分享: a revocable, expiring capability to read one battle report.

The capability read path is guarded independently from participant authorization:

* ``create`` mints an unguessable code for a report **the caller participated in**;
* ``view`` accepts that code from *any* player and renders the stored snapshot and
  log verbatim, through the same renderer the 战报 detail page uses;
* ``revoke`` lets the owner close a code early; ``sweep_expired`` closes it lazily
  once it ages out.

A share code is a bearer capability: whoever holds it may read that one report, so
the code is random rather than derived from the sequential ``battle_id``, and the
share row stores only ``battle_id`` — never a copy of the snapshot, which is already
immutable. Sharing moves no stones or items, writes no battle record and advances no
quest, achievement, daily or weekly counter.
"""

import re
import secrets

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from . import battle_records

# Base32 without 0/O/1/I: a code is read aloud and retyped, so ambiguous glyphs are
# excluded.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12
READER_PREFIX = "shareview_"


def rule(ctx: Context):
    return ctx.content.rules.share


def readers(ctx: Context, user_id: str | None = None) -> int:
    """Distinct players who successfully opened any share owned by ``user_id``."""
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{READER_PREFIX}%"),
    ).fetchone()
    return int(row["total"])


def record_reader(ctx: Context, owner_id: str, viewer_id: str) -> None:
    """One row per owner/viewer; repeat reads of any share do not add another."""
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO NOTHING",
        (owner_id, f"{READER_PREFIX}{viewer_id}"),
    )


def mint_code() -> str:
    """A random, unambiguous capability code. Never derived from the battle id."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def _today(ctx: Context) -> str:
    return beijing_day(ctx.now)


def _created_today(ctx: Context, user_id: str) -> int:
    rows = ctx.repo.conn.execute(
        "SELECT created_at FROM battle_shares WHERE owner_id=?", (user_id,),
    )
    today = _today(ctx)
    return sum(1 for row in rows if beijing_day(row["created_at"]) == today)


def sweep_expired(ctx: Context) -> int:
    """Close every overdue share; a stale code can never be opened again."""
    cursor = ctx.repo.conn.execute(
        "UPDATE battle_shares SET state='revoked', closed_at=? WHERE state='active' AND expires_at<=?",
        (ctx.now, ctx.now),
    )
    return cursor.rowcount if cursor.rowcount > 0 else 0


def resolve(ctx: Context, code: str):
    """The active, unexpired share row for a code, or None."""
    return ctx.repo.conn.execute(
        "SELECT * FROM battle_shares WHERE share_id=? AND state='active' AND expires_at>?",
        (code, ctx.now),
    ).fetchone()


def own_shares(ctx: Context, user_id: str | None = None) -> list:
    owner = user_id or ctx.user_id
    return ctx.repo.conn.execute(
        "SELECT * FROM battle_shares WHERE owner_id=? ORDER BY created_at DESC, share_id DESC",
        (owner,),
    ).fetchall()


def _report_row(ctx: Context, battle_id: int, owner_id: str):
    """The stored report, tagged with the owner's side so the replay reads coherently."""
    row = ctx.repo.conn.execute(
        "SELECT b.*, COALESCE(("
        "  SELECT p.side FROM battle_participants p WHERE p.battle_id=b.battle_id AND p.user_id=?"
        "), 0) AS side FROM battle_records b WHERE b.battle_id=?",
        (owner_id, battle_id),
    ).fetchone()
    return row


def _remaining_days(ctx: Context, row) -> int:
    return max(0, (int(row["expires_at"]) - ctx.now + 86399) // 86400)


def _state_text(ctx: Context, row) -> str:
    """Distinguish an aged-out code from one the owner revoked on purpose."""
    if row["state"] != "active":
        expired = int(row["expires_at"]) <= ctx.now
        return "已过期" if expired else "已撤回"
    if int(row["expires_at"]) <= ctx.now:
        return "已过期"
    return f"剩 {_remaining_days(ctx, row)} 天"


def _valid_code(arg: str) -> str:
    text = arg.strip().upper()
    if not re.fullmatch(rf"[{ALPHABET}]{{{CODE_LENGTH}}}", text):
        raise GameError(f"分享码为 {CODE_LENGTH} 位，仅含 {ALPHABET}。")
    return text


def create(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    rules = rule(ctx)
    text = arg.strip()
    if not text.isdecimal():
        raise GameError("格式：灵宠分享 <战报编号>。")
    battle_id = int(text)
    row = ctx.repo.battle_report(player.user_id, battle_id)
    if row is None:
        raise GameError("只能分享自己参与过的战报，请查看 灵宠战报。")
    sweep_expired(ctx)
    if _created_today(ctx, player.user_id) >= rules.daily_limit:
        raise GameError(f"今日分享已达 {rules.daily_limit} 次，明日 00:00（北京时间）再分享。")
    code = mint_code()
    while ctx.repo.conn.execute(
        "SELECT 1 FROM battle_shares WHERE share_id=?", (code,),
    ).fetchone() is not None:
        code = mint_code()
    ctx.repo.conn.execute(
        "INSERT INTO battle_shares(share_id, battle_id, owner_id, created_at, expires_at, state,"
        " closed_at, views) VALUES (?, ?, ?, ?, ?, 'active', NULL, 0)",
        (code, battle_id, player.user_id, ctx.now, ctx.now + rules.code_days * 86400),
    )
    return Reply("战报已分享", (
        f"战报 #{battle_id} 的分享码：{code}",
        f"任何修士用 灵宠分享 查看 {code} 都能读这场战报。",
        f"{rules.code_days} 天内有效，随时可用 灵宠分享 撤回 {code} 让它立即失效。",
        f"今日已分享 {_created_today(ctx, player.user_id)}/{rules.daily_limit} 次。",
    ), ("灵宠分享 我的", "灵宠战报"))


def view(ctx: Context, arg: str) -> Reply:
    ctx.player()
    code = _valid_code(arg)
    sweep_expired(ctx)
    row = resolve(ctx, code)
    if row is None:
        raise GameError("分享码无效或已失效，请向分享者确认。")
    report = _report_row(ctx, int(row["battle_id"]), row["owner_id"])
    if report is None:
        raise GameError("该战报已不可读取。")
    if row["owner_id"] != ctx.user_id:
        record_reader(ctx, row["owner_id"], ctx.user_id)
    ctx.repo.conn.execute(
        "UPDATE battle_shares SET views=views+1 WHERE share_id=? AND state='active'", (code,),
    )
    owner = ctx.repo.player(row["owner_id"])
    rendered = battle_records.render_report(report)
    return Reply(
        rendered.title,
        (
            f"由 {owner.uid_label if owner is not None else '已离去的修士'} 分享 · {code}"
            f" · {_state_text(ctx, row)} · 以分享者视角",
            *rendered.lines,
        ),
        ("灵宠战报", "灵宠分享 我的"),
    )


def revoke(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    code = _valid_code(arg)
    sweep_expired(ctx)
    closed = ctx.repo.conn.execute(
        "UPDATE battle_shares SET state='revoked', closed_at=? "
        "WHERE share_id=? AND owner_id=? AND state='active'",
        (ctx.now, code, player.user_id),
    )
    if closed.rowcount != 1:
        raise GameError("没有可撤回的分享，请查看 灵宠分享 我的。")
    return Reply("分享已撤回", (f"分享码 {code} 已失效。",), ("灵宠分享 我的", "灵宠战报"))


def mine(ctx: Context, arg: str = "") -> Reply:
    player = ctx.player()
    sweep_expired(ctx)
    rows = own_shares(ctx, player.user_id)
    rules = rule(ctx)
    paged = paginate(rows, arg, "灵宠分享 我的", "灵宠分享 我的", rules.list_page_size)
    lines = [f"我的分享 {len(rows)} 条 · 第 {paged.number}/{paged.total} 页 · 每天最多 {rules.daily_limit} 次。"]
    links = []
    for row in paged.entries:
        lines.append(
            f"{row['share_id']} · 战报 #{row['battle_id']} · {_state_text(ctx, row)}"
            f" · 已读 {row['views']} 次"
        )
        index = len(lines) - 1
        if row["state"] == "active" and int(row["expires_at"]) > ctx.now:
            links.append(InlineCommand(index, "查看", f"灵宠分享 查看 {row['share_id']}"))
            links.append(InlineCommand(index, "撤回", f"灵宠分享 撤回 {row['share_id']}"))
    if not rows:
        lines.append("还没有分享过战报。用 灵宠分享 <战报编号> 把一场战斗变成分享码。")
    lines.append("发起分享：灵宠分享 <战报编号>。")
    return Reply(
        "灵宠分享 我的",
        tuple(lines),
        (*paged.navigation, "灵宠战报", "灵宠目标")[:4],
        tuple(links),
    )


def catalog(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠分享",
            (
                "尚未结契，先完成领养，才能分享战报。",
                "分享会把一场你参与过的战报变成分享码，其他修士凭码即可阅读。",
                "分享码由你随时撤回，到期也会自动失效。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sweep_expired(ctx)
    player = ctx.player()
    rules = rule(ctx)
    rows = own_shares(ctx, player.user_id)
    active = [row for row in rows if row["state"] == "active" and int(row["expires_at"]) > ctx.now]
    lines = [
        f"有效期内的分享 {len(active)} 条 · 今日已分享 {_created_today(ctx, player.user_id)}/{rules.daily_limit} 次"
        f" · 每个分享码有效 {rules.code_days} 天。",
        "把一场战报分享给别人：灵宠分享 <战报编号>。",
        "打开别人的分享：灵宠分享 查看 <分享码>。",
        "预约：分享码是随机生成的凭据，谁拿到谁就能读那一场战报。",
    ]
    if active:
        lines.append("— 有效期内的分享 —")
    links = []
    for row in active[:rules.list_page_size]:
        lines.append(f"{row['share_id']} · 战报 #{row['battle_id']} · {_state_text(ctx, row)} · 已读 {row['views']} 次")
        index = len(lines) - 1
        links.append(InlineCommand(index, "查看", f"灵宠分享 查看 {row['share_id']}"))
        links.append(InlineCommand(index, "撤回", f"灵宠分享 撤回 {row['share_id']}"))
    return Reply("灵宠分享", tuple(lines), ("灵宠分享 我的", "灵宠分享奖励", "灵宠战报", "灵宠目标")[:4], tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if head == "查看":
        return view(ctx, rest)
    if head == "撤回":
        return revoke(ctx, rest)
    if head == "我的":
        return mine(ctx, rest)
    if re.fullmatch(r"[0-9]+", head):
        return create(ctx, head)
    raise GameError("格式：灵宠分享 [<战报编号>|查看 <分享码>|撤回 <分享码>|我的 [页码]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "分享：尚未结契"
    rules = rule(ctx)
    rows = own_shares(ctx, user_id)
    active = sum(
        1 for row in rows if row["state"] == "active" and int(row["expires_at"]) > ctx.now
    )
    return f"分享：有效 {active} 条 · 今日 {_created_today(ctx, user_id)}/{rules.daily_limit} 次"


__all__ = [
    "ALPHABET", "CODE_LENGTH", "catalog", "create", "dispatch", "mine", "mint_code", "objective_line",
    "own_shares", "resolve", "revoke", "sweep_expired", "view",
]
