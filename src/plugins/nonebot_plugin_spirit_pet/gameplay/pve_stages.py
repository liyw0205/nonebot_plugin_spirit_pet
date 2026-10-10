"""Persistent PVE chapter stages.

Stages are deliberately separate from ordinary dungeons: a successful clear
creates a per-player progress row, while a failed attempt never advances it.
All participants still pay the normal PVE cost, so helping another dao friend
is useful without duplicating first-clear rewards.
"""

import json
from sqlite3 import Row

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..domain.stage_content import Stage
from ..gameplay.battle_records import capture_snapshot, record_battle
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from .combat import Fighter, enemy_fighter, fight
from .loadout import combatant, team_pets
from .mastery import award_mastery
from .quests import advance
from .rewards import grant
from .teams.common import membership, require_leader


def _ordered(ctx: Context) -> list[Stage]:
    return sorted(ctx.content.stages.values(), key=lambda stage: stage.order)


def _stage(ctx: Context, argument: str) -> Stage:
    value = argument.strip()
    if value.isdecimal():
        order = quantity(value, len(ctx.content.stages))
        return next(stage for stage in _ordered(ctx) if stage.order == order)
    return named(ctx.content.stages, value)


def _progress_labels(ctx: Context, stages: list[Stage]) -> dict[str, str]:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return {stage.id: "尚未结契" for stage in stages}
    cleared = {
        row["stage_id"] for row in ctx.repo.conn.execute(
            "SELECT stage_id FROM pve_stage_progress WHERE user_id=?", (ctx.user_id,),
        )
    }
    return {
        stage.id: (
            "已通关" if stage.id in cleared else
            "可挑战" if stage.previous_id is None or stage.previous_id in cleared else
            "未解锁"
        )
        for stage in stages
    }


def catalog(ctx: Context, arg: str) -> Reply:
    entries = _ordered(ctx)
    if arg and not arg.isdecimal():
        stage = _stage(ctx, arg)
        progress = _progress_labels(ctx, entries)[stage.id]
        realm = next(realm.name for realm in ctx.content.realms if realm.id == stage.min_realm)
        mode = "组队" if stage.team else "单人"
        reward = stage.reward
        enemy_names = "、".join(ctx.content.enemies[key].name for key in stage.enemies)
        enemy_techniques = tuple(
            f"{ctx.content.enemies[key].name}招式："
            f"{ctx.content.skills[ctx.content.enemies[key].signature_skill].name}"
            f"（每 {ctx.content.enemies[key].skill_every} 次行动施展）"
            for key in stage.enemies if ctx.content.enemies[key].signature_skill
        )
        return Reply(f"关卡 {stage.order} · {stage.name}", (
            stage.description,
            f"进度：{progress}",
            f"{mode} · {realm}起 · 精力 {stage.energy} · 敌手：{enemy_names}",
            *enemy_techniques,
            f"首通奖励：修为 {reward.exp.minimum}-{reward.exp.maximum} · "
            f"灵石 {reward.stones.minimum}-{reward.stones.maximum}",
            *(f"{ctx.content.items[key].name}：{bounds.minimum}-{bounds.maximum}"
              for key, bounds in reward.items.items()),
            "每位道友每关仅领取一次首通奖励；已通关者可组队助战。",
        ), (f"{'灵宠组队关卡' if stage.team else '灵宠挑战关卡'} {stage.order}", "灵宠关卡"))
    page = paginate(entries, arg, "灵宠关卡", "灵宠关卡")
    progress = _progress_labels(ctx, entries)
    lines = []
    for stage in page.entries:
        realm = next(realm.name for realm in ctx.content.realms if realm.id == stage.min_realm)
        lines.append(
            f"{stage.order}. {stage.name} · {progress[stage.id]} · "
            f"{'组队' if stage.team else '单人'} · {realm}起 · 精力 {stage.energy}"
        )
    commands = [
        f"{'灵宠组队关卡' if stage.team else '灵宠挑战关卡'} {stage.order}"
        for stage in page.entries
    ]
    commands.extend(page.navigation)
    return Reply(f"灵宠关卡 {page.number}/{page.total}", tuple(lines), tuple(commands))


def _progress(ctx: Context, user_id: str, stage_id: str) -> Row | None:
    return ctx.repo.conn.execute(
        "SELECT * FROM pve_stage_progress WHERE user_id=? AND stage_id=?",
        (user_id, stage_id),
    ).fetchone()


def _prior_reply(ctx: Context, stage: Stage) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != stage.id:
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    data = json.loads(row["reply"])
    return Reply.from_data(data)


def _require_previous(ctx: Context, stage: Stage, user_id: str) -> None:
    if stage.previous_id is not None and _progress(ctx, user_id, stage.previous_id) is None:
        previous = ctx.content.stages[stage.previous_id]
        raise GameError(f"{ctx.player(user_id).dao_name}尚未通关前置关卡：{previous.name}。")


def _active_team(ctx: Context) -> list[Row]:
    member = require_leader(ctx)
    rows = ctx.repo.conn.execute(
        "SELECT m.*, p.dao_name, t.leader_id FROM team_members m JOIN players p USING(user_id) "
        "JOIN teams t USING(team_id) "
        "WHERE m.team_id=? ORDER BY m.user_id", (member["team_id"],),
    ).fetchall()
    if len(rows) < 2:
        raise GameError("组队关卡至少需要两名玩家。")
    return rows


def _participants(ctx: Context, stage: Stage) -> list[str]:
    if not stage.team:
        return [ctx.user_id]
    rows = _active_team(ctx)
    user_ids = [row["user_id"] for row in rows]
    selected = team_pets(ctx, user_ids, rows[0]["leader_id"])
    expected: dict[str, list[int]] = {}
    for user_id, pet in selected:
        expected.setdefault(user_id, []).append(pet.pet_id)
    for row in rows:
        ready = row["ready_pet_ids"]
        actual = [int(item) for item in json.loads(ready)] if ready else (
            [row["ready_pet_id"]] if row["ready_pet_id"] is not None else []
        )
        if actual != expected.get(row["user_id"], []):
            raise GameError(f"{ctx.player(row['user_id']).dao_name}尚未准备当前出战灵宠。")
    return user_ids


def _enemy_fighters(ctx: Context, stage: Stage) -> list[Fighter]:
    return [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in stage.enemies]


def _settle_cost(ctx: Context, user_ids: list[str], stage: Stage) -> None:
    member = ctx.repo.conn.execute(
        "SELECT leader_id FROM teams JOIN team_members USING(team_id) WHERE team_members.user_id=?",
        (ctx.user_id,),
    ).fetchone()
    selected = team_pets(ctx, user_ids, member["leader_id"] if member else None) if len(user_ids) > 1 else [
        (user_ids[0], pet) for pet in ctx.active_pets(user_ids[0])
    ]
    for user_id, pet in selected:
        player = ctx.player(user_id)
        pet.energy -= stage.energy
        player.last_pve = ctx.now
    for user_id in user_ids:
        ctx.repo.invalidate_ready(user_id)


def challenge(ctx: Context, arg: str) -> Reply:
    stage = _stage(ctx, arg or "1")
    prior = _prior_reply(ctx, stage)
    if prior is not None:
        return prior
    user_ids = _participants(ctx, stage)
    selected = team_pets(ctx, user_ids, _active_team(ctx)[0]["leader_id"]) if len(user_ids) > 1 else [
        (user_ids[0], pet) for pet in ctx.active_pets(user_ids[0])
    ]
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == stage.min_realm)
    checked_users = set()
    for user_id, pet in selected:
        player = ctx.player(user_id)
        _require_previous(ctx, stage, player.user_id)
        if pet.realm < minimum:
            raise GameError(f"{pet.name}境界不足，{stage.name}需要{ctx.content.realms[minimum].name}。")
        if user_id not in checked_users:
            ctx.check_action(player, pet, "pve", stage.energy, ctx.config.spirit_pet_pve_cooldown)
            checked_users.add(user_id)
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < stage.energy:
                raise GameError(f"{pet.name}精力不足，需要 {stage.energy} 点。")

    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    enemies = _enemy_fighters(ctx, stage)
    capture = capture_snapshot(ctx, (allies, enemies), ([user_id for user_id, _ in selected], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    # Costs and proficiency apply to every attempt, including a defeat.  The
    # progress insert and first-clear grants below remain in this transaction.
    _settle_cost(ctx, user_ids, stage)
    lines = [f"第{stage.order}关 · {stage.name} · {battle.rounds} 回合", *battle.lines]
    for user_id, pet in selected:
        lines.extend(award_mastery(
            ctx, user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    if battle.winner == 0:
        for user_id in user_ids:
            advance(ctx, "pve", user_id)
        first_clear_users: list[str] = []
        for user_id in user_ids:
            inserted = ctx.repo.conn.execute(
                "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, stage_id) DO NOTHING",
                (user_id, stage.id, ctx.now, ctx.operation_id),
            )
            if inserted.rowcount == 1:
                first_clear_users.append(user_id)
        if first_clear_users:
            for user_id in first_clear_users:
                reward = grant(ctx, stage.reward, user_id)
                lines.append(f"{ctx.player(user_id).dao_name}首通{stage.name}：" + "，".join(reward))
        else:
            lines.append("本队成员均已完成本关，本次为助战挑战，不重复发放首通奖励。")
        title = "关卡首通" if first_clear_users else "关卡助战胜利"
    else:
        title = "关卡平局" if battle.winner == -1 else "关卡败退"
        if battle.winner != 0:
            lines.append("本次挑战未通关，关卡进度不变。")
    lines.append(f"每只灵宠精力 -{stage.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠关卡", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=stage.id, battle_name=stage.name,
    )
    return reply


def team_challenge(ctx: Context, arg: str) -> Reply:
    stage = _stage(ctx, arg or "1")
    if not stage.team:
        raise GameError("该关卡为单人关卡，请发送 灵宠挑战关卡 关卡编号。")
    if membership(ctx) is None:
        raise GameError("尚未加入队伍，请先组建队伍并准备出战灵宠。")
    return challenge(ctx, stage.id)


# Explicit alias for command registries that prefer the full verb.
challenge_stage = challenge
