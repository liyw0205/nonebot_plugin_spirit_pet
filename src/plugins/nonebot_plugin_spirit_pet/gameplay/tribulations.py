"""Tribulation contracts: three weekly dungeons, each under one numeric modifier.

State lives in the existing ``quest_progress`` table:

* ``trib_<week_start>_<slot>`` — 1 once that slot's first clear has paid
* ``trib_<week_start>_all`` — 1 once the all-three bonus has paid

The weekly lineup is deterministic: dungeon and modifier are picked from the content by the
week index, so every player sees the same three contracts and they rotate next week.
"""

import math

from ..application.context import Context
from ..domain.content import Dungeon, Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.tribulation_content import Tribulation, TribulationModifier
from ..utils.time import beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

SLOT_KEY = "trib_"


def config(ctx: Context) -> Tribulation:
    return sorted(ctx.content.tribulations.values(), key=lambda entry: entry.id)[0]


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _dungeons(ctx: Context) -> list[Dungeon]:
    return sorted(ctx.content.dungeons.values(), key=lambda entry: entry.id)


def contracts(ctx: Context) -> list[tuple[int, Dungeon, TribulationModifier]]:
    entry = config(ctx)
    dungeons = _dungeons(ctx)
    start = week_start(ctx)
    picked = []
    for slot in range(entry.slots):
        dungeon = dungeons[(start // 86400 + slot * 7) % len(dungeons)]
        modifier = entry.modifiers[(start // 86400 + slot * 2) % len(entry.modifiers)]
        picked.append((slot + 1, dungeon, modifier))
    return picked


def _key(start: int, slot: int) -> str:
    return f"{SLOT_KEY}{start}_{slot}"


def cleared(ctx: Context, slot: int, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(week_start(ctx), slot)),
    ).fetchone()
    return row is not None


def all_cleared(ctx: Context, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{SLOT_KEY}{week_start(ctx)}_all"),
    ).fetchone()
    return row is not None


def cleared_count(ctx: Context, user_id: str | None = None) -> int:
    return sum(1 for slot, _, _ in contracts(ctx) if cleared(ctx, slot, user_id))


def energy_cost(ctx: Context, modifier: TribulationModifier) -> int:
    return max(1, math.ceil(config(ctx).energy * modifier.energy_multiplier))


def scaled_enemies(ctx: Context, dungeon: Dungeon, modifier: TribulationModifier) -> list:
    enemies = []
    for key in dungeon.enemies:
        base = ctx.content.enemies[key]
        stats = base.stats
        enemies.append(base.model_copy(update={
            "stats": Stats(
                hp=max(1, round(stats.hp * modifier.hp)),
                attack=max(1, round(stats.attack * modifier.attack)),
                defense=max(0, round(stats.defense * modifier.defense)),
                speed=max(1, round(stats.speed * modifier.speed)),
            ),
        }))
    return enemies


def _reward_text(ctx: Context, modifier: TribulationModifier) -> str:
    reward = modifier.reward
    parts = [f"修为 {reward.exp.minimum}", f"灵石 {reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠劫境 [挑战 <1-3>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠劫境",
            (
                "尚未结契，先完成领养，才能接下劫境契约。",
                "每周三份契约：一份秘境配一个词缀，难度与奖励各不相同。",
                "每份契约每周首通发奖，三份全清另有一份周奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = config(ctx)
    lines = [f"劫境：本周已清 {cleared_count(ctx)}/{entry.slots} 份契约（北京时间周一 00:00 更换）。"]
    links = []
    for slot, dungeon, modifier in contracts(ctx):
        cost = energy_cost(ctx, modifier)
        state = "已通关" if cleared(ctx, slot) else "可挑战"
        first = scaled_enemies(ctx, dungeon, modifier)[0]
        limit = f" · {modifier.round_limit} 回合上限" if modifier.round_limit else ""
        lines.append(
            f"{slot}. {dungeon.name} · {modifier.name}（{modifier.description}）{limit}"
            f" · 精力 {cost}/只"
        )
        lines.append(
            f"   敌手 {first.name} 气血 {first.stats.hp} · 攻击 {first.stats.attack}"
            f" · 防御 {first.stats.defense} · 速度 {first.stats.speed}"
            f" · 奖励 {_reward_text(ctx, modifier)} · {state}"
        )
        if not cleared(ctx, slot):
            links.append(InlineCommand(len(lines) - 1, "挑战", f"灵宠劫境 挑战 {slot}"))
    bonus = entry.bonus
    lines.append(
        f"三份全清奖励：修为 {bonus.exp.minimum} · 灵石 {bonus.stones.minimum}"
        + "".join(
            f" · {ctx.content.items[item_id].name} {bounds.minimum}"
            for item_id, bounds in bonus.items.items()
        )
        + ("（已领）" if all_cleared(ctx) else "")
    )
    return Reply("灵宠劫境", tuple(lines), ("灵宠劫境", "灵宠秘境", "灵宠战报"), tuple(links))


def _slot(ctx: Context, text: str) -> tuple[int, Dungeon, TribulationModifier]:
    value = text.strip()
    if not value.isdecimal():
        raise GameError("格式：灵宠劫境 挑战 <1-3>。")
    slot = int(value)
    for number, dungeon, modifier in contracts(ctx):
        if number == slot:
            return number, dungeon, modifier
    raise GameError(f"劫境只有 {config(ctx).slots} 份契约。")


def challenge(ctx: Context, arg: str) -> Reply:
    entry = config(ctx)
    if not arg.strip():
        raise GameError("格式：灵宠劫境 挑战 <1-3>。")
    slot, dungeon, modifier = _slot(ctx, arg)
    if cleared(ctx, slot):
        raise GameError(f"第 {slot} 份契约本周已通关。")
    player = ctx.player()
    cost = energy_cost(ctx, modifier)
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    checked = False
    for _, pet in selected:
        if not checked:
            ctx.check_action(player, pet, "pve", cost, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < cost:
                raise GameError(f"{pet.name}精力不足，本契约需要 {cost} 点。")

    enemies = [enemy_fighter(enemy, ctx.content.skills) for enemy in scaled_enemies(ctx, dungeon, modifier)]
    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    for _, pet in selected:
        pet.energy -= cost
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"{dungeon.name} · {modifier.name} · {battle.rounds} 回合", *battle.lines]
    for _, pet in selected:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    overtime = bool(modifier.round_limit) and battle.rounds > modifier.round_limit
    if battle.winner == 0 and not overtime:
        advance(ctx, "pve")
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (ctx.user_id, _key(week_start(ctx), slot)),
        )
        lines.append(f"第 {slot} 份契约首通：" + "，".join(grant(ctx, modifier.reward)))
        if cleared_count(ctx) >= entry.slots and not all_cleared(ctx):
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, f"{SLOT_KEY}{week_start(ctx)}_all"),
            )
            lines.append("三份契约全清：" + "，".join(grant(ctx, entry.bonus)))
        title = "劫境契约达成"
    elif battle.winner == 0:
        lines.append(f"超过 {modifier.round_limit} 回合上限，本次契约未达成。")
        title = "劫境超时"
    else:
        title = "劫境平局" if battle.winner == -1 else "劫境败退"
        lines.append("本次契约未达成，进度不变。")
    lines.append(f"每只灵宠精力 -{cost}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠劫境", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=_key(week_start(ctx), slot), battle_name=f"劫境·{dungeon.name}",
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠劫境 [挑战 <1-3>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    return f"劫境：本周 {cleared_count(ctx, user_id)}/{config(ctx).slots} 已清"
