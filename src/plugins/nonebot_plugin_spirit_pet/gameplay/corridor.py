"""Endless corridor: one floor per call, with a cash-out decision between floors.

State lives in the existing ``quest_progress`` table:

* ``corridor_floor`` — the next floor to fight (an absent row means no run)
* ``corridor_best_<Beijing week start>`` — deepest floor cleared this week

Route choices freeze the current segment's modifiers. Pending stones/experience
store the amount actually earned; old floor-only saves still derive their totals
until their next successful battle.
"""

import json
from dataclasses import replace

from ..application.context import Context
from ..domain.content import Range, Reward, Stats
from ..domain.corridor_content import Corridor, CorridorPath
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.time import beijing_week
from . import corridor_paths
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

FLOOR_KEY = "corridor_floor"
BEST_PREFIX = "corridor_best_"
STONES_KEY = "corridor_pending_stones"
EXP_KEY = "corridor_pending_exp"


def corridor(ctx: Context) -> Corridor:
    return sorted(ctx.content.corridor.values(), key=lambda entry: entry.id)[0]


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def floor_of(ctx: Context, user_id: str | None = None) -> int | None:
    """The next floor to fight, or ``None`` when no run is active."""
    value = _progress(ctx, FLOOR_KEY, user_id)
    return value or None


def best_of(ctx: Context, user_id: str | None = None) -> int:
    return _progress(ctx, f"{BEST_PREFIX}{week_start(ctx)}", user_id)


def cleared(floor: int) -> int:
    return max(0, floor - 1)


def pending_stones(ctx: Context, cleared_floors: int) -> int:
    entry = corridor(ctx)
    return sum(entry.stones_at(floor) for floor in range(1, cleared_floors + 1))


def pending_exp(ctx: Context, cleared_floors: int) -> int:
    entry = corridor(ctx)
    return sum(entry.exp_at(floor) for floor in range(1, cleared_floors + 1))


def earned(ctx: Context, reached: int) -> tuple[int, int]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id IN (?, ?)",
        (ctx.user_id, STONES_KEY, EXP_KEY),
    ).fetchall()
    values = {row["quest_id"]: row["progress"] for row in rows}
    if not values:
        return pending_stones(ctx, reached), pending_exp(ctx, reached)
    if len(values) != 2:
        raise GameError("回廊待领奖励记录不完整，请联系管理员检查。")
    return values[STONES_KEY], values[EXP_KEY]


def _add_earned(ctx: Context, floor: int, path: CorridorPath) -> None:
    stones, exp = earned(ctx, floor - 1)
    entry = corridor(ctx)
    values = (
        (STONES_KEY, stones + entry.stones_at(floor) * path.reward_percent // 100),
        (EXP_KEY, exp + entry.exp_at(floor) * path.reward_percent // 100),
    )
    ctx.repo.conn.executemany(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        [(ctx.user_id, key, value) for key, value in values],
    )


def milestones_reached(ctx: Context, cleared_floors: int) -> dict[str, int]:
    totals: dict[str, int] = {}
    for milestone in corridor(ctx).milestones:
        if milestone.floor <= cleared_floors:
            for item_id, amount in milestone.items.items():
                totals[item_id] = totals.get(item_id, 0) + amount
    return totals


def scaled_enemy(ctx: Context, floor: int, path: CorridorPath | None = None):
    entry = corridor(ctx)
    base = ctx.content.enemies[entry.base_enemy]
    rates = entry.scaling

    def factor(rate: float) -> float:
        return (1 + rate) ** (floor - 1)

    stats = base.stats
    scaled = Stats(
        hp=max(1, round(stats.hp * factor(rates.hp))),
        attack=max(1, round(stats.attack * factor(rates.attack))),
        defense=max(0, round(stats.defense * factor(rates.defense))),
        speed=max(1, round(stats.speed * factor(rates.speed))),
    )
    if path is not None:
        scaled = scaled.model_copy(update={
            field: max(1, getattr(scaled, field) * getattr(path, f"{field}_percent") // 100)
            for field in ("hp", "attack", "speed")
        })
    return base.model_copy(update={
        "name": f"{base.name}{floor}层",
        "stats": scaled,
    })


def _reward_text(ctx: Context, stones: int, exp: int, items: dict[str, int]) -> str:
    parts = [f"灵石 {stones}", f"修为 {exp}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in items.items()
    )
    return " · ".join(parts)


def _settle(ctx: Context, cleared_floors: int, *, full: bool) -> tuple[str, ...]:
    """Pay the run out; a defeat halves stones/exp and drops every milestone."""
    stones, exp = earned(ctx, cleared_floors)
    items = milestones_reached(ctx, cleared_floors) if full else {}
    if not full:
        stones //= 2
        exp //= 2
    if not (stones or exp or items):
        return ("本次未积累奖励。",)
    reward = Reward(
        exp=Range(minimum=exp, maximum=exp),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )
    return grant(ctx, reward)


def _write_best(ctx: Context, reached: int) -> None:
    if reached <= best_of(ctx):
        return
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{BEST_PREFIX}{week_start(ctx)}", reached),
    )


def _clear_run(ctx: Context) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id IN (?, ?, ?)",
        (ctx.user_id, FLOOR_KEY, STONES_KEY, EXP_KEY),
    )
    corridor_paths.clear(ctx)


def _can_fight(ctx: Context, path: CorridorPath) -> bool:
    try:
        pets = _idle_roster(ctx)
    except GameError:
        return False
    for pet in pets:
        preview = replace(pet)
        restore_energy(preview, ctx.now, ctx.config.spirit_pet_energy_interval)
        if preview.energy < path.energy:
            return False
    return True


def _idle_roster(ctx: Context):
    ctx.player()
    pets = ctx.repo.active_pets(ctx.user_id)
    if not pets:
        raise ctx.missing_pet()
    for pet in pets:
        if pet.archived:
            raise ctx.archived_active_pet(pet, ctx.user_id)
        ctx.require_idle_pet(pet)
    return pets


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠回廊 [挑战|收手|择路 层数 路线]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠回廊",
            (
                "尚未结契，先完成领养，才能踏入回廊。",
                "回廊一层比一层凶险，每胜一层都会累积待领奖励。",
                "随时可以收手兑现；战败只能拿回一半，且拿不到里程碑。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = corridor(ctx)
    current = floor_of(ctx)
    reached = cleared(current) if current else 0
    stones, exp = earned(ctx, reached)
    path = corridor_paths.current(ctx, entry, current or 1)
    items = milestones_reached(ctx, reached)
    lines = [
        f"{entry.name}：共 {entry.max_floor} 层，常道每只灵宠每层精力 {entry.energy}。",
        entry.description,
        f"当前：第 {current if current else 1} 层待战 · 已清 {reached} 层"
        f" · 待领 {_reward_text(ctx, stones, exp, items)}",
        f"本周最深：{best_of(ctx)} 层。",
    ]
    preview_floor = min(current or 1, entry.max_floor)
    preview = scaled_enemy(ctx, preview_floor, path)
    lines.append(
        f"下一层：{preview.name} · 气血 {preview.stats.hp} · 攻击 {preview.stats.attack}"
        f" · 防御 {preview.stats.defense} · 速度 {preview.stats.speed}"
    )
    upcoming = [milestone.floor for milestone in entry.milestones if milestone.floor > reached]
    if upcoming:
        lines.append(f"下一个里程碑：第 {upcoming[0]} 层。")
    else:
        lines.append("里程碑已全部达成。")
    commands = ["灵宠回廊"]
    links = []
    can_fight = _can_fight(ctx, path)
    if current is None and can_fight:
        lines.append("入廊：每次挑战只打一层，胜利后可继续或收手。")
        links.append(InlineCommand(len(lines) - 1, "挑战", "灵宠回廊 挑战"))
    elif current is None:
        lines.append("伙伴外出或精力不足：先休整或更换出战伙伴，再入回廊。")
    elif current is not None:
        if can_fight:
            links.append(InlineCommand(2, "挑战", "灵宠回廊 挑战"))
        if reached:
            links.append(InlineCommand(2, "收手", "灵宠回廊 收手"))
        if not can_fight:
            lines.append("伙伴外出或精力不足：先休整或更换出战伙伴，再继续深入。")
    start = corridor_paths.segment_start(preview_floor)
    lines.append(
        f"本段 {start}-{min(start + 4, entry.max_floor)} 层：{corridor_paths.describe(path)}。"
    )
    if preview_floor == start and path.id == "common":
        lines.append("可择路：本段首次挑战后锁定；直接挑战沿常道前进。")
        try:
            _idle_roster(ctx)
        except GameError:
            available = False
        else:
            available = True
        for option in entry.paths:
            lines.append(corridor_paths.describe(option))
            if available:
                links.append(InlineCommand(
                    len(lines) - 1, "择路", f"灵宠回廊 择路 {preview_floor} {option.name}",
                ))
    commands.extend(("灵宠战报", "我的灵宠"))
    return Reply("灵宠回廊", tuple(lines), tuple(commands), tuple(links))


def _prior_reply(ctx: Context) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or not str(row["battle_key"]).startswith("corridor_"):
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def challenge(ctx: Context, arg: str) -> Reply:
    if arg.strip() and arg.strip() != "挑战":
        raise GameError("格式：灵宠回廊 挑战。")
    corridor_paths.check_receipt(ctx)
    prior = _prior_reply(ctx)
    if prior is not None:
        return prior
    entry = corridor(ctx)
    current = floor_of(ctx)
    if current is not None and current > entry.max_floor:
        raise GameError(f"{entry.name}已到尽头，请先收手。")
    floor = current or 1
    path = corridor_paths.current(ctx, entry, floor)
    player = ctx.player()
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    for _, pet in selected:
        ctx.require_idle_pet(pet)
        if pet.energy < path.energy:
            raise GameError(f"{pet.name}精力不足，{path.name}每层需要 {path.energy} 点。")

    enemy = scaled_enemy(ctx, floor, path)
    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    enemies = [enemy_fighter(enemy, ctx.content.skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    for _, pet in selected:
        pet.energy -= path.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"第{floor}层 · {enemy.name} · {battle.rounds} 回合", corridor_paths.describe(path), *battle.lines]
    for _, pet in selected:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    if battle.winner == 0:
        _add_earned(ctx, floor, path)
        advance(ctx, "pve")
        reached = floor
        _write_best(ctx, reached)
        if floor >= entry.max_floor:
            settled = _settle(ctx, reached, full=True)
            _clear_run(ctx)
            lines.append("已打通回廊尽头：" + "，".join(settled))
            title = "回廊通关"
        else:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
                " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
                (ctx.user_id, FLOOR_KEY, floor + 1),
            )
            stones, exp = earned(ctx, reached)
            items = milestones_reached(ctx, reached)
            lines.append(f"已清 {reached} 层，待领 {_reward_text(ctx, stones, exp, items)}。")
            lines.append("继续挑战会更深更险；收手可立即兑现。")
            if (floor + 1) % corridor_paths.SEGMENT_SIZE == 1:
                lines.append("前方是新一段岔路，可打开回廊择路，或直接沿常道继续。")
            title = "回廊深入"
    else:
        reached = max(0, floor - 1)
        _write_best(ctx, reached)
        settled = _settle(ctx, reached, full=False)
        _clear_run(ctx)
        lines.append("本次战败，只能取回一半：" + "，".join(settled))
        title = "回廊败退" if battle.winner == 1 else "回廊平局"

    lines.append(f"每只灵宠精力 -{path.energy}；气血仅在本场战斗内结算。")
    commands = ("灵宠回廊", "灵宠战报", "我的灵宠")
    reply = Reply(title, tuple(lines), commands)
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=f"corridor_{floor}", battle_name=f"回廊第{floor}层",
    )
    return reply


def cash_out(ctx: Context, arg: str) -> Reply:
    if arg.strip() and arg.strip() != "收手":
        raise GameError("格式：灵宠回廊 收手。")
    corridor_paths.check_receipt(ctx)
    current = floor_of(ctx)
    if current is None:
        raise GameError("当前没有进行中的回廊，先发送 灵宠回廊 挑战。")
    reached = cleared(current)
    if reached <= 0:
        raise GameError("尚未通过任何一层，没有可兑现的奖励。")
    stones_before, exp_before = earned(ctx, reached)
    settled = _settle(ctx, reached, full=True)
    _write_best(ctx, reached)
    _clear_run(ctx)
    corridor_paths.mark_receipt(ctx, reached)
    lines = [
        f"收手兑现：已清 {reached} 层，灵石 {stones_before} · 修为 {exp_before}。",
        "奖励已发放：" + "，".join(settled),
        f"本周最深：{best_of(ctx)} 层。",
    ]
    return Reply("灵宠回廊", tuple(lines), ("灵宠回廊", "灵宠战报", "我的灵宠"))


def choose_path(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2 or len(parts[0]) > 2 or not parts[0].isascii() or not parts[0].isdecimal():
        raise GameError("格式：灵宠回廊 择路 层数 路线，例如 灵宠回廊 择路 1 疾行道。")
    corridor_paths.check_receipt(ctx)
    entry = corridor(ctx)
    floor = floor_of(ctx) or 1
    if int(parts[0]) != floor or floor != corridor_paths.segment_start(floor) or floor > entry.max_floor:
        raise GameError("该岔路已过期，只能在每段首层挑战前择路，请重新打开 灵宠回廊。")
    if corridor_paths.current(ctx, entry, floor).id != "common":
        raise GameError("本段已经择路，下一段开始前不能更换。")
    path = next((path for path in entry.paths if parts[1] in (path.id, path.name)), None)
    if path is None:
        raise GameError("未知回廊路线，请重新打开 灵宠回廊。")
    _idle_roster(ctx)
    corridor_paths.save(ctx, floor, path)
    corridor_paths.mark_receipt(ctx, floor)
    return page(ctx, "")


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    if parts[0] == "收手":
        return cash_out(ctx, " ".join(parts[1:]))
    if parts[0] == "择路":
        return choose_path(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠回廊 [挑战|收手|择路 层数 路线]。")


def objective_line(ctx: Context, user_id: str) -> str:
    current = floor_of(ctx, user_id)
    best = best_of(ctx, user_id)
    path = corridor_paths.current(ctx, corridor(ctx), current or 1, user_id)
    if current is None:
        choice = f" · 已择{path.name}" if path.id != "common" else ""
        return f"回廊：本周最深 {best} 层 · 尚未入廊{choice}"
    choice = " · 可择路" if current == corridor_paths.segment_start(current) and path.id == "common" else ""
    return f"回廊：本周最深 {best} 层 · 第 {current} 层待战 · {path.name}{choice}"
