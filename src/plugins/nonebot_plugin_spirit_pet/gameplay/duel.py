"""灵宠斗法: an exchange-based duel with one player decision per message.

Every other combat mode in this plugin resolves a whole encounter inside a single
command. A duel persists the fight between messages instead: the player picks one
stance per exchange, only the two health pools survive, and ``fight`` is asked for
exactly one round with ``max_rounds=1``. State lives in the existing
``quest_progress`` table for compatibility, with opening metadata and durable
action replies in ``duel_actions``:

* ``duel_target`` — 1-based index into the sorted opponent list
* ``duel_round`` — the exchange about to be fought (1-based)
* ``duel_hp`` / ``duel_enemy_hp`` — health carried from the previous exchange

A win pays the opponent's weekly reward once per Beijing week
(``duel_week_<week start>_<opponent id>``). Duels deliberately write no battle
record and advance no daily/weekly counters: a bout is several exchanges, so a
single record would either misreport it or collide on ``battle_records``.
"""

import re

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.duel_content import DuelOpponent
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, beijing_week
from .combat import Fighter, fight
from .loadout import combatant
from .rewards import grant
from . import duel_tactics as tactics

TARGET_KEY = "duel_target"
ROUND_KEY = "duel_round"
HP_KEY = "duel_hp"
ENEMY_HP_KEY = "duel_enemy_hp"
WEEK_PREFIX = "duel_week_"
STATE_KEYS = (TARGET_KEY, ROUND_KEY, HP_KEY, ENEMY_HP_KEY)
MAX_RATE = 2.5
# `duel_week_<week start epoch>_<opponent id>`; opponent ids carry no underscore.
WEEK_MARKER = re.compile(r"^duel_week_([0-9]+)_(.+)$")
HISTORY_PAGE_SIZE = 6
HISTORY = frozenset({"战历", "战绩"})


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
    latest = ctx.repo.latest_duel_action(owner)
    bout = latest["bout"] if latest and latest["status"] == "active" else None
    if bout is None and not 1 <= index <= len(ladder):
        return None
    if stored[ROUND_KEY] < 1 or stored[HP_KEY] <= 0 or stored[ENEMY_HP_KEY] <= 0:
        return None
    return {
        "opponent": DuelOpponent.model_validate(bout["opponent"]) if bout else ladder[index - 1],
        "bout": bout,
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


def weeks_won(ctx: Context, user_id: str | None = None) -> list[tuple[int, int]]:
    """Every recorded duel week as ``(week start, distinct guardians beaten)``.

    The markers `duel_week_<week start>_<opponent id>` are written once per week and
    never cleaned, and until now only the current week was ever read, so an older
    win was unreachable. This groups exactly those rows: newest week first, and
    guardians that later left the shipped content still count under their id.
    """
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (owner, f"{WEEK_PREFIX}*"),
    ).fetchall()
    weeks: dict[int, set[str]] = {}
    for row in rows:
        match = WEEK_MARKER.match(str(row["quest_id"]))
        if match is None:
            continue
        weeks.setdefault(int(match.group(1)), set()).add(match.group(2))
    return [(start, len(ids)) for start, ids in sorted(weeks.items(), reverse=True)]


def _beaten_in_week(ctx: Context, user_id: str, start: int) -> list[str]:
    """Names of the guardians beaten in one recorded week, in ladder order."""
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (user_id, f"{WEEK_PREFIX}{start}_*"),
    ).fetchall()
    prefix = f"{WEEK_PREFIX}{start}_"
    beaten = {str(row["quest_id"])[len(prefix):] for row in rows}
    ordered = [entry.name for entry in opponents(ctx) if entry.id in beaten]
    # A win recorded against content that has since been removed is still a win.
    retired = sorted(beaten - {entry.id for entry in opponents(ctx)})
    return ordered + [f"{entry_id}（已下线）" for entry_id in retired]


def history(ctx: Context, arg: str) -> Reply:
    """Read-only record of past duel weeks; pays nothing, writes nothing."""
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "斗法战历",
            (
                "尚未结契，先完成领养，才能留下斗法战绩。",
                "战历按周回顾你胜过哪些护法，只读，不补发奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    records = weeks_won(ctx)
    if not records:
        return Reply(
            "斗法战历",
            (
                "还没有胜过任何护法，先发送 灵宠斗法 挑一位试试。",
                "每胜一位护法会在本周留下一笔记录，战历按周汇总。",
            ),
            ("灵宠斗法", "灵宠目标", "我的灵宠"),
        )
    page = paginate(records, arg, "斗法战历", "灵宠斗法 战历", HISTORY_PAGE_SIZE)
    lines = [
        f"共 {len(records)} 周有胜绩 · 第 {page.number}/{page.total} 页（新的在前）。",
    ]
    for start, count in page.entries:
        names = _beaten_in_week(ctx, ctx.user_id, start)
        lines.append(
            f"{beijing_day(start)} 起那一周 · 胜 {count}/{len(opponents(ctx))} 位护法"
        )
        lines.append("   " + ("、".join(names) if names else "无记录"))
    lines.append("战历只读：不重打、不补发奖励，也不改变本周进度。")
    return Reply(
        "斗法战历",
        tuple(lines),
        (*page.navigation, "灵宠斗法", "灵宠目标")[:4],
    )


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
    try:
        pet = tactics.preview_pet(ctx)
    except GameError as error:
        if state(ctx) is None:
            raise
        return Reply("灵宠斗法", (str(error), "可先认输结束当前斗法，再选择伙伴。"),
                     ("灵宠列表", "灵宠封存库"), (InlineCommand(1, "认输", "灵宠斗法 认输"),))
    current = state(ctx)
    rule = tactics.rule(ctx, current)
    lines = [
        f"斗法：{rule.exchanges} 回合内分胜负，每回合精力 {rule.energy}。",
        "气血跨回合保留；选择出手会立即结算一回合。",
    ]
    state_line = None
    if current is not None:
        state_line = len(lines)
        lines.append(_status_text(current))
        original = current["bout"]["pet_name"] if current["bout"] else pet.name
        lines.append(f"我方 {original} · 本场剩余气血 {current['hp']}")
    wins = weekly_wins(ctx)
    lines.append(f"本周已胜 {wins}/{len(ladder)} 位护法。")
    links: list[InlineCommand] = []
    if current is not None:
        reason = tactics.blocked(ctx, pet, current)
        if reason:
            lines.append(reason)
            links.append(InlineCommand(state_line, "认输", "灵宠斗法 认输"))
            return Reply("灵宠斗法", tuple(lines), ("灵宠列表", "灵宠行程", "灵宠斗法 回顾"), tuple(links))
        lines.extend(tactics.preview_lines(ctx, current))
        stance_line = len(lines)
        lines.append("本回合出手：")
        for stance in rule.stances.values():
            links.append(InlineCommand(stance_line, stance.name, f"灵宠斗法 {stance.name}"))
        links.append(InlineCommand(state_line, "认输", "灵宠斗法 认输"))
        commands = ("灵宠斗法 回顾", "灵宠斗法 战历", "我的灵宠")
        return Reply("灵宠斗法", tuple(lines), commands, tuple(links))
    for opponent in ladder:
        requirement = realm_index(ctx, opponent.realm)
        if claimed(ctx, ctx.user_id, opponent):
            status = "本周已胜"
        elif pet.realm < requirement:
            status = f"需 {ctx.content.realms[requirement].name}"
        else:
            status = tactics.blocked(ctx, pet) or "可挑战"
        lines.append(f"{opponent.name}（{ctx.content.realms[requirement].name}）· 奖励 {_reward_text(ctx, opponent.reward)} · {status}")
        if status == "可挑战":
            links.append(InlineCommand(len(lines) - 1, "挑战", f"灵宠斗法 {opponent.name}"))
        links.append(InlineCommand(len(lines) - 1, "观招", f"灵宠斗法 详情 {opponent.name}"))
    if pet.energy < rule.energy:
        lines.append(f"{pet.name}精力不足：每回合需要 {rule.energy} 点。")
    return Reply("灵宠斗法", tuple(lines), ("灵宠斗法 回顾", "灵宠斗法 战历", "我的灵宠"), tuple(links))


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
    bout = tactics.opening(ctx, pet, opponent)
    lines = [
        f"对上{opponent.name}：{opponent.description}",
        f"对方气血 {opponent.stats.hp} · 攻击 {opponent.stats.attack} · 防御 {opponent.stats.defense}"
        f" · 速度 {opponent.stats.speed}",
        f"我方 {pet.name} 气血 {fighter.stats.hp} · 攻击 {fighter.stats.attack} · 防御 {fighter.stats.defense}"
        f" · 速度 {fighter.stats.speed}",
        f"本场由编号 {pet.pet_id} 的{pet.name}出战，换宠后需调回原伙伴才能继续。",
        *tactics.preview_lines(ctx, {"bout": bout, "opponent": opponent, "round": 1}),
        f"第 1/{rule.exchanges} 回合，选择出手：",
    ]
    prompt = len(lines) - 1
    links = tuple(
        InlineCommand(prompt, stance.name, f"灵宠斗法 {stance.name}") for stance in rule.stances.values()
    )
    reply = Reply("斗法开局", tuple(lines), ("灵宠斗法", "灵宠斗法 回顾", "我的灵宠"), links)
    return tactics.record(ctx, bout, "start", "active", reply, round=1)


def exchange(ctx: Context, arg: str) -> Reply:
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的斗法，先发送 灵宠斗法 <护法名>。")
    pet = _pet(ctx)
    reason = tactics.blocked(ctx, pet, current)
    if reason:
        raise GameError(reason)
    rule = tactics.rule(ctx, current)
    stance_key = next((key for key, value in rule.stances.items() if arg in (key, value.name)), None)
    if stance_key is None:
        raise GameError("未知出手：可用 抢攻、稳守、游斗。")
    stance = rule.stances[stance_key]
    opponent = current["opponent"]
    bout = current["bout"] or tactics.opening(ctx, pet, opponent, legacy=True)
    current["bout"] = bout
    player = _player_fighter(ctx, pet, current["hp"])
    enemy = _enemy_fighter(opponent, current["enemy_hp"])
    move = tactics.intent(current)
    outcome, dealt, taken = tactics.response(move, stance_key)
    _applied(player, stance.dealt * dealt, stance.taken * taken)
    pet.energy -= rule.energy
    ctx.repo.invalidate_ready(ctx.user_id)
    battle = fight([player], [enemy], ctx.rng, ctx.content.elements, max_rounds=1)
    hp = max(0, player.hp)
    enemy_hp = max(0, enemy.hp)
    lines = [f"第 {current['round']}/{rule.exchanges} 回合 · {stance.name}",
             f"护法出手：{tactics.NAMES[move] if move else '旧局平招'} · {outcome} · 出伤 ×{player.dealt:.3f} / 承伤 ×{player.taken:.3f}",
             f"本回合精力 -{rule.energy} · 剩余 {pet.energy}；我方气血 {hp}/{player.stats.hp} · 对方气血 {enemy_hp}/{opponent.stats.hp}",
             *battle.lines]

    def finish(status: str, reply: Reply) -> Reply:
        return tactics.record(ctx, bout, "exchange", status, reply, round=current["round"],
                              stance=stance_key, intent=move, outcome=outcome,
                              hp=hp, enemy_hp=enemy_hp, energy=rule.energy)
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
        return finish("won", Reply("斗法得胜", tuple(lines), ("灵宠斗法 回顾", "我的灵宠", "灵宠突破", "灵宠目标")))
    if hp <= 0:
        _clear(ctx)
        lines.append(f"{pet.name}气血耗尽，斗法中断，未获得本周奖励。")
        lines.append(f"每回合精力 -{rule.energy}；下周或成长后再来挑战。")
        return finish("lost", Reply("斗法败退", tuple(lines), ("灵宠斗法 回顾", "灵宠修炼", "我的灵宠")))
    if current["round"] >= rule.exchanges:
        _clear(ctx)
        lines.append(f"{rule.exchanges} 回合用尽仍未分胜负，斗法以平局收场。")
        lines.append(f"每回合精力 -{rule.energy}；气血只在本场斗法内保留。")
        return finish("draw", Reply("斗法平局", tuple(lines), ("灵宠斗法 回顾", "灵宠修炼", "我的灵宠")))
    _write(ctx, ROUND_KEY, current["round"] + 1)
    _write(ctx, HP_KEY, hp)
    _write(ctx, ENEMY_HP_KEY, enemy_hp)
    lines.append(
        f"我方 {pet.name} 气血 {hp}/{player.stats.hp} · {opponent.name} 气血 {enemy_hp}/{opponent.stats.hp}"
    )
    lines.extend(tactics.preview_lines(ctx, {**current, "round": current["round"] + 1}))
    stance_line = len(lines)
    lines.append("下一回合出手：")
    links = tuple(
        InlineCommand(stance_line, item.name, f"灵宠斗法 {item.name}") for item in rule.stances.values()
    )
    links += (InlineCommand(0, "认输", "灵宠斗法 认输"),)
    return finish("active", Reply("斗法 · 第 %d 回合" % current["round"], tuple(lines), ("灵宠斗法", "灵宠斗法 回顾", "我的灵宠"), links))


def forfeit(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠斗法 认输。")
    current = state(ctx)
    if current is None:
        raise GameError("当前没有进行中的斗法。")
    opponent = current["opponent"]
    _clear(ctx)
    bout = current["bout"]
    if bout is None:
        owner = ctx.player()
        pet = ctx.repo.pet(owner.active_pet_id) if owner.active_pet_id else None
        bout = tactics.opening(ctx, pet, opponent, legacy=True) if pet else {
            "id": ctx.operation_id, "pet_id": None, "pet_name": "旧局伙伴未记录",
            "opponent": opponent.model_dump(mode="json"),
            "rule": ctx.content.rules.duel.model_dump(mode="json"), "legacy": True,
        }
    reply = Reply(
        "斗法中止",
        (
            f"你向{opponent.name}抱拳认输，本场斗法到此为止。",
            "认输不发奖励、不额外扣精力；已消耗精力不返还，气血不带回下一场。",
            f"本周已胜 {weekly_wins(ctx)}/{len(opponents(ctx))} 位护法。",
        ),
        ("灵宠斗法", "灵宠斗法 回顾", "我的灵宠"),
    )
    return tactics.record(ctx, bout, "forfeit", "forfeit", reply, round=current["round"])


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    head = parts[0]
    if head == "详情":
        return tactics.detail(ctx, " ".join(parts[1:]))
    if head == "回顾":
        return tactics.review(ctx, " ".join(parts[1:]))
    if head in HISTORY:
        return history(ctx, " ".join(parts[1:]))
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
    current = state(ctx)
    if current and current.get("bout"):
        return any(value in (key, stance.name) for key, stance in tactics.rule(ctx, current).stances.items())
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
    move = tactics.intent(current)
    hint = f" · 将出{tactics.NAMES[move]}" if move else " · 旧局平招"
    return f"斗法：本周已胜 {wins}/{total} 位护法 · {current['opponent'].name} 第 {current['round']} 回合" + hint


__all__ = [
    "claimed", "dispatch", "exchange", "forfeit", "history", "objective_line", "opponents",
    "page", "start", "state", "weekly_wins", "weeks_won",
]
