"""Pet race: a scored, non-combat contest derived from a pet's final stats.

No fight, no RNG: each track weights the four stats and boosts one of them through its ``terrain``
entry, the weighted total becomes speed, and the track length divides it into a time in tenths of
a second. Because the stats come from ``loadout.combatant``, every other system (mood, sect,
tempering, gear, combos, specialization, ascension) feeds the race for free.

Only two rows are stored, both in ``quest_progress``:

* ``race_best_<week_start>`` — this week's best time in tenths of a second
* ``race_day_<beijing date>`` — runs used today
"""

from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day, beijing_week
from .loadout import combatant
from .pet_targets import pet_id

BEST_KEY = "race_best_"
DAY_KEY = "race_day_"
STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def rule(ctx: Context):
    return ctx.content.rules.race


def tracks(ctx: Context):
    return sorted(ctx.content.races.values(), key=lambda track: track.id)


def track(ctx: Context, now: int | None = None):
    """Today's track: identical for every player, rotating once per Beijing day."""
    listed = tracks(ctx)
    day = date.fromisoformat(beijing_day(now if now is not None else ctx.now)).toordinal()
    return listed[day % len(listed)]


def _best_key(ctx: Context, now: int | None = None) -> str:
    return f"{BEST_KEY}{beijing_week(now if now is not None else ctx.now)[0]}"


def _day_key(ctx: Context, now: int | None = None) -> str:
    return f"{DAY_KEY}{beijing_day(now if now is not None else ctx.now)}"


def weekly_best(ctx: Context, user_id: str | None = None, now: int | None = None) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _best_key(ctx, now)),
    ).fetchone()
    return None if row is None else int(row["progress"])


def runs_today(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _day_key(ctx)),
    ).fetchone()
    return int(row["progress"]) if row else 0


def remaining_today(ctx: Context, user_id: str | None = None) -> int:
    return max(0, rule(ctx).daily_limit - runs_today(ctx, user_id))


def time_text(tenths: int) -> str:
    return f"{tenths / 10:.1f} 秒"


def weights_text(ctx: Context) -> str:
    return "、".join(
        f"{STAT_LABELS[stat]} {weight:.0%}" for stat, weight in rule(ctx).weights.items()
    )


def terrain_text(ctx: Context, entry) -> str:
    return f"{STAT_LABELS[entry.terrain.stat]} ×{entry.terrain.multiplier:g}"


def _stats(ctx: Context, pet, user_id: str | None = None):
    return combatant(ctx, user_id or ctx.user_id, pet_id=pet.pet_id, recover_energy=False).stats


def time_of(ctx: Context, pet, entry, user_id: str | None = None) -> int:
    """Race time in tenths of a second: weighted stats over the track length, deterministic."""
    stats = _stats(ctx, pet, user_id)
    total = 0.0
    for stat, weight in rule(ctx).weights.items():
        value = getattr(stats, stat)
        if stat == entry.terrain.stat:
            value = value * entry.terrain.multiplier
        total += value * weight
    return max(1, round(entry.length * 100 / max(total, 1.0)))


def _pets(ctx: Context, user_id: str | None = None):
    return sorted(ctx.repo.owned_pets(user_id or ctx.user_id), key=lambda pet: pet.pet_id)


def _rank(ctx: Context, user_id: str | None = None, now: int | None = None) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT ranked FROM ("
        "SELECT progress.user_id AS user_id,"
        " ROW_NUMBER() OVER (ORDER BY progress.progress ASC, identity.id ASC) AS ranked"
        " FROM quest_progress progress JOIN player_identity identity USING(user_id)"
        " WHERE progress.quest_id=?"
        ") WHERE user_id=?",
        (_best_key(ctx, now), user_id or ctx.user_id),
    ).fetchone()
    return int(row["ranked"]) if row is not None else None


def _board_rows(ctx: Context, now: int | None = None, limit: int = 3):
    return ctx.repo.conn.execute(
        "SELECT identity.id + 9999 AS uid, progress.progress AS time, progress.user_id AS user_id"
        " FROM quest_progress progress JOIN player_identity identity USING(user_id)"
        " WHERE progress.quest_id=?"
        " ORDER BY progress.progress ASC, identity.id ASC LIMIT ?",
        (_best_key(ctx, now), limit),
    ).fetchall()


def board(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠竞速榜 不接受参数，直接发送即可。")
    entry = track(ctx)
    rows = _board_rows(ctx)
    lines = [f"本周赛道：{entry.name}（{entry.length} 米 · 地形 {terrain_text(ctx, entry)}）。"]
    lines.extend(
        f"{index}. UID {row['uid']} · 最好 {time_text(row['time'])}"
        for index, row in enumerate(rows, 1)
    )
    if not rows:
        lines.append("本周尚无人留下成绩，成为第一个上板的伙伴主人吧。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠竞速榜", tuple(lines), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))
    best = weekly_best(ctx)
    rank = _rank(ctx)
    if best is None:
        lines.append("你本周尚未参赛。")
    else:
        lines.append(f"你的最好成绩 {time_text(best)}，本周第 {rank} 名。")
    lines.append("每周一按北京时间重置，上周成绩留在档案里不再参与排名。")
    return Reply("灵宠竞速榜", tuple(lines), ("灵宠竞速", "灵宠目标"), ())


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠竞速 [报名 <伙伴编号>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠竞速",
            (
                "尚未结契，先完成领养，才能带伙伴参赛。",
                "竞速不看运气：伙伴的最终四维决定用时，速度权重最高。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = track(ctx)
    cost = rule(ctx).energy
    remaining = remaining_today(ctx)
    best = weekly_best(ctx)
    lines = [
        f"本周赛道：{entry.name}（{entry.length} 米 · 地形 {terrain_text(ctx, entry)}）——{entry.description}",
        f"用时按四维加权换算：{weights_text(ctx)}；地形属性按倍率计入。",
        f"每次报名消耗 {cost} 点精力，今日剩余 {remaining}/{rule(ctx).daily_limit} 次"
        + (f"，本周最好 {time_text(best)}（第 {_rank(ctx)} 名）。" if best is not None else "，本周尚未参赛。"),
    ]
    links = []
    for pet in _pets(ctx):
        projected = time_of(ctx, pet, entry)
        if ctx.repo.active_expedition(pet.pet_id) is not None:
            state = "外出中"
        elif pet.energy < cost:
            state = f"精力不足（{pet.energy}/{cost}）"
        elif remaining <= 0:
            state = "今日次数已用尽"
        else:
            state = "可报名"
        lines.append(
            f"{pet.name}（编号 {pet.pet_id}）· 预计 {time_text(projected)} · {state}"
        )
        if state == "可报名":
            links.append(InlineCommand(len(lines) - 1, "报名", f"灵宠竞速 报名 {pet.pet_id}"))
    lines.append("格式：灵宠竞速 报名 <伙伴编号>。")
    return Reply("灵宠竞速", tuple(lines), ("灵宠竞速", "灵宠竞速榜", "我的灵宠"), tuple(links))


def enter(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠竞速 报名 <伙伴编号>。")
    target = pet_id(arg.strip())
    pet = next((owned for owned in _pets(ctx) if owned.pet_id == target), None)
    if pet is None:
        archived = ctx.repo.conn.execute(
            "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1", (ctx.user_id, target),
        ).fetchone()
        if archived is not None:
            raise GameError(f"{archived['name']}已封存，请先复原后再报名。")
        raise GameError("没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
    ctx.require_idle_pet(pet)
    cost = rule(ctx).energy
    if remaining_today(ctx) <= 0:
        raise GameError(f"今日报名次数已用尽（每日 {rule(ctx).daily_limit} 次，北京时间 00:00 刷新）。")
    if pet.energy < cost:
        raise GameError(f"{pet.name}精力不足：报名需要 {cost} 点，当前 {pet.energy} 点。")

    entry = track(ctx)
    tenths = time_of(ctx, pet, entry)
    pet.energy -= cost
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, _day_key(ctx), runs_today(ctx) + 1),
    )
    previous = weekly_best(ctx)
    improved = previous is None or tenths < previous
    if improved:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (ctx.user_id, _best_key(ctx), tenths),
        )
    ctx.repo.invalidate_ready(ctx.user_id)
    best_now = weekly_best(ctx)
    assert best_now is not None
    lines = [
        f"{pet.name}在{entry.name}跑出 {time_text(tenths)}（{entry.length} 米），精力 -{cost}。",
        f"本周最好 {time_text(best_now)}"
        + (f"，比上次快 {time_text(previous - tenths)}。" if improved and previous is not None else "。" if improved else "，本次未超越，不计入最好成绩。"),
        f"本次名次：本周第 {_rank(ctx)} 名；今日剩余 {remaining_today(ctx)} 次。",
    ]
    return Reply("竞速成绩", tuple(lines), ("灵宠竞速", "灵宠竞速榜", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "报名":
        return enter(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠竞速 [报名 <伙伴编号>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "竞速：尚未结契"
    best = weekly_best(ctx, user_id)
    if best is None:
        return "竞速：本周尚未参赛"
    return f"竞速：本周最好 {time_text(best)}"
