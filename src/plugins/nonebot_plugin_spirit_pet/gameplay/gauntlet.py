"""Attrition gauntlet: consecutive opponents with the player's health carrying over.

Every other mode builds fresh fighters per encounter. Here the player's side is built **once** and
the same ``Fighter`` objects are passed to ``fight()`` for each round, so the hp left after round *n*
is the hp the lineup starts round *n+1* with. Losing a round ends the run immediately.

State lives in ``quest_progress``: ``gauntlet_<week_start>_<ladder>_<round>`` marks a round cleared
this week and ``gauntlet_<week_start>_<ladder>_all`` marks that ladder's full clear, so rewards are
paid once per ladder per week. More than one ladder may ship (an early one and a late-realm one), so
the ladder id is part of every key; the original single-ladder keys gain the ladder id they always
implied.
"""

import re

from ..application.context import Context
from ..domain.content import Stats
from ..domain.gauntlet_content import Gauntlet
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

KEY = "gauntlet_"
HISTORY = frozenset({"战历", "战绩"})
HISTORY_PAGE_SIZE = 6
# `gauntlet_[<ladder id>_]<week start>_<round|all>`; the default ladder has no id part.
WEEK_MARKER = re.compile(r"^gauntlet_(?:([a-z][a-z0-9_]*)_)?([0-9]+)_([0-9]+|all)$")


def ladders(ctx: Context) -> list[Gauntlet]:
    """Stable order: content order by id, so the shipped ladder stays first."""
    return sorted(ctx.content.gauntlets.values(), key=lambda entry: entry.id)


def config(ctx: Context) -> Gauntlet:
    """The default ladder (`gauntlet`), kept for existing callers and old tests."""
    return ladders(ctx)[0]


def ladder(ctx: Context, value: str) -> Gauntlet:
    return named({entry.id: entry for entry in ladders(ctx)}, value)


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _prefix(ctx: Context, ladder_id: str | None = None) -> str:
    """Key prefix: the legacy `gauntlet_` for the shipped ladder, else `gauntlet_<id>_`."""
    entry = config(ctx) if ladder_id is None else ladder(ctx, ladder_id)
    return KEY if entry.id == config(ctx).id else f"{KEY}{entry.id}_"


def _round_key(ctx: Context, round_number: int, ladder_id: str | None = None) -> str:
    """`gauntlet_<week>_<round>` for the shipped ladder; later ladders add their id.

    The original single-ladder keys are byte-for-byte preserved so an existing week's
    markers keep counting; a second ladder namespaces only its own keys, which is what
    keeps the two ladders independent.
    """
    return f"{_prefix(ctx, ladder_id)}{week_start(ctx)}_{round_number}"


def _all_key(ctx: Context, ladder_id: str | None = None) -> str:
    return f"{_prefix(ctx, ladder_id)}{week_start(ctx)}_all"


def cleared(ctx: Context, round_number: int, user_id: str | None = None, ladder_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _round_key(ctx, round_number, ladder_id)),
    ).fetchone()
    return row is not None


def all_cleared(ctx: Context, user_id: str | None = None, ladder_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _all_key(ctx, ladder_id)),
    ).fetchone()
    return row is not None


def deepest(ctx: Context, user_id: str | None = None, ladder_id: str | None = None) -> int:
    entry = config(ctx) if ladder_id is None else ladder(ctx, ladder_id)
    return sum(1 for number in range(1, len(entry.rounds) + 1) if cleared(ctx, number, user_id, entry.id))


def weeks_run(ctx: Context, user_id: str | None = None) -> list[tuple[int, str, int]]:
    """Every recorded run as ``(week start, ladder id, rounds cleared)``, newest first.

    The per-round markers are written once per week and never cleaned, and only the
    current week is ever read, so a past week was unreachable. This groups exactly
    those rows; a ladder that has left the content is still reported by its id.
    """
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id or ctx.user_id, f"{KEY}*"),
    ).fetchall()
    known = {entry.id for entry in ladders(ctx)}
    weeks: dict[tuple[int, str], set[int]] = {}
    for row in rows:
        match = WEEK_MARKER.match(str(row["quest_id"]))
        if match is None:
            continue
        start, ladder_id, what = int(match.group(2)), match.group(1) or config(ctx).id, match.group(3)
        if what == "all" or ladder_id not in known:
            # The `_all` marker and retired ladders still prove the run happened.
            weeks.setdefault((start, ladder_id), set())
            continue
        weeks.setdefault((start, ladder_id), set()).add(int(what))
    return sorted(
        ((start, ladder_id, len(rounds)) for (start, ladder_id), rounds in weeks.items()),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )


def history(ctx: Context, arg: str) -> Reply:
    """Read-only record of past gauntlet weeks; pays nothing, writes nothing."""
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "擂台战历",
            (
                "尚未结契，先完成领养，才能留下擂台战绩。",
                "战历按周回顾你打到第几关，只读，不补发奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    records = weeks_run(ctx)
    if not records:
        return Reply(
            "擂台战历",
            (
                "还没有擂台记录，先发送 灵宠擂台 挑战一次。",
                "每通过一关会在本周留下一笔凭证，战历按周汇总。",
            ),
            ("灵宠擂台", "灵宠目标", "我的灵宠"),
        )
    page = paginate(records, arg, "擂台战历", "灵宠擂台 战历", HISTORY_PAGE_SIZE)
    lines = [
        f"共 {len(records)} 条周记录 · 第 {page.number}/{page.total} 页（新的在前）。",
    ]
    names = {entry.id: entry.name for entry in ladders(ctx)}
    for start, ladder_id, rounds in page.entries:
        name = names.get(ladder_id, f"{ladder_id}（已下线）")
        lines.append(f"{beijing_day(start)} 起那一周 · {name} · 通过 {rounds} 关")
    lines.append("战历只读：不重打、不补发奖励，也不改变本周进度。")
    return Reply(
        "擂台战历",
        tuple(lines),
        (*page.navigation, "灵宠擂台", "灵宠目标")[:4],
    )


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


def ladder_text(ctx: Context, entry) -> str:
    done = deepest(ctx, None, entry.id)
    return (
        f"{entry.name}（{len(entry.rounds)} 关 · 每只 {entry.energy} 精力）"
        f" · 本周已过 {done}/{len(entry.rounds)}"
        + (" · 已全清" if all_cleared(ctx, None, entry.id) else "")
    )


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠擂台 [名单|战历|挑战 [擂台名]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠擂台",
            (
                "尚未结契，先完成领养，才能登上擂台。",
                "连关连战，血量跨关延续；倒下即止，逐关首通与全清都有奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = config(ctx)
    done = deepest(ctx)
    lines = [
        f"擂台：本周已过 {done}/{len(entry.rounds)} 关。"
        f"每次挑战每只出战伙伴消耗 {entry.energy} 精力，血量跨关延续，落败即止。"
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
        f"全清奖励：修为 {bonus.exp.minimum} · 灵石 {bonus.stones.minimum}"
        + "".join(
            f" · {ctx.content.items[item_id].name} {bounds.minimum}"
            for item_id, bounds in bonus.items.items()
        )
        + ("（已领）" if all_cleared(ctx) else "")
    )
    if len(ladders(ctx)) > 1:
        lines.append(f"另有 {len(ladders(ctx)) - 1} 座擂台：发送 灵宠擂台 名单 查看并挑战。")
    lines.append("北京时间每周一 00:00 重置逐关凭证与全清奖励。")
    links = ()
    if not all_cleared(ctx):
        links = (InlineCommand(0, "挑战擂台", "灵宠擂台 挑战"),)
    return Reply("灵宠擂台", tuple(lines), ("灵宠擂台", "灵宠秘境", "灵宠战报"), links)


def roster(ctx: Context, arg: str) -> Reply:
    """All shipped ladders, so a late-realm player can pick the harder one."""
    if arg.strip():
        raise GameError("格式：灵宠擂台 名单。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "擂台名单",
            ("尚未结契，先完成领养，才能登上擂台。",),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = [f"擂台共 {len(ladders(ctx))} 座，逐座独立计周、独立发奖。"]
    links = []
    for entry in ladders(ctx):
        lines.append(ladder_text(ctx, entry))
        lines.append(f"   {entry.description}")
        if not all_cleared(ctx, None, entry.id):
            links.append(InlineCommand(len(lines) - 2, "挑战", f"灵宠擂台 挑战 {entry.id}"))
    lines.append("发送 灵宠擂台 查看第一座擂台的逐关详情，灵宠擂台 战历 回顾往期。")
    return Reply(
        "擂台名单",
        tuple(lines),
        ("灵宠擂台", "灵宠擂台 战历", "灵宠目标")[:4],
        tuple(links),
    )


def challenge(ctx: Context, arg: str) -> Reply:
    arg = arg.strip()
    entry = ladder(ctx, arg) if arg else config(ctx)
    if arg and ctx.repo.player(ctx.user_id) is None:
        raise GameError("尚未结契，先完成领养。")
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
                raise GameError(f"{pet.name}精力不足，{entry.name}需要 {entry.energy} 点。")

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
        if not cleared(ctx, number, None, entry.id):
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
                " ON CONFLICT(user_id, quest_id) DO NOTHING",
                (ctx.user_id, _round_key(ctx, number, entry.id)),
            )
            lines.append(f"第 {number} 关首通：" + "，".join(grant(ctx, round_.reward)))
        deciding = (number, battle, capture, enemies[0].name, "擂台过关")
        if number == len(entry.rounds) and not all_cleared(ctx, None, entry.id):
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
                (ctx.user_id, _all_key(ctx, entry.id)),
            )
            lines.append("全清：" + "，".join(grant(ctx, entry.bonus)))

    if deciding is not None:
        number, battle, capture, enemy_name, title = deciding
        record_battle(
            ctx, kind="pve_stage", battle=battle, capture=capture,
            reply=Reply(title, tuple(lines)), battle_key=_round_key(ctx, number, entry.id),
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
        f"本次通过 {cleared_now} 关，{entry.name}本周最深 {deepest(ctx, None, entry.id)}"
        f"/{len(entry.rounds)} 关；每只出战伙伴精力 -{entry.energy}。"
    )
    return Reply(title, tuple(lines), ("灵宠擂台", "灵宠战报", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    if head in HISTORY:
        return history(ctx, " ".join(parts[1:]))
    if head == "名单":
        return roster(ctx, " ".join(parts[1:]))
    if head == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠擂台 [名单|战历|挑战 [擂台名]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "擂台：尚未结契"
    done = deepest(ctx, user_id)
    return f"擂台：本周已过 {done}/{len(config(ctx).rounds)} 关" if done else "擂台：本周尚未挑战"
