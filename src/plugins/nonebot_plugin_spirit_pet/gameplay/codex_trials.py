"""Codex species trials: one permanent solo fight per owned species.

Each trial pits the player's own specimen against a boosted "幻影" of the same species
(species base stats × ``boost``, same elements, no skills). A first clear per species pays
once and counts toward the 9/18/27 milestones; repeats are practice runs.

State lives in the existing ``quest_progress`` table:

* ``codex_trial_<species_id>`` — rounds of the first clear
* ``codex_trial_milestone_<count>`` — 1 once that milestone has been paid
"""

from ..application.context import Context
from ..domain.codex_trial_content import CodexRotation, CodexTrial
from ..domain.content import Enemy, Species, Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, beijing_week
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance

TRIAL_KEY = "codex_trial_"
MILESTONE_KEY = "codex_trial_milestone_"
WEEK_KEY = "codex_week_"
WEEK_ALL_KEY = "codex_week_all_"
PAGE_SIZE = 9
HISTORY_HEAD = "战历"
HISTORY_PAGE_SIZE = 6


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


def _week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _week_ordinal(ctx: Context) -> int:
    """Stable integer per Beijing week, used to rotate both conditions and species."""
    return _week_start(ctx) // (7 * 86400)


def weekly_slots(ctx: Context) -> list[tuple[CodexRotation, Species, str | None]]:
    """This week's (rotation, species, required element) for each slot, in fixed order.

    Both the condition and the species slide by one each week, and ``(ordinal + i) % n``
    with ``i < n`` is always a distinct index, so a week can never show the same rotation
    twice. Same week + same slot = same trial for every player on the server.
    """
    entry = trial(ctx)
    if not entry.weekly_slots:
        return []
    ordinal = _week_ordinal(ctx)
    rotations = entry.rotations
    species = species_list(ctx)
    slots = []
    for index in range(entry.weekly_slots):
        rotation = rotations[(ordinal + index) % len(rotations)]
        target = species[(ordinal + index) % len(species)]
        element = None
        if rotation.kind == "element_lock":
            element = rotation.elements[(ordinal + index) % len(rotation.elements)]
        slots.append((rotation, target, element))
    return slots


def weekly_enemy(ctx: Context, species, rotation):
    """The mirror, with this rotation's condition applied on top of the trial's boost."""
    boost = trial(ctx).boost
    scale = rotation.scale if rotation.kind == "stat_scale" else 1.0
    factor = boost * scale
    base = species.stats
    return Enemy(
        id=f"codex_week_{species.id}",
        name=f"{species.name}幻影",
        stats=Stats(
            hp=max(1, round(base.hp * factor)),
            attack=max(1, round(base.attack * factor)),
            defense=max(0, round(base.defense * factor)),
            speed=max(1, round(base.speed * factor)),
        ),
        elements=species.elements,
        primary_element=species.primary_element,
        signature_skill=None,
        skill_every=None,
    )


def _rotation_text(ctx: Context, rotation) -> str:
    if rotation.kind == "round_limit":
        return f"{rotation.rounds} 回合内取胜"
    if rotation.kind == "element_lock":
        return "限定属性：" + "、".join(ctx.content.elements[key].name for key in rotation.elements)
    return f"幻影四维 ×{rotation.scale:g}（叠加图鉴加成）"


def _rotation_reward_text(ctx: Context, rotation) -> str:
    reward = rotation.reward
    parts = [f"灵石 {reward.stones.minimum}"]
    if reward.exp.maximum:
        parts.append(f"修为 {reward.exp.minimum}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def weekly_cleared(ctx: Context, user_id: str | None = None) -> set[int]:
    """Which slot numbers this player has cleared in the current week."""
    prefix = f"{WEEK_KEY}{_week_start(ctx)}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{prefix}%"),
    ).fetchall()
    done = set()
    for row in rows:
        tail = row["quest_id"][len(prefix):]
        if tail.isdecimal():
            done.add(int(tail))
    return done


def weeks_run(ctx: Context, user_id: str | None = None) -> list[tuple[int, int, bool]]:
    """Every recorded weekly-trial week as ``(week start, slots cleared, bonus paid)``.

    The per-slot rows and the ``codex_week_all_<week>`` marker are written once per
    week and never cleaned, while only the current week is ever read, so a past week
    was unreachable. This groups exactly those rows, newest week first.
    """
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{WEEK_KEY}%"),
    ).fetchall()
    weeks: dict[int, set[int]] = {}
    bonuses: set[int] = set()
    for row in rows:
        key = str(row["quest_id"])
        # `<all_prefix><week>` is prefix-first, `<week_key><week>_<slot>` is week-first.
        if key.startswith(WEEK_ALL_KEY):
            tail = key[len(WEEK_ALL_KEY):]
            if tail.isdecimal():
                bonuses.add(int(tail))
                weeks.setdefault(int(tail), set())
            continue
        tail = key[len(WEEK_KEY):]
        start_text, _, what = tail.partition("_")
        if not start_text.isdecimal():
            continue
        if what.isdecimal():
            weeks.setdefault(int(start_text), set()).add(int(what))
    return sorted(
        ((start, len(slots), start in bonuses) for start, slots in weeks.items()),
        key=lambda item: item[0],
        reverse=True,
    )


def history(ctx: Context, arg: str) -> Reply:
    """Read-only record of past weekly-trial weeks; pays nothing, writes nothing."""
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "图鉴试炼战历",
            (
                "尚未结契，先完成领养，才能留下试炼战绩。",
                "战历按周回顾你通关了几场每周试炼，只读，不补发奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    records = weeks_run(ctx)
    if not records:
        return Reply(
            "图鉴试炼战历",
            (
                "还没有每周试炼记录，先发送 灵宠图鉴试炼 每周 查看本周题目。",
                "每通关一场会在本周留下一笔凭证，战历按周汇总。",
            ),
            ("灵宠图鉴试炼 每周", "灵宠目标", "我的灵宠"),
        )
    page = paginate(records, arg, "图鉴试炼战历", "灵宠图鉴试炼 战历", HISTORY_PAGE_SIZE)
    slots = len(weekly_slots(ctx))
    lines = [
        f"共 {len(records)} 周有记录 · 第 {page.number}/{page.total} 页（新的在前）。",
    ]
    for start, count, bonus in page.entries:
        lines.append(
            f"{beijing_day(start)} 起那一周 · 通关 {count}/{slots} 场"
            + (" · 周奖已领" if bonus else "")
        )
    lines.append("战历只读：不重打、不补发奖励，也不改变本周进度。")
    return Reply(
        "图鉴试炼战历",
        tuple(lines),
        (*page.navigation, "灵宠图鉴试炼 每周", "灵宠目标")[:4],
    )


def weekly_page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "图鉴试炼 · 每周",
            (
                "尚未结契，先完成领养，才能挑战每周轮换的图鉴试炼。",
                "每周三场，条件由周号决定：限回合、限属性或加强幻影；同周全服一致。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entry = trial(ctx)
    slots = weekly_slots(ctx)
    if not slots:
        raise GameError("当前没有配置每周图鉴试炼。")
    done = weekly_cleared(ctx)
    lines = [
        f"本周 {len(done)}/{len(slots)} 场已通关 · 每场只考验一只伙伴，装备与灵术都会计入。",
    ]
    links = []
    for index, (rotation, species, element) in enumerate(slots, 1):
        state = "已通关" if index in done else "可挑战"
        element_text = f" · 需{ctx.content.elements[element].name}属性" if element else ""
        lines.append(
            f"{index}. {rotation.name} · {species.name}幻影 · {_rotation_text(ctx, rotation)}"
            f"{element_text} · {state} · 精力 {rotation.energy}"
        )
        lines.append(f"   {rotation.description} · 首通 {_rotation_reward_text(ctx, rotation)}")
        if index not in done:
            links.append(InlineCommand(
                len(lines) - 2, "挑战", f"灵宠图鉴试炼 每周 {index}",
            ))
    bonus = entry.weekly_bonus
    if bonus is not None:
        items = "、".join(
            f"{ctx.content.items[item_id].name} {bounds.minimum}"
            for item_id, bounds in bonus.items.items()
        )
        lines.append(f"三场全清追加：灵石 {bonus.stones.minimum} · 修为 {bonus.exp.minimum} · {items}。")
    lines.append("每周一 00:00（北京时间）换新，未通关的场次不保留。")
    return Reply("图鉴试炼 · 每周", tuple(lines),
                 ("灵宠图鉴试炼", "灵宠图鉴试炼 每周", "灵宠目标", "灵宠战报"), tuple(links))


def _pay_rotation(ctx: Context, rotation, pet) -> list[str]:
    reward = rotation.reward
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    exp = ctx.rng.randint(reward.exp.minimum, reward.exp.maximum)
    player = ctx.player()
    player.stones += stones
    pet.exp += exp
    lines = [f"灵石 +{stones}，{pet.name}修为 +{exp}"]
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return lines


def _pay_weekly_bonus(ctx: Context, pet) -> list[str]:
    bonus = trial(ctx).weekly_bonus
    if bonus is None:
        return []
    marker = f"{WEEK_ALL_KEY}{_week_start(ctx)}"
    existing = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, marker),
    ).fetchone()
    if existing is not None:
        return []
    stones = ctx.rng.randint(bonus.stones.minimum, bonus.stones.maximum)
    exp = ctx.rng.randint(bonus.exp.minimum, bonus.exp.maximum)
    player = ctx.player()
    player.stones += stones
    pet.exp += exp
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, marker),
    )
    parts = [f"灵石 +{stones}", f"{pet.name}修为 +{exp}"]
    for item_id, bounds in bonus.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            parts.append(f"{ctx.content.items[item_id].name} +{amount}")
    return ["本周三场全清：" + "，".join(parts)]


def weekly_trial(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text.isdecimal():
        raise GameError("格式：灵宠图鉴试炼 每周 <序号>，先用 灵宠图鉴试炼 每周 看本周场次。")
    index = int(text)
    slots = weekly_slots(ctx)
    if not slots:
        raise GameError("当前没有配置每周图鉴试炼。")
    if not 1 <= index <= len(slots):
        raise GameError(f"本周只有 {len(slots)} 场每周试炼。")
    rotation, species, element = slots[index - 1]
    if index in weekly_cleared(ctx):
        raise GameError(f"本周第 {index} 场已经通关，下周再来。")
    player = ctx.player()
    pet = ctx.pet()
    if element is not None:
        owned = ctx.content.species[pet.species_id].elements
        if element not in owned:
            raise GameError(
                f"本周第 {index} 场只容{ctx.content.elements[element].name}属性的伙伴出战，"
                f"{pet.name}的种族属性不匹配。"
            )
    ctx.check_action(player, pet, "pve", rotation.energy, ctx.config.spirit_pet_pve_cooldown)

    enemy = weekly_enemy(ctx, species, rotation)
    allies = [combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)]
    enemies = [enemy_fighter(enemy, ctx.content.skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id], []))
    limit = rotation.rounds if rotation.kind == "round_limit" else None
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements, max_rounds=limit)

    pet.energy -= rotation.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"{rotation.name} · {species.name}幻影 · {battle.rounds} 回合", *battle.lines]
    lines.extend(award_mastery(
        ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
    ))
    marker = f"{WEEK_KEY}{_week_start(ctx)}_{index}"
    if battle.winner == 0:
        advance(ctx, "pve")
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (ctx.user_id, marker, battle.rounds),
        )
        lines.append(f"第 {index} 场通关：" + "，".join(_pay_rotation(ctx, rotation, pet)))
        if len(weekly_cleared(ctx)) >= len(slots):
            lines.extend(_pay_weekly_bonus(ctx, pet))
        title = "每周试炼通关"
    elif limit is not None and battle.winner == -1:
        title = "每周试炼超时"
        lines.append(f"未能在 {limit} 回合内取胜，本场不算通关。")
    else:
        title = "每周试炼平局" if battle.winner == -1 else "每周试炼败退"
        lines.append("本次未通关，本周进度不变。")
    lines.append(f"精力 -{rotation.energy}；本周已通关 {len(weekly_cleared(ctx))}/{len(slots)} 场。")
    reply = Reply(title, tuple(lines), ("灵宠图鉴试炼 每周", "灵宠战报", "我的灵宠"))
    record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=f"codex_week_{_week_start(ctx)}_{index}",
        battle_name=f"每周图鉴试炼·{rotation.name}",
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if parts and parts[0] == HISTORY_HEAD:
        if len(parts) > 2:
            raise GameError("格式：灵宠图鉴试炼 战历 [页码]。")
        return history(ctx, parts[1] if len(parts) == 2 else "")
    if parts and parts[0] == "挑战":
        return challenge(ctx, " ".join(parts[1:]))
    if parts and parts[0] == "每周":
        rest = " ".join(parts[1:])
        if not rest:
            return weekly_page(ctx)
        return weekly_trial(ctx, rest)
    return page(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    total = len(species_list(ctx))
    line = f"图鉴试炼：已通关 {len(cleared(ctx, user_id))}/{total}"
    slots = weekly_slots(ctx)
    if slots and ctx.repo.player(user_id) is not None:
        line += f" · 本周 {len(weekly_cleared(ctx, user_id))}/{len(slots)}"
    return line
