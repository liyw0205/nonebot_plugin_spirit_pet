"""Sect trial: one weekly boss that only members of that sect may face.

The sect had an identity and a daily button, but no fight of its own. This trial
closes the loop opened by the mission board: missions pay contribution in small
amounts every day, the trial pays a larger weekly sum once.

State lives in ``quest_progress``:

* ``sect_trial_<week start>_<sect>`` — cleared this week
* contributions go through ``sects``/``sect_contrib_<sect>`` and the weekly
  ledger ``sect_week_contrib_<week start>``

The fight itself runs through the shared PVE path (``check_action``, ``fight``,
mastery, battle record), so cooldowns, energy and reports stay consistent.
"""

import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day, beijing_week
from . import sects
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .rewards import grant

TRIAL_PREFIX = "sect_trial_"
BATTLE_KEY = "sect_trial"


def trial_for(ctx: Context, sect):
    return next(
        (entry for entry in ctx.content.sect_trials.values() if entry.sect == sect.id), None,
    )


def _key(now: int, trial) -> str:
    return f"{TRIAL_PREFIX}{beijing_week(now)[0]}_{trial.sect}"


def cleared(ctx: Context, trial, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _key(ctx.now, trial)),
    ).fetchone()
    return row is not None


def _realm_index(ctx: Context, realm_id: str) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == realm_id)


def _reward_text(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}"] if reward.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts) if parts else "无奖励"


def boss(ctx: Context, trial):
    return ctx.content.enemies[trial.enemy]


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 试炼 [挑战]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠师门 · 试炼",
            (
                "尚未结契，先完成领养，才能参加师门试炼。",
                "拜入师门后每周可挑战一次本门试炼，胜者得贡献与奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，先发送 灵宠师门 拜入 <门派>。")
    trial = trial_for(ctx, sect)
    if trial is None:
        raise GameError("本门暂无试炼内容。")
    enemy = boss(ctx, trial)
    rank = sects.rank_of(ctx, sect).rank
    cleared_now = cleared(ctx, trial)
    lines = [
        f"{sect.name} · {trial.name}（每周一次，周一 00:00 北京时间重置）。",
        trial.description,
        f"要求：境界 {ctx.content.realms[_realm_index(ctx, trial.min_realm)].name}起"
        f" · {trial.min_rank} 阶 · 每只出战伙伴精力 {trial.energy}。",
        f"敌手：{enemy.name} · 气血 {enemy.stats.hp} · 攻击 {enemy.stats.attack}"
        f" · 防御 {enemy.stats.defense} · 速度 {enemy.stats.speed}",
        f"胜者得：贡献 +{trial.contribution} · {_reward_text(ctx, trial.reward)}。",
        f"本周状态：{'已通过' if cleared_now else '未通过'}。",
    ]
    links = []
    if not cleared_now and rank >= trial.min_rank:
        links.append(InlineCommand(len(lines) - 1, "挑战试炼", "灵宠师门 试炼 挑战"))
    elif rank < trial.min_rank:
        lines.append(f"阶位不足：需 {trial.min_rank} 阶，当前 {rank} 阶；先积累贡献。")
    return Reply("灵宠师门 · 试炼", tuple(lines), ("灵宠师门", "灵宠战报", "灵宠目标"), tuple(links))


def _prior_reply(ctx: Context) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != BATTLE_KEY:
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def challenge(ctx: Context, arg: str) -> Reply:
    if arg.strip() and arg.strip() != "挑战":
        raise GameError("格式：灵宠师门 试炼 挑战。")
    prior = _prior_reply(ctx)
    if prior is not None:
        return prior
    player = ctx.player()
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，先发送 灵宠师门 拜入 <门派>。")
    trial = trial_for(ctx, sect)
    if trial is None:
        raise GameError("本门暂无试炼内容。")
    if cleared(ctx, trial):
        raise GameError("本周的师门试炼已经通过，下周一 00:00 后可再次挑战。")
    rank = sects.rank_of(ctx, sect).rank
    if rank < trial.min_rank:
        raise GameError(f"{trial.name}需要 {trial.min_rank} 阶，当前 {rank} 阶。")
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    minimum = _realm_index(ctx, trial.min_realm)
    if max(pet.realm for _, pet in selected) < minimum:
        raise GameError(
            f"{trial.name}要求出战伙伴达到"
            f"{ctx.content.realms[minimum].name}，当前阵容境界不足。"
        )
    checked = False
    for _, pet in selected:
        if not checked:
            ctx.check_action(player, pet, "pve", trial.energy, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < trial.energy:
                raise GameError(f"{pet.name}精力不足，试炼需要 {trial.energy} 点。")

    enemy = boss(ctx, trial)
    allies = [
        combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected
    ]
    enemies = [enemy_fighter(enemy, ctx.content.skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    for _, pet in selected:
        pet.energy -= trial.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    won = battle.winner == 0
    lines = [f"{sect.name} · {trial.name}：{'取胜' if won else '落败'}", *battle.lines]
    for _, pet in selected:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))
    if won:
        result = grant(ctx, trial.reward)
        total = sects.contribution(ctx, sect) + trial.contribution
        sects._set(ctx, f"{sects.CONTRIB}{sect.id}", total)
        sects._set(
            ctx,
            f"{sects.WEEK_CONTRIB}{beijing_week(ctx.now)[0]}",
            sects.week_contribution(ctx) + trial.contribution,
        )
        sects._set(ctx, _key(ctx.now, trial), 1)
        lines.extend((
            f"试炼奖励：{'，'.join(result)}。",
            f"门派贡献 +{trial.contribution}（{total}，{sects.rank_of(ctx, sect).rank} 阶）"
            f" · 本周贡献 {sects.week_contribution(ctx)}。",
        ))
        pending = sects.weekly_claimable(ctx)
        if pending:
            lines.append(f"周俸可领取：{[tier.tier for tier in pending]} 档。")
    else:
        lines.append("试炼未通过：不发奖励，下周可再次挑战。")
    lines.append(f"每只出战伙伴精力 -{trial.energy}；气血仅在本场战斗内结算。")
    reply = Reply(
        "师门试炼 · 通过" if won else "师门试炼 · 未过",
        tuple(lines),
        ("灵宠师门", "灵宠师门 周俸", "灵宠战报"),
    )
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=BATTLE_KEY, battle_name=trial.name,
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠师门 试炼 [挑战]。")


def objective_line(ctx: Context, user_id: str) -> str | None:
    sect = sects.current(ctx, user_id)
    if sect is None:
        return None
    trial = trial_for(ctx, sect)
    if trial is None or cleared(ctx, trial, user_id):
        return None
    return f"师门试炼：本周未过（{sect.name}）"


__all__ = ["BATTLE_KEY", "TRIAL_PREFIX", "challenge", "cleared", "dispatch", "objective_line", "page"]
