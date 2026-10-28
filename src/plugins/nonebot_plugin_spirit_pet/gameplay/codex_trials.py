"""Codex species trials: one permanent solo fight per owned species.

Each trial pits the player's own specimen against a boosted "幻影" of the same species
(species base stats × ``boost``, same elements, no skills). A first clear per species pays
once and counts toward the 9/18/27 milestones; repeats are practice runs.

State lives in the existing ``quest_progress`` table:

* ``codex_trial_<species_id>`` — rounds of the first clear
* ``codex_trial_milestone_<count>`` — 1 once that milestone has been paid
"""

from ..application.context import Context
from ..domain.codex_trial_content import CodexTrial
from ..domain.content import Enemy, Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance

TRIAL_KEY = "codex_trial_"
MILESTONE_KEY = "codex_trial_milestone_"
PAGE_SIZE = 9


def trial(ctx: Context) -> CodexTrial:
    return sorted(ctx.content.codex_trials.values(), key=lambda entry: entry.id)[0]


def species_list(ctx: Context):
    return sorted(ctx.content.species.values(), key=lambda entry: entry.id)


def cleared(ctx: Context, user_id: str | None = None) -> dict[str, int]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{TRIAL_KEY}%"),
    )
    return {row["quest_id"][len(TRIAL_KEY):]: int(row["progress"]) for row in rows}


def _owned_pets(ctx: Context, user_id: str | None = None):
    return ctx.repo.owned_pets(user_id or ctx.user_id)


def _pet_for(ctx: Context, species_id: str):
    pets = [pet for pet in _owned_pets(ctx) if pet.species_id == species_id and not pet.archived]
    if not pets:
        return None
    player = ctx.player()
    active = next((pet for pet in pets if pet.pet_id == player.active_pet_id), None)
    return active or sorted(pets, key=lambda pet: pet.pet_id)[0]


def enemy_for(ctx: Context, species) -> Enemy:
    boost = trial(ctx).boost
    base = species.stats
    return Enemy(
        id=f"codex_{species.id}",
        name=f"{species.name}幻影",
        stats=Stats(
            hp=max(1, round(base.hp * boost)),
            attack=max(1, round(base.attack * boost)),
            defense=max(0, round(base.defense * boost)),
            speed=max(1, round(base.speed * boost)),
        ),
        elements=species.elements,
        primary_element=species.primary_element,
        signature_skill=None,
        skill_every=None,
    )


def _reward_text(ctx: Context) -> str:
    reward = trial(ctx).reward
    parts = [f"灵石 {reward.stones.minimum}"]
    if reward.exp.maximum:
        parts.append(f"修为 {reward.exp.minimum}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def _state(ctx: Context, species_id: str, rounds: int | None) -> str:
    if rounds is not None:
        return f"已通关（{rounds} 回合）"
    return "可挑战" if _pet_for(ctx, species_id) is not None else "未拥有"


def page(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠图鉴试炼",
            (
                "尚未结契，先完成领养，才能带着伙伴挑战同族幻影。",
                "每个种族都有一场一对一试炼：用自家伙伴击败该族幻影，首通发奖。",
                "试炼只考验这一只伙伴，装备、灵术、天赋与师门都会计入。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = trial(ctx)
    cleared_map = cleared(ctx)
    entries = species_list(ctx)
    paged = paginate(entries, arg, "灵宠图鉴试炼", "灵宠图鉴试炼", PAGE_SIZE)
    lines = [
        f"已通关 {len(cleared_map)}/{len(entries)} · 第 {paged.number}/{paged.total} 页"
        f" · 每场精力 {entry.energy} · 首通 {_reward_text(ctx)}",
    ]
    links = []
    for species in paged.entries:
        rounds = cleared_map.get(species.id)
        enemy = enemy_for(ctx, species)
        lines.append(
            f"{species.name} · {_state(ctx, species.id, rounds)}"
            f" · 幻影 气血 {enemy.stats.hp} · 攻击 {enemy.stats.attack}"
            f" · 防御 {enemy.stats.defense} · 速度 {enemy.stats.speed}"
        )
        if rounds is not None or _pet_for(ctx, species.id) is not None:
            links.append(InlineCommand(len(lines) - 1, "挑战", f"灵宠图鉴试炼 挑战 {species.name}"))
    milestones = [
        f"{milestone.count} 族 → "
        + "、".join(
            f"{ctx.content.items[item_id].name} {amount}"
            for item_id, amount in milestone.items.items()
        )
        for milestone in entry.milestones
    ]
    if milestones:
        lines.append("里程碑：" + "、".join(milestones) + "。")
    lines.append("首通后仍可再战，只作练习，不重复发奖。")
    return Reply(
        f"灵宠图鉴试炼 {paged.number}/{paged.total}",
        tuple(lines),
        (*paged.navigation, "灵宠图鉴试炼", "灵宠图鉴"),
        tuple(links),
    )


def _pay_reward(ctx: Context, entry: CodexTrial, pet) -> list[str]:
    lines = []
    stones = ctx.rng.randint(entry.reward.stones.minimum, entry.reward.stones.maximum)
    exp = ctx.rng.randint(entry.reward.exp.minimum, entry.reward.exp.maximum)
    player = ctx.player()
    player.stones += stones
    pet.exp += exp
    lines.append(f"灵石 +{stones}，{pet.name}修为 +{exp}")
    for item_id, bounds in entry.reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return lines


def _pay_milestones(ctx: Context, entry: CodexTrial, reached: int) -> list[str]:
    lines = []
    for milestone in entry.milestones:
        if milestone.count > reached:
            continue
        marker = f"{MILESTONE_KEY}{milestone.count}"
        existing = ctx.repo.conn.execute(
            "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, marker),
        ).fetchone()
        if existing is not None:
            continue
        parts = []
        for item_id, amount in milestone.items.items():
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            parts.append(f"{ctx.content.items[item_id].name} +{amount}")
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (ctx.user_id, marker),
        )
        lines.append(f"里程碑 {milestone.count} 族：" + "，".join(parts))
    return lines


def challenge(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠图鉴试炼 挑战 <种族名>。")
    entry = trial(ctx)
    species = named(ctx.content.species, text)
    pet = _pet_for(ctx, species.id)
    if pet is None:
        raise GameError(f"尚未拥有{species.name}，无法挑战该族幻影。")
    player = ctx.player()
    ctx.check_action(player, pet, "pve", entry.energy, ctx.config.spirit_pet_pve_cooldown)

    enemy = enemy_for(ctx, species)
    allies = [combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)]
    enemies = [enemy_fighter(enemy, ctx.content.skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)

    pet.energy -= entry.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"{species.name} · 幻影 · {battle.rounds} 回合", *battle.lines]
    lines.extend(award_mastery(
        ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
    ))

    if battle.winner == 0:
        advance(ctx, "pve")
        inserted = ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (ctx.user_id, f"{TRIAL_KEY}{species.id}", battle.rounds),
        )
        if inserted.rowcount == 1:
            lines.append(f"首通{species.name}试炼：" + "，".join(_pay_reward(ctx, entry, pet)))
            lines.extend(_pay_milestones(ctx, entry, len(cleared(ctx))))
            title = "图鉴试炼首通"
        else:
            lines.append("该族试炼此前已通关，本次为练习，不重复发放首通奖励。")
            title = "图鉴试炼再胜"
    else:
        title = "图鉴试炼平局" if battle.winner == -1 else "图鉴试炼败退"
        lines.append("本次未通关，试炼进度不变。")
    lines.append(f"精力 -{entry.energy}；气血仅在本场战斗内结算。")
    reply = Reply(title, tuple(lines), ("灵宠图鉴试炼", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=f"codex_{species.id}", battle_name=f"图鉴试炼·{species.name}",
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if parts and parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    return page(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    total = len(species_list(ctx))
    return f"图鉴试炼：已通关 {len(cleared(ctx, user_id))}/{total}"
