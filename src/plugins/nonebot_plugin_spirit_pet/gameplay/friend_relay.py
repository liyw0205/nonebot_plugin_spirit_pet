"""Two consenting friends fight separate, frozen dungeon legs in one durable run."""

from hashlib import sha256
import sqlite3

from pydantic import ValidationError

from ..application.context import Context
from ..domain.friend_relay_state import INVITE_SECONDS, FriendRelaySnapshot, RelayFighter, RelayLeg
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.time import beijing_week
from . import friends, pet_targets
from .battle_records import BattleCapture, capture_snapshot, record_battle
from .combat import Fighter, enemy_fighter, fight
from .loadout import combatant
from .mastery import study
from .rewards import grant

TITLE = "灵宠接力"
FORMAT = f"{TITLE} 预览 秘境 伙伴编号 好友UID"
ACTIVE = {"pending", "first", "second"}
LABELS = {
    "pending": "待好友同意", "first": "待第一棒", "second": "待第二棒",
    "completed": "两棒全胜", "defeated": "试炼败退", "cancelled": "已退出",
    "rejected": "已拒绝", "expired": "邀请已到期",
}
PAGE_SIZE = 5


def _runs(ctx: Context, user_id: str | None = None, **filters) -> list[FriendRelaySnapshot]:
    try:
        rows = ctx.repo.friend_relay_runs(user_id or ctx.user_id, **filters)
        return [FriendRelaySnapshot.model_validate(row) for row in rows]
    except (ValidationError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("接力快照或记录损坏，成本、名额与战报保留；请联系管理员核对存档。") from exc


def active(ctx: Context, user_id: str | None = None) -> FriendRelaySnapshot | None:
    rows = _runs(ctx, user_id, active_only=True)
    return rows[0] if rows else None


def _run(ctx: Context, value: str) -> FriendRelaySnapshot:
    rows = _runs(ctx, run_id=quantity(value, 9_223_372_036_854_775_807))
    if not rows:
        raise GameError("没有找到属于你的接力局号。")
    return rows[0]


def _clock(ctx: Context, run: FriendRelaySnapshot) -> None:
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近接力操作，请等待时钟恢复；本局保留。")


def _slot(week: int) -> str:
    return f"friend_relay_week_{week}"


def _available(ctx: Context, user_id: str) -> None:
    rows = _runs(ctx, user_id)
    if rows:
        _clock(ctx, rows[0])
    if active(ctx, user_id) is not None:
        raise GameError("你或好友已有进行中的接力，请先续战、拒绝、退出或关闭到期邀请。")
    _weekly_available(ctx, user_id)


def _weekly_available(ctx: Context, user_id: str) -> None:
    if ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, _slot(beijing_week(ctx.now)[0])),
    ).fetchone():
        raise GameError("你或好友本周接力名额已使用；每人每周只能同意开局一次。")


def _pet(ctx: Context, user_id: str, pet_id: int, minimum: int):
    pet = next((pet for pet in ctx.repo.owned_pets(user_id) if pet.pet_id == pet_id), None)
    if pet is None:
        raise GameError("接力指定伙伴已封存或不在原主人名册；本局保留，可复原后继续或退出。")
    ctx.require_idle_pet(pet)
    if pet.realm < minimum:
        raise GameError("指定伙伴境界不足，无法参加该秘境接力。")
    return pet


def _freeze(fighter: Fighter) -> RelayFighter:
    values = {field: getattr(fighter, field) for field in RelayFighter.model_fields}
    for field in ("elements", "skills", "equipment_sets"):
        values[field] = list(values[field])
    return RelayFighter.model_validate(values)


def _fighter(frozen: RelayFighter) -> Fighter:
    return Fighter.create(**{field: getattr(frozen, field) for field in RelayFighter.model_fields})


def _record(ctx: Context, run: FriendRelaySnapshot, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, run.model_dump(), reply)
    return reply


def _change(run: FriendRelaySnapshot, **updates) -> FriendRelaySnapshot:
    return FriendRelaySnapshot.model_validate({**run.model_dump(), **updates})


def _display(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return player.uid_label if player else "已离去的修士"


def _terms(ctx: Context, parts: list[str]):
    if len(parts) != 3:
        raise GameError(f"格式：{FORMAT}。")
    player = ctx.player()
    dungeon = named(ctx.content.dungeons, parts[0])
    if dungeon.team:
        raise GameError("接力只选现有单人秘境，请从 灵宠秘境 选择。")
    pet = pet_targets.named_pet(ctx, parts[1], "接力", refresh_energy=False)
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm)
    _pet(ctx, ctx.user_id, pet.pet_id, minimum)
    target = friends._target(ctx, parts[2], player)
    if not friends.linked(ctx, ctx.user_id, target.user_id):
        raise GameError("接力需要双方已经成为好友。")
    for user_id in (ctx.user_id, target.user_id):
        _available(ctx, user_id)
    return dungeon, pet, target, minimum


def _new(ctx: Context, terms) -> FriendRelaySnapshot:
    dungeon, pet, target, minimum = terms
    run_id = max(1, int(sha256(f"friend-relay:{ctx.user_id}:{ctx.operation_id}".encode()).hexdigest()[:14], 16))
    return FriendRelaySnapshot(
        run_id=run_id, owner_id=ctx.user_id, helper_id=target.user_id,
        owner_pet_id=pet.pet_id, owner_pet_name=pet.name,
        dungeon_id=dungeon.id, dungeon_name=dungeon.name,
        min_realm=minimum, realm_name=ctx.content.realms[minimum].name,
        energy=dungeon.energy, cooldown=ctx.config.spirit_pet_pve_cooldown,
        mastery_per_use=ctx.content.rules.skill_proficiency_per_use,
        reward=dungeon.reward,
        reward_names={key: ctx.content.items[key].name for key in dungeon.reward.items},
        enemies=[_freeze(enemy_fighter(ctx.content.enemies[key], ctx.content.skills)) for key in dungeon.enemies],
        elements=dict(ctx.content.elements), status="pending", started_at=ctx.now,
        expires_at=ctx.now + INVITE_SECONDS, updated_at=ctx.now,
    )


def _cost(run: FriendRelaySnapshot) -> str:
    return f"每人一棒、精力 {run.energy}；各自出战时记录共享秘境调息 {run.cooldown} 秒"


def _reward_text(run: FriendRelaySnapshot) -> str:
    def bounds(value):
        return str(value.minimum) if value.minimum == value.maximum else f"{value.minimum}—{value.maximum}"
    return "、".join((f"修为 {bounds(run.reward.exp)}", f"灵石 {bounds(run.reward.stones)}", *(
        f"{run.reward_names[key]} {bounds(value)}" for key, value in run.reward.items.items()
    )))


def preview(ctx: Context, parts: list[str]) -> Reply:
    terms = _terms(ctx, parts)
    run = _new(ctx, terms)
    return Reply(TITLE + " · 预览", (
        f"邀请 {_display(ctx, run.helper_id)} 接力 {run.dungeon_name}，你派 {run.owner_pet_name}（编号 {run.owner_pet_id}）。",
        f"双方伙伴须达 {run.realm_name}；{_cost(run)}。邀请不扣精力、不占周名额。",
        "好友同意时冻结双方当时的伙伴属性、技能和规则，并占双方同意当周各一次名额；战败或退出不退名额。",
        f"双方依序各自出战；两胜时双方各获 {_reward_text(run)}，修为给原指定伙伴。邀请有效 24 小时，开局后可跨周续战。",
    ), (f"{TITLE} 邀请 {run.dungeon_name} {run.owner_pet_id} {terms[2].uid}", TITLE, "灵宠好友", "灵宠秘境"))


def invite(ctx: Context, parts: list[str]) -> Reply:
    run = _new(ctx, _terms(ctx, parts))
    return _record(ctx, run, _detail(ctx, run))


def _content_available(ctx: Context, run: FriendRelaySnapshot) -> None:
    if set(run.reward.items) - set(ctx.content.items):
        raise GameError("接力奖励引用的内容缺失，本局保留；请联系管理员核对。")
    skills = {skill.id for fighter in run.fighters for skill in fighter.skills}
    if skills - set(ctx.content.skills):
        raise GameError("接力技能引用的内容缺失，本局保留；请联系管理员核对。")


def _close(ctx: Context, run: FriendRelaySnapshot, status: str) -> Reply:
    ended = _change(run, status=status, updated_at=ctx.now, finished_at=ctx.now)
    return _record(ctx, ended, _detail(ctx, ended))


def accept(ctx: Context, value: str, pet_value: str) -> Reply:
    run = _run(ctx, value)
    if ctx.user_id != run.helper_id:
        raise GameError("只有受邀好友本人可以同意接力。")
    _clock(ctx, run)
    if run.status != "pending":
        raise GameError("该邀请已经处理，请重新打开接力页面。")
    if ctx.now >= run.expires_at:
        return _close(ctx, run, "expired")
    if not friends.linked(ctx, run.owner_id, run.helper_id):
        raise GameError("双方已解除好友，不能开局；可拒绝或退出邀请。")
    helper = pet_targets.named_pet(ctx, pet_value, "接力", refresh_energy=False)
    pets = [_pet(ctx, run.owner_id, run.owner_pet_id, run.min_realm),
            _pet(ctx, run.helper_id, helper.pet_id, run.min_realm)]
    for user_id in (run.owner_id, run.helper_id):
        _weekly_available(ctx, user_id)
        rows = _runs(ctx, user_id)
        if rows:
            _clock(ctx, rows[0])
        if any(other.run_id != run.run_id for other in _runs(ctx, user_id, active_only=True)):
            raise GameError("参与者已有另一局接力。")
    fighters, captures = [], []
    for user_id, pet in zip((run.owner_id, run.helper_id), pets):
        fighter = combatant(ctx, user_id, pet_id=pet.pet_id, recover_energy=False)
        fighters.append(_freeze(fighter))
        captures.append(capture_snapshot(
            ctx, ([fighter], [_fighter(enemy) for enemy in run.enemies]), ([user_id], []),
        ).snapshot)
    ready = _change(run, helper_pet_id=helper.pet_id, helper_pet_name=helper.name,
                    fighters=[value.model_dump() for value in fighters], captures=captures,
                    accepted_at=ctx.now, week=beijing_week(ctx.now)[0], status="first", updated_at=ctx.now)
    _content_available(ctx, ready)
    for user_id in (run.owner_id, run.helper_id):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
            (user_id, _slot(ready.week)),
        )
    return _record(ctx, ready, _detail(ctx, ready))


def leave(ctx: Context, value: str, *, reject: bool = False) -> Reply:
    run = _run(ctx, value)
    _clock(ctx, run)
    if reject and (ctx.user_id != run.helper_id or run.status != "pending"):
        raise GameError("只有受邀好友可以拒绝待同意邀请。")
    if run.status not in ACTIVE:
        raise GameError("本局已结束，不能重复退出。")
    status = "rejected" if reject else "cancelled"
    if run.status == "pending" and ctx.now >= run.expires_at:
        status = "expired"
    return _close(ctx, run, status)


def _mastery(ctx: Context, run: FriendRelaySnapshot, fighter: RelayFighter, uses: dict[str, int]) -> list[str]:
    lines = []
    # Frozen equipped skills still gain real proficiency after the owner changes loadout.
    for skill in fighter.skills:
        gained = uses.get(skill.id, 0) * run.mastery_per_use
        if not gained:
            continue
        row = ctx.repo.conn.execute(
            "SELECT proficiency,level FROM learned_skills WHERE pet_id=? AND skill_id=?", (fighter.pet_id, skill.id),
        ).fetchone()
        if row is None:
            raise GameError("接力冻结技能的学习记录缺失，本局保留；请联系管理员核对。")
        level, proficiency, _ = study(ctx, fighter.pet_id, skill.id, gained)
        lines.append(f"{skill.name}：实战使用 {uses[skill.id]} 次，现为 {level}级/{proficiency}熟练度。")
    return lines


def challenge(ctx: Context, value: str, stage: str) -> Reply:
    run = _run(ctx, value)
    _clock(ctx, run)
    expected = {"first": "1", "second": "2"}.get(run.status)
    if stage != expected or expected is None:
        raise GameError("该局号或棒次已过期，请重新打开接力页面。")
    index = int(stage) - 1
    owners = (run.owner_id, run.helper_id)
    pet_ids = (run.owner_pet_id, run.helper_pet_id)
    if ctx.user_id != owners[index]:
        raise GameError("尚未轮到你，必须由本棒对应玩家本人出战。")
    if not friends.linked(ctx, *owners):
        raise GameError("双方已解除好友，不能继续接力；任一方可退出，已付成本与战报保留。")
    _content_available(ctx, run)
    pets = [_pet(ctx, user_id, pet_id, run.min_realm) for user_id, pet_id in zip(owners, pet_ids)]
    pet = pets[index]
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    player = ctx.player()
    ctx.check_action(player, pet, "pve", run.energy, run.cooldown)
    last_pve = player.last_pve
    ally = _fighter(run.fighters[index])
    battle = fight([ally], [_fighter(enemy) for enemy in run.enemies], ctx.rng, run.elements, max_rounds=run.max_rounds)
    pet.energy -= run.energy
    player.last_pve = ctx.now
    mastery = _mastery(ctx, run, run.fighters[index], battle.skill_uses[0].get(pet.pet_id, {}))
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"局号 {run.run_id} · 第 {stage} 棒 · {run.dungeon_name} · {battle.rounds} 回合", *battle.lines, *mastery,
             f"{pet.name}精力 -{run.energy}；本棒调息 {run.cooldown} 秒，气血仅在本场结算。"]
    passed = battle.winner == 0
    status = ("second" if index == 0 else "completed") if passed else "defeated"
    settlement = None
    if status == "completed":
        settlement = {}
        for user_id, selected in zip(owners, pets):
            settlement[user_id] = list(grant(ctx, run.reward, user_id, pet_id=selected.pet_id))
            lines.append(f"{_display(ctx, user_id)}的{selected.name}终章：{'；'.join(settlement[user_id])}。")
            ctx.repo.invalidate_ready(user_id)
    elif status == "second":
        lines.append("第一棒获胜，等待好友本人接棒；终章奖励尚未结算。")
    else:
        lines.append("本棒未胜，接力结束；已付成本、熟练度与战报保留，无终章奖励。")
    reply = Reply(TITLE + " · " + LABELS[status], tuple(lines), (TITLE, f"{TITLE} 记录", "灵宠战报", "灵宠目标"))
    capture = BattleCapture(run.captures[index], tuple(
        {"user_id": user_id, "side": 0, "permission": "participant"} for user_id in owners
    ))
    report_id = record_battle(ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
                              battle_key=f"friend_relay_{run.run_id}_{stage}", battle_name=f"接力·{run.dungeon_name}·第{stage}棒")
    leg = RelayLeg(user_id=ctx.user_id, pet_id=pet.pet_id, winner=battle.winner, rounds=battle.rounds,
                   report_id=report_id, energy=run.energy, last_pve_before=last_pve, played_at=ctx.now, mastery=mastery)
    result = _change(run, status=status, updated_at=ctx.now,
                     outcomes=[*[leg.model_dump() for leg in run.outcomes], leg.model_dump()],
                     finished_at=None if status == "second" else ctx.now, settlement=settlement)
    return _record(ctx, result, reply)


def _detail(ctx: Context, run: FriendRelaySnapshot) -> Reply:
    index = 0 if ctx.user_id == run.owner_id else 1
    expired = run.status == "pending" and ctx.now >= run.expires_at
    label = "邀请到期，待关闭" if expired else LABELS[run.status]
    lines = [
        f"局号 {run.run_id} · {run.dungeon_name} · {label}。",
        f"第一棒：{_display(ctx, run.owner_id)}的{run.owner_pet_name}（编号 {run.owner_pet_id}）；"
        f"第二棒：{_display(ctx, run.helper_id)}的{run.helper_pet_name or '待选择伙伴'}。",
        f"境界 {run.realm_name}起；{_cost(run)}；两胜各得 {_reward_text(run)}。",
        "同意开局占双方当周名额，冻结双方当时属性与技能；各棒由本人执行。战败/退出不退已付精力、调息与名额。",
    ]
    commands, links = [], []
    if expired:
        commands.append(f"{TITLE} 退出 {run.run_id}")
    elif run.status == "pending":
        if index == 1:
            lines.append("选择你的在册伙伴，确认上述费用后同意；邀请有效 24 小时。")
            links.append(InlineCommand(len(lines) - 1, "选伙伴并同意", f"{TITLE} 同意 {run.run_id} "))
            commands.append(f"{TITLE} 拒绝 {run.run_id}")
        else:
            commands.append(f"{TITLE} 退出 {run.run_id}")
    elif run.status in {"first", "second"}:
        turn = 0 if run.status == "first" else 1
        lines.append(f"当前轮到 {_display(ctx, (run.owner_id, run.helper_id)[turn])} 本人执行第 {turn + 1} 棒；本局可跨周续战。")
        if index == turn:
            commands.append(f"{TITLE} 出战 {run.run_id} {turn + 1}")
        commands.append(f"{TITLE} 退出 {run.run_id}")
    for number, outcome in enumerate(run.outcomes, 1):
        lines.append(f"第 {number} 棒：{'胜利' if outcome.winner == 0 else '平局' if outcome.winner == -1 else '败退'}"
                     f" · {outcome.rounds} 回合 · 已付精力 {outcome.energy} · 战报 {outcome.report_id}。")
        links.append(InlineCommand(len(lines) - 1, "查看战报", f"灵宠战报 查看 {outcome.report_id}"))
    if run.settlement:
        lines.append("你的终章所得：" + "；".join(run.settlement[ctx.user_id]) + "。")
    elif run.status not in ACTIVE:
        lines.append("本局无终章奖励；已发生的战报、成本与周名额保留。")
    commands.extend((f"{TITLE} 记录", "灵宠好友", "灵宠秘境"))
    return Reply(TITLE, tuple(lines), tuple(commands[:4]), tuple(links))


def history(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) > 1:
        raise GameError(f"格式：{TITLE} 记录 [页码]。")
    page = quantity(parts[0], 999) if parts else 1
    runs = [run for run in _runs(ctx) if run.status not in ACTIVE]
    pages = max(1, (len(runs) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"接力记录共 {pages} 页。")
    lines = [f"共 {len(runs)} 局已结束接力 · 第 {page}/{pages} 页。"]
    links = []
    for run in runs[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        role = "第一棒" if run.owner_id == ctx.user_id else "第二棒"
        lines.append(f"局号 {run.run_id} · {run.dungeon_name} · 你是{role} · {LABELS[run.status]}。")
        links.append(InlineCommand(len(lines) - 1, "查看详情", f"{TITLE} 详情 {run.run_id}"))
    commands = []
    if page > 1:
        commands.append(f"{TITLE} 记录 {page - 1}")
    if page < pages:
        commands.append(f"{TITLE} 记录 {page + 1}")
    return Reply(TITLE + " · 记录", tuple(lines), (*commands, TITLE, "灵宠好友"), tuple(links))


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("先领养伙伴并结交好友，再各自派一位伙伴依序迎战。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = active(ctx)
    if run:
        return _detail(ctx, run)
    used = ctx.repo.conn.execute("SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
                                 (ctx.user_id, _slot(beijing_week(ctx.now)[0]))).fetchone()
    return Reply(TITLE, (
        "与好友各选一只伙伴，接力挑战同一现有单人秘境；两棒分别战斗，两胜才结算终章。",
        f"本周开局名额：{'已用' if used else '可用'}（每人每周一次，好友同意时占用）。邀请有效 24 小时，开局可跨周续战。",
        f"{FORMAT}。",
    ), (f"{TITLE} 记录", "灵宠好友", "灵宠秘境", "灵宠列表"),
        (InlineCommand(2, "填写接力约定", f"{TITLE} 预览 "),))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return page(ctx)
    action, rest = parts[0], parts[1:]
    if action == "预览":
        return preview(ctx, rest)
    if action == "邀请":
        return invite(ctx, rest)
    if action == "同意" and len(rest) == 2:
        return accept(ctx, *rest)
    if action == "出战" and len(rest) == 2:
        return challenge(ctx, *rest)
    if action in {"拒绝", "退出"} and len(rest) == 1:
        return leave(ctx, rest[0], reject=action == "拒绝")
    if action == "详情" and len(rest) == 1:
        return _detail(ctx, _run(ctx, rest[0]))
    if action == "记录":
        return history(ctx, rest)
    raise GameError(f"格式：{FORMAT}，或 {TITLE} 邀请 秘境 伙伴编号 好友UID / 同意 局号 伙伴编号 / 出战 局号 棒次 / 拒绝、退出、详情 局号 / 记录 [页码]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = active(ctx, user_id)
    if run is None:
        return "接力：暂无进行中的试炼"
    if run.status == "pending":
        status = "待你本人选宠同意" if user_id == run.helper_id else "等待好友本人选宠同意"
        if ctx.now >= run.expires_at:
            status = "邀请到期，待关闭"
    else:
        owner = run.owner_id if run.status == "first" else run.helper_id
        status = "轮到你本人出战" if owner == user_id else "等待好友本人接棒"
    return f"接力：局号 {run.run_id} · {status}"
