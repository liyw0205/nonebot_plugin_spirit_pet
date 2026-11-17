"""A durable three-stage relay with disjoint, frozen tactical presets."""

import json
from hashlib import sha256

from ..application.context import Context
from ..domain.content import Enemy, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from . import lineup_presets
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

TITLE = "灵宠轮战"
KIND = "roster_relay"
ENERGY = 10
PROFILES = (
    ("群敌", ("wood_guard", "wood_guard", "wood_guard"), 40),
    ("重甲", ("ancient_guard",), 40),
    ("速攻", ("moon_wolf",), 8),
)


def latest(ctx: Context, user_id: str | None = None) -> dict | None:
    row = ctx.repo.conn.execute(
        "SELECT snapshot FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')=? ORDER BY action_id DESC LIMIT 1",
        (user_id or ctx.user_id, KIND),
    ).fetchone()
    return json.loads(row["snapshot"]) if row else None


def active(ctx: Context) -> dict | None:
    state = latest(ctx)
    return state if state and state["status"] == "active" else None


def _clock(ctx: Context, state: dict | None) -> None:
    if state and ctx.now < state["updated_at"]:
        raise GameError("时间早于上次轮战，请等待时钟恢复。")


def _record(ctx: Context, state: dict, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {**state, "kind": KIND, "updated_at": ctx.now}, reply,
    )
    return reply


def _key(state: dict, stage: int) -> str:
    return f"relay_reward_{state['week']}_{stage}"


def _paid(ctx: Context, state: dict, stage: int) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _key(state, stage)),
    ).fetchone() is not None


def _pay(ctx: Context, state: dict, stage: int, reward: dict) -> tuple[str, ...]:
    if _paid(ctx, state, stage):
        return ("本周该项奖励已领取，本次仅检验战术。",)
    result = grant(ctx, Reward.model_validate(reward))
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
        (ctx.user_id, _key(state, stage)),
    )
    return result


def _reward(stones: int, ore: int) -> dict:
    return {"exp": {"minimum": 40, "maximum": 40},
            "stones": {"minimum": stones, "maximum": stones},
            "items": {"forge_ore": {"minimum": ore, "maximum": ore}}}


def _render(ctx: Context, state: dict, prefix: tuple[str, ...] = ()) -> Reply:
    stage = state["stage"]
    lines = [*prefix, f"轮次 {state['run']} · 已胜 {stage}/3 场。"]
    links = []
    outcomes = {entry["stage"]: entry for entry in state["outcomes"]}
    for index, entry in enumerate(state["stages"]):
        plan = entry["plan"]
        names = "、".join(f"编号 {pet_id}" for pet_id in plan["members"])
        reward = entry["reward"]
        lines.append(
            f"第 {index + 1} 场 · {entry['name']} · 预设 {plan['slot']}（{names}）"
            f" · {entry['limit']} 回合 · 每宠精力 {entry['energy']}"
            f" · 周首胜：灵石 {reward['stones']['minimum']} / 锻灵矿 {reward['items']['forge_ore']['minimum']}。"
        )
        enemies = [Enemy.model_validate(enemy) for enemy in entry["enemies"]]
        lines.append("敌手：" + "；".join(
            f"{enemy.name} {enemy.stats.hp}/{enemy.stats.attack}/{enemy.stats.defense}/{enemy.stats.speed}"
            for enemy in enemies
        ) + "（气血/攻击/防御/速度）。")
        outcome = outcomes.get(index + 1)
        if outcome:
            result = "胜" if outcome["passed"] else "未通过"
            lines.append(
                f"结果：{result} · {outcome['rounds']} 回合 · 已付精力 {outcome['paid_energy']}。"
            )
        if index == stage and state["status"] == "active":
            links.append(InlineCommand(
                len(lines) - (3 if outcome else 2), "派出战术", f"{TITLE} 出战 {state['run']} {stage + 1}",
            ))
    if state["status"] == "active":
        lines.append("已冻结三套战术；出战会应用该场配置。各场气血独立，落败终止，已获奖励保留。")
        links.append(InlineCommand(len(lines) - 1, "放弃本轮", f"{TITLE} 放弃 {state['run']} {stage + 1}"))
    return Reply(TITLE, tuple(lines), ("灵宠出战预设", "灵宠战报", "灵宠目标"), tuple(links))


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先完成领养。", "三套不同伙伴的战术，轮流迎战群敌、重甲与速攻。"),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    state = active(ctx)
    if state:
        return _render(ctx, state)
    lines = [
        "三套完整战术各出战一场，伙伴不可重复；至少准备三只伙伴。",
        "每场每宠精力 10，沿用秘境调息；速攻场须在 8 回合内击破。",
        "每周逐场首胜获修为 40、灵石 60、锻灵矿 1；三场全胜追加修为 40、灵石 100、锻灵矿 2。",
        "按预设顺序决定三场派遣，例如 灵宠轮战 开始 1 2 3。开局冻结，后续保存预设不改本轮。",
    ]
    try:
        plans = [lineup_presets.export_plan(ctx, slot) for slot in (1, 2, 3)]
    except GameError as exc:
        lines.append(f"尚不可开局：{exc}")
        links = ()
    else:
        members = [pet_id for plan in plans for pet_id in plan["members"]]
        if len(set(members)) != len(members):
            lines.append("尚不可开局：三套预设含重复伙伴，请先调整出战预设。")
            links = ()
        else:
            links = (InlineCommand(3, "按 1、2、3 开始", f"{TITLE} 开始 1 2 3"),)
    return Reply(TITLE, tuple(lines), ("灵宠出战预设", "灵宠目标"), links)


def start(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 3 or set(parts) != {"1", "2", "3"}:
        raise GameError(f"格式：{TITLE} 开始 预设 预设 预设，例如 {TITLE} 开始 1 2 3。")
    previous = latest(ctx)
    _clock(ctx, previous)
    if previous and previous["status"] == "active":
        raise GameError("已有轮战进行中，请继续或放弃本轮。")
    plans = [lineup_presets.export_plan(ctx, int(part)) for part in parts]
    members = [pet_id for plan in plans for pet_id in plan["members"]]
    if len(set(members)) != len(members):
        raise GameError("三套战术不能重复使用同一伙伴，请安排不同伙伴后重新保存。")
    stages = []
    for plan, (name, enemy_ids, limit) in zip(plans, PROFILES):
        stages.append({"name": name, "plan": plan, "limit": limit, "energy": ENERGY,
                       "enemies": [ctx.content.enemies[key].model_dump() for key in enemy_ids],
                       "reward": _reward(60, 1)})
    state = {"run": sha256(ctx.operation_id.encode()).hexdigest()[:16], "status": "active",
             "started_at": ctx.now, "week": beijing_week(ctx.now)[0], "stage": 0,
             "stages": stages, "bonus": _reward(100, 2), "outcomes": []}
    return _record(ctx, state, _render(ctx, state, ("轮战已开启，尚未扣除精力。",)))


def _guard(ctx: Context, parts: list[str]) -> dict:
    if len(parts) != 2 or parts[1] not in ("1", "2", "3"):
        raise GameError(f"请从 {TITLE} 当前页面选择出战或放弃。")
    state = active(ctx)
    if state is None or state["run"] != parts[0] or state["stage"] + 1 != int(parts[1]):
        raise GameError(f"该轮次或场次已过期，请重新打开 {TITLE}。")
    _clock(ctx, state)
    return state


def abandon(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    state = _guard(ctx, parts)
    state["status"] = "abandoned"
    return _record(ctx, state, Reply(TITLE, (f"本轮已放弃，已胜 {state['stage']} 场；已获奖励保留。",),
                                     (TITLE, "灵宠出战预设")))


def challenge(ctx: Context, parts: list[str]) -> Reply:
    player = ctx.player()
    state = _guard(ctx, parts)
    entry = state["stages"][state["stage"]]
    lineup_presets.apply_plan(ctx, entry["plan"])
    pets = ctx.active_pets()
    for index, pet in enumerate(pets):
        if index == 0:
            ctx.check_action(player, pet, "pve", entry["energy"], ctx.config.spirit_pet_pve_cooldown)
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < entry["energy"]:
                raise GameError(f"{pet.name}精力不足，需要 {entry['energy']} 点。")
    allies = [combatant(ctx, pet_id=pet.pet_id, recover_energy=False) for pet in pets]
    enemies = [enemy_fighter(Enemy.model_validate(enemy), ctx.content.skills) for enemy in entry["enemies"]]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id] * len(allies), []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements, max_rounds=entry["limit"])
    lines = [f"第 {state['stage'] + 1} 场 · {entry['name']} · {battle.rounds} 回合", *battle.lines]
    for pet in pets:
        pet.energy -= entry["energy"]
        lines.extend(award_mastery(ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id))
    player.last_pve = ctx.now
    passed = battle.winner == 0 and battle.rounds <= entry["limit"]
    state["outcomes"].append({"stage": state["stage"] + 1, "passed": passed,
                              "pets": [pet.pet_id for pet in pets], "rounds": battle.rounds,
                              "paid_energy": entry["energy"] * len(pets)})
    if passed:
        lines.extend(_pay(ctx, state, state["stage"] + 1, entry["reward"]))
        advance(ctx, "pve")
        state["stage"] += 1
        if state["stage"] == 3:
            lines.extend(_pay(ctx, state, 4, state["bonus"]))
            state["status"] = "completed"
            lines.append("三套战术全胜，本轮完成。")
        else:
            lines.append("本场获胜，下一场由另一套伙伴战术迎战。")
    else:
        state["status"] = "defeated"
        lines.append("本场未通过，轮战结束；已获奖励保留。")
    lines.append(f"本场每只伙伴精力 -{entry['energy']}；已应用预设 {entry['plan']['slot']}。")
    reply = _render(ctx, state, tuple(lines))
    record_battle(ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
                  battle_key=f"relay_{state['run']}_{len(state['outcomes'])}", battle_name=f"轮战·{entry['name']}")
    return _record(ctx, state, reply)


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts[0] == "开始":
        return start(ctx, parts[1:])
    if parts[0] == "出战":
        return challenge(ctx, parts[1:])
    if parts[0] == "放弃":
        return abandon(ctx, parts[1:])
    raise GameError(f"格式：{TITLE} [开始 1 2 3|出战 轮次 场次|放弃 轮次 场次]。")


def objective_line(ctx: Context, user_id: str) -> str:
    state = latest(ctx, user_id)
    labels = {"active": "进行中", "completed": "全胜", "defeated": "败退", "abandoned": "已放弃"}
    return f"轮战：已胜 {state['stage']}/3 · {labels[state['status']]}" if state else "轮战：尚未开启"
