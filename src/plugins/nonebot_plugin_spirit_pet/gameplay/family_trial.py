"""Private lineage-qualified weekly battles with persistent attrition between stages."""

from dataclasses import asdict
from hashlib import sha256
import json
import re

from ..application.context import Context
from ..domain.content import Enemy, Stats
from ..domain.battle_content import Element
from ..domain.family_trial_content import FamilyTrial, FamilyTrialStage
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from ..utils.time import beijing_week
from . import pedigree
from .battle_records import BattleCapture, capture_snapshot, record_battle
from .combat import Fighter, enemy_fighter, fight
from .economy import restore_energy
from .fighter_state import pack as pack_fighter, unpack as unpack_fighter
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

TITLE = "灵宠家族试炼"
KIND = "family_trial"
WEEK_SECONDS = 7 * 86_400
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def read_only(argument: str) -> bool:
    return not argument.split() or argument.split()[0] in {"家族", "战历", "历史", "回顾"}


def _week_index(week_start: int) -> int:
    # 1970-01-05 00:00 in Beijing is the first Monday anchor.
    return (week_start - 316_800) // WEEK_SECONDS


def current_trial(ctx: Context, week_start: int | None = None) -> FamilyTrial:
    start = beijing_week(ctx.now)[0] if week_start is None else week_start
    offset = _week_index(start) % len(ctx.content.family_trial_rotation)
    trial_id = ctx.content.family_trial_rotation[offset]
    return ctx.content.family_trials[trial_id]


def _reply_data(reply: Reply) -> str:
    return json.dumps(asdict(reply), ensure_ascii=False)


def _reward_text(ctx: Context, reward) -> str:
    def amount(bounds):
        return str(bounds.minimum) if bounds.minimum == bounds.maximum else f"{bounds.minimum}–{bounds.maximum}"
    return "、".join([
        f"修为 {amount(reward.exp)}", f"灵石 {amount(reward.stones)}",
        *(f"{ctx.content.items[key].name} ×{amount(bounds)}" for key, bounds in reward.items.items()),
    ])


def _scaled_enemy(ctx: Context, stage: FamilyTrialStage) -> Enemy:
    base = ctx.content.enemies[stage.enemy]
    stats = base.stats
    return base.model_copy(update={
        "stats": Stats(
            hp=max(1, round(stats.hp * stage.hp_scale)),
            attack=max(1, round(stats.attack * stage.attack_scale)),
            defense=max(0, round(stats.defense * stage.defense_scale)),
            speed=max(1, round(stats.speed * stage.speed_scale)),
        ),
    })


def _snapshot(ctx: Context, trial: FamilyTrial, family: dict, pets: list, fighters: list[Fighter]) -> dict:
    stages = []
    for index, stage in enumerate(trial.stages, 1):
        enemy = _scaled_enemy(ctx, stage)
        enemies = [enemy_fighter(enemy, ctx.content.skills)]
        capture = capture_snapshot(
            ctx, (fighters, enemies), ([ctx.user_id] * len(fighters), []),
        )
        stages.append({
            "definition": stage.model_dump(mode="json"),
            "enemy": enemy.model_dump(mode="json"),
            "fighters": [pack_fighter(fighter) for fighter in enemies],
            "capture": asdict(capture),
        })
    return {
        "version": 1,
        "trial": trial.model_dump(mode="json"),
        "family_key": family["key"],
        "family_members": list(family["members"]),
        "family_edges": family["edges"],
        "elements": {key: value.model_dump(mode="json") for key, value in ctx.content.elements.items()},
        "roster": [
            {"pet_id": pet.pet_id, "name": pet.name, "species_id": pet.species_id}
            for pet in pets
        ],
        "fighters": [pack_fighter(fighter) for fighter in fighters],
        "stages": stages,
        "bonus": trial.bonus.model_dump(mode="json"),
    }


def _run(ctx: Context, run_id: str | None = None, *, week_start: int | None = None,
         user_id: str | None = None):
    owner = user_id or ctx.user_id
    if run_id is not None:
        row = ctx.repo.conn.execute(
            "SELECT * FROM family_trial_runs WHERE user_id=? AND run_id=?",
            (owner, run_id),
        ).fetchone()
    else:
        start = beijing_week(ctx.now)[0] if week_start is None else week_start
        row = ctx.repo.conn.execute(
            "SELECT * FROM family_trial_runs WHERE user_id=? AND week_start=?",
            (owner, start),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["snapshot"] = json.loads(result["snapshot"])
    return result


def _record_action(ctx: Context, run: dict, reply: Reply, *, status: str | None = None,
                   current_stage: int | None = None, snapshot: dict | None = None) -> None:
    next_status = status or run["status"]
    next_stage = run["current_stage"] if current_stage is None else current_stage
    state = run["snapshot"] if snapshot is None else snapshot
    ctx.repo.conn.execute(
        "UPDATE family_trial_runs SET status=?,current_stage=?,updated_at=?,snapshot=?,reply=? "
        "WHERE run_id=? AND user_id=?",
        (next_status, next_stage, ctx.now, json.dumps(state, ensure_ascii=False), _reply_data(reply),
         run["run_id"], ctx.user_id),
    )
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": KIND, "run_id": run["run_id"], "status": next_status,
         "current_stage": next_stage}, reply,
    )


def _reward(ctx: Context, run: dict, key: str, definition: dict) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO family_trial_rewards(run_id,user_id,reward_key,operation_id,granted_at,reward_snapshot) "
        "VALUES (?,?,?,?,?,?)",
        (run["run_id"], ctx.user_id, key, ctx.operation_id, ctx.now,
         json.dumps(definition, ensure_ascii=False)),
    )


def _stage_rows(ctx: Context, run_id: str) -> dict[int, dict]:
    return {
        int(row["stage_no"]): dict(row)
        for row in ctx.repo.conn.execute(
            "SELECT * FROM family_trial_stages WHERE run_id=? ORDER BY stage_no", (run_id,),
        )
    }


def _render(ctx: Context, run: dict) -> Reply:
    state = run["snapshot"]
    trial = FamilyTrial.model_validate(state["trial"])
    stage_rows = _stage_rows(ctx, run["run_id"])
    rewards = {
        str(row["reward_key"])
        for row in ctx.repo.conn.execute(
            "SELECT reward_key FROM family_trial_rewards WHERE run_id=?", (run["run_id"],),
        )
    }
    lines = [
        f"家族起点 #{state['family_key']} · 阵容 "
        + "、".join(f"{member['name']}（#{member['pet_id']}）" for member in state["roster"]),
        f"本周轮换：{trial.name} · 每阶段每只消耗精力 {trial.energy}。",
        f"周名额已用 1/1 · 全通追加：{_reward_text(ctx, trial.bonus)}。",
    ]
    links = []
    for number, entry in enumerate(state["stages"], 1):
        stage = FamilyTrialStage.model_validate(entry["definition"])
        enemy = Enemy.model_validate(entry["enemy"])
        reward_state = "已发放" if f"stage_{number}" in rewards else "胜利后发放"
        result = stage_rows.get(number)
        if result:
            outcome = {"won": "胜", "lost": "败", "draw": "平局", "timeout": "超回合"}[result["outcome"]]
            remaining = json.loads(result["remaining_hp"])
            lines.append(
                f"第 {number} 阶 · {enemy.name} · {outcome} · {result['rounds']} 回合 · "
                f"余气 { '、'.join(str(value) for value in remaining) } · {reward_state}。"
            )
            links.append(InlineCommand(
                len(lines) - 1, "查看战报", f"灵宠战报 查看 {result['battle_id']}",
            ))
        else:
            lines.append(
                f"第 {number} 阶 · {enemy.name} · 气血 {enemy.stats.hp} · "
                f"攻击 {enemy.stats.attack} · 防御 {enemy.stats.defense} · 速度 {enemy.stats.speed} · "
                f"限 {stage.max_rounds} 回合 · {_reward_text(ctx, stage.reward)} · {reward_state}。"
            )
    if run["status"] == "active":
        if ctx.now >= run["week_start"] + WEEK_SECONDS:
            lines.append("本轮活动周已结束，不能再继续；打开试炼查看往期。")
        elif run["updated_at"] > ctx.now:
            lines.append("当前时间早于上次操作，等待时钟恢复后继续。")
        else:
            index = int(run["current_stage"]) - 1
            if index < len(trial.stages):
                stage_no = index + 1
                links.append(InlineCommand(
                    1, f"挑战第 {stage_no} 阶", f"{TITLE} 继续 {run['run_id']} {stage_no}",
                ))
                lines.append("同一阵容与剩余气血会跨阶段保留；每次继续只进行一阶。")
                links.append(InlineCommand(
                    len(lines) - 1, "放弃本轮", f"{TITLE} 放弃 {run['run_id']}",
                ))
    else:
        labels = {"completed": "已全通", "defeated": "已止步", "abandoned": "已放弃", "expired": "已过期"}
        lines.append(f"本轮{labels.get(run['status'], run['status'])}。")
    if "full_clear" in rewards:
        lines.append("家族全通奖励已发放。")
    commands = ("灵宠家族试炼 战历", "灵宠谱系", "灵宠战报", "灵宠亲子合战")
    return Reply(f"{TITLE} · {trial.name}", tuple(lines), commands, tuple(links))


def _overview(ctx: Context, page_arg: str = "1") -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(TITLE, ("尚未结契，先完成领养。",), ("灵宠帮助",))
    week_start = beijing_week(ctx.now)[0]
    run = _run(ctx, week_start=week_start)
    if run is not None:
        return _render(ctx, run)
    trial = current_trial(ctx, week_start)

    lines = [
        f"本周轮换：{trial.name} · {trial.description}",
        f"选取同一家族的 {trial.minimum_members}–{trial.maximum_members} 位在册伙伴；"
        f"每周限开一轮，每阶每只消耗精力 {trial.energy} 并进入 PVE 调息。",
        f"共 {len(trial.stages)} 阶；胜利逐阶发放奖励，全通追加家族奖励。",
        f"周名额已用 0/1 · 全通追加：{_reward_text(ctx, trial.bonus)}。",
    ]
    for index, stage in enumerate(trial.stages, 1):
        lines.append(f"第 {index} 阶 · {ctx.content.enemies[stage.enemy].name} · 限 {stage.max_rounds} 回合 · {_reward_text(ctx, stage.reward)}。")
    links = []
    families = [
        family for family in pedigree.family_members(ctx, ctx.user_id)
        if len(family["members"]) >= trial.minimum_members
    ]
    page = paginate(families, page_arg, TITLE, f"{TITLE} 家族", 6)
    lines.append(f"家族列表 · 第 {page.number}/{page.total} 页。")
    eligible = 0
    for family in page.entries:
        current = []
        ready = []
        for pet_id in family["members"]:
            row = ctx.repo.conn.execute(
                "SELECT name,archived FROM pets WHERE user_id=? AND pet_id=?",
                (ctx.user_id, pet_id),
            ).fetchone()
            if row is not None and not row["archived"]:
                expedition = ctx.repo.active_expedition(pet_id)
                note = ""
                if expedition:
                    note = "·外出中" if ctx.now < expedition["finishes_at"] else "·派遣待领取"
                else:
                    ready.append(pet_id)
                current.append((pet_id, str(row["name"]) + note))
        if len(current) < trial.minimum_members:
            lines.append(f"家族 #{family['key']} · 在册 {len(current)} 位，其他成员封存或已归灵，人数不足。")
            continue
        eligible += 1
        roster = "、".join(f"{name}（#{pet_id}）" for pet_id, name in current[:8])
        lines.append(
            f"家族 #{family['key']} · {len(family['members'])} 位 / "
            f"{family['generations']} 代 · 在册 {len(current)} 位 / 可出战 {len(ready)} 位：{roster}。"
        )
        if len(ready) >= trial.minimum_members:
            links.append(InlineCommand(
                len(lines) - 1, "选择家族", f"{TITLE} 开始 {week_start}:{trial.id} " + " ".join(
                    str(pet_id) for pet_id in ready[:trial.minimum_members]
                ),
            ))
    if not eligible:
        lines.append("尚无在册人数足够的可验证家族；真实培育灵卵孵化后建立亲缘，封存或归灵成员不可出战。")
    lines.append("开始格式：灵宠家族试炼 开始 编号 编号 [第三位编号]。查看只读，不占本周名额。")
    return Reply(TITLE, tuple(lines), (*page.navigation, "灵宠谱系", "灵宠家族试炼 战历", "灵宠亲子合战")[:4], tuple(links))


def start(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    week_start = beijing_week(ctx.now)[0]
    trial = current_trial(ctx, week_start)
    if parts and ":" in parts[0]:
        if parts[0] != f"{week_start}:{trial.id}":
            raise GameError("本周试炼已轮换，请重新打开家族试炼。")
        parts = parts[1:]
    if len(parts) not in (2, 3) or any(not part.isdecimal() for part in parts):
        raise GameError(f"格式：{TITLE} 开始 编号 编号 [第三位编号]。")
    selected_ids = [int(part) for part in parts]
    if len(set(selected_ids)) != len(selected_ids):
        raise GameError("同一轮不能重复选择伙伴。")
    if not trial.minimum_members <= len(selected_ids) <= trial.maximum_members:
        raise GameError(f"本周须选择 {trial.minimum_members}–{trial.maximum_members} 位同族伙伴。")
    family_by_pet = {
        pet_id: family
        for family in pedigree.family_members(ctx, ctx.user_id)
        for pet_id in family["members"]
    }
    families = [family_by_pet.get(pet_id) for pet_id in selected_ids]
    if any(family is None for family in families) or len({family["key"] for family in families}) != 1:
        raise GameError("所选伙伴必须属于同一个有真实孵化凭证的家族。")
    family = families[0]

    existing = _run(ctx, week_start=week_start)
    if existing is not None:
        raise GameError("本周已开启过家族试炼；不能重复占用周名额。")
    latest = ctx.repo.conn.execute(
        "SELECT MAX(updated_at) FROM family_trial_runs WHERE user_id=?", (ctx.user_id,),
    ).fetchone()[0]
    if latest is not None and latest > ctx.now:
        raise GameError("时间早于上次试炼操作，请等待时钟恢复。")
    expired = ctx.repo.conn.execute(
        "SELECT * FROM family_trial_runs WHERE user_id=? AND status='active' AND week_start<?",
        (ctx.user_id, week_start),
    ).fetchall()
    for old in expired:
        ctx.repo.conn.execute(
            "UPDATE family_trial_runs SET status='expired',updated_at=? WHERE run_id=?",
            (max(int(old["updated_at"]), week_start), old["run_id"]),
        )

    pets = []
    for pet_id in selected_ids:
        pet = ctx.repo.pet(pet_id)
        if pet.user_id != ctx.user_id:
            raise GameError("所选伙伴不属于你。")
        if pet.archived:
            raise GameError(f"{pet.name}已封存，复原后才能参试。")
        ctx.require_idle_pet(pet)
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        pets.append(pet)
    fighters = [combatant(ctx, pet_id=pet.pet_id, recover_energy=False) for pet in pets]
    state = _snapshot(ctx, trial, family, pets, fighters)
    run_id = sha256(ctx.operation_id.encode()).hexdigest()[:16]
    reply = Reply(
        TITLE,
        (f"{trial.name}已开局，本周名额已锁定；尚未扣精力。", "按页面逐阶继续，途中可重启后恢复。"),
        ("灵宠家族试炼 战历", "灵宠谱系"),
        (InlineCommand(1, "进入第 1 阶", f"{TITLE} 继续 {run_id} 1"),),
    )
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": KIND, "run_id": run_id, "status": "active", "current_stage": 1}, reply,
    )
    ctx.repo.conn.execute(
        "INSERT INTO family_trial_runs(run_id,user_id,week_start,trial_id,status,current_stage,"
        "started_at,updated_at,snapshot,reply,start_operation_id) VALUES (?,?,?,?, 'active',1,?,?,?,?,?)",
        (run_id, ctx.user_id, week_start, trial.id, ctx.now, ctx.now,
         json.dumps(state, ensure_ascii=False), _reply_data(reply), ctx.operation_id),
    )
    for slot, pet in enumerate(pets, 1):
        ctx.repo.conn.execute(
            "INSERT INTO family_trial_members(run_id,user_id,slot,pet_id) VALUES (?,?,?,?)",
            (run_id, ctx.user_id, slot, pet.pet_id),
        )
    return reply


def _expire(ctx: Context, run: dict) -> Reply:
    reply = Reply(TITLE, ("本轮活动周已结束，试炼关闭；已发奖励保留。",),
                  (f"{TITLE} 战历", "灵宠谱系"))
    _record_action(ctx, run, reply, status="expired")
    return reply


def continue_run(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 2 or not RUN_ID_PATTERN.fullmatch(parts[0]) or not parts[1].isdecimal():
        raise GameError(f"格式：{TITLE} 继续 轮次编号 阶段。请从当前试炼页进入。")
    run = _run(ctx, parts[0])
    if run is None:
        raise GameError("这轮家族试炼不存在或不属于你。")
    if run["status"] != "active":
        raise GameError("这轮家族试炼已经结束。")
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次试炼操作，请等待时钟恢复。")
    if ctx.now >= run["week_start"] + WEEK_SECONDS:
        return _expire(ctx, run)
    stage_no = int(parts[1])
    if stage_no != int(run["current_stage"]):
        raise GameError("该阶段已过期或尚未开启，请重新打开家族试炼。")
    state = run["snapshot"]
    trial = FamilyTrial.model_validate(state["trial"])
    if stage_no > len(trial.stages):
        raise GameError("本轮没有更多阶段。")
    roster = state["roster"]
    pets = []
    fighters = [unpack_fighter(value) for value in state["fighters"]]
    for member in roster:
        pet = ctx.repo.pet(int(member["pet_id"]))
        if pet.user_id != ctx.user_id or pet.archived:
            raise GameError(f"{member['name']}当前不可出战，恢复在册状态后可继续本轮。")
        ctx.require_idle_pet(pet)
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        pets.append(pet)
    player = ctx.player()
    ctx.check_action(
        player, pets[0], "pve", trial.energy, ctx.config.spirit_pet_pve_cooldown,
    )
    for pet in pets[1:]:
        if pet.energy < trial.energy:
            raise GameError(f"{pet.name}精力不足，需要 {trial.energy} 点。")

    for pet in pets:
        pet.energy -= trial.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    stage_entry = state["stages"][stage_no - 1]
    stage = FamilyTrialStage.model_validate(stage_entry["definition"])
    enemy = Enemy.model_validate(stage_entry["enemy"])
    enemies = [unpack_fighter(value) for value in stage_entry["fighters"]]
    previous_uses = {fighter.pet_id: dict(fighter.skill_uses) for fighter in fighters}
    elements = {key: Element.model_validate(value) for key, value in state["elements"].items()}
    battle = fight(fighters, enemies, ctx.rng, elements, max_rounds=stage.max_rounds)
    capture_data = stage_entry["capture"]
    capture = BattleCapture(capture_data["snapshot"], tuple(capture_data["participants"]))
    won = battle.winner == 0 and battle.rounds <= stage.max_rounds
    if won:
        outcome = "won"
    elif battle.winner == 1:
        outcome = "lost"
    else:
        outcome = "timeout" if battle.rounds >= stage.max_rounds else "draw"

    lines = [f"第 {stage_no} 阶 · {enemy.name} · {battle.rounds} 回合",
             f"每只精力 -{trial.energy} · PVE 调息 {ctx.config.spirit_pet_pve_cooldown} 秒。", *battle.lines]
    for pet in pets:
        lines.extend(award_mastery(
            ctx, ctx.user_id, {
                key: amount - previous_uses[pet.pet_id].get(key, 0)
                for key, amount in battle.skill_uses[0].get(pet.pet_id, {}).items()
            }, pet_id=pet.pet_id,
        ))
    standing = "、".join(f"{fighter.name.rsplit('的', 1)[-1]} {fighter.hp}/{fighter.stats.hp}"
                          for fighter in fighters)
    lines.append(f"家族余气：{standing}。")
    status = "active"
    next_stage = stage_no + 1
    if won:
        lines.append("本阶通过，阶段奖励：" + "，".join(grant(
            ctx, stage.reward, pet_id=pets[0].pet_id,
        )))
        advance(ctx, "pve")
        if stage_no == len(trial.stages):
            status = "completed"
            lines.append("全阶段完成，家族奖励：" + "，".join(grant(
                ctx, trial.bonus, pet_id=pets[0].pet_id,
            )))
    else:
        status = "defeated"
        next_stage = stage_no
        result = {"lost": "未能取胜", "draw": "本阶平局", "timeout": "超出阶段回合上限"}[outcome]
        lines.append(f"{result}，本轮结束；已解锁奖励保留，未开放阶段关闭。")

    reply = Reply(
        f"{TITLE} · 第 {stage_no} 阶 {'通过' if won else '止步'}",
        tuple(lines), (TITLE, "灵宠战报", "灵宠谱系"),
    )
    battle_id = record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=f"family_trial_{run['run_id']}_{stage_no}",
        battle_name=f"家族试炼·{trial.name}·第{stage_no}阶·{enemy.name}",
    )
    ctx.repo.conn.execute(
        "INSERT INTO family_trial_stages(run_id,stage_no,battle_id,outcome,rounds,remaining_hp,played_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (run["run_id"], stage_no, battle_id, outcome, battle.rounds,
         json.dumps(list(battle.remaining_hp[0]), ensure_ascii=False), ctx.now),
    )
    _record_action(ctx, run, reply, status=status, current_stage=next_stage,
                   snapshot={**state, "fighters": [pack_fighter(fighter) for fighter in fighters]})
    if won:
        _reward(ctx, run, f"stage_{stage_no}", stage.reward.model_dump(mode="json"))
    if won and stage_no == len(trial.stages):
        _reward(ctx, run, "full_clear", trial.bonus.model_dump(mode="json"))
    return reply


def abandon(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 1 or not RUN_ID_PATTERN.fullmatch(parts[0]):
        raise GameError(f"格式：{TITLE} 放弃 轮次编号。")
    run = _run(ctx, parts[0])
    if run is None or run["status"] != "active":
        raise GameError("没有可放弃的家族试炼。")
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次试炼操作，请等待时钟恢复。")
    if ctx.now >= run["week_start"] + WEEK_SECONDS:
        return _expire(ctx, run)
    reply = Reply(TITLE, ("本轮已放弃；已发阶段奖励保留，后续阶段关闭。",), (TITLE, "灵宠家族试炼 战历"))
    _record_action(ctx, run, reply, status="abandoned")
    return reply


def history(ctx: Context, argument: str) -> Reply:
    ctx.player()
    if not argument:
        page_arg = "1"
    else:
        parts = argument.split()
        if len(parts) != 1:
            raise GameError(f"格式：{TITLE} 战历 [页码]。")
        page_arg = parts[0]
    rows = [dict(row) for row in ctx.repo.conn.execute(
        "SELECT * FROM family_trial_runs WHERE user_id=? ORDER BY week_start DESC,started_at DESC",
        (ctx.user_id,),
    ).fetchall()]
    page = paginate(rows, page_arg, f"{TITLE}战历", f"{TITLE} 战历", 6)
    lines = [f"共 {len(rows)} 轮 · 第 {page.number}/{page.total} 页（新的在前）。"]
    links = []
    for row in page.entries:
        trial_name = FamilyTrial.model_validate(json.loads(row["snapshot"])["trial"]).name
        completed = int(ctx.repo.conn.execute(
            "SELECT COUNT(*) FROM family_trial_stages WHERE run_id=? AND outcome='won'",
            (row["run_id"],),
        ).fetchone()[0])
        lines.append(
            f"周起点 {row['week_start']} · {trial_name} · 已胜 {completed} 阶 · {row['status']} · "
            f"轮次 {row['run_id']}。"
        )
        links.append(InlineCommand(
            len(lines) - 1, "回顾", f"{TITLE} 回顾 {row['run_id']} 1",
        ))
    return Reply(f"{TITLE}战历 {page.number}/{page.total}", tuple(lines),
                 (*page.navigation, TITLE, "灵宠谱系")[:4], tuple(links))


def review(ctx: Context, argument: str) -> Reply:
    ctx.player()
    parts = argument.split()
    if len(parts) not in (1, 2) or not RUN_ID_PATTERN.fullmatch(parts[0]):
        raise GameError(f"格式：{TITLE} 回顾 轮次编号 [页码]。")
    run = _run(ctx, parts[0])
    if run is None:
        raise GameError("这轮试炼不存在或不属于你。")
    page_no = int(parts[1]) if len(parts) == 2 and parts[1].isdecimal() else 1
    if len(parts) == 2 and not parts[1].isdecimal():
        raise GameError("页码必须是正整数。")
    state = run["snapshot"]
    stages = ctx.repo.conn.execute(
        "SELECT s.*,b.title FROM family_trial_stages s JOIN battle_records b USING(battle_id) "
        "WHERE run_id=? ORDER BY stage_no", (run["run_id"],),
    ).fetchall()
    page = paginate([dict(row) for row in stages], str(page_no), f"{TITLE}回顾", f"{TITLE} 回顾 {run['run_id']}", 6)
    lines = [
        f"{FamilyTrial.model_validate(state['trial']).name} · 家族 #{state['family_key']} · "
        + "、".join(f"{member['name']}（#{member['pet_id']}）" for member in state["roster"]),
    ]
    links = []
    for stage_row in page.entries:
        hp = "、".join(map(str, json.loads(stage_row["remaining_hp"])))
        lines.append(
            f"第 {stage_row['stage_no']} 阶 · {stage_row['outcome']} · {stage_row['rounds']} 回合 · "
            f"家族余气 {hp}。"
        )
        links.append(InlineCommand(
            len(lines) - 1, "打开战报", f"灵宠战报 查看 {stage_row['battle_id']}",
        ))
    return Reply(f"{TITLE}回顾 {page.number}/{page.total}", tuple(lines),
                 (*page.navigation, f"{TITLE} 战历", "灵宠谱系")[:4], tuple(links))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return _overview(ctx)
    head = parts[0]
    if head == "家族":
        if len(parts) != 2:
            raise GameError(f"格式：{TITLE} 家族 页码。")
        return _overview(ctx, parts[1])
    if head == "开始":
        return start(ctx, parts[1:])
    if head == "继续":
        return continue_run(ctx, parts[1:])
    if head == "放弃":
        return abandon(ctx, parts[1:])
    if head in {"战历", "历史"}:
        return history(ctx, " ".join(parts[1:]))
    if head == "回顾":
        return review(ctx, " ".join(parts[1:]))
    raise GameError(f"格式：{TITLE} [开始 编号 编号 [编号]|继续 轮次 阶段|放弃 轮次|战历 [页码]|回顾 轮次 [页码]]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "家族试炼：尚未结契"
    row = _run(ctx, week_start=beijing_week(ctx.now)[0], user_id=user_id)
    if row is None:
        return "家族试炼：本周尚未开局"
    name = FamilyTrial.model_validate(row["snapshot"]["trial"]).name
    if row["status"] == "active" and ctx.now >= row["week_start"] + WEEK_SECONDS:
        return f"家族试炼：{name}本周已过期"
    return f"家族试炼：{name} · 阶段 {row['current_stage']} · {row['status']}"


def today_state(ctx: Context, user_id: str) -> str | None:
    row = _run(ctx, user_id=user_id)
    if row:
        return objective_line(ctx, user_id) if row["status"] == "active" else None
    trial = current_trial(ctx)
    for family in pedigree.family_members(ctx, user_id):
        count = ctx.repo.conn.execute(
            "SELECT COUNT(*) FROM pets WHERE user_id=? AND archived=0 AND pet_id IN ("
            + ",".join("?" for _ in family["members"]) + ")", (user_id, *family["members"]),
        ).fetchone()[0]
        if count >= trial.minimum_members:
            return "家族试炼：本周尚未开局"
    return None
