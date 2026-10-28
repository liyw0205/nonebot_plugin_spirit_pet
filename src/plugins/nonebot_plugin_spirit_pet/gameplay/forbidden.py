"""Weekly forbidden zone: rotating depths behind a lineup restriction.

Progress is weekly and lives in the existing ``quest_progress`` table:

* ``forbidden_<week_start>_<depth_id>`` — ``progress`` = rounds of the clearing win
* ``forbidden_<week_start>_all`` — the all-clear bonus marker

No schema change is needed, and the zone rotation is derived from the Beijing week
start, so the same week always shows the same zone and the next week shifts.
"""

import json

from ..application.context import Context
from ..domain.forbidden_content import ForbiddenDepth, ForbiddenZone
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

PREFIX = "forbidden_"
BONUS = "all"
WEEK = 7 * 86400

RESTRICTIONS = {
    "solo": ("独行", "只允许一只灵宠出战"),
    "duo": ("双生", "只允许两只灵宠出战"),
    "same_element": ("同心", "出战灵宠须同属一种主属性"),
}


def zones(ctx: Context) -> list[ForbiddenZone]:
    return sorted(ctx.content.forbidden.values(), key=lambda zone: zone.id)


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def zone_for(ctx: Context, start: int | None = None) -> ForbiddenZone:
    entries = zones(ctx)
    begin = week_start(ctx) if start is None else start
    return entries[(begin // 86400) % len(entries)]


def next_zone(ctx: Context) -> ForbiddenZone:
    return zone_for(ctx, week_start(ctx) + WEEK)


def restriction(zone: ForbiddenZone) -> tuple[str, str]:
    return RESTRICTIONS[zone.restriction.type]


def _ordered(zone: ForbiddenZone) -> list[ForbiddenDepth]:
    return sorted(zone.depths, key=lambda depth: depth.order)


def _prefix(start: int) -> str:
    return f"{PREFIX}{start}_"


def _cleared(ctx: Context, start: int, user_id: str | None = None) -> set[str]:
    owner = user_id or ctx.user_id
    prefix = _prefix(start)
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{prefix}%"),
    )
    return {
        row["quest_id"][len(prefix):]
        for row in rows
        if row["quest_id"].startswith(prefix)
        and row["quest_id"][len(prefix):] != BONUS
    }


def _bonus_claimed(ctx: Context, start: int, user_id: str | None = None) -> bool:
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (owner, f"{_prefix(start)}{BONUS}"),
    ).fetchone()
    return row is not None


def best_rounds(ctx: Context, depth_id: str, start: int, user_id: str | None = None) -> int | None:
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT MIN(b.rounds) AS best FROM battle_records b"
        " JOIN battle_participants p ON p.battle_id=b.battle_id"
        " WHERE p.user_id=? AND b.kind='pve_stage' AND b.battle_key=?"
        " AND b.winner_side=p.side AND b.played_at>=? AND b.played_at<?",
        (owner, depth_id, start, start + WEEK),
    ).fetchone()
    return None if row is None or row["best"] is None else int(row["best"])


def _realm_name(ctx: Context, realm_id: str) -> str:
    return next(realm.name for realm in ctx.content.realms if realm.id == realm_id)


def _depth(ctx: Context, zone: ForbiddenZone, arg: str) -> ForbiddenDepth:
    value = arg.strip()
    depths = _ordered(zone)
    if not value:
        return depths[0]
    if value.isdecimal():
        order = int(value)
        if not 1 <= order <= len(depths):
            raise GameError(f"禁地层号应为 1-{len(depths)} 的整数。")
        return depths[order - 1]
    for depth in depths:
        if value in (depth.name, depth.id):
            return depth
    for other in zones(ctx):
        if other.id != zone.id and any(value in (d.name, d.id) for d in other.depths):
            raise GameError(f"本周禁地是{zone.name}，只能挑战本周禁地。")
    raise GameError("未找到该禁地层，请填写层号或名称。")


def _state(depth: ForbiddenDepth, zone: ForbiddenZone, cleared: set[str], player) -> str:
    if player is None:
        return "尚未结契"
    if depth.id in cleared:
        return "本周已通关"
    if depth.order == 1 or _ordered(zone)[depth.order - 2].id in cleared:
        return "可挑战"
    return "未解锁"


def _amount(bounds) -> str:
    return f"{bounds.minimum}" if bounds.minimum == bounds.maximum else f"{bounds.minimum}-{bounds.maximum}"


def _reward_text(ctx: Context, reward) -> str:
    parts = []
    if reward.exp.maximum:
        parts.append(f"修为 {_amount(reward.exp)}")
    if reward.stones.maximum:
        parts.append(f"灵石 {_amount(reward.stones)}")
    parts.extend(
        f"{ctx.content.items[key].name} {_amount(bounds)}"
        for key, bounds in reward.items.items()
    )
    return " · ".join(parts)


def _detail(ctx: Context, zone: ForbiddenZone, depth: ForbiddenDepth, player) -> Reply:
    label, rule = restriction(zone)
    cleared = _cleared(ctx, week_start(ctx)) if player is not None else set()
    state = _state(depth, zone, cleared, player)
    best = best_rounds(ctx, depth.id, week_start(ctx)) if player is not None else None
    enemies = "、".join(ctx.content.enemies[key].name for key in depth.enemies)
    techniques = tuple(
        f"{ctx.content.enemies[key].name}招式："
        f"{ctx.content.skills[ctx.content.enemies[key].signature_skill].name}"
        f"（每 {ctx.content.enemies[key].skill_every} 次行动施展）"
        for key in depth.enemies if ctx.content.enemies[key].signature_skill
    )
    commands = []
    if state in ("可挑战", "本周已通关"):
        commands.append(f"灵宠挑战禁地 {depth.order}")
    commands.extend(("灵宠禁地", "灵宠秘境"))
    return Reply(f"{zone.name} · {depth.name}", (
        depth.description,
        f"禁制：{label} · {rule}；进度：{state}。",
        f"{_realm_name(ctx, depth.min_realm)}起 · 精力 {depth.energy} · 敌手：{enemies}",
        *techniques,
        f"本周最佳：{best} 回合" if best is not None else "本周最佳：尚未通关",
        f"单层首通奖励（每周一次）：{_reward_text(ctx, depth.reward)}",
        f"全清奖励（每周一次）：{_reward_text(ctx, zone.bonus)}",
    ), tuple(commands))


def catalog(ctx: Context, arg: str) -> Reply:
    zone = zone_for(ctx)
    player = ctx.repo.player(ctx.user_id)
    if arg.strip():
        return _detail(ctx, zone, _depth(ctx, zone, arg), player)
    start = week_start(ctx)
    cleared = _cleared(ctx, start) if player is not None else set()
    label, rule = restriction(zone)
    depths = _ordered(zone)
    done = sum(1 for depth in depths if depth.id in cleared)
    lines = [
        f"本周禁地：{zone.name}（{label}：{rule}）",
        zone.description,
        f"本周进度：{done}/{len(depths)} 层 · 周一 00:00 换禁地。",
    ]
    links = []
    for depth in depths:
        state = _state(depth, zone, cleared, player)
        best = best_rounds(ctx, depth.id, start) if player is not None else None
        suffix = f" · 本周最佳 {best} 回合" if best is not None else ""
        lines.append(
            f"{depth.order}. {depth.name} · {state} · {_realm_name(ctx, depth.min_realm)}起"
            f" · 精力 {depth.energy}{suffix}"
        )
        if state in ("可挑战", "本周已通关"):
            links.append(InlineCommand(len(lines) - 1, "前往挑战", f"灵宠挑战禁地 {depth.order}"))
    lines.append(f"单层首通奖励每周一次；全清奖励：{_reward_text(ctx, zone.bonus)}。")
    upcoming = next_zone(ctx)
    upcoming_label, upcoming_rule = restriction(upcoming)
    lines.append(f"下周：{upcoming.name}（{upcoming_label}：{upcoming_rule}）。")
    return Reply(
        "灵宠禁地", tuple(lines),
        ("灵宠秘境", "灵宠关卡", "灵宠战报", "我的灵宠"), tuple(links),
    )


def _prior_reply(ctx: Context, depth: ForbiddenDepth) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != depth.id:
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def _check_restriction(ctx: Context, zone: ForbiddenZone, pets) -> None:
    label, rule = restriction(zone)
    if zone.restriction.type == "solo" and len(pets) != 1:
        raise GameError(f"{zone.name}的禁制为{label}：{rule}。")
    if zone.restriction.type == "duo" and len(pets) != 2:
        raise GameError(f"{zone.name}的禁制为{label}：{rule}。")
    if zone.restriction.type == "same_element":
        primary = {ctx.content.species[pet.species_id].primary_element for pet in pets}
        if len(primary) != 1:
            raise GameError(f"{zone.name}的禁制为{label}：{rule}。")


def _require_previous(ctx: Context, zone: ForbiddenZone, depth: ForbiddenDepth, cleared: set[str]) -> None:
    if depth.order > 1:
        previous = _ordered(zone)[depth.order - 2]
        if previous.id not in cleared:
            raise GameError(f"尚未通关前置层：{previous.name}。")


def challenge(ctx: Context, arg: str) -> Reply:
    zone = zone_for(ctx)
    depth = _depth(ctx, zone, arg)
    prior = _prior_reply(ctx, depth)
    if prior is not None:
        return prior
    player = ctx.player()
    pets = ctx.active_pets(ctx.user_id)
    if not pets:
        raise GameError("尚未选择出战灵宠。")
    _check_restriction(ctx, zone, pets)
    start = week_start(ctx)
    _require_previous(ctx, zone, depth, _cleared(ctx, start))
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == depth.min_realm)
    for pet in pets:
        if pet.realm < minimum:
            raise GameError(f"{pet.name}境界不足，{depth.name}需要{ctx.content.realms[minimum].name}。")
    for index, pet in enumerate(pets):
        if index == 0:
            ctx.check_action(player, pet, "pve", depth.energy, ctx.config.spirit_pet_pve_cooldown)
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < depth.energy:
                raise GameError(f"{pet.name}精力不足，需要 {depth.energy} 点。")

    allies = [
        combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id) for pet in pets
    ]
    enemies = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in depth.enemies]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    for pet in pets:
        pet.energy -= depth.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"{zone.name} · {depth.name} · {battle.rounds} 回合", *battle.lines]
    for pet in pets:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    if battle.winner == 0:
        advance(ctx, "pve")
        key = f"{_prefix(start)}{depth.id}"
        inserted = ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (ctx.user_id, key, battle.rounds),
        )
        if inserted.rowcount == 1:
            lines.append(f"{player.uid_label}首通{depth.name}：" + "，".join(grant(ctx, depth.reward)))
            if depth.order == len(zone.depths) and not _bonus_claimed(ctx, start):
                ctx.repo.conn.execute(
                    "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
                    " VALUES (?, ?, ?, 1)",
                    (ctx.user_id, f"{_prefix(start)}{BONUS}", battle.rounds),
                )
                lines.append(f"{zone.name}全清：" + "，".join(grant(ctx, zone.bonus)))
            title = "禁地首通"
        else:
            lines.append("本层本周已通关，本次为再战练习，不重复发放周奖励。")
            title = "禁地再胜"
    else:
        title = "禁地平局" if battle.winner == -1 else "禁地败退"
        lines.append("本次挑战未通关，本周进度不变。")
    lines.append(f"每只灵宠精力 -{depth.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠禁地", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle_key=depth.id, battle_name=f"{zone.name}·{depth.name}",
        battle=battle, capture=capture, reply=reply,
    )
    return reply


def objective_line(ctx: Context, user_id: str) -> str:
    zone = zone_for(ctx)
    cleared = _cleared(ctx, week_start(ctx), user_id)
    depths = _ordered(zone)
    done = sum(1 for depth in depths if depth.id in cleared)
    if done >= len(depths):
        return f"灵宠禁地：本周已通关 {done}/{len(depths)} 层 · {zone.name}"
    upcoming = next(depth for depth in depths if depth.id not in cleared)
    return f"灵宠禁地：本周 {done}/{len(depths)} 层 · 下一层 {upcoming.name}"
