"""Attrition gauntlet: five opponents in a row with the player's health carrying over.

Every other mode builds fresh fighters per encounter. Here the player's side is built **once** and
the same ``Fighter`` objects are passed to ``fight()`` for each round, so the hp left after round *n*
is the hp the lineup starts round *n+1* with. Losing a round ends the run immediately.

State lives in ``quest_progress``: ``gauntlet_<week_start>_<round>`` marks a round cleared this week
and ``gauntlet_<week_start>_all`` marks the full clear, so rewards are paid once per week.
"""

from ..application.context import Context
from ..domain.content import Stats
from ..domain.gauntlet_content import Gauntlet
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

KEY = "gauntlet_"


def config(ctx: Context) -> Gauntlet:
    return sorted(ctx.content.gauntlets.values(), key=lambda entry: entry.id)[0]


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _round_key(ctx: Context, round_number: int) -> str:
    return f"{KEY}{week_start(ctx)}_{round_number}"


def cleared(ctx: Context, round_number: int, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _round_key(ctx, round_number)),
    ).fetchone()
    return row is not None


def all_cleared(ctx: Context, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{KEY}{week_start(ctx)}_all"),
    ).fetchone()
    return row is not None


def deepest(ctx: Context, user_id: str | None = None) -> int:
    return sum(1 for number in range(1, len(config(ctx).rounds) + 1) if cleared(ctx, number, user_id))


def scaled(ctx: Context, entry) -> list:
    base = ctx.content.enemies[entry.enemy]
    stats = base.stats
    return [base.model_copy(update={
        "stats": Stats(
            hp=max(1, round(stats.hp * entry.hp_scale)),
            attack=max(1, round(stats.attack * entry.attack_scale)),
            defense=max(0, round(stats.defense * entry.defense_scale)),
            speed=max(1, round(stats.speed * entry.speed_scale)),
        ),
    })]


def reward_text(ctx: Context, entry) -> str:
    reward = entry.reward
    parts = [f"修为 {reward.exp.minimum}", f"灵石 {reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠擂台 [挑战]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠擂台",
            (
                "尚未结契，先完成领养，才能登上擂台。",
                "五关连战，血量跨关延续；倒下即止，逐关首通与全清都有奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = config(ctx)
    done = deepest(ctx)
    lines = [
        f"擂台：本周已过 {done}/{len(entry.rounds)} 关。"
        f"每次挑战每只出战伙伴消耗 {entry.energy} 精力，血量跨关延续，落败即止。",
    ]
    for number, round_ in enumerate(entry.rounds, 1):
        enemy = scaled(ctx, round_)[0]
        state = "已通关" if cleared(ctx, number) else "未通关"
        lines.append(
            f"{number}. {enemy.name} · 气血 {enemy.stats.hp} · 攻击 {enemy.stats.attack}"
            f" · 防御 {enemy.stats.defense} · 速度 {enemy.stats.speed}"
            f" · 奖励 {reward_text(ctx, round_)} · {state}"
        )
    bonus = entry.bonus
    lines.append(
        f"五关全清奖励：修为 {bonus.exp.minimum} · 灵石 {bonus.stones.minimum}"
        + "".join(
            f" · {ctx.content.items[item_id].name} {bounds.minimum}"
            for item_id, bounds in bonus.items.items()
        )
        + ("（已领）" if all_cleared(ctx) else "")
    )
    lines.append("北京时间每周一 00:00 重置逐关凭证与全清奖励。")
    links = ()
    if not all_cleared(ctx):
        links = (InlineCommand(0, "挑战擂台", "灵宠擂台 挑战"),)
    return Reply("灵宠擂台", tuple(lines), ("灵宠擂台", "灵宠秘境", "灵宠战报"), links)


def challenge(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠擂台 挑战。")
    entry = config(ctx)
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
                raise GameError(f"{pet.name}精力不足，擂台需要 {entry.energy} 点。")

    allies = [combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id) for user_id, pet in selected]
    for _, pet in selected:
        pet.energy -= entry.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)

    lines = []
    cleared_now = 0
    deciding = None
    for number, round_ in enumerate(entry.rounds, 1):
        if all(unit.hp <= 0 for unit in allies):
            break
        enemies = [enemy_fighter(enemy, ctx.content.skills) for enemy in scaled(ctx, round_)]
        # The snapshot is taken with the hp the lineup actually carries into this round.
        capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
        battle = fight(allies, enemies, ctx.rng, ctx.content.elements)
        for user_id, pet in selected:
            lines.extend(award_mastery(
                ctx, user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
            ))
        standing = "、".join(f"{unit.name} {unit.hp}/{unit.stats.hp}" for unit in allies)
        if battle.winner != 0:
            lines.append(
                f"第 {number} 关 {enemies[0].name}："
                + ("平局" if battle.winner == -1 else "败")
                + f" · {battle.rounds} 回合 · 剩余 {standing}。"
            )
            deciding = (number, battle, capture, enemies[0].name, "擂台落败")
            break
        cleared_now += 1
        lines.append(
            f"第 {number} 关 {enemies[0].name}：胜 · {battle.rounds} 回合 · 剩余 {standing}。"
        )
        if not cleared(ctx, number):
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
                " ON CONFLICT(user_id, quest_id) DO NOTHING",
                (ctx.user_id, _round_key(ctx, number)),
            )
            lines.append(f"第 {number} 关首通：" + "，".join(grant(ctx, round_.reward)))
        deciding = (number, battle, capture, enemies[0].name, "擂台过关")
        if number == len(entry.rounds) and not all_cleared(ctx):
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, f"{KEY}{week_start(ctx)}_all"),
            )
            lines.append("五关全清：" + "，".join(grant(ctx, entry.bonus)))

    if deciding is not None:
        number, battle, capture, enemy_name, title = deciding
        record_battle(
            ctx, kind="pve_stage", battle=battle, capture=capture,
            reply=Reply(title, tuple(lines)), battle_key=_round_key(ctx, number),
            battle_name=f"擂台·{enemy_name}",
        )
    if cleared_now:
        advance(ctx, "pve")
    if cleared_now == len(entry.rounds):
        title = "擂台全清"
    elif cleared_now:
        title = "擂台止步"
    else:
        title = "擂台首关失守"
    lines.append(
        f"本次通过 {cleared_now} 关，本周最深 {deepest(ctx)}/{len(entry.rounds)} 关；"
        f"每只出战伙伴精力 -{entry.energy}。"
    )
    return Reply(title, tuple(lines), ("灵宠擂台", "灵宠战报", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠擂台 [挑战]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "擂台：尚未结契"
    done = deepest(ctx, user_id)
    return f"擂台：本周已过 {done}/{len(config(ctx).rounds)} 关" if done else "擂台：本周尚未挑战"
