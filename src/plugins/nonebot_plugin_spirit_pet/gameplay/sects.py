"""Spirit sects: one persistent sect per player, daily practice, contribution ranks.

State lives in the existing ``quest_progress`` table:

* ``sect_member_<id>`` — joined (kept when switching)
* ``sect_current_<id>`` — the active sect
* ``sect_contrib_<id>`` — contribution points toward ranks
* ``sect_day_<Beijing date>`` — today's practice flag
* ``sect_claim_<id>_<rank>`` — one-time rank reward claimed

The passive is derived, never stored: ``passive`` reports the current rank's rate
and ``loadout.combatant`` applies it to that owner's pets.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.sect_content import Sect, SectRank
from ..utils.arguments import named
from ..utils.time import beijing_day

MEMBER = "sect_member_"
CURRENT = "sect_current_"
CONTRIB = "sect_contrib_"
DAY = "sect_day_"
CLAIM = "sect_claim_"


def sects(ctx: Context) -> list[Sect]:
    return sorted(ctx.content.sects.values(), key=lambda sect: sect.id)


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _set(ctx: Context, key: str, value: int, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user_id or ctx.user_id, key, value),
    )


def joined(ctx: Context, user_id: str | None = None) -> set[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{MEMBER}%"),
    )
    return {row["quest_id"][len(MEMBER):] for row in rows}


def current(ctx: Context, user_id: str | None = None) -> Sect | None:
    for sect in sects(ctx):
        if _progress(ctx, f"{CURRENT}{sect.id}", user_id):
            return sect
    return None


def contribution(ctx: Context, sect: Sect, user_id: str | None = None) -> int:
    return _progress(ctx, f"{CONTRIB}{sect.id}", user_id)


def rank_of(ctx: Context, sect: Sect, user_id: str | None = None) -> SectRank:
    return sect.rank_at(contribution(ctx, sect, user_id))


def practiced_today(ctx: Context, user_id: str | None = None) -> bool:
    return bool(_progress(ctx, f"{DAY}{beijing_day(ctx.now)}", user_id))


def claimed(ctx: Context, sect: Sect, entry: SectRank, user_id: str | None = None) -> bool:
    return bool(_progress(ctx, f"{CLAIM}{sect.id}_{entry.rank}", user_id))


def claimable(ctx: Context, sect: Sect, user_id: str | None = None) -> list[SectRank]:
    reached = rank_of(ctx, sect, user_id).rank
    return [
        entry for entry in sect.ranks
        if entry.rank <= reached and not claimed(ctx, sect, entry, user_id)
    ]


def passive(ctx: Context, user_id: str | None = None) -> tuple[str, float] | None:
    """(stat, rate) for the owner's current sect and rank, or None when sectless."""
    sect = current(ctx, user_id)
    if sect is None:
        return None
    return sect.stat, rank_of(ctx, sect, user_id).rate


def _passive_text(sect: Sect, entry: SectRank) -> str:
    labels = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
    return f"{labels[sect.stat]} +{entry.rate:.0%}"


def _ladder_text(sect: Sect) -> str:
    return "/".join(f"{entry.rate:.0%}" for entry in sect.ranks)


def _progress_text(sect: Sect, entry: SectRank, points: int) -> str:
    following = next((item for item in sect.ranks if item.rank == entry.rank + 1), None)
    if following is None:
        return f"贡献 {points}（已满阶）"
    return f"贡献 {points}/{following.contribution}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 [拜入|修行|领赏] [门派]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠师门",
            (
                "尚未结契，先完成领养，才能拜入师门。",
                "师门给一份随阶位成长的被动：剑阁加攻击、玄门加气血、丹鼎门加防御、御兽宗加速度。",
                "每日修行一次积累贡献，贡献提升阶位，阶位可领一次性奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    player = ctx.player()
    member = current(ctx)
    lines = []
    links = []
    if member is None:
        lines.append("尚未拜入师门：首次拜入免费，只能选一门。")
        for sect in sects(ctx):
            lines.append(f"{sect.name} · {_passive_text(sect, sect.ranks[0])} 起 · 阶位加成 {_ladder_text(sect)}")
            links.append(InlineCommand(len(lines) - 1, "拜入", f"灵宠师门 拜入 {sect.name}"))
        lines.append("拜入后可每日修行积累贡献；转投他派需 500 灵石，各派贡献分别保留。")
        return Reply("灵宠师门", tuple(lines), ("灵宠师门", "我的灵宠", "灵宠目标"), tuple(links))

    entry = rank_of(ctx, member)
    points = contribution(ctx, member)
    pending = claimable(ctx, member)
    lines.append(
        f"当前：{member.name} · {entry.rank} 阶 · {_passive_text(member, entry)}"
        f" · {_progress_text(member, entry, points)}"
    )
    lines.append(member.description)
    lines.append(f"阶位加成：{_ladder_text(member)}（随贡献提升）。")
    state = "今日已修行" if practiced_today(ctx) else "今日可修行"
    lines.append(
        f"每日修行：{state} · 消耗精力 {ctx.content.rules.sect.practice_energy}"
        f" · 贡献 +{ctx.content.rules.sect.daily_contribution}"
        f" · 修为 +{ctx.content.rules.sect.practice_exp}。"
    )
    if pending:
        lines.append(f"可领阶位奖励：{'、'.join(str(item.rank) for item in pending)} 阶。")
        links.append(InlineCommand(len(lines) - 1, "领赏", "灵宠师门 领赏"))
    else:
        lines.append("暂无可领阶位奖励。")
    if not practiced_today(ctx):
        links.append(InlineCommand(3, "修行", "灵宠师门 修行"))
    lines.append(f"转投他派：{ctx.content.rules.sect.switch_stones} 灵石，各派贡献分别保留。")
    others = "、".join(sect.name for sect in sects(ctx) if sect.id != member.id)
    lines.append(f"其他门派：{others}（灵宠师门 拜入 <门派>）。")
    return Reply("灵宠师门", tuple(lines), ("灵宠师门", "我的灵宠", "灵宠目标"), tuple(links))


def join(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠师门 拜入 <门派>。")
    sect = named(ctx.content.sects, text)
    member = current(ctx)
    if member is not None and member.id == sect.id:
        raise GameError(f"你已在{sect.name}门下。")
    cost = ctx.content.rules.sect.switch_stones
    if member is not None:
        if cost and player.stones < cost:
            raise GameError(f"转投师门需要 {cost} 灵石，当前 {player.stones}。")
        player.stones -= cost
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
            (ctx.user_id, f"{CURRENT}%"),
        )
    _set(ctx, f"{MEMBER}{sect.id}", 1)
    _set(ctx, f"{CURRENT}{sect.id}", 1)
    entry = rank_of(ctx, sect)
    lines = [
        f"已拜入{sect.name}：{_passive_text(sect, entry)}（{entry.rank} 阶）。"
        + (f"转投消耗灵石 {cost}。" if member is not None else "首次拜入不消耗灵石。"),
        f"{_progress_text(sect, entry, contribution(ctx, sect))}，每日修行可积累贡献。",
        sect.description,
    ]
    return Reply("灵宠师门", tuple(lines), ("灵宠师门", "我的灵宠", "灵宠目标"))


def practice(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 修行。")
    player = ctx.player()
    sect = current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，先发送 灵宠师门 拜入 <门派>。")
    if practiced_today(ctx):
        raise GameError("今日已修行，北京时间 00:00 后可再次修行。")
    rules = ctx.content.rules.sect
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    if pet.energy < rules.practice_energy:
        raise GameError(f"{pet.name}精力不足，修行需要 {rules.practice_energy} 点。")

    before = rank_of(ctx, sect).rank
    pet.energy -= rules.practice_energy
    pet.exp += rules.practice_exp
    points = contribution(ctx, sect) + rules.daily_contribution
    _set(ctx, f"{CONTRIB}{sect.id}", points)
    _set(ctx, f"{DAY}{beijing_day(ctx.now)}", 1)
    ctx.repo.invalidate_ready(ctx.user_id)

    entry = rank_of(ctx, sect)
    lines = [
        f"{sect.name}修行：{pet.name} 修为 +{rules.practice_exp}，精力 -{rules.practice_energy}"
        f"（{pet.energy}/100）。",
        f"贡献 +{rules.daily_contribution}，{_progress_text(sect, entry, points)}"
        f" · {entry.rank} 阶 · {_passive_text(sect, entry)}。",
    ]
    if entry.rank > before:
        lines.append(f"阶位提升：{before} 阶 → {entry.rank} 阶，记得 灵宠师门 领赏。")
    return Reply("灵宠师门", tuple(lines), ("灵宠师门", "灵宠目标", "我的灵宠"))


def claim(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 领赏。")
    player = ctx.player()
    sect = current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，暂无可领奖励。")
    pending = claimable(ctx, sect)
    if not pending:
        raise GameError("暂无可领的阶位奖励，先通过修行积累贡献。")
    lines = [f"{sect.name}阶位奖励："]
    for entry in pending:
        player.stones += entry.stones
        parts = [f"灵石 +{entry.stones}"]
        for item_id, amount in entry.items.items():
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            parts.append(f"{ctx.content.items[item_id].name} +{amount}")
        _set(ctx, f"{CLAIM}{sect.id}_{entry.rank}", 1)
        lines.append(f"{entry.rank} 阶：" + "，".join(parts) + f"（{_passive_text(sect, entry)}）。")
    lines.append(f"贡献 {contribution(ctx, sect)} · 阶位 {rank_of(ctx, sect).rank}。")
    return Reply("灵宠师门", tuple(lines), ("灵宠师门", "灵宠目标", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "拜入":
        return join(ctx, " ".join(parts[1:]))
    if parts[0] == "修行":
        return practice(ctx, " ".join(parts[1:]))
    if parts[0] == "领赏":
        return claim(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠师门 [拜入|修行|领赏] [门派]。")


def objective_line(ctx: Context, user_id: str) -> str:
    sect = current(ctx, user_id)
    if sect is None:
        return "师门：尚未拜入"
    entry = rank_of(ctx, sect, user_id)
    return f"师门：{sect.name} {entry.rank} 阶 · {_progress_text(sect, entry, contribution(ctx, sect, user_id))}"
