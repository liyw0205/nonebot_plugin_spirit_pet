"""灵宠斗法: an exchange-based duel with one player decision per message.

Every other combat mode in this plugin resolves a whole encounter inside a single
command. A duel persists the fight between messages instead: the player picks one
stance per exchange, only the two health pools survive, and ``fight`` is asked for
exactly one round with ``max_rounds=1``. State lives in the existing
``quest_progress`` table (no schema change):

* ``duel_target`` — 1-based index into the sorted opponent list
* ``duel_round`` — the exchange about to be fought (1-based)
* ``duel_hp`` / ``duel_enemy_hp`` — health carried from the previous exchange

A win pays the opponent's weekly reward once per Beijing week
(``duel_week_<week start>_<opponent id>``). Duels deliberately write no battle
record and advance no daily/weekly counters: a bout is several exchanges, so a
single record would either misreport it or collide on ``battle_records``.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.duel_content import DuelOpponent
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_week
from .combat import Fighter, fight
from .loadout import combatant
from .rewards import grant

TARGET_KEY = "duel_target"
ROUND_KEY = "duel_round"
HP_KEY = "duel_hp"
ENEMY_HP_KEY = "duel_enemy_hp"
WEEK_PREFIX = "duel_week_"
STATE_KEYS = (TARGET_KEY, ROUND_KEY, HP_KEY, ENEMY_HP_KEY)
MAX_RATE = 2.5


def opponents(ctx: Context) -> list[DuelOpponent]:
    """Stable ladder order: realm first, then id."""
    order = {realm.id: index for index, realm in enumerate(ctx.content.realms)}
    return sorted(ctx.content.duels.values(), key=lambda entry: (order[entry.realm], entry.id))


def realm_index(ctx: Context, realm_id: str) -> int:
    for index, realm in enumerate(ctx.content.realms):
        if realm.id == realm_id:
            return index
    return len(ctx.content.realms)


def _week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _marker(ctx: Context, opponent: DuelOpponent) -> str:
    return f"{WEEK_PREFIX}{_week_start(ctx)}_{opponent.id}"


def _write(ctx: Context, key: str, value: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, value),
    )


def _clear(ctx: Context) -> None:
    ctx.repo.conn.execute(
        f"DELETE FROM quest_progress WHERE user_id=? AND quest_id IN ({','.join('?' * len(STATE_KEYS))})",
        (ctx.user_id, *STATE_KEYS),
    )


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    """The active bout, or ``None`` when the stored rows are missing or corrupt."""
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        f"SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id IN"
        f" ({','.join('?' * len(STATE_KEYS))})",
        (owner, *STATE_KEYS),
    ).fetchall()
    stored = {row["quest_id"]: int(row["progress"]) for row in rows}
    if len(stored) != len(STATE_KEYS):
        return None
    index = stored[TARGET_KEY]
    ladder = opponents(ctx)
    if not 1 <= index <= len(ladder):
        return None
    if stored[ROUND_KEY] < 1 or stored[HP_KEY] <= 0 or stored[ENEMY_HP_KEY] <= 0:
        return None
    return {
        "opponent": ladder[index - 1],
        "round": stored[ROUND_KEY],
        "hp": stored[HP_KEY],
        "enemy_hp": stored[ENEMY_HP_KEY],
    }


def claimed(ctx: Context, user_id: str, opponent: DuelOpponent) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, _marker(ctx, opponent)),
    ).fetchone()
    return bool(row and row["claimed"])


def weekly_wins(ctx: Context, user_id: str | None = None) -> int:
    """Opponents already beaten this week (the marker key carries the week)."""
    pattern = f"{WEEK_PREFIX}{_week_start(ctx)}_*"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (user_id or ctx.user_id, pattern),
    ).fetchall()
    prefix = f"{WEEK_PREFIX}{_week_start(ctx)}_"
    known = {opponent.id for opponent in opponents(ctx)}
    return sum(1 for row in rows if str(row["quest_id"])[len(prefix):] in known)


def _stance(ctx: Context, value: str):
    rule = ctx.content.rules.duel
    entry = rule.stances.get(value)
    if entry is None:
        entry = next((stance for stance in rule.stances.values() if stance.name == value), None)
    if entry is None:
        raise GameError("未知出手：可用 抢攻、稳守、游斗。")
    return entry


def _reward_text(ctx: Context, reward: Reward) -> str:
    def span(bounds: Range) -> str:
        return f"{bounds.minimum}" if bounds.minimum == bounds.maximum else f"{bounds.minimum}-{bounds.maximum}"

    parts = [f"灵石 {span(reward.stones)}", f"修为 {span(reward.exp)}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {span(bounds)}" for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def _pet(ctx: Context):
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    return pet


def _player_fighter(ctx: Context, pet, hp: int) -> Fighter:
    fighter = combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
    # 斗法不比灵术：每回合只结算一次四维对拼，所以技能不进入这一模式，
    # 否则 skill_interval/actions 会在每回合重置后失真。
    fighter.skills = ()
    fighter.actions = 0
    fighter.hp = min(hp, fighter.stats.hp)
    return fighter


def _enemy_fighter(opponent: DuelOpponent, hp: int) -> Fighter:
    fighter = Fighter.create(opponent.name, opponent.stats, (), ())
    fighter.hp = min(hp, opponent.stats.hp)
    return fighter


def _applied(fighter: Fighter, dealt: float, taken: float) -> None:
    fighter.dealt = min(MAX_RATE, max(0.25, fighter.dealt * dealt))
    fighter.taken = min(MAX_RATE, max(0.25, fighter.taken * taken))


def _status_text(entry: dict) -> str:
    return (
        f"斗法进行中：{entry['opponent'].name} · 第 {entry['round']} 回合"
        f" · 对方气血 {entry['enemy_hp']}/{entry['opponent'].stats.hp}"
    )


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠斗法 [护法名|抢攻|稳守|游斗|认输]。")
    rule = ctx.content.rules.duel
    ladder = opponents(ctx)
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠斗法",
            (
                "尚未结契，先完成领养，才能踏进斗法场。",
                f"斗法逐回合进行，{rule.exchanges} 回合内分胜负，每回合消耗 {rule.energy} 点精力。",
                "每回合选择抢攻、稳守或游斗，气血会保留到下一回合。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = ctx.pet()
    lines = [
        f"斗法：{rule.exchanges} 回合内分胜负，每回合精力 {rule.energy}。",
        "气血跨回合保留；选择出手会立即结算一回合。",
    ]
    current = state(ctx)
    state_line = None
    if current is not None:
        state_line = len(lines)
        lines.append(_status_text(current))
        lines.append(
            f"我方 {pet.name} 气血 {current['hp']}/{combatant(ctx, pet_id=pet.pet_id, recover_energy=False).stats.hp}"
        )
    wins = weekly_wins(ctx)
    lines.append(f"本周已胜 {wins}/{len(ladder)} 位护法。")
    links: list[InlineCommand] = []
    if current is not None:
        if ctx.repo.active_expedition(pet.pet_id) is not None:
            lines.append(f"{pet.name}正在外出派遣，斗法暂时无法继续。")
            lines.append("等伙伴归来再出手，或先认输结束本场。")
            links.append(InlineCommand(state_line, "认输", "灵宠斗法 认输"))
            return Reply("灵宠斗法", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"), tuple(links))
        stance_line = len(lines)
        lines.append("本回合出手：")
        for stance in rule.stances.values():
            links.append(InlineCommand(stance_line, stance.name, f"灵宠斗法 {stance.name}"))
        links.append(InlineCommand(state_line, "认输", "灵宠斗法 认输"))
        commands = ("灵宠斗法", "灵宠战报", "我的灵宠")
        return Reply("灵宠斗法", tuple(lines), commands, tuple(links))
    for opponent in ladder:
        requirement = realm_index(ctx, opponent.realm)
        if claimed(ctx, ctx.user_id, opponent):
            status = "本周已胜"
        elif pet.realm < requirement:
            status = f"需 {ctx.content.realms[requirement].name}"
        else:
            status = "可挑战"
        lines.append(f"{opponent.name}（{ctx.content.realms[requirement].name}）· 奖励 {_reward_text(ctx, opponent.reward)} · {status}")
        if status == "可挑战":
            links.append(InlineCommand(len(lines) - 1, "挑战", f"灵宠斗法 {opponent.name}"))
    if pet.energy < rule.energy:
        lines.append(f"{pet.name}精力不足：每回合需要 {rule.energy} 点。")
    return Reply("灵宠斗法", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"), tuple(links))


def _opponent(ctx: Context, value: str) -> DuelOpponent:
    return named({entry.id: entry for entry in opponents(ctx)}, value)


def start(ctx: Context, arg: str) -> Reply:
    rule = ctx.content.rules.duel
    opponent = _opponent(ctx, arg)
    if state(ctx) is not None:
        raise GameError("当前斗法尚未结束，请先出手或认输。")
    pet = _pet(ctx)
    requirement = realm_index(ctx, opponent.realm)
    if pet.realm < requirement:
        raise GameError(f"{opponent.name}需 {ctx.content.realms[requirement].name} 境界，先让伙伴成长吧。")
    if claimed(ctx, ctx.user_id, opponent):
        raise GameError(f"本周已胜过{opponent.name}，下周再来。")
    if pet.energy < rule.energy:
        raise GameError(f"{pet.name}精力不足，斗法每回合需要 {rule.energy} 点。")
    fighter = combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
    _clear(ctx)
    _write(ctx, TARGET_KEY, opponents(ctx).index(opponent) + 1)
    _write(ctx, ROUND_KEY, 1)
    _write(ctx, HP_KEY, fighter.stats.hp)
    _write(ctx, ENEMY_HP_KEY, opponent.stats.hp)
    lines = [
        f"对上{opponent.name}：{opponent.description}",
        f"对方气血 {opponent.stats.hp} · 攻击 {opponent.stats.attack} · 防御 {opponent.stats.defense}"
        f" · 速度 {opponent.stats.speed}",
        f"我方 {pet.name} 气血 {fighter.stats.hp} · 攻击 {fighter.stats.attack} · 防御 {fighter.stats.defense}"
        f" · 速度 {fighter.stats.speed}",
        f"第 1/{rule.exchanges} 回合，选择出手：",
    ]
    prompt = len(lines) - 1
    links = tuple(
        InlineCommand(prompt, stance.name, f"灵宠斗法 {stance.name}") for stance in rule.stances.values()
    )
    return Reply("斗法开局", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"), links)


def exchange(ctx: Context, arg: str) -> Reply:
    rule = ctx.content.rules.duel
    stance = _stance(ctx, arg)
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的斗法，先发送 灵宠斗法 <护法名>。")
    pet = _pet(ctx)
    if pet.energy < rule.energy:
        raise GameError(f"{pet.name}精力不足，斗法每回合需要 {rule.energy} 点。")
    opponent = current["opponent"]
    player = _player_fighter(ctx, pet, current["hp"])
    enemy = _enemy_fighter(opponent, current["enemy_hp"])
    _applied(player, stance.dealt, stance.taken)
    pet.energy -= rule.energy
    ctx.repo.invalidate_ready(ctx.user_id)
    battle = fight([player], [enemy], ctx.rng, ctx.content.elements, max_rounds=1)
    hp = max(0, player.hp)
    enemy_hp = max(0, enemy.hp)
    lines = [f"第 {current['round']}/{rule.exchanges} 回合 · {stance.name}", *battle.lines]
    if enemy_hp <= 0:
        _clear(ctx)
        marker = _marker(ctx, opponent)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
            (ctx.user_id, marker),
        )
        paid = grant(ctx, opponent.reward)
        lines.append(f"击败{opponent.name}，本周奖励：" + "，".join(paid))
        lines.append(f"本周已胜 {weekly_wins(ctx)}/{len(opponents(ctx))} 位护法。")
        lines.append(f"每回合精力 -{rule.energy}；气血只在本场斗法内保留。")
        return Reply("斗法得胜", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"))
    if hp <= 0:
        _clear(ctx)
        lines.append(f"{pet.name}气血耗尽，斗法中断，未获得本周奖励。")
        lines.append(f"每回合精力 -{rule.energy}；下周或成长后再来挑战。")
        return Reply("斗法败退", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"))
    if current["round"] >= rule.exchanges:
        _clear(ctx)
        lines.append(f"{rule.exchanges} 回合用尽仍未分胜负，斗法以平局收场。")
        lines.append(f"每回合精力 -{rule.energy}；气血只在本场斗法内保留。")
        return Reply("斗法平局", tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"))
    _write(ctx, ROUND_KEY, current["round"] + 1)
    _write(ctx, HP_KEY, hp)
    _write(ctx, ENEMY_HP_KEY, enemy_hp)
    lines.append(
        f"我方 {pet.name} 气血 {hp}/{player.stats.hp} · {opponent.name} 气血 {enemy_hp}/{opponent.stats.hp}"
    )
    stance_line = len(lines)
    lines.append("下一回合出手：")
    links = tuple(
        InlineCommand(stance_line, item.name, f"灵宠斗法 {item.name}") for item in rule.stances.values()
    )
    links += (InlineCommand(0, "认输", "灵宠斗法 认输"),)
    return Reply("斗法 · 第 %d 回合" % current["round"], tuple(lines), ("灵宠斗法", "灵宠战报", "我的灵宠"), links)


def forfeit(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠斗法 认输。")
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的斗法。")
    opponent = current["opponent"]
    _clear(ctx)
    return Reply(
        "斗法中止",
        (
            f"你向{opponent.name}抱拳认输，本场斗法到此为止。",
            "认输不发奖励；气血不会带回下一场，精力照常扣除。",
            f"本周已胜 {weekly_wins(ctx)}/{len(opponents(ctx))} 位护法。",
        ),
        ("灵宠斗法", "灵宠战报", "我的灵宠"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    if len(parts) > 1 and head == "认输":
        return forfeit(ctx, " ".join(parts[1:]))
    if len(parts) == 1 and head == "认输":
        return forfeit(ctx, "")
    if _is_stance(ctx, head):
        if len(parts) > 1:
            raise GameError("格式：灵宠斗法 抢攻|稳守|游斗。")
        return exchange(ctx, head)
    return start(ctx, arg)


def _is_stance(ctx: Context, value: str) -> bool:
    try:
        _stance(ctx, value)
    except GameError:
        return False
    return True


def objective_line(ctx: Context, user_id: str) -> str:
    current = state(ctx, user_id)
    wins = weekly_wins(ctx, user_id)
    total = len(opponents(ctx))
    if current is None:
        return f"斗法：本周已胜 {wins}/{total} 位护法 · 未开局"
    return f"斗法：本周已胜 {wins}/{total} 位护法 · {current['opponent'].name} 第 {current['round']} 回合"


__all__ = [
    "claimed", "dispatch", "exchange", "forfeit", "objective_line", "opponents", "page",
    "start", "state", "weekly_wins",
]
