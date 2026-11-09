"""灵宠串门: a friends-only daily visit that pays bond experience to both pets.

Friendship already had a complete handshake but no action of its own — mail and
borrow were the only things a friend unlocked, and 灵田浇水 is team-gated. This
adds the smallest complete social daily: visit a friend's active companion, both
companions gain bond experience, and the visitor takes home a small stone gift.

State lives in ``quest_progress``: ``visit_day_<date>`` counts visits used today
and ``visit_<date>_<uid>`` locks one visit per friend per Beijing day. Both keys
carry the date, so the budget and the locks reset by themselves.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from . import bond_levels, friends

DAY_PREFIX = "visit_day_"
VISIT_PREFIX = "visit_"
VISITS_PER_DAY = 3
BOND_EXP = 5
STONES = 20


def _counter(ctx: Context, quest_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, quest_id),
    ).fetchone()
    return int(row["progress"]) if row else 0


def used_today(ctx: Context, user_id: str | None = None) -> int:
    return _counter(ctx, f"{DAY_PREFIX}{beijing_day(ctx.now)}", user_id)


def left_today(ctx: Context, user_id: str | None = None) -> int:
    return max(0, VISITS_PER_DAY - used_today(ctx, user_id))


def visited_today(ctx: Context, friend_id: str, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{VISIT_PREFIX}{beijing_day(ctx.now)}_{friend_id}"),
    ).fetchone()
    return row is not None


def _award_bond(ctx: Context, owner: str, pet_id: int, amount: int) -> None:
    """Bond experience for a pet that may belong to either side of the visit."""
    quest_id = bond_levels.key(pet_id)
    current = _counter(ctx, quest_id, owner)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (owner, quest_id, current + amount),
    )


def _write_visit(ctx: Context, friend_id: str) -> None:
    day = beijing_day(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
        (ctx.user_id, f"{DAY_PREFIX}{day}"),
    )
    ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed)"
        " VALUES (?, ?, 1, 0)",
        (ctx.user_id, f"{VISIT_PREFIX}{day}_{friend_id}"),
    )


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠串门 [UID]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠串门",
            (
                "串门是好友之间的每日互动：去对方伙伴那里坐坐，双方伙伴都涨羁绊经验。",
                "尚未结契，先完成领养，再去认识别的修士。",
            ),
            ("灵宠帮助",),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    roster = friends.friends(ctx, player.user_id)
    lines = [f"今日串门 {used_today(ctx)}/{VISITS_PER_DAY} 次 · 好友 {len(roster)} 位。"]
    links = []
    if not roster:
        lines.append("还没有好友；先发送 灵宠好友 添加 <UID> 结识一位。")
    for row in roster:
        friend_id = friends.other_side(row, player.user_id)
        done = visited_today(ctx, friend_id)
        state = "已串门" if done else "可串门"
        lines.append(f"{friends._uid_label(ctx, friend_id)}（{friends._uid(ctx, friend_id)}）· {state}")
        if not done:
            links.append(InlineCommand(
                len(lines) - 1, "串门", f"灵宠串门 {friends._uid(ctx, friend_id)}",
            ))
    lines.append(f"每次串门双方伙伴各得羁绊经验 {BOND_EXP}，自己另得灵石 {STONES}。")
    return Reply("灵宠串门", tuple(lines), ("灵宠好友", "灵宠目标", "我的灵宠"), tuple(links))


def visit(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not text:
        return page(ctx)
    target = friends._target(ctx, text, player)
    if not friends.linked(ctx, player.user_id, target.user_id):
        raise GameError("只能去好友家串门：先互加好友。")
    if visited_today(ctx, target.user_id):
        raise GameError("今天已经去过这位好友家串门了，明日再来。")
    if left_today(ctx) <= 0:
        raise GameError(f"今日串门次数已用完（每日 {VISITS_PER_DAY} 次），明日再来。")
    if target.active_pet_id is None:
        raise GameError("对方尚未选择出战伙伴，改日再来。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)

    _award_bond(ctx, player.user_id, pet.pet_id, BOND_EXP)
    _award_bond(ctx, target.user_id, target.active_pet_id, BOND_EXP)
    player.stones += STONES
    _write_visit(ctx, target.user_id)

    host_pet = ctx.repo.pet(target.active_pet_id)
    host_name = host_pet.name if host_pet is not None else "对方的伙伴"
    return Reply(
        "灵宠串门",
        (
            f"{pet.name}在{host_name}那儿坐了一会儿，两只伙伴都长了羁绊经验 +{BOND_EXP}。",
            f"灵石 +{STONES}（余 {player.stones}）· 今日还剩 {left_today(ctx, player.user_id)} 次。",
        ),
        ("灵宠串门", "灵宠好友", "我的灵宠"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    return visit(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "串门：尚未结契"
    roster = friends.friends(ctx, user_id)
    return (
        f"串门：今日 {used_today(ctx, user_id)}/{VISITS_PER_DAY} 次"
        f" · 好友 {len(roster)} 位"
    )


__all__ = [
    "BOND_EXP", "DAY_PREFIX", "STONES", "VISITS_PER_DAY", "VISIT_PREFIX",
    "dispatch", "left_today", "objective_line", "page", "used_today", "visit",
    "visited_today",
]
