"""Weekly team trial: a rotating team boss that must fall within a round limit.

The weekly clear is stored in ``quest_progress`` as
``team_trial_<week_start>_<trial_id>`` per member (progress = their best passing
rounds), so no schema change is needed and the ledger rotates with the week.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.team_trial_content import TeamTrial
from ..utils.time import beijing_week
from . import battle_pass
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant, team_pets
from .mastery import award_mastery
from .quests import advance
from .rewards import grant
from .teams.common import TEAM_HELP, membership, require_leader
from .teams.party import _ready_ids

PREFIX = "team_trial_"
WEEK = 7 * 86400


def trials(ctx: Context) -> list[TeamTrial]:
    return sorted(ctx.content.team_trials.values(), key=lambda trial: trial.id)


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def trial_for(ctx: Context, start: int | None = None) -> TeamTrial:
    entries = trials(ctx)
    begin = week_start(ctx) if start is None else start
    return entries[(begin // 86400) % len(entries)]


def next_trial(ctx: Context) -> TeamTrial:
    return trial_for(ctx, week_start(ctx) + WEEK)


def _key(start: int, trial_id: str) -> str:
    return f"{PREFIX}{start}_{trial_id}"


def best(ctx: Context, user_id: str, start: int, trial_id: str) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, _key(start, trial_id)),
    ).fetchone()
    return None if row is None else int(row["progress"])


def _members(ctx: Context, team_id: int, leader_id: str):
    return ctx.repo.conn.execute(
        "SELECT m.*, identity.id AS player_internal_id FROM team_members m"
        " JOIN player_identity identity USING(user_id)"
        " WHERE m.team_id=? ORDER BY (m.user_id=?) DESC, identity.id",
        (team_id, leader_id),
    ).fetchall()


def _realm_name(ctx: Context, realm_id: str) -> str:
    return next(realm.name for realm in ctx.content.realms if realm.id == realm_id)


def _enemy_names(ctx: Context, trial: TeamTrial) -> str:
    return "、".join(ctx.content.enemies[key].name for key in trial.enemies)


def _reward_text(ctx: Context, trial: TeamTrial) -> str:
    def amount(bounds):
        return f"{bounds.minimum}" if bounds.minimum == bounds.maximum else f"{bounds.minimum}-{bounds.maximum}"

    parts = [f"修为 {amount(trial.reward.exp)}", f"灵石 {amount(trial.reward.stones)}"]
    parts.extend(
        f"{ctx.content.items[key].name} {amount(bounds)}"
        for key, bounds in trial.reward.items.items()
    )
    return " · ".join(parts)


def _roster(ctx: Context, member, rows) -> tuple[list, bool, bool]:
    """(selected, every member ready, can run now)."""
    selected = team_pets(ctx, [row["user_id"] for row in rows], member["leader_id"])
    by_user: dict[str, list[int]] = {}
    for user_id, pet in selected:
        by_user.setdefault(user_id, []).append(pet.pet_id)
    ready = all(_ready_ids(row) == by_user.get(row["user_id"], []) for row in rows)
    return selected, ready, len(rows) >= 2 and ready


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠团队试炼 不接受参数，直接发送即可。")
    trial = trial_for(ctx)
    upcoming = next_trial(ctx)
    member = membership(ctx) if ctx.repo.player(ctx.user_id) is not None else None
    lines = [
        f"本周试炼：{trial.name}（{_enemy_names(ctx, trial)}）",
        trial.description,
        f"回合上限：{trial.round_limit} 回合内击破 · {_realm_name(ctx, trial.min_realm)}起"
        f" · 每只灵宠精力 {trial.energy}",
        f"每人每周首通奖励：{_reward_text(ctx, trial)}",
    ]
    links = []
    commands = ["灵宠团队试炼"]
    if member is None:
        lines.append("尚未组队：先建立小队并邀请同伴，试炼需要 2-3 名已准备的玩家。")
        lines.append(f"下周：{upcoming.name}（回合上限 {upcoming.round_limit}）。")
        return Reply(
            "灵宠团队试炼", tuple(lines), ("灵宠队伍", "灵宠秘境", TEAM_HELP),
            (InlineCommand(4, "组队指南", TEAM_HELP),),
        )

    rows = _members(ctx, member["team_id"], member["leader_id"])
    start = week_start(ctx)
    selected, ready, can_run = _roster(ctx, member, rows)
    prepared = sum(1 for row in rows if _ready_ids(row))
    lines.append(f"队伍：{len(rows)}/{ctx.content.rules.max_team_size} · 已准备 {prepared}/{len(rows)}。")
    best_round = None
    for row in rows:
        uid_label = f"UID {row['player_internal_id'] + 9999}"
        rounds = best(ctx, row["user_id"], start, trial.id)
        state = f"已通关（{rounds} 回合）" if rounds is not None else "未通关"
        lines.append(f"{'队长' if row['user_id'] == member['leader_id'] else '队员'} {uid_label} · {state}")
        if rounds is not None and (best_round is None or rounds < best_round):
            best_round = rounds
        if row["user_id"] != ctx.user_id:
            links.append(InlineCommand(len(lines) - 1, "查看名帖", f"灵宠队伍 {uid_label}"))
    lines.append(f"队伍最佳：{best_round} 回合。" if best_round is not None else "队伍最佳：本周尚无通关记录。")
    if member["leader_id"] == ctx.user_id:
        if can_run:
            commands.append("灵宠团队试炼 挑战")
        else:
            missing = "至少两名成员" if len(rows) < 2 else "全体成员准备"
            lines.append(f"挑战条件：{missing}（灵宠队伍 可查看准备状态）。")
    else:
        lines.append("仅队长可以发起团队试炼。")
    lines.append(f"下周：{upcoming.name}（回合上限 {upcoming.round_limit}）。")
    commands.extend(("灵宠队伍", "灵宠战报"))
    return Reply("灵宠团队试炼", tuple(lines), tuple(commands), tuple(links))


def _prior_reply(ctx: Context, trial: TeamTrial) -> Reply | None:
    import json

    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != trial.id:
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def _gate(ctx: Context, selected, trial: TeamTrial, minimum: int) -> None:
    first_checked = set()
    for user_id, pet in selected:
        player = ctx.player(user_id)
        if pet.realm < minimum:
            raise GameError(
                f"{pet.name}境界不足，{trial.name}需要{ctx.content.realms[minimum].name}。"
            )
        if user_id not in first_checked:
            ctx.check_action(player, pet, "pve", trial.energy, ctx.config.spirit_pet_pve_cooldown)
            first_checked.add(user_id)
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < trial.energy:
                raise GameError(f"{pet.name}精力不足，需要 {trial.energy} 点。")


def _passed(battle, trial: TeamTrial) -> bool:
    return battle.winner == 0 and battle.rounds <= trial.round_limit


def challenge(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    trial = trial_for(ctx)
    prior = _prior_reply(ctx, trial)
    if prior is not None:
        return prior
    rows = _members(ctx, member["team_id"], member["leader_id"])
    if len(rows) < 2:
        raise GameError("组队试炼至少需要两名玩家。")
    selected, ready, can_run = _roster(ctx, member, rows)
    if not ready:
        raise GameError("全体成员准备后才能挑战。")
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == trial.min_realm)
    _gate(ctx, selected, trial, minimum)

    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    enemies = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in trial.enemies]
    capture = capture_snapshot(ctx, (allies, enemies), ([user_id for user_id, _ in selected], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    start = week_start(ctx)
    by_user = {row["user_id"]: ctx.player(row["user_id"]) for row in rows}
    lines = [f"{trial.name} · {battle.rounds} 回合（上限 {trial.round_limit}）", *battle.lines]
    for user_id, pet in selected:
        pet.energy -= trial.energy
        by_user[user_id].last_pve = ctx.now
        lines.extend(award_mastery(
            ctx, user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    passed = _passed(battle, trial)
    if passed:
        for row in rows:
            user_id = row["user_id"]
            previous = best(ctx, user_id, start, trial.id)
            if previous is None:
                advance(ctx, "pve", user_id)
                battle_pass.add_experience(ctx, "pve_win", user_id)
                ctx.repo.conn.execute(
                    "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
                    (user_id, _key(start, trial.id), battle.rounds),
                )
                lines.append(
                    f"{by_user[user_id].uid_label}首通：" + "，".join(grant(ctx, trial.reward, user_id))
                )
            else:
                if battle.rounds < previous:
                    ctx.repo.conn.execute(
                        "UPDATE quest_progress SET progress=? WHERE user_id=? AND quest_id=?",
                        (battle.rounds, user_id, _key(start, trial.id)),
                    )
                lines.append(f"{by_user[user_id].uid_label}本周已通关，本次为助战，不重复发放奖励。")
        title = "团队试炼通关"
    elif battle.winner == 0:
        lines.append(f"超过 {trial.round_limit} 回合上限，本次试炼未通过。")
        title = "团队试炼超时"
    else:
        lines.append("本次试炼未通过，成员奖励不变。")
        title = "团队试炼败退" if battle.winner == 1 else "团队试炼平局"

    for row in rows:
        ctx.repo.invalidate_ready(row["user_id"])
    lines.append(f"每只灵宠精力 -{trial.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠团队试炼", "灵宠队伍", "灵宠战报"))
    record_battle(
        ctx, kind="pve_stage", battle_key=trial.id, battle_name=trial.name,
        battle=battle, capture=capture, reply=reply,
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    """Page by default; ``挑战`` runs the weekly battle."""
    if arg.strip() == "挑战":
        return challenge(ctx, arg)
    return page(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    member = membership(ctx, user_id)
    if member is None:
        return "团队试炼：尚未组队"
    trial = trial_for(ctx)
    rounds = best(ctx, user_id, week_start(ctx), trial.id)
    if rounds is None:
        return f"团队试炼：本周未通关 · {trial.name}"
    return f"团队试炼：本周已通关（{rounds} 回合）· {trial.name}"
