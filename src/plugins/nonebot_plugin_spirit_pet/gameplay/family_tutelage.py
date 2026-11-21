"""Paid direct-parent lessons and a real single-pet skill examination."""

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import re

from ..application.context import Context
from ..domain.battle_content import Element
from ..domain.content import Enemy
from ..domain.family_tutelage_content import FamilyTutelageCourse, FamilyTutelageRules
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import BEIJING, beijing_week
from . import mastery
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .compatibility import check_requirements
from .fighter_state import pack, unpack
from .loadout import combatant
from .pet_targets import named_pet, pet_id
from .release import released

TITLE = "灵宠家族传习"
KIND = "family_tutelage"
ID = re.compile(r"^[0-9a-f]{16}$")
STATES = {"active": "进行中", "completed": "已结业", "failed": "考核机会已用尽",
          "cancelled": "已取消", "expired": "已到期"}
OUTCOMES = {"passed": "通过", "unused": "获胜但未施目标术", "lost": "战败", "draw": "平局", "timeout": "超回合"}


def read_only(argument: str) -> bool:
    return not argument.split() or argument.split()[0] in {"课程", "亲子", "预览", "记录", "详情", "伙伴"}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, BEIJING).strftime("%Y-%m-%d %H:%M")


def _load(ctx: Context, course_id: str | None = None, user_id: str | None = None):
    owner = user_id or ctx.user_id
    query = "SELECT * FROM family_tutelage_courses WHERE user_id=?"
    args = [owner]
    if course_id is not None:
        query += " AND course_id=?"
        args.append(course_id)
    else:
        query += " AND status='active'"
    row = ctx.repo.conn.execute(query, args).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["snapshot"] = json.loads(row["snapshot"])
    return result


def _definition(ctx: Context, value: str) -> FamilyTutelageCourse:
    course = next((course for course in ctx.content.family_tutelage.values()
                   if value in (course.id, course.name)), None)
    if course is None:
        raise GameError("没有这门传习课程，请打开灵宠家族传习选择。")
    return course


def _pet(ctx: Context, number: int):
    row = ctx.repo.conn.execute("SELECT 1 FROM pets WHERE user_id=? AND pet_id=?",
                                (ctx.user_id, number)).fetchone()
    if row is None:
        raise GameError("没有属于你的传习伙伴，请从本人亲子列表选择。")
    pet = ctx.repo.pet(number)
    if released(ctx, number) or pet.archived:
        raise GameError(f"{pet.name}已封存或归灵，当前不能参加传习。")
    ctx.require_idle_pet(pet)
    return pet


def _graduated(ctx: Context, child_id: int, skill: str) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM family_tutelage_graduations WHERE user_id=? AND child_id=? AND skill_id=?",
        (ctx.user_id, child_id, skill),
    ).fetchone() is not None


def _eligible(ctx: Context, course: FamilyTutelageCourse, parent_id: int, child_id: int):
    parent, child = _pet(ctx, parent_id), _pet(ctx, child_id)
    egg = ctx.repo.conn.execute(
        "SELECT * FROM pet_lineage_eggs WHERE user_id=? AND status='hatched' AND child_pet_id=? "
        "AND (parent_a_id=? OR parent_b_id=?)",
        (ctx.user_id, child_id, parent_id, parent_id),
    ).fetchone()
    if egg is None:
        raise GameError("讲师必须是本人已孵化凭证中的直接亲本，同族、祖辈或旁支不能代替。")
    if ctx.now < egg["finished_at"]:
        raise GameError("时间早于真实孵化凭证，请等待时钟恢复。")
    for pet in (parent, child):
        check_requirements(ctx, pet, ctx.content.skills[course.skill].requirements)
    parent_skill = mastery.progress(ctx, parent_id).get(course.skill)
    child_skill = mastery.progress(ctx, child_id).get(course.skill)
    if parent_skill is None or child_skill is None:
        raise GameError("双宠都须先用原秘笈学会目标灵术；传习不会教授未学会的技能。")
    if parent_skill[0] < course.parent_level:
        raise GameError(f"亲本目标灵术至少需要 {course.parent_level} 级。")
    if ctx.content.skill_levels[child_skill[0]].required_proficiency is None:
        raise GameError("后代目标灵术已满级，无需开课。")
    if _graduated(ctx, child_id, course.skill):
        raise GameError("这位后代的该术已经结业，换亲本或跨周也不能重复领奖。")
    return parent, child, dict(egg)


def _clock(ctx: Context) -> None:
    latest = ctx.repo.conn.execute(
        "SELECT MAX(updated_at) FROM family_tutelage_courses WHERE user_id=?", (ctx.user_id,),
    ).fetchone()[0]
    if latest is not None and ctx.now < latest:
        raise GameError("时间早于上次传习操作，请等待时钟恢复。")


def _quota(ctx: Context) -> tuple[int, int]:
    week = beijing_week(ctx.now)[0]
    rows = ctx.repo.conn.execute(
        "SELECT snapshot FROM family_tutelage_courses WHERE user_id=? AND week_start=? ORDER BY started_at,course_id",
        (ctx.user_id, week),
    ).fetchall()
    limit = json.loads(rows[0]["snapshot"])["rules"]["weekly_starts"] if rows else ctx.content.family_tutelage_rules.weekly_starts
    return len(rows), limit


def _cost(course: FamilyTutelageCourse, names: dict) -> str:
    return f"双宠各 {course.lesson_energy} 精力、灵石 {course.lesson_stones}、" + "、".join(
        f"{names[key]} ×{amount}" for key, amount in course.lesson_materials.items()
    )


def _record(ctx: Context, run: dict, reply: Reply, **changes) -> None:
    run.update(changes)
    ctx.repo.conn.execute(
        "UPDATE family_tutelage_courses SET status=?,lessons_done=?,attempts_used=?,updated_at=?,reply=? "
        "WHERE user_id=? AND course_id=?",
        (run["status"], run["lessons_done"], run["attempts_used"], ctx.now, _json(asdict(reply)),
         ctx.user_id, run["course_id"]),
    )
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now,
                                {"kind": KIND, "course_id": run["course_id"], **changes}, reply)


def _last_lesson(ctx: Context, run: dict) -> int | None:
    return ctx.repo.conn.execute(
        "SELECT MAX(taught_at) FROM family_tutelage_lessons WHERE course_id=?", (run["course_id"],),
    ).fetchone()[0]


def _render(ctx: Context, run: dict) -> Reply:
    state = run["snapshot"]
    course = FamilyTutelageCourse.model_validate(state["course"])
    rules = FamilyTutelageRules.model_validate(state["rules"])
    status = "expired" if run["status"] == "active" and ctx.now >= run["expires_at"] else run["status"]
    lines = [f"{course.name} · 课号 {run['course_id']} · {STATES[status]}",
             f"讲师 {state['parent']['name']}（#{run['parent_id']}） → 后代 {state['child']['name']}（#{run['child_id']}）",
             f"目标：{state['skill_name']} · 孵化凭证 #{run['egg_record_id']} · 开课周 {_time(run['week_start'])}",
             f"讲习 {run['lessons_done']}/{rules.lessons} · 考核 {run['attempts_used']}/{rules.attempts} · 到期 {_time(run['expires_at'])}（北京时间）",
             "每次讲习：" + _cost(course, state["material_names"]) + f"；间隔至少 {rules.interval} 秒。",
             f"考核：原后代精力 {course.exam_energy}、PVE 调息，限 {course.max_rounds} 回合；获胜且实际施放目标术才结业。",
             f"结业仅目标术额外熟练度，最多 {course.proficiency}；每后代每术永久一次，无额外物品或灵石。"]
    commands = []
    if status == "active" and ctx.now >= run["updated_at"]:
        if run["lessons_done"] < rules.lessons:
            last = _last_lesson(ctx, run)
            ready = last is None or ctx.now >= last + rules.interval
            lines.append("已可讲习。" if ready else f"距下次讲习还需 {last + rules.interval - ctx.now} 秒。")
            if ready:
                commands.append(f"{TITLE} 讲习 {run['course_id']} {run['lessons_done'] + 1}")
        else:
            commands.append(f"{TITLE} 考核 {run['course_id']} {run['attempts_used'] + 1}")
        commands.append(f"{TITLE} 取消 {run['course_id']}")
    elif status == "active":
        lines.append("时间早于上次操作，等待时钟恢复。")
    if status == "expired" and run["status"] == "active":
        commands.append(f"{TITLE} 取消 {run['course_id']}")
    commands.extend((f"{TITLE} 记录", "灵宠谱系"))
    links = [InlineCommand(1, "后代灵术", f"灵宠技能 伙伴 {run['child_id']}")]
    for row in ctx.repo.conn.execute(
        "SELECT lesson_no,taught_at FROM family_tutelage_lessons WHERE course_id=? ORDER BY lesson_no",
        (run["course_id"],),
    ):
        lines.append(f"第 {row['lesson_no']} 次讲习 · {_time(row['taught_at'])} · 已付清本次成本。")
    for row in ctx.repo.conn.execute(
        "SELECT * FROM family_tutelage_exams WHERE course_id=? ORDER BY attempt_no", (run["course_id"],),
    ):
        lines.append(f"第 {row['attempt_no']} 次考核 · {OUTCOMES[row['outcome']]} · {row['rounds']} 回合 · 目标施法 {row['target_uses']} 次。")
        links.append(InlineCommand(len(lines) - 1, "查看战报", f"灵宠战报 查看 {row['battle_id']}"))
    graduation = ctx.repo.conn.execute(
        "SELECT proficiency FROM family_tutelage_graduations WHERE course_id=?", (run["course_id"],),
    ).fetchone()
    if graduation:
        lines.append(f"结业实际额外熟练度 +{graduation['proficiency']}。")
    return Reply(TITLE, tuple(lines), tuple(commands[:4]), tuple(links))


def overview(ctx: Context, selector: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴。",), ("灵宠帮助",))
    if not selector and (run := _load(ctx)):
        return _render(ctx, run)
    chosen = named_pet(ctx, selector, "传习", refresh_energy=False) if selector else None
    used, limit = _quota(ctx)
    rules = ctx.content.family_tutelage_rules
    lines = [f"本周开课 {used}/{limit} · 同时一门 · 每门七日内完成，取消不退已付成本或名额。",
             f"直接亲本与后代须已学同术；完成 {rules.lessons} 次讲习后由原后代真实出战。"]
    links = []
    if chosen:
        lines.append(f"当前筛选后代：{chosen.name}（#{chosen.pet_id}）。")
    for course in ctx.content.family_tutelage.values():
        lines.append(f"{course.name} · 亲本灵术至少 {course.parent_level} 级 · 结业额外熟练度最多 {course.proficiency}。")
        suffix = f" {chosen.pet_id}" if chosen else ""
        links.append(InlineCommand(len(lines) - 1, "选择亲子", f"{TITLE} 亲子 {course.id} 1{suffix}"))
    return Reply(TITLE, tuple(lines), (f"{TITLE} 记录", "灵宠谱系", "灵宠技能图鉴"), tuple(links))


def pairs(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if not 1 <= len(parts) <= 3:
        raise GameError(f"格式：{TITLE} 亲子 课程 [页码] [后代编号]。")
    course = _definition(ctx, parts[0])
    child_filter = pet_id(parts[2]) if len(parts) == 3 else None
    if child_filter is not None:
        _pet(ctx, child_filter)
    entries = []
    for egg in ctx.repo.lineage_eggs(ctx.user_id):
        if child_filter is not None and egg["child_pet_id"] != child_filter:
            continue
        for parent_id in (egg["parent_a_id"], egg["parent_b_id"]):
            try:
                parent, child, _ = _eligible(ctx, course, parent_id, egg["child_pet_id"])
            except GameError:
                continue
            entries.append((parent, child))
    page = paginate(entries, parts[1] if len(parts) >= 2 else "1", TITLE, f"{TITLE} 亲子 {course.id}", 6)
    lines = [f"{course.name} · 合格直接亲子 {len(entries)} 对 · 第 {page.number}/{page.total} 页。"]
    links = []
    for parent, child in page.entries:
        lines.append(f"{parent.name}（#{parent.pet_id}） → {child.name}（#{child.pet_id}）")
        links.append(InlineCommand(len(lines) - 1, "预览开课", f"{TITLE} 预览 {course.id} {parent.pet_id} {child.pet_id}"))
    if not entries:
        lines.append("尚无合格亲子；须真实培育孵化，双宠学习同术，亲本升至要求等级，后代未满级且未结业。")
    navigation = tuple(command + (f" {child_filter}" if child_filter else "") for command in page.navigation)
    return Reply(TITLE, tuple(lines), (*navigation, TITLE, "灵宠谱系", "灵宠技能图鉴")[:4], tuple(links))


def _start_check(ctx: Context) -> None:
    _clock(ctx)
    run = _load(ctx)
    if run and ctx.now < run["expires_at"]:
        raise GameError("已有一门传习进行中，请先完成或取消原课。")
    used, limit = _quota(ctx)
    if used >= limit:
        raise GameError("本周开课名额已用尽；取消或过期也不返还名额。")


def preview(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 3:
        raise GameError(f"格式：{TITLE} 预览 课程 亲本编号 后代编号。")
    course = _definition(ctx, parts[0])
    parent, child, egg = _eligible(ctx, course, pet_id(parts[1]), pet_id(parts[2]))
    names = {key: ctx.content.items[key].name for key in course.lesson_materials}
    rules = ctx.content.family_tutelage_rules
    lines = [f"{course.name} · {parent.name} → {child.name} · 真实孵化凭证 #{egg['egg_record_id']}",
             f"两次讲习，每次{_cost(course, names)}；两次间隔至少 {rules.interval} 秒。",
             f"敌手 {ctx.content.enemies[course.enemy].name} · 限 {course.max_rounds} 回合 · 每次精力 {course.exam_energy} · 最多 {rules.attempts} 次。",
             "开课只占名额，不预扣讲习成本。七日到期，取消不退已付成本或名额。",
             "考核要获胜且实际施放目标术；满血回春转普攻不算施法，治疗课程应同时整备伤害灵术。",
             f"结业只给原后代目标术额外熟练度最多 {course.proficiency}，每后代每术永久唯一。"]
    commands = []
    try:
        _start_check(ctx)
    except GameError as exc:
        lines.append(str(exc))
    else:
        commands.append(f"{TITLE} 开课 {course.id} {parent.pet_id} {child.pet_id} {beijing_week(ctx.now)[0]}")
    commands.extend((TITLE, "灵宠谱系"))
    return Reply(TITLE + " · 开课预览", tuple(lines), tuple(commands))


def start(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 4 or parts[3] != str(beijing_week(ctx.now)[0]):
        raise GameError("开课入口已过期，请重新预览本周课程。")
    _start_check(ctx)
    course = _definition(ctx, parts[0])
    parent, child, egg = _eligible(ctx, course, pet_id(parts[1]), pet_id(parts[2]))
    rules = ctx.content.family_tutelage_rules.model_copy(update={"weekly_starts": _quota(ctx)[1]})
    old = _load(ctx)
    if old:
        ctx.repo.conn.execute("UPDATE family_tutelage_courses SET status='expired',updated_at=? WHERE course_id=?",
                              (ctx.now, old["course_id"]))
    enemy = ctx.content.enemies[course.enemy]
    state = {"version": 1, "course": course.model_dump(mode="json"), "rules": rules.model_dump(mode="json"),
             "parent": {"pet_id": parent.pet_id, "name": parent.name, "species_id": parent.species_id},
             "child": {"pet_id": child.pet_id, "name": child.name, "species_id": child.species_id},
             "egg": egg, "skill_name": ctx.content.skills[course.skill].name,
             "material_names": {key: ctx.content.items[key].name for key in course.lesson_materials},
             "enemy": enemy.model_dump(mode="json"), "fighter": pack(enemy_fighter(enemy, ctx.content.skills)),
             "elements": {key: element.model_dump(mode="json") for key, element in ctx.content.elements.items()}}
    course_id = sha256(ctx.operation_id.encode()).hexdigest()[:16]
    reply = Reply(TITLE, (f"{course.name}已开课，讲师 {parent.name}、后代 {child.name}；未预扣成本。",
                          "七日内完成两次讲习，再由原后代参加考核。"),
                  (f"{TITLE} 讲习 {course_id} 1", TITLE, f"{TITLE} 记录"))
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, {"kind": KIND, "course_id": course_id}, reply)
    ctx.repo.conn.execute(
        "INSERT INTO family_tutelage_courses(course_id,user_id,parent_id,child_id,egg_record_id,skill_id,week_start,"
        "start_operation_id,status,started_at,updated_at,expires_at,snapshot,reply) VALUES (?,?,?,?,?,?,?,?,'active',?,?,?,?,?)",
        (course_id, ctx.user_id, parent.pet_id, child.pet_id, egg["egg_record_id"], course.skill,
         beijing_week(ctx.now)[0], ctx.operation_id, ctx.now, ctx.now, ctx.now + rules.duration,
         _json(state), _json(asdict(reply))),
    )
    return reply


def _action_run(ctx: Context, parts: list[str], step: str | None = None) -> dict:
    ctx.player()
    if len(parts) != (2 if step else 1) or not ID.fullmatch(parts[0]):
        raise GameError("传习入口参数无效，请打开当前课程。")
    run = _load(ctx, parts[0])
    if run is None:
        raise GameError("这门传习不存在或不属于你。")
    if run["status"] != "active":
        raise GameError("这门传习已经结束。")
    _clock(ctx)
    if step and parts[1] != str(run[step] + 1):
        raise GameError("讲习步骤或考核次数已过期，请重新打开当前课程。")
    return run


def _expire(ctx: Context, run: dict) -> Reply | None:
    if ctx.now < run["expires_at"]:
        return None
    reply = Reply(TITLE, ("课程七日期限已到，已支付成本与开课名额不退；历史和战报保留。",), (TITLE, f"{TITLE} 记录"))
    _record(ctx, run, reply, status="expired")
    return reply


def lesson(ctx: Context, parts: list[str]) -> Reply:
    run = _action_run(ctx, parts, "lessons_done")
    if expired := _expire(ctx, run):
        return expired
    course = FamilyTutelageCourse.model_validate(run["snapshot"]["course"])
    rules = FamilyTutelageRules.model_validate(run["snapshot"]["rules"])
    if run["lessons_done"] >= rules.lessons:
        raise GameError("讲习已完成，请由原后代参加考核。")
    last = _last_lesson(ctx, run)
    if last is not None and ctx.now < last + rules.interval:
        raise GameError(f"讲习间隔未到，还需 {last + rules.interval - ctx.now} 秒。")
    parent, child = _pet(ctx, run["parent_id"]), _pet(ctx, run["child_id"])
    for pet in (parent, child):
        if course.skill not in mastery.progress(ctx, pet.pet_id):
            raise GameError("原亲子伙伴须仍已学会目标灵术。")
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        if pet.energy < course.lesson_energy:
            raise GameError(f"{pet.name}精力不足，需要 {course.lesson_energy}。")
    player = ctx.player()
    if player.stones < course.lesson_stones:
        raise GameError(f"灵石不足，需要 {course.lesson_stones}。")
    for key, amount in course.lesson_materials.items():
        ctx.repo.consume_item(ctx.user_id, key, amount)
    player.stones -= course.lesson_stones
    parent.energy -= course.lesson_energy
    child.energy -= course.lesson_energy
    number = run["lessons_done"] + 1
    reply = Reply(TITLE, (f"第 {number}/{rules.lessons} 次讲习完成；" + _cost(course, run["snapshot"]["material_names"]) + "。",
                          "讲习不直接发熟练度；完成考核才可结业。"), (TITLE, f"{TITLE} 记录"))
    _record(ctx, run, reply, lessons_done=number)
    ctx.repo.conn.execute(
        "INSERT INTO family_tutelage_lessons VALUES (?,?,?,?,?)",
        (run["course_id"], number, ctx.operation_id, ctx.now,
         _json({"energy_each": course.lesson_energy, "stones": course.lesson_stones, "materials": course.lesson_materials})),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return reply


def _remaining(ctx: Context, level: int, proficiency: int, maximum: int) -> int:
    remaining = -proficiency
    while ctx.content.skill_levels[level].required_proficiency is not None:
        remaining += ctx.content.skill_levels[level].required_proficiency
        level += 1
    return max(0, min(maximum, remaining))


def exam(ctx: Context, parts: list[str]) -> Reply:
    run = _action_run(ctx, parts, "attempts_used")
    if expired := _expire(ctx, run):
        return expired
    state = run["snapshot"]
    course = FamilyTutelageCourse.model_validate(state["course"])
    rules = FamilyTutelageRules.model_validate(state["rules"])
    if run["lessons_done"] != rules.lessons or run["attempts_used"] >= rules.attempts:
        raise GameError("尚未完成全部讲习或考核机会已用尽。")
    child = _pet(ctx, run["child_id"])
    if not ctx.repo.conn.execute(
        "SELECT 1 FROM learned_skills WHERE pet_id=? AND skill_id=? AND equipped=1",
        (child.pet_id, course.skill),
    ).fetchone():
        raise GameError("原后代须携带目标灵术再考核；本次未消耗机会。")
    restore_energy(child, ctx.now, ctx.config.spirit_pet_energy_interval)
    player = ctx.player()
    ctx.check_action(player, child, "pve", course.exam_energy, ctx.config.spirit_pet_pve_cooldown)
    fighter = combatant(ctx, pet_id=child.pet_id, recover_energy=False)
    enemy = unpack(state["fighter"])
    capture = capture_snapshot(ctx, ([fighter], [enemy]), ([ctx.user_id], []))
    elements = {key: Element.model_validate(value) for key, value in state["elements"].items()}
    child.energy -= course.exam_energy
    player.last_pve = ctx.now
    battle = fight([fighter], [enemy], ctx.rng, elements, max_rounds=course.max_rounds)
    uses = battle.skill_uses[0].get(child.pet_id, {})
    target_uses = uses.get(course.skill, 0)
    won = battle.winner == 0 and battle.rounds <= course.max_rounds
    outcome = "passed" if won and target_uses else "unused" if won else (
        "lost" if battle.winner == 1 else "timeout" if battle.rounds >= course.max_rounds else "draw")
    lines = [f"{course.name} · 原后代 {child.name} · {battle.rounds} 回合 · 目标施法 {target_uses} 次。",
             f"精力 -{course.exam_energy}，进入 PVE 调息。", *battle.lines]
    lines.extend(mastery.award_mastery(ctx, ctx.user_id, uses, pet_id=child.pet_id))
    gain = 0
    reward = None
    if outcome == "passed":
        if _graduated(ctx, child.pet_id, course.skill):
            raise GameError("这位后代的该术已结业，不能重复领奖。")
        before = mastery.progress(ctx, child.pet_id)[course.skill]
        gain = _remaining(ctx, *before, course.proficiency)
        level, proficiency, _ = mastery.study(ctx, child.pet_id, course.skill, gain)
        reward = {"skill": course.skill, "maximum": course.proficiency, "actual": gain,
                  "before": before, "after": [level, proficiency]}
        lines.append(f"结业：{state['skill_name']}额外熟练度 +{gain}；{mastery.progress_text(ctx, level, proficiency)}。")
        if gain == 0:
            lines.append("目标术已在其他成长或本场普通熟练度结算中满级，实际额外收益为零。")
    else:
        labels = {"unused": "虽获胜但未实际施放目标术", "lost": "战败", "timeout": "超过回合上限", "draw": "平局"}
        lines.append(labels[outcome] + "，本次未结业并消耗一次考核机会。")
    number = run["attempts_used"] + 1
    status = "completed" if outcome == "passed" else "failed" if number >= rules.attempts else "active"
    lines.append(f"考核 {number}/{rules.attempts} · {STATES[status]}。")
    reply = Reply(TITLE + (" · 结业" if outcome == "passed" else " · 未通过"), tuple(lines),
                  (TITLE, f"{TITLE} 记录", f"灵宠技能 伙伴 {child.pet_id}"))
    battle_id = record_battle(ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
                              battle_key=f"family_tutelage_{run['course_id']}_{number}",
                              battle_name=f"家族传习·{course.name}·{Enemy.model_validate(state['enemy']).name}")
    _record(ctx, run, reply, attempts_used=number, status=status)
    ctx.repo.conn.execute("INSERT INTO family_tutelage_exams VALUES (?,?,?,?,?,?,?,?)",
                          (run["course_id"], number, ctx.operation_id, battle_id, outcome,
                           battle.rounds, target_uses, ctx.now))
    if reward is not None:
        ctx.repo.conn.execute("INSERT INTO family_tutelage_graduations VALUES (?,?,?,?,?,?,?,?)",
                              (ctx.user_id, child.pet_id, course.skill, run["course_id"], ctx.operation_id,
                               gain, ctx.now, _json(reward)))
    ctx.repo.invalidate_ready(ctx.user_id)
    return reply


def cancel(ctx: Context, parts: list[str]) -> Reply:
    run = _action_run(ctx, parts)
    if expired := _expire(ctx, run):
        return expired
    reply = Reply(TITLE, ("课程已取消，实际已付成本与本周开课名额不退；无结业奖励。",), (TITLE, f"{TITLE} 记录"))
    _record(ctx, run, reply, status="cancelled")
    return reply


def history(ctx: Context, argument: str) -> Reply:
    ctx.player()
    rows = ctx.repo.conn.execute("SELECT * FROM family_tutelage_courses WHERE user_id=? ORDER BY started_at DESC,course_id DESC",
                                 (ctx.user_id,)).fetchall()
    page = paginate(rows, argument or "1", TITLE, f"{TITLE} 记录", 6)
    lines = [f"共 {len(rows)} 门 · 第 {page.number}/{page.total} 页。"]
    links = []
    for row in page.entries:
        state = json.loads(row["snapshot"])
        status = "expired" if row["status"] == "active" and ctx.now >= row["expires_at"] else row["status"]
        lines.append(f"{state['course']['name']} · {state['parent']['name']} → {state['child']['name']} · {STATES[status]}")
        links.append(InlineCommand(len(lines) - 1, "课程档案", f"{TITLE} 详情 {row['course_id']}"))
    return Reply(TITLE + " · 记录", tuple(lines), (*page.navigation, TITLE, "灵宠谱系")[:4], tuple(links))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts or parts == ["课程"]:
        return overview(ctx)
    if len(parts) == 2 and parts[0] == "伙伴":
        return overview(ctx, parts[1])
    if parts[0] == "亲子":
        return pairs(ctx, parts[1:])
    if parts[0] == "预览":
        return preview(ctx, parts[1:])
    if parts[0] == "开课":
        return start(ctx, parts[1:])
    if parts[0] == "讲习":
        return lesson(ctx, parts[1:])
    if parts[0] == "考核":
        return exam(ctx, parts[1:])
    if parts[0] == "取消":
        return cancel(ctx, parts[1:])
    if parts[0] == "记录":
        return history(ctx, " ".join(parts[1:]))
    if len(parts) == 2 and parts[0] == "详情" and ID.fullmatch(parts[1]):
        ctx.player()
        run = _load(ctx, parts[1])
        if run is None:
            raise GameError("这门传习不存在或不属于你。")
        return _render(ctx, run)
    raise GameError(f"格式：{TITLE} [课程|亲子 课程|预览 课程 亲本 后代|记录 [页码]]；从课程页选择具体操作。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = _load(ctx, user_id=user_id)
    if not run:
        return "家族传习：当前无在途课程"
    if ctx.now >= run["expires_at"]:
        return "家族传习：课程已到期，可关闭后查看本周名额"
    return f"家族传习：{run['snapshot']['course']['name']} · 讲习 {run['lessons_done']}/2 · 考核 {run['attempts_used']} 次"


def today_state(ctx: Context, user_id: str) -> str | None:
    run = _load(ctx, user_id=user_id)
    if run is None or ctx.now < run["updated_at"]:
        return None
    if ctx.now >= run["expires_at"]:
        return "家族传习：课程到期待关闭"
    if run["lessons_done"] < 2:
        last = _last_lesson(ctx, run)
        if last is not None and ctx.now < last + run["snapshot"]["rules"]["interval"]:
            return None
    return objective_line(ctx, user_id)
