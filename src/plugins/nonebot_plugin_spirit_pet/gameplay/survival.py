"""Survival trial: an unkillable guardian, scored by how many rounds the lineup lasts.

State lives in the existing ``quest_progress`` table:

* ``survival_best`` — deepest survived rounds
* ``survival_milestone_<rounds>`` — 1 once that milestone has been paid
"""

import json

from ..application.context import Context
from ..domain.content import Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.survival_content import SurvivalTrial
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .rewards import grant

BEST_KEY = "survival_best"
MILESTONE_KEY = "survival_milestone_"


def trial(ctx: Context) -> SurvivalTrial:
    return sorted(ctx.content.survival.values(), key=lambda entry: entry.id)[0]


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def best(ctx: Context, user_id: str | None = None) -> int:
    return _progress(ctx, BEST_KEY, user_id)


def guardian(ctx: Context):
    entry = trial(ctx)
    base = ctx.content.enemies[entry.enemy]
    stats = base.stats
    return base.model_copy(update={
        "name": f"{base.name}守关",
        "stats": Stats(
            hp=max(1, round(stats.hp * entry.hp_multiplier)),
            attack=max(1, round(stats.attack * entry.attack_multiplier)),
            defense=max(0, round(stats.defense * entry.defense_multiplier)),
            speed=max(1, round(stats.speed * entry.speed_multiplier)),
        ),
    })


def _reward_text(ctx: Context, milestone) -> str:
    reward = milestone.reward
    parts = []
    if reward.exp.maximum:
        parts.append(f"修为 {reward.exp.minimum}")
    parts.append(f"灵石 {reward.stones.minimum}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def _milestone_state(ctx: Context, milestone, depth: int) -> str:
    if _progress(ctx, f"{MILESTONE_KEY}{milestone.rounds}"):
        return "已领"
    return "可达" if depth >= milestone.rounds else "未达"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠守关 [挑战]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠守关",
            (
                "尚未结契，先完成领养，才能带伙伴守关。",
                "守关的守卫打不死，只比拼你的阵容能撑过多少回合。",
                "历史最深永久保留，达到 5/10/15/20 回合各发一次里程碑奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = trial(ctx)
    boss = guardian(ctx)
    depth = best(ctx)
    lines = [
        f"守关：撑过回合数即为成绩，目标 {entry.target} 回合；每场精力 {entry.energy}。",
        entry.description,
        f"守卫：{boss.name} · 气血 {boss.stats.hp} · 攻击 {boss.stats.attack}"
        f" · 防御 {boss.stats.defense} · 速度 {boss.stats.speed}",
        f"历史最深：{depth} 回合。",
    ]
    for milestone in entry.milestones:
        lines.append(
            f"{milestone.rounds} 回合 · {_reward_text(ctx, milestone)} · {_milestone_state(ctx, milestone, depth)}"
        )
    links = []
    if depth < entry.target:
        links.append(InlineCommand(0, "挑战", "灵宠守关 挑战"))
    else:
        lines.append("已达最终目标；仍可再战刷新最深回合。")
        links.append(InlineCommand(0, "再战", "灵宠守关 挑战"))
    return Reply("灵宠守关", tuple(lines), ("灵宠守关", "灵宠战报", "我的灵宠"), tuple(links))


def _prior_reply(ctx: Context) -> Reply | None:
    row = ctx.repo.conn.execute(
        "SELECT initiator_id, kind, battle_key, reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["initiator_id"] != ctx.user_id:
        raise GameError("该战斗消息已被其他身份处理，不能复用。")
    if row["kind"] != "pve_stage" or row["battle_key"] != "survival":
        raise GameError("该战斗消息已被用于其他结算，不能复用。")
    return Reply.from_data(json.loads(row["reply"]))


def challenge(ctx: Context, arg: str) -> Reply:
    if arg.strip() and arg.strip() != "挑战":
        raise GameError("格式：灵宠守关 挑战。")
    prior = _prior_reply(ctx)
    if prior is not None:
        return prior
    entry = trial(ctx)
    player = ctx.player()
    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    checked = False
    for _, pet in selected:
        if not checked:
            ctx.check_action(player, pet, "pve", entry.energy, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < entry.energy:
                raise GameError(f"{pet.name}精力不足，守关需要 {entry.energy} 点。")

    boss = guardian(ctx)
    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    enemies = [enemy_fighter(boss, ctx.content.skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    for _, pet in selected:
        pet.energy -= entry.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    survived = entry.target if battle.winner == 0 else battle.rounds
    lines = [f"守关 · 撑过 {survived} 回合（目标 {entry.target}）", *battle.lines]
    for _, pet in selected:
        lines.extend(award_mastery(
            ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
        ))

    before = best(ctx)
    if survived > before:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (ctx.user_id, BEST_KEY, survived),
        )
        lines.append(f"刷新历史最深：{before} → {survived} 回合。")
    else:
        lines.append(f"未刷新历史最深（{before} 回合）。")
    for milestone in entry.milestones:
        if survived < milestone.rounds or before >= milestone.rounds:
            continue
        marker = f"{MILESTONE_KEY}{milestone.rounds}"
        existing = ctx.repo.conn.execute(
            "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, marker),
        ).fetchone()
        if existing is not None:
            continue
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (ctx.user_id, marker),
        )
        lines.append(f"{milestone.rounds} 回合里程碑：" + "，".join(grant(ctx, milestone.reward)))

    reached = max(before, survived)
    title = "守关达成" if reached >= entry.target else "守关结束"
    lines.append(f"每只灵宠精力 -{entry.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠守关", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key="survival", battle_name=entry.name,
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠守关 [挑战]。")


def objective_line(ctx: Context, user_id: str) -> str:
    depth = best(ctx, user_id)
    return "守关：尚未挑战" if depth == 0 else f"守关：最深 {depth} 回合"
