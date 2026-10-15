"""Trial tower: a single-player climb of escalating floors.

Floors reuse the chapter-stage shape (sequential unlock, one-time first-clear
reward) but are harder, single-player only, and keep their progress in the
existing ``pve_stage_progress`` table so no schema change is needed.
"""

import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.tower_content import TowerFloor
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

# Tower progress shares the stage table; the prefix keeps the two apart so the
# chapter achievement metric never counts tower floors.
TOWER_PREFIX = "tower_"


def _ordered(ctx: Context) -> list[TowerFloor]:
    return sorted(ctx.content.tower.values(), key=lambda floor: floor.order)


def _floor(ctx: Context, argument: str) -> TowerFloor:
    value = argument.strip()
    if value.isdecimal():
        order = quantity(value, len(ctx.content.tower))
        return next(floor for floor in _ordered(ctx) if floor.order == order)
    return named(ctx.content.tower, value)


def _cleared(ctx: Context, user_id: str | None = None) -> set[str]:
    return {
        row["stage_id"] for row in ctx.repo.conn.execute(
            "SELECT stage_id FROM pve_stage_progress WHERE user_id=? AND stage_id LIKE ?",
            (user_id or ctx.user_id, f"{TOWER_PREFIX}%"),
        )
    }


def _depth(ctx: Context, cleared: set[str]) -> int:
    return max((floor.order for floor in ctx.content.tower.values() if floor.id in cleared), default=0)


def _state(floor: TowerFloor, cleared: set[str], player) -> str:
    if player is None:
        return "尚未结契"
    if floor.id in cleared:
        return "已通关"
    if floor.previous_id is None or floor.previous_id in cleared:
        return "可挑战"
    return "未解锁"


def _realm_name(ctx: Context, floor: TowerFloor) -> str:
    return next(realm.name for realm in ctx.content.realms if realm.id == floor.min_realm)


def catalog(ctx: Context, arg: str) -> Reply:
    entries = _ordered(ctx)
    player = ctx.repo.player(ctx.user_id)
    cleared = _cleared(ctx) if player is not None else set()
    depth = _depth(ctx, cleared)
    if arg and not arg.isdecimal():
        floor = _floor(ctx, arg)
        state = _state(floor, cleared, player)
        reward = floor.reward
        enemies = "、".join(ctx.content.enemies[key].name for key in floor.enemies)
        techniques = tuple(
            f"{ctx.content.enemies[key].name}招式："
            f"{ctx.content.skills[ctx.content.enemies[key].signature_skill].name}"
            f"（每 {ctx.content.enemies[key].skill_every} 次行动施展）"
            for key in floor.enemies if ctx.content.enemies[key].signature_skill
        )
        commands = []
        if state in ("可挑战", "已通关"):
            commands.append(f"灵宠挑战万灵塔 {floor.order}")
        commands.extend(("灵宠万灵塔", "灵宠关卡"))
        return Reply(f"万灵塔 {floor.order} · {floor.name}", (
            floor.description,
            f"进度：{state} · 当前深度 {depth}/{len(entries)} 层",
            f"单人 · {_realm_name(ctx, floor)}起 · 精力 {floor.energy} · 敌手：{enemies}",
            *techniques,
            f"首通奖励：修为 {reward.exp.minimum}-{reward.exp.maximum} · "
            f"灵石 {reward.stones.minimum}-{reward.stones.maximum}",
            *(f"{ctx.content.items[key].name}：{bounds.minimum}-{bounds.maximum}"
              for key, bounds in reward.items.items()),
            "每层首通奖励只领取一次；重复挑战用于练习与熟练度，不再发放首通奖励。",
        ), tuple(commands))
    page = paginate(entries, arg, "万灵塔", "灵宠万灵塔")
    lines = [f"当前深度：{depth}/{len(entries)} 层。"]
    links = []
    for floor in page.entries:
        state = _state(floor, cleared, player)
        lines.append(
            f"{floor.order}. {floor.name} · {state} · {_realm_name(ctx, floor)}起 · 精力 {floor.energy}"
        )
        # Only openable floors link a direct run; locked and unregistered rows keep none.
        if state in ("可挑战", "已通关"):
            links.append(InlineCommand(len(lines) - 1, "前往挑战", f"灵宠挑战万灵塔 {floor.order}"))
    return Reply(
        f"万灵塔 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "灵宠关卡", "灵宠秘境"), tuple(links),
    )


def _prior_reply(ctx: Context, floor: TowerFloor) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != floor.id:
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def _require_previous(ctx: Context, floor: TowerFloor, cleared: set[str]) -> None:
    if floor.previous_id is not None and floor.previous_id not in cleared:
        previous = ctx.content.tower[floor.previous_id]
        raise GameError(f"尚未通关前置塔层：{previous.name}。")


def challenge(ctx: Context, arg: str) -> Reply:
    floor = _floor(ctx, arg or "1")
    prior = _prior_reply(ctx, floor)
    if prior is not None:
        return prior
    player = ctx.player()
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    _require_previous(ctx, floor, _cleared(ctx))
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == floor.min_realm)
    checked = False
    for _, pet in selected:
        if pet.realm < minimum:
            raise GameError(f"{pet.name}境界不足，{floor.name}需要{ctx.content.realms[minimum].name}。")
        if not checked:
            ctx.check_action(player, pet, "pve", floor.energy, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < floor.energy:
                raise GameError(f"{pet.name}精力不足，需要 {floor.energy} 点。")

    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    enemies = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in floor.enemies]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    # Costs and proficiency apply to every attempt, including a defeat; the
    # progress insert and first-clear grant below stay in the same transaction.
    for _, pet in selected:
        pet.energy -= floor.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"第{floor.order}层 · {floor.name} · {battle.rounds} 回合", *battle.lines]
    for _, pet in selected:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    if battle.winner == 0:
        advance(ctx, "pve")
        inserted = ctx.repo.conn.execute(
            "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, stage_id) DO NOTHING",
            (ctx.user_id, floor.id, ctx.now, ctx.operation_id),
        )
        if inserted.rowcount == 1:
            lines.append(f"{player.uid_label}首通{floor.name}：" + "，".join(grant(ctx, floor.reward)))
            title = "塔层首通"
        else:
            lines.append("本层此前已通关，本次为再战练习，不重复发放首通奖励。")
            title = "塔层再胜"
    else:
        title = "塔层平局" if battle.winner == -1 else "塔层败退"
        lines.append("本次挑战未通关，塔层进度不变。")
    lines.append(f"每只灵宠精力 -{floor.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠万灵塔", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=floor.id, battle_name=floor.name,
    )
    return reply


def depth(ctx: Context, user_id: str | None = None) -> int:
    """Highest cleared floor order, used by the achievement metric and status pages."""
    return _depth(ctx, _cleared(ctx, user_id))
