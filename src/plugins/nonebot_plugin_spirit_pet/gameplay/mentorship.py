"""灵宠师徒: a veteran takes a newcomer under wing, and graduation pays both.

The game has friends, teams, mail and spars — every one of them between peers. Nothing
connects a player who has climbed to 金丹 with one who just adopted a 青鸾, so the only
way knowledge moves is out-of-game chat. This slice adds the missing vertical edge:
an apprentice asks, a mentor accepts, and when the apprentice's best companion reaches
``mentor.graduate_realm`` either side can close the relation and both are paid once.

Design notes that matter for correctness:

* A relation is two rows in ``quest_progress`` — ``mentorlink_<mentor>`` on the
  apprentice's row and ``apprentice_<apprentice>`` on the mentor's. They are written and
  deleted together, so "half a relation" cannot happen; a reader treats a missing half as
  no relation at all.
* ``mentorreq_<apprentice>`` on the mentor's row is a request with an expiry in
  ``progress``. Requests never award anything and expire by read, so no cleanup job.
* Graduation pays **once per apprentice**: the apprentice's row keeps ``graduated`` so a
  player cannot re-enrol, be expelled, re-enrol and be paid again.
* A mentor must already stand above the candidate, and the candidate must still be below
  the graduation realm — otherwise "teaching" would be a free reward for two veterans.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day

LINK = "mentorlink_"
APPRENTICE = "apprentice_"
REQUEST = "mentorreq_"
LESSON = "mentorlesson_"
GRADUATED = "graduated"
TITLE = "灵宠师徒"



def _pay(ctx: Context, reward, user_id: str) -> list[str]:
    """Pay stones and items only.

    ``rewards.grant`` also pays exp and therefore insists the receiving pet is idle —
    wrong here: graduation must never require the *other* player's pet to be home. It
    also prints "修为 +0" when a reward carries no exp, which reads like a bug.
    """
    player = ctx.player(user_id)
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    player.stones += stones
    lines = [f"灵石 +{stones}"]
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if amount:
            ctx.repo.add_item(user_id, item_id, amount)
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return lines

def rule(ctx: Context):
    return ctx.content.rules.mentor


def _key(prefix: str, user_id: str) -> str:
    return f"{prefix}{user_id}"


def _set(ctx: Context, owner: str, prefix: str, value: str, progress: int = 1) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (owner, _key(prefix, value), progress),
    )


def _drop(ctx: Context, owner: str, prefix: str, value: str) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?", (owner, _key(prefix, value)),
    )


def _has(ctx: Context, owner: str, prefix: str, value: str) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?", (owner, _key(prefix, value)),
    ).fetchone() is not None


def _uids(ctx: Context, owner: str, prefix: str) -> list[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{prefix}%"),
    ).fetchall()
    return [row["quest_id"][len(prefix):] for row in rows]


def _uid(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return str(player.uid) if player is not None else "已离去的修士"


def realm_index(ctx: Context, user_id: str) -> int:
    """Best realm reached by this player's companions, as an index into the realm ladder."""
    return max((pet.realm for pet in ctx.repo.owned_pets(user_id)), default=0)


def _label(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return player.uid_label if player is not None else "已离去的修士"


def mentor_of(ctx: Context, user_id: str | None = None) -> str | None:
    found = _uids(ctx, user_id or ctx.user_id, LINK)
    return found[0] if found else None


def apprentices(ctx: Context, user_id: str | None = None) -> list[str]:
    return _uids(ctx, user_id or ctx.user_id, APPRENTICE)


def requests(ctx: Context, user_id: str | None = None) -> list[tuple[str, int]]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{REQUEST}%"),
    ).fetchall()
    live = [
        (row["quest_id"][len(REQUEST):], int(row["progress"]))
        for row in rows if int(row["progress"]) > ctx.now
    ]
    return sorted(live, key=lambda item: item[1])


def graduated(ctx: Context, user_id: str | None = None) -> bool:
    return _has(ctx, user_id or ctx.user_id, GRADUATED, "")


def lesson_key(now: int, apprentice_id: str) -> str:
    return f"{LESSON}{beijing_day(now)}_{apprentice_id}"


def lessons_today(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS used FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{LESSON}{beijing_day(ctx.now)}_%"),
    ).fetchone()
    return int(row["used"])


def taught(ctx: Context, apprentice_id: str, user_id: str | None = None) -> bool:
    return _has(ctx, user_id or ctx.user_id, f"{LESSON}{beijing_day(ctx.now)}_", apprentice_id)


def _lesson_state(ctx: Context, apprentice_id: str) -> str:
    """Read-only reason for the lesson page; the command repeats the checks authoritatively."""
    if taught(ctx, apprentice_id):
        return "今日已传道"
    if lessons_today(ctx) >= rule(ctx).lesson.daily_limit:
        return "今日次数已用尽"
    mentor = ctx.repo.player(ctx.user_id)
    if mentor is None or mentor.active_pet_id is None:
        return "你无出战伙伴"
    mentor_pet = ctx.repo.pet(mentor.active_pet_id)
    if mentor_pet.archived:
        return "你的出战伙伴已封存"
    if ctx.repo.active_expedition(mentor_pet.pet_id) is not None:
        return "你的伙伴外出中"
    peer = ctx.repo.player(apprentice_id)
    if peer is None:
        return "徒弟已离去"
    if peer.active_pet_id is None:
        return "徒弟无出战伙伴"
    peer_pet = ctx.repo.pet(peer.active_pet_id)
    if peer_pet.archived:
        return "徒弟的出战伙伴已封存"
    if ctx.repo.active_expedition(peer_pet.pet_id) is not None:
        return "徒弟的伙伴外出中"
    return "可传道"


def lesson_page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} 传道 [<徒弟UID>]。")
    rules = rule(ctx).lesson
    if ctx.repo.player(ctx.user_id) is None:
        lines = [
            f"师父每天可向徒弟传道 {rules.daily_limit} 次：每次消耗自己出战伙伴 {rules.energy} 精力，",
            f"徒弟出战伙伴得 {rules.exp} 修为，师父得 {rules.stones} 灵石。",
            "每位徒弟每天只能被同一位师父传道一次；出师或逐出后自然停止。",
            "尚未结契，先完成领养，才能拜师或收徒。",
        ]
        return Reply(TITLE, tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))
    roster = apprentices(ctx)
    lines = [
        f"今日传道 {lessons_today(ctx)}/{rules.daily_limit} 次。",
        f"徒弟 {len(roster)}/{rule(ctx).max_apprentices} 名。",
    ]
    links = []
    if not roster:
        lines.append("门下暂无徒弟；先收徒，才能开始传道。")
    for user_id in roster:
        peer = ctx.repo.player(user_id)
        if peer is None:
            continue
        state = _lesson_state(ctx, user_id)
        lines.append(f"{peer.uid_label} · {state}")
        if state == "可传道":
            links.append(InlineCommand(len(lines) - 1, "传道", f"{TITLE} 传道 {peer.uid}"))
    lines.append("传道消耗师父出战伙伴精力；徒弟伙伴获得修为，师父获得灵石。")
    return Reply(TITLE, tuple(lines), (TITLE, "我的灵宠", "灵宠帮助"), tuple(links[:8]))


def lesson(ctx: Context, arg: str) -> Reply:
    me = ctx.player()
    target = _target(ctx, arg)
    if not _has(ctx, me.user_id, APPRENTICE, target.user_id):
        raise GameError("该修士不是你的徒弟。")
    rules = rule(ctx).lesson
    if taught(ctx, target.user_id):
        raise GameError(f"{target.uid_label}今日已经传过道了，明天再来。")
    if lessons_today(ctx) >= rules.daily_limit:
        raise GameError(f"今日传道次数已用尽（每日 {rules.daily_limit} 次，北京时间 00:00 刷新）。")
    master_pet = ctx.pet(me.user_id)
    ctx.require_idle_pet(master_pet)
    if master_pet.energy < rules.energy:
        raise GameError(f"{master_pet.name}精力不足：传道需要 {rules.energy} 点，当前 {master_pet.energy} 点。")
    apprentice_pet = ctx.pet(target.user_id)
    ctx.require_idle_pet(apprentice_pet)
    master_pet.energy -= rules.energy
    apprentice_pet.exp += rules.exp
    me.stones += rules.stones
    _set(ctx, me.user_id, f"{LESSON}{beijing_day(ctx.now)}_", target.user_id, 1)
    left = rules.daily_limit - lessons_today(ctx)
    return Reply("师徒传道", (
        f"你向 {target.uid_label} 传道：{master_pet.name}精力 -{rules.energy}，",
        f"{apprentice_pet.name}修为 +{rules.exp}，你获得灵石 +{rules.stones}。",
        f"今日还可传道 {left} 次。",
    ), (TITLE, TITLE + " 传道", "我的灵宠"))


def _target(ctx: Context, text: str):
    if not text.strip():
        raise GameError(f"格式：{TITLE} <UID> 或 {TITLE} 同意|拒绝|逐出 <UID>。")
    player = ctx.repo.player_by_uid(text.strip())
    if player is None:
        raise GameError("没有找到这位玩家，请填写有效的 UID。")
    if player.user_id == ctx.user_id:
        raise GameError("不能与自己结为师徒。")
    return player


def _graduate_line(ctx: Context) -> tuple[str, int]:
    realm_id = rule(ctx).graduate_realm
    index = next(
        position for position, realm in enumerate(ctx.content.realms) if realm.id == realm_id
    )
    return ctx.content.realms[index].name, index


def ask(ctx: Context, arg: str) -> Reply:
    me = ctx.player()
    mentor = _target(ctx, arg)
    rules = rule(ctx)
    if mentor_of(ctx, me.user_id) is not None:
        raise GameError("你已经有师父了，先出师或请对方逐出。")
    if graduated(ctx, me.user_id):
        raise GameError("你已经出师，不能再拜师。")
    realm_name, graduate_index = _graduate_line(ctx)
    if realm_index(ctx, me.user_id) >= graduate_index:
        raise GameError(f"你的伙伴已到达{realm_name}境，无需再拜师。")
    if realm_index(ctx, mentor.user_id) <= realm_index(ctx, me.user_id):
        raise GameError("对方境界不高过你，拜师没有意义。")
    if len(apprentices(ctx, mentor.user_id)) >= rules.max_apprentices:
        raise GameError(f"对方已收满 {rules.max_apprentices} 名徒弟。")
    if _has(ctx, me.user_id, LINK, mentor.user_id):
        raise GameError("你们已经是师徒。")
    _set(ctx, mentor.user_id, REQUEST, me.user_id, ctx.now + rules.request_hours * 3600)
    return Reply(TITLE, (
        f"已向 {mentor.uid_label} 递上拜师帖，{rules.request_hours} 小时内有效。",
        f"对方发 {TITLE} 同意 {me.uid} 即可收徒；出师条件是伙伴到达{realm_name}境。",
        "师徒关系建立后，出师时双方各得一份谢礼。",
    ), (TITLE, "我的灵宠", "灵宠帮助"))


def accept(ctx: Context, arg: str) -> Reply:
    me = ctx.player()
    candidate = _target(ctx, arg)
    rules = rule(ctx)
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _key(REQUEST, candidate.user_id)),
    ).fetchone()
    if row is None:
        raise GameError("没有来自该修士的拜师帖。")
    if int(row["progress"]) <= ctx.now:
        raise GameError("这份拜师帖已经过期，请让对方重新发送。")
    if mentor_of(ctx, candidate.user_id) is not None:
        raise GameError("对方已经有师父了。")
    if len(apprentices(ctx)) >= rules.max_apprentices:
        raise GameError(f"你已收满 {rules.max_apprentices} 名徒弟。")
    _set(ctx, ctx.user_id, APPRENTICE, candidate.user_id)
    _set(ctx, candidate.user_id, LINK, ctx.user_id)
    _drop(ctx, ctx.user_id, REQUEST, candidate.user_id)
    realm_name, _ = _graduate_line(ctx)
    return Reply(TITLE, (
        f"你收下了 {candidate.uid_label}，师徒关系已成立。",
        f"对方伙伴到达{realm_name}境后可出师，届时双方各得一份谢礼。",
        f"当前徒弟 {len(apprentices(ctx))}/{rules.max_apprentices} 名。",
    ), (TITLE, "我的灵宠", "灵宠帮助"))


def reject(ctx: Context, arg: str) -> Reply:
    ctx.player()
    candidate = _target(ctx, arg)
    if not _has(ctx, ctx.user_id, REQUEST, candidate.user_id):
        raise GameError("没有来自该修士的拜师帖。")
    _drop(ctx, ctx.user_id, REQUEST, candidate.user_id)
    return Reply(TITLE, (f"已退回 {candidate.uid_label} 的拜师帖。",), (TITLE, "我的灵宠"))


def expel(ctx: Context, arg: str) -> Reply:
    ctx.player()
    candidate = _target(ctx, arg)
    if not _has(ctx, ctx.user_id, APPRENTICE, candidate.user_id):
        raise GameError("该修士不是你的徒弟。")
    _drop(ctx, ctx.user_id, APPRENTICE, candidate.user_id)
    _drop(ctx, candidate.user_id, LINK, ctx.user_id)
    return Reply(TITLE, (
        f"已解除与 {candidate.uid_label} 的师徒关系。",
        "逐出不发谢礼；对方仍可重新拜师。",
    ), (TITLE, "我的灵宠"))


def graduate(ctx: Context, arg: str) -> Reply:
    me = ctx.player()
    if arg.strip():
        raise GameError(f"格式：{TITLE} 出师。")
    mentor_id = mentor_of(ctx, me.user_id)
    if mentor_id is None:
        raise GameError("你还没有师父。")
    realm_name, graduate_index = _graduate_line(ctx)
    if realm_index(ctx, me.user_id) < graduate_index:
        raise GameError(f"伙伴需先到达{realm_name}境才能出师。")
    rules = rule(ctx)
    lines = [f"{_label(ctx, mentor_id)}的教导到此为止，你已出师。"]
    lines.extend(f"出师谢礼：{line}" for line in _pay(ctx, rules.apprentice_reward, me.user_id))
    lines.extend(f"师父所得：{line}" for line in _pay(ctx, rules.mentor_reward, mentor_id))
    _drop(ctx, mentor_id, APPRENTICE, me.user_id)
    _drop(ctx, me.user_id, LINK, mentor_id)
    _set(ctx, me.user_id, GRADUATED, "", 1)
    lines.append("出师后不能再拜师；师徒双方各得一份谢礼。")
    return Reply(TITLE, tuple(lines), (TITLE, "我的灵宠", "灵宠目标"))


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [<UID>|同意|拒绝|逐出 <UID>|出师]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能拜师或收徒。",
                "徒弟发 灵宠师徒 <UID> 递拜师帖，师父发 灵宠师徒 同意 <UID> 收徒。",
                "徒弟的伙伴到达出师境界后可出师，双方各得一份谢礼。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    realm_name, graduate_index = _graduate_line(ctx)
    lines = []
    links = []
    mentor_id = mentor_of(ctx)
    if mentor_id is not None:
        ready = realm_index(ctx, ctx.user_id) >= graduate_index
        lines.append(
            f"师父：{_label(ctx, mentor_id)}"
            f" · {'可以出师' if ready else f'需伙伴到达{realm_name}境'}"
        )
        if ready:
            links.append(InlineCommand(len(lines) - 1, "出师", f"{TITLE} 出师"))
    elif graduated(ctx):
        lines.append("你已经出师，不再拜师。")
    else:
        lines.append(
            f"暂无师父。发 {TITLE} <UID> 向境界更高的修士递拜师帖"
            f"（出师线：{realm_name}境）。"
        )
    roster = apprentices(ctx)
    lines.append(f"徒弟 {len(roster)}/{rule(ctx).max_apprentices} 名。")
    if roster:
        lines.append(f"今日传道 {lessons_today(ctx)}/{rule(ctx).lesson.daily_limit} 次。")
        links.append(InlineCommand(len(lines) - 1, "查看可传道徒弟", f"{TITLE} 传道"))
    for user_id in roster:
        peer = ctx.repo.player(user_id)
        if peer is None:
            continue
        ready = realm_index(ctx, user_id) >= graduate_index
        reached = ctx.content.realms[realm_index(ctx, user_id)].name
        lines.append(
            f"{peer.uid_label} · 伙伴已达{reached}境{' · 可出师' if ready else ''}"
        )
        links.append(InlineCommand(len(lines) - 1, "逐出", f"{TITLE} 逐出 {peer.uid}"))
    pending = requests(ctx)
    if pending:
        lines.append("待我处理的拜师帖：")
        for user_id, until in pending:
            peer = ctx.repo.player(user_id)
            if peer is None:
                continue
            lines.append(f"{peer.uid_label} · 剩 {max(0, until - ctx.now) // 3600} 小时")
            links.append(InlineCommand(len(lines) - 1, "同意", f"{TITLE} 同意 {peer.uid}"))
            links.append(InlineCommand(len(lines) - 1, "拒绝", f"{TITLE} 拒绝 {peer.uid}"))
    return Reply(TITLE, tuple(lines), (TITLE, "我的灵宠", "灵宠帮助"), tuple(links[:8]))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head, rest = parts[0], " ".join(parts[1:])
    if head == "同意":
        return accept(ctx, rest)
    if head == "拒绝":
        return reject(ctx, rest)
    if head == "逐出":
        return expel(ctx, rest)
    if head == "出师":
        return graduate(ctx, rest)
    if head == "传道":
        return lesson_page(ctx, rest) if not rest.strip() else lesson(ctx, rest)
    return ask(ctx, " ".join(parts))


def objective_line(ctx: Context, user_id: str) -> str:
    """Only a live relation is worth a line; a graduated player has nothing to track."""
    if ctx.repo.player(user_id) is None:
        return "师徒：尚未结契"
    mentor_id = mentor_of(ctx, user_id)
    if mentor_id is not None:
        return f"师徒：在 {_label(ctx, mentor_id)} 门下"
    if graduated(ctx, user_id):
        return "师徒：已出师"
    roster = len(apprentices(ctx, user_id))
    if roster:
        return f"师徒：门下 {roster}/{rule(ctx).max_apprentices} 名徒弟"
    return "师徒：尚未拜师"


__all__ = [
    "APPRENTICE", "GRADUATED", "LESSON", "LINK", "REQUEST", "TITLE", "accept", "apprentices", "ask",
    "dispatch", "expel", "graduate", "graduated", "lesson", "lesson_page", "lessons_today",
    "mentor_of", "page", "realm_index", "reject", "requests", "taught",
]
