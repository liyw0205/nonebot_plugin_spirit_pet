"""灵宠借力: carry a friend's companion's strength into your own fight.

``support`` (schema ≤ 26) lends *your own* bench pets' base stats to your active pet, and
``friends`` (schema 24) made friendship a real, player-managed edge — but the two never
met, so a friend was worth a mailbox and nothing in combat. This module connects them.

The design is deliberately narrow:

* only a friend may borrow, and only a companion that its owner has explicitly lent;
* one borrowed companion at a time, worth ``borrow.rate`` of its base stats — capped at the
  support roster's own ceiling so your own bench always stays the primary path;
* nothing is granted to the lender (a payout would make alt-account lending profitable);
* every validity rule is checked on read (``current``), not by a cleanup job, so unfriending,
  expiring, archiving or sending the lent pet on an expedition invalidates the bonus at once.

State rides in ``quest_progress`` (no schema change): the lender writes ``lend_<pet_id>``
whose ``progress`` is the expiry timestamp, the borrower writes ``borrow_pet`` and
``borrow_until``. A half-written pair simply reads as "no borrow".
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .combat import pet_stats
from . import friends

LEND_PREFIX = "lend_"
BORROW_PET = "borrow_pet"
BORROW_UNTIL = "borrow_until"
TITLE = "灵宠借力"
STAT_LABELS = (("hp", "气血"), ("attack", "攻击"), ("defense", "防御"), ("speed", "速度"))


def rule(ctx: Context):
    return ctx.content.rules.borrow


def rate(ctx: Context) -> float:
    return rule(ctx).rate


def keep_days(ctx: Context) -> int:
    return rule(ctx).keep_days


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row is not None else 0


def _set(ctx: Context, key: str, value: int, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user_id or ctx.user_id, key, value),
    )


def _drop(ctx: Context, keys: tuple[str, ...], user_id: str | None = None) -> None:
    owner = user_id or ctx.user_id
    for key in keys:
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?", (owner, key),
        )


def _load(ctx: Context, pet_id: int):
    try:
        return ctx.repo.pet(pet_id)
    except GameError:
        return None


def lent(ctx: Context, user_id: str | None = None) -> dict[int, int]:
    """Pets this player has lent out, mapped to their expiry timestamp."""
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{LEND_PREFIX}%"),
    ).fetchall()
    offers = {}
    for row in rows:
        tail = row["quest_id"][len(LEND_PREFIX):]
        if tail.isdecimal():
            offers[int(tail)] = int(row["progress"])
    return offers


def _lent_by(ctx: Context, pet_id: int, owner: str) -> int:
    """Expiry of a specific pet's lend offer, or 0 when it is not on offer."""
    return _progress(ctx, f"{LEND_PREFIX}{pet_id}", owner)


def current(ctx: Context, user_id: str | None = None):
    """The companion this player is currently borrowing, or None.

    Every rule is re-checked here so a borrow cannot outlive its justification: the
    borrower must still be friends with the owner, the owner's offer must still be
    open, and the lent companion must still be available.
    """
    borrower = user_id or ctx.user_id
    pet_id = _progress(ctx, BORROW_PET, borrower)
    until = _progress(ctx, BORROW_UNTIL, borrower)
    if not pet_id or until <= ctx.now:
        return None
    pet = _load(ctx, pet_id)
    if pet is None or pet.archived or pet.user_id == borrower:
        return None
    if not friends.linked(ctx, pet.user_id, borrower):
        return None
    if _lent_by(ctx, pet.pet_id, pet.user_id) <= ctx.now:
        return None
    if ctx.repo.active_expedition(pet.pet_id) is not None:
        return None
    return pet, until


def _contributions(ctx: Context, pet) -> dict[str, int]:
    stats = pet_stats(pet, ctx.content)
    value = rate(ctx)
    return {key: int(getattr(stats, key) * value) for key, _ in STAT_LABELS}


def bonus(ctx: Context, user_id: str | None = None) -> dict[str, int]:
    """The borrowed companion's contribution, or all zeros when nothing is borrowed."""
    borrowed = current(ctx, user_id)
    if borrowed is None:
        return {key: 0 for key, _ in STAT_LABELS}
    return _contributions(ctx, borrowed[0])


def _bonus_text(values: dict[str, int]) -> str:
    text = " · ".join(f"{label} +{values[key]}" for key, label in STAT_LABELS if values[key])
    return text or "无加成"


def _uid(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return str(player.uid) if player is not None else "已离去的修士"


def _days(seconds: int) -> str:
    if seconds <= 0:
        return "已到期"
    days = seconds // 86400
    return f"{days} 天" if days else "不足 1 天"


def _borrower(ctx: Context, pet_id: int, owner: str) -> str:
    """Who currently holds this lent pet, as a UID label ('' when nobody does)."""
    rows = ctx.repo.conn.execute(
        "SELECT user_id FROM quest_progress WHERE quest_id=? AND progress=?", (BORROW_PET, pet_id),
    ).fetchall()
    for row in rows:
        holder = row["user_id"]
        if holder == owner:
            continue
        borrowed = current(ctx, holder)
        if borrowed is not None and borrowed[0].pet_id == pet_id:
            return _uid(ctx, holder)
    return ""


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [出借 <编号>|收回 <编号>|借用 <UID> <编号>|归还]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能与好友互借伙伴。",
                "好友可以把自己的一只伙伴借给你，让它把基础四维的一部分借给你的出战伙伴。",
                "只有好友能借，出借方随时可以收回。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    links = []
    offers = lent(ctx)
    borrowed = current(ctx)
    lines = [
        f"借力：好友的伙伴借出自身基础四维的 {rate(ctx):.0%}（不含装备、淬魂与师门），"
        f"一次一只，出借保留 {keep_days(ctx)} 天。",
    ]
    if borrowed is None:
        lines.append("当前没有借来的伙伴。")
    else:
        pet, until = borrowed
        lines.append(
            f"当前借来：{pet.name}（编号 {pet.pet_id}）· 主人 UID {_uid(ctx, pet.user_id)}"
            f" · 剩余 {_days(until - ctx.now)} · {_bonus_text(_contributions(ctx, pet))}"
        )
        links.append(InlineCommand(len(lines) - 1, "归还", f"{TITLE} 归还"))
    lines.append(f"我挂出的伙伴：{len(offers)} 只。")
    for pet_id, until in sorted(offers.items()):
        pet = _load(ctx, pet_id)
        if pet is None:
            continue
        holder = _borrower(ctx, pet_id, ctx.user_id)
        state = f"借出中：UID {holder}" if holder else "待借出"
        if until <= ctx.now:
            state = "已到期，可收回"
        lines.append(f"编号 {pet.pet_id}：{pet.name} · {state} · 剩 {_days(until - ctx.now)}")
        links.append(InlineCommand(len(lines) - 1, "收回", f"{TITLE} 收回 {pet.pet_id}"))
    if not offers:
        lines.append("还没有挂出伙伴。发送「灵宠借力 出借 <编号>」把一只伙伴借给好友。")
    available = []
    for friend in friends.friends(ctx):
        other = friends.other_side(friend, ctx.user_id)
        for pet_id, until in sorted(lent(ctx, other).items()):
            if until <= ctx.now:
                continue
            pet = _load(ctx, pet_id)
            if pet is None or pet.archived or ctx.repo.active_expedition(pet.pet_id) is not None:
                continue
            if borrowed is not None and borrowed[0].pet_id == pet.pet_id:
                continue
            available.append((other, pet, until))
    if available:
        lines.append("好友挂出的伙伴：")
        for owner, pet, until in available:
            lines.append(
                f"UID {_uid(ctx, owner)} 的 {pet.name}（编号 {pet.pet_id}）"
                f" · 剩 {_days(until - ctx.now)} · {_bonus_text(_contributions(ctx, pet))}"
            )
            links.append(InlineCommand(
                len(lines) - 1, "借用", f"{TITLE} 借用 {_uid(ctx, owner)} {pet.pet_id}",
            ))
    else:
        lines.append("没有可借的好友伙伴：先用 灵宠好友 添加好友，再请对方出借。")
    lines.append("解除好友、对方收回、伙伴封存或外出，借来的加成都立即失效。")
    return Reply(
        TITLE, tuple(lines), (TITLE, "灵宠好友", "我的灵宠", "灵宠目标")[:4], tuple(links),
    )


def lend(ctx: Context, arg: str) -> Reply:
    ctx.player()
    text = arg.strip()
    if not text.isdecimal():
        raise GameError(f"格式：{TITLE} 出借 <编号>。")
    pet = _owned_pet(ctx, int(text))
    if pet.archived:
        raise GameError(f"{pet.name}已封存，先复原才能出借。")
    ctx.require_idle_pet(pet)
    until = ctx.now + keep_days(ctx) * 86400
    _set(ctx, f"{LEND_PREFIX}{pet.pet_id}", until)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply(TITLE, (
        f"{pet.name}（编号 {pet.pet_id}）已挂出，{keep_days(ctx)} 天内好友可以借用。",
        f"借出期间伙伴仍可修炼、出战与装备；你随时可以发送「{TITLE} 收回 {pet.pet_id}」。",
    ), (TITLE, "灵宠好友", "灵宠列表", "我的灵宠"))


def withdraw(ctx: Context, arg: str) -> Reply:
    ctx.player()
    text = arg.strip()
    if not text.isdecimal():
        raise GameError(f"格式：{TITLE} 收回 <编号>。")
    pet_id = int(text)
    if _lent_by(ctx, pet_id, ctx.user_id) <= 0:
        raise GameError("这只伙伴当前没有挂出。")
    _drop(ctx, (f"{LEND_PREFIX}{pet_id}",))
    ctx.repo.invalidate_ready(ctx.user_id)
    pet = _load(ctx, pet_id)
    name = pet.name if pet is not None else f"编号 {pet_id}"
    return Reply(TITLE, (
        f"{name}已收回，好友借去的加成同时失效。",
        "已借出的伙伴不会因此丢失任何东西。",
    ), (TITLE, "灵宠列表", "我的灵宠"))


def take(ctx: Context, arg: str) -> Reply:
    ctx.player()
    parts = arg.split()
    if len(parts) != 2 or not parts[0].isdecimal() or not parts[1].isdecimal():
        raise GameError(f"格式：{TITLE} 借用 <好友UID> <伙伴编号>。")
    owner = ctx.repo.player_by_uid(parts[0])
    if owner is None:
        raise GameError("未找到该 UID 对应的修士。")
    if owner.user_id == ctx.user_id:
        raise GameError("不能借用自己挂出的伙伴。")
    if not friends.linked(ctx, owner.user_id, ctx.user_id):
        raise GameError("只能借用好友的伙伴，先用 灵宠好友 添加对方。")
    pet = _load(ctx, int(parts[1]))
    if pet is None or pet.user_id != owner.user_id:
        raise GameError("对方没有这只伙伴。")
    until = _lent_by(ctx, pet.pet_id, owner.user_id)
    if until <= 0:
        raise GameError(f"{pet.name}没有被挂出，请让对方发送「{TITLE} 出借 {pet.pet_id}」。")
    if until <= ctx.now:
        raise GameError(f"{pet.name}的挂出已经到期，请让对方重新挂出。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，暂时不能借用。")
    if ctx.repo.active_expedition(pet.pet_id) is not None:
        raise GameError(f"{pet.name}正在外出派遣，暂时不能借用。")
    if not ctx.repo.active_pets(ctx.user_id):
        raise GameError("请先选择出战伙伴，借来的属性才有地方加成。")
    previous = current(ctx)
    _set(ctx, BORROW_PET, pet.pet_id)
    _set(ctx, BORROW_UNTIL, min(until, ctx.now + keep_days(ctx) * 86400))
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"已借来 {pet.name}（编号 {pet.pet_id}），{_bonus_text(_contributions(ctx, pet))}"
        " 加给当前出战伙伴。",
        f"主人 UID {_uid(ctx, owner.user_id)}，到期时间与对方的挂出一致。",
    ]
    if previous is not None and previous[0].pet_id != pet.pet_id:
        lines.append(f"已替换先前借来的 {previous[0].name}。")
    return Reply(TITLE, tuple(lines), (TITLE, "我的灵宠", "灵宠好友", "灵宠目标"))


def release(ctx: Context, arg: str) -> Reply:
    ctx.player()
    if arg.strip():
        raise GameError(f"格式：{TITLE} 归还。")
    if current(ctx) is None and _progress(ctx, BORROW_PET) == 0:
        raise GameError("当前没有借来的伙伴。")
    _drop(ctx, (BORROW_PET, BORROW_UNTIL))
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply(TITLE, (
        "已归还借来的伙伴，加成立即失效。",
        "好友仍可再次借给你，只要对方的挂出还没到期。",
    ), (TITLE, "灵宠好友", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    rest = " ".join(parts[1:])
    if head == "出借":
        return lend(ctx, rest)
    if head == "收回":
        return withdraw(ctx, rest)
    if head == "借用":
        return take(ctx, rest)
    if head == "归还":
        return release(ctx, rest)
    if head.isdecimal() and len(parts) == 2:
        return take(ctx, arg)
    raise GameError(
        f"格式：{TITLE} [出借 <编号>|收回 <编号>|借用 <UID> <编号>|归还]。"
    )


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "借力：尚未结契"
    offers = len(lent(ctx, user_id))
    borrowed = current(ctx, user_id)
    if borrowed is None:
        return f"借力：挂出 {offers} 只 · 未借入"
    return f"借力：挂出 {offers} 只 · 借入 {borrowed[0].name}"


def _owned_pet(ctx: Context, pet_id: int):
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的这只灵宠。")
    return ctx.repo.pet(pet_id)


__all__ = [
    "BORROW_PET", "BORROW_UNTIL", "LEND_PREFIX", "bonus", "current", "dispatch", "lend", "lent",
    "objective_line", "page", "release", "take", "withdraw",
]
