"""逐回合单人关卡战术。

章节关卡原本一次性自动结算。本模块把单人关卡拆成可暂停的回合：每回合
预告一种敌方意图，玩家选择强攻、稳守或破法，血量和每个敌人的剩余血量
写入既有 ``quest_progress``，因此不需要新的表或迁移。
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.stage_content import Stage
from ..gameplay.battle_records import capture_snapshot, record_battle
from ..utils.arguments import named, quantity
from . import battle_pass
from .combat import Battle, enemy_fighter, fight
from .loadout import combatant
from .pve_stages import _progress, _require_previous
from .quests import advance
from .rewards import grant

STAGE_KEY = "stage_tactic_stage"
PET_KEY = "stage_tactic_pet"
ROUND_KEY = "stage_tactic_round"
HP_KEY = "stage_tactic_hp"
ENEMY_PREFIX = "stage_tactic_enemy_"
CLEAR_PREFIX = "stage_tactic_clear_"
STATE_KEYS = (STAGE_KEY, PET_KEY, ROUND_KEY, HP_KEY)
MAX_ENEMIES = 5

STANCES = {
    "强攻": (1.18, 1.18),
    "稳守": (0.86, 0.72),
    "破法": (1.06, 0.92),
}
INTENTS = ("试探", "蓄力", "压制")
COUNTERS = {"试探": "强攻", "蓄力": "破法", "压制": "稳守"}


def _ordered(ctx: Context) -> list[Stage]:
    return sorted(ctx.content.stages.values(), key=lambda stage: stage.order)


def _stage(ctx: Context, value: str) -> Stage:
    text = value.strip()
    if text.isdecimal():
        order = quantity(text, len(ctx.content.stages))
        return next(stage for stage in _ordered(ctx) if stage.order == order)
    return named(ctx.content.stages, text)


def _write(ctx: Context, key: str, value: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, value),
    )


def _clear(ctx: Context) -> None:
    keys = (*STATE_KEYS, *(f"{ENEMY_PREFIX}{index}" for index in range(MAX_ENEMIES)))
    placeholders = ",".join("?" for _ in keys)
    ctx.repo.conn.execute(
        f"DELETE FROM quest_progress WHERE user_id=? AND quest_id IN ({placeholders})",
        (ctx.user_id, *keys),
    )


def active(ctx: Context, user_id: str | None = None) -> bool:
    return state(ctx, user_id) is not None


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    owner = user_id or ctx.user_id
    keys = (*STATE_KEYS, *(f"{ENEMY_PREFIX}{index}" for index in range(MAX_ENEMIES)))
    placeholders = ",".join("?" for _ in keys)
    rows = ctx.repo.conn.execute(
        f"SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id IN ({placeholders})",
        (owner, *keys),
    ).fetchall()
    values = {row["quest_id"]: int(row["progress"]) for row in rows}
    if not all(key in values for key in STATE_KEYS):
        return None
    try:
        stage = next(stage for stage in _ordered(ctx) if stage.order == values[STAGE_KEY])
    except StopIteration:
        return None
    enemies = [values.get(f"{ENEMY_PREFIX}{index}") for index in range(len(stage.enemies))]
    if any(hp is None or hp <= 0 for hp in enemies):
        return None
    if values[ROUND_KEY] < 1 or values[HP_KEY] <= 0:
        return None
    pet_owner = ctx.repo.conn.execute(
        "SELECT user_id, archived FROM pets WHERE pet_id=?", (values[PET_KEY],),
    ).fetchone()
    if pet_owner is None or pet_owner["user_id"] != owner or pet_owner["archived"]:
        return None
    return {
        "stage": stage,
        "pet_id": values[PET_KEY],
        "round": values[ROUND_KEY],
        "hp": values[HP_KEY],
        "enemy_hp": enemies,
    }


def _intent(current: dict) -> str:
    return INTENTS[(current["round"] - 1) % len(INTENTS)]


def _minimum_realm(ctx: Context, stage: Stage) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == stage.min_realm)


def _current(ctx: Context, current: dict) -> dict:
    stage = current["stage"]
    current["enemies"] = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in stage.enemies]
    current["pet"] = ctx.repo.pet(current["pet_id"])
    current["pet_hp"] = combatant_stats(ctx, current["pet"]).hp
    return current


def combatant_stats(ctx: Context, pet) -> object:
    return combatant(ctx, pet_id=pet.pet_id, recover_energy=False).stats


def _progress_label(ctx: Context, stage: Stage) -> str:
    row = _progress(ctx, ctx.user_id, stage.id)
    if row is not None:
        return "已通关"
    if stage.previous_id is None or _progress(ctx, ctx.user_id, stage.previous_id) is not None:
        return "可挑战"
    return "未解锁"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠关卡战术。进入关卡请发送 灵宠关卡战术 开始 编号。")
    current = state(ctx)
    if current is not None:
        current = _current(ctx, current)
        stage = current["stage"]
        intent = _intent(current)
        lines = [
            f"战术关卡：第 {stage.order} 关 · {stage.name}",
            f"第 {current['round']} 回合 · 我方气血 {current['hp']}/{current['pet_hp']}",
            "敌方气血：" + "、".join(
                f"{index + 1}号 {hp}/{enemy.stats.hp}"
                for index, (hp, enemy) in enumerate(zip(current["enemy_hp"], current["enemies"]))
            ),
            f"敌方预告：{intent} · 克制出手：{COUNTERS[intent]}",
            "选择一项行动，结算一回合；也可以认输结束本场。",
        ]
        line = len(lines)
        lines.append("本回合行动：")
        links = tuple(
            InlineCommand(line, stance, f"灵宠关卡战术 {stance}") for stance in STANCES
        ) + (InlineCommand(0, "认输", "灵宠关卡战术 认输"),)
        return Reply("灵宠关卡战术", tuple(lines), ("灵宠关卡", "灵宠关卡战绩", "灵宠目标"), links)

    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠关卡战术",
            ("尚未结契，先完成领养，才能挑战逐回合关卡。", "单人关卡可逐回合选择强攻、稳守或破法。"),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    entries = [stage for stage in _ordered(ctx) if not stage.team]
    lines = ["单人关卡战术：每场开局扣除该关卡精力，回合中可随时查看预告。"]
    links = []
    for stage in entries:
        status = _progress_label(ctx, stage)
        lines.append(f"{stage.order}. {stage.name} · {status} · 精力 {stage.energy}")
        if status in ("可挑战", "已通关"):
            links.append(InlineCommand(len(lines) - 1, "开始战术", f"灵宠关卡战术 开始 {stage.order}"))
    return Reply("灵宠关卡战术", tuple(lines), ("灵宠关卡", "灵宠帮助", "灵宠目标"), tuple(links))


def _ensure_not_duel(ctx: Context) -> None:
    from . import duel

    if duel.state(ctx) is not None:
        raise GameError("当前正在进行斗法，请先完成或认输，再进入关卡战术。")


def _record(ctx: Context, event: str, status: str, reply: Reply, **details) -> Reply:
    ctx.repo.record_stage_tactic_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"event": event, "status": status, **details}, reply,
    )
    return reply


def start(ctx: Context, value: str) -> Reply:
    stage = _stage(ctx, value)
    if stage.team:
        raise GameError("组队关卡不能进入战术模式，请使用 灵宠组队关卡。")
    if state(ctx) is not None:
        raise GameError("当前已有进行中的关卡战术，请先出手或认输。")
    _ensure_not_duel(ctx)
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    minimum = _minimum_realm(ctx, stage)
    if pet.realm < minimum:
        raise GameError(f"{pet.name}境界不足，{stage.name}需要{ctx.content.realms[minimum].name}。")
    if stage.previous_id is not None:
        _require_previous(ctx, stage, ctx.user_id)
    player = ctx.player()
    ctx.check_action(player, pet, "pve", stage.energy, ctx.config.spirit_pet_pve_cooldown)
    _clear(ctx)
    pet.energy -= stage.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    _write(ctx, STAGE_KEY, stage.order)
    _write(ctx, PET_KEY, pet.pet_id)
    _write(ctx, ROUND_KEY, 1)
    _write(ctx, HP_KEY, combatant_stats(ctx, pet).hp)
    for index, key in enumerate(stage.enemies):
        _write(ctx, f"{ENEMY_PREFIX}{index}", ctx.content.enemies[key].stats.hp)
    current = _current(ctx, {"stage": stage, "pet_id": pet.pet_id, "round": 1,
                             "hp": combatant_stats(ctx, pet).hp,
                             "enemy_hp": [ctx.content.enemies[key].stats.hp for key in stage.enemies]})
    intent = _intent(current)
    lines = [
        f"进入第 {stage.order} 关 · {stage.name}：{stage.description}",
        f"本场由 {pet.name} 出战，开局精力 -{stage.energy}；气血将在回合间保留。",
        f"敌方预告：{intent} · 克制出手：{COUNTERS[intent]}",
        "首回合行动：",
    ]
    prompt = len(lines) - 1
    links = tuple(InlineCommand(prompt, stance, f"灵宠关卡战术 {stance}") for stance in STANCES)
    return _record(ctx, "start", "active", Reply(
        "战术关卡开局", tuple(lines), ("灵宠关卡战术", "灵宠关卡", "我的灵宠"), links,
    ), stage_id=stage.id, round=1)


def _battle(ctx: Context, current: dict, stance_name: str):
    intent = _intent(current)
    dealt, taken = STANCES[stance_name]
    counter = COUNTERS[intent] == stance_name
    if counter:
        dealt *= 1.12
        taken *= 0.82
    elif stance_name != "稳守":
        dealt *= 0.92
        taken *= 1.08
    pet = current["pet"]
    player = combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
    player.skills = ()
    player.actions = max(0, current["round"] - 1)
    player.hp = min(current["hp"], player.stats.hp)
    player.dealt = dealt
    player.taken = taken
    enemies = []
    for index, key in enumerate(current["stage"].enemies):
        enemy = enemy_fighter(ctx.content.enemies[key], ctx.content.skills)
        enemy.hp = min(current["enemy_hp"][index], enemy.stats.hp)
        enemy.actions = max(0, current["round"] - 1)
        if counter:
            enemy.dealt = 0.82
        enemies.append(enemy)
    capture = capture_snapshot(ctx, ([player], enemies), ([ctx.user_id], []))
    battle = fight([player], enemies, ctx.rng, ctx.content.elements, max_rounds=1)
    return player, enemies, capture, battle, counter


def exchange(ctx: Context, stance_name: str) -> Reply:
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的关卡战术，请先发送 灵宠关卡战术 开始 编号。")
    if stance_name not in STANCES:
        raise GameError("未知行动：可用 强攻、稳守、破法。")
    current = _current(ctx, current)
    pet = ctx.pet()
    if pet.pet_id != current["pet_id"]:
        raise GameError(f"本场由编号 {current['pet_id']} 的伙伴出战，请切回原伙伴或认输。")
    player, enemies, capture, battle, counter = _battle(ctx, current, stance_name)
    hp = max(0, player.hp)
    enemy_hp = [max(0, enemy.hp) for enemy in enemies]
    stage = current["stage"]
    outcome = "破招" if counter else "应对"
    lines = [
        f"第 {current['round']} 回合 · {stance_name}",
        f"敌方预告：{_intent(current)} · {outcome} · 出伤 ×{player.dealt:.3f} / 承伤 ×{player.taken:.3f}",
        f"我方气血 {hp}/{player.stats.hp} · 敌方：" + "、".join(
            f"{index + 1}号 {value}/{enemy.stats.hp}" for index, (value, enemy) in enumerate(zip(enemy_hp, enemies))
        ),
        *battle.lines,
    ]
    next_round = current["round"] + 1

    def finish(status: str, reply: Reply) -> Reply:
        if status in ("won", "lost", "draw"):
            final = Battle(battle.winner, current["round"], tuple(lines), battle.skill_uses, battle.history)
            record_battle(ctx, kind="pve_stage", battle=final, capture=capture, reply=reply,
                          battle_key=stage.id, battle_name=stage.name)
        return _record(ctx, "exchange", status, reply, stage_id=stage.id, round=current["round"], stance=stance_name)

    if battle.winner == 0 or not any(enemy_hp):
        _clear(ctx)
        player_state = ctx.player()
        advance(ctx, "pve", player_state.user_id)
        battle_pass.add_experience(ctx, "pve_win", player_state.user_id)
        inserted = ctx.repo.conn.execute(
            "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, stage_id) DO NOTHING",
            (ctx.user_id, stage.id, ctx.now, ctx.operation_id),
        )
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1, progress=1",
            (ctx.user_id, f"{CLEAR_PREFIX}{stage.id}"),
        )
        lines.append("战术通关，逐回合判断成功！")
        if inserted.rowcount == 1:
            lines.append("首通奖励：" + "，".join(grant(ctx, stage.reward)))
            title = "战术关卡首通"
        else:
            lines.append("本关已经通关，本次只记录战术胜利，不重复发放首通奖励。")
            title = "战术关卡胜利"
        lines.append(f"本场共 {current['round']} 回合；开局已扣除 {stage.energy} 点精力。")
        return finish("won", Reply(title, tuple(lines), ("灵宠关卡战术", "灵宠关卡星级", "灵宠目标")))
    if hp <= 0:
        _clear(ctx)
        lines.append("伙伴气血耗尽，战术关卡败退，关卡进度不变。")
        reply = Reply("战术关卡败退", tuple(lines), ("灵宠关卡战术", "灵宠修炼", "我的灵宠"))
        return finish("lost", reply)
    if current["round"] >= 40:
        _clear(ctx)
        lines.append("回合上限已到，战术关卡以平局收场，关卡进度不变。")
        return finish("draw", Reply("战术关卡平局", tuple(lines), ("灵宠关卡战术", "灵宠关卡", "灵宠目标")))

    _write(ctx, ROUND_KEY, next_round)
    _write(ctx, HP_KEY, hp)
    for index, value in enumerate(enemy_hp):
        _write(ctx, f"{ENEMY_PREFIX}{index}", value)
    lines.append(f"下一回合预告：{INTENTS[(next_round - 1) % len(INTENTS)]} · 可选择强攻、稳守或破法。")
    line = len(lines)
    lines.append("下一回合行动：")
    links = tuple(InlineCommand(line, stance, f"灵宠关卡战术 {stance}") for stance in STANCES)
    links += (InlineCommand(0, "认输", "灵宠关卡战术 认输"),)
    reply = Reply(f"战术关卡 · 第 {current['round']} 回合", tuple(lines),
                  ("灵宠关卡战术", "灵宠关卡", "我的灵宠"), links)
    return finish("active", reply)


def forfeit(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠关卡战术 认输。")
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的关卡战术。")
    _clear(ctx)
    return _record(ctx, "forfeit", "forfeit", Reply("战术关卡中止", (
        f"已退出第 {current['stage'].order} 关 · {current['stage'].name}，不发放奖励。",
        "开局已消耗的精力不返还；关卡进度保持不变。",
    ), ("灵宠关卡战术", "灵宠关卡", "我的灵宠")), stage_id=current["stage"].id,
                  round=current["round"])


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "开始":
        if len(parts) != 2:
            raise GameError("格式：灵宠关卡战术 开始 关卡编号。")
        return start(ctx, parts[1])
    if len(parts) == 1 and parts[0] == "认输":
        return forfeit(ctx)
    if len(parts) == 1 and parts[0] in STANCES:
        return exchange(ctx, parts[0])
    raise GameError("格式：灵宠关卡战术 [开始 关卡编号|强攻|稳守|破法|认输]。")


def objective_line(ctx: Context, user_id: str) -> str:
    current = state(ctx, user_id)
    if current is not None:
        return f"关卡战术：第 {current['stage'].order} 关第 {current['round']} 回合进行中"
    total = sum(1 for stage in ctx.content.stages.values() if not stage.team)
    done = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (user_id, f"{CLEAR_PREFIX}*"),
    ).fetchone()[0]
    return f"关卡战术：已完成 {done}/{total} 处单人关卡"


__all__ = ["active", "dispatch", "objective_line", "page", "state"]
