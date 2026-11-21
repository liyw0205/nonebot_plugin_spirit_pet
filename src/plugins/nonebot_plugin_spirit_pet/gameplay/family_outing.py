"""Three-stage private outings for a verified direct parent and child."""

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import re

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import BEIJING, beijing_week
from . import bond_levels
from .release import released
from .pet_targets import pet_id

TITLE = "灵宠亲子伴游"
KIND = "family_outing"
ID = re.compile(r"^[0-9a-f]{16}$")
STATES = {"active": "同行中", "completed": "已完程", "cancelled": "已取消", "expired": "已到期"}


def read_only(argument: str) -> bool:
    return not argument.split() or argument.split()[0] in {"路线", "亲子", "预览", "记录", "详情"}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _time(value: int) -> str:
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _load(ctx: Context, trip_id: str | None = None, user_id: str | None = None):
    query = "SELECT * FROM family_outing_runs WHERE user_id=?"
    args = [user_id or ctx.user_id]
    if trip_id is None:
        query += " AND status='active'"
    else:
        query += " AND trip_id=?"
        args.append(trip_id)
    row = ctx.repo.conn.execute(query, args).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["snapshot"] = json.loads(row["snapshot"])
    return result


def _clock(ctx: Context) -> None:
    latest = ctx.repo.conn.execute(
        "SELECT MAX(updated_at) FROM family_outing_runs WHERE user_id=?", (ctx.user_id,),
    ).fetchone()[0]
    if latest is not None and ctx.now < latest:
        raise GameError("时间早于上次伴游操作，请等待时钟恢复。")


def _quota(ctx: Context) -> tuple[int, int]:
    rows = ctx.repo.conn.execute(
        "SELECT snapshot FROM family_outing_runs WHERE user_id=? AND week_start=? ORDER BY started_at,trip_id",
        (ctx.user_id, beijing_week(ctx.now)[0]),
    ).fetchall()
    limit = json.loads(rows[0]["snapshot"])["rules"]["weekly_starts"] if rows else ctx.content.family_outings.rules.weekly_starts
    return len(rows), limit


def _pet(ctx: Context, number: int):
    if ctx.repo.conn.execute("SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, number)).fetchone() is None:
        raise GameError("没有属于你的伴游伙伴，请从本人亲子列表选择。")
    pet = ctx.repo.pet(number)
    if pet.archived or released(ctx, number):
        raise GameError(f"{pet.name}已封存或归灵，当前不能伴游。")
    ctx.require_idle_pet(pet)
    return pet


def _eligible(ctx: Context, parent_id: int, child_id: int):
    parent, child = _pet(ctx, parent_id), _pet(ctx, child_id)
    egg = ctx.repo.conn.execute(
        "SELECT * FROM pet_lineage_eggs WHERE user_id=? AND status='hatched' AND child_pet_id=? "
        "AND (parent_a_id=? OR parent_b_id=?)", (ctx.user_id, child_id, parent_id, parent_id),
    ).fetchone()
    if egg is None:
        raise GameError("伴游须选择本人真实孵化凭证中的直接亲本与后代；同族、祖辈或旁支不能代替。")
    if ctx.now < egg["finished_at"]:
        raise GameError("时间早于真实孵化凭证，请等待时钟恢复。")
    return parent, child, dict(egg)


def _route(ctx: Context, value: str):
    route = next((route for route in ctx.content.family_outings.routes if value in (route.id, route.name)), None)
    if route is None:
        raise GameError("没有这条伴游路线，请重新选择。")
    return route


def _story(text: str, state: dict) -> str:
    return text.format(parent=state["parent"]["name"], child=state["child"]["name"])


def _cost(choice: dict, state: dict) -> str:
    text = f"亲本精力 {choice['parent_energy']}、后代精力 {choice['child_energy']}"
    if choice["food"]:
        text += f"、{state['food_name']} ×{choice['food']}"
    return text


def _next(run: dict) -> tuple[list[str], tuple[str, ...]]:
    state = run["snapshot"]
    stage = state["route"]["stages"][run["steps_done"]]
    lines = [f"下一段 {run['steps_done'] + 1}/3 · {stage['name']}：" + _story(stage["text"], state)]
    lines.extend(f"{choice['name']}：{_cost(choice, state)}；本程默契 +{choice['rapport']}。" for choice in state["choices"])
    commands = tuple(f"{TITLE} 选择 {run['trip_id']} {run['steps_done'] + 1} {choice['id']}" for choice in state["choices"])
    return lines, (*commands, f"{TITLE} 取消 {run['trip_id']}")


def _render(ctx: Context, run: dict) -> Reply:
    state = run["snapshot"]
    status = "expired" if run["status"] == "active" and ctx.now >= run["expires_at"] else run["status"]
    lines = [f"{state['route']['name']} · 程号 {run['trip_id']} · {STATES[status]}",
             f"亲本 {state['parent']['name']}（#{run['parent_id']}）与后代 {state['child']['name']}（#{run['child_id']}）",
             f"真实孵化凭证 #{run['egg_record_id']} · 行程 {run['steps_done']}/3 · 本程默契 {run['rapport']}",
             f"出发 {_time(run['started_at'])} · 到期 {_time(run['expires_at'])}（北京时间）",
             "每周两程、同时一程；取消或到期不返名额及已花成本，完程仅给原双宠既有羁绊经验。"]
    for row in ctx.repo.conn.execute("SELECT * FROM family_outing_steps WHERE trip_id=? ORDER BY step_no", (run["trip_id"],)):
        step = json.loads(row["snapshot"])
        lines.extend((f"第 {row['step_no']} 段 · {step['stage_name']} · {step['choice']['name']} · {_time(row['acted_at'])}",
                      step["story"], f"已付：{_cost(step['choice'], state)}；本程默契 +{step['choice']['rapport']}。"))
    reward = ctx.repo.conn.execute("SELECT reward_snapshot FROM family_outing_rewards WHERE trip_id=?", (run["trip_id"],)).fetchone()
    if reward:
        receipt = json.loads(reward["reward_snapshot"])
        lines.append(f"{receipt['tier']['name']} · 亲本羁绊经验 +{receipt['parent']['gain']}、后代 +{receipt['child']['gain']}，已结算。")
    links = []
    if status == "active" and ctx.now >= run["updated_at"]:
        next_lines, commands = _next(run)
        lines.extend(next_lines)
        links.append(InlineCommand(0, "伴游记录", f"{TITLE} 记录"))
    else:
        commands = (TITLE, f"{TITLE} 记录", "灵宠羁绊", "灵宠谱系")
        if status == "expired" and run["status"] == "active":
            commands = (f"{TITLE} 取消 {run['trip_id']}", f"{TITLE} 记录", "灵宠羁绊", "灵宠谱系")
        elif status == "active":
            lines.append("时间早于上次操作，请等待时钟恢复。")
    return Reply(TITLE, tuple(lines), tuple(commands), tuple(links))


def overview(ctx: Context, *, routes: bool = False) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴。",), ("灵宠帮助",))
    if not routes and (run := _load(ctx)):
        return _render(ctx, run)
    used, limit = _quota(ctx)
    lines = [f"本周出发 {used}/{limit} · 同时一程 · 每程 24 小时。",
             "选择真实直接亲子走完三段，各段明确支付双宠精力或灵食，完程再给原双宠羁绊经验。"]
    links = []
    for route in ctx.content.family_outings.routes:
        lines.append(f"{route.name} · " + " → ".join(stage.name for stage in route.stages))
        links.append(InlineCommand(len(lines) - 1, "选择亲子", f"{TITLE} 亲子 {route.id}"))
    lines.append("伴游不增加单宠出游的游历值、特产或见闻，也不占每日相伴次数。")
    return Reply(TITLE, tuple(lines), (f"{TITLE} 记录", "灵宠谱系", "灵宠羁绊"), tuple(links))


def pairs(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if not 1 <= len(parts) <= 2:
        raise GameError(f"格式：{TITLE} 亲子 路线 [页码]。")
    route = _route(ctx, parts[0])
    entries = []
    for egg in ctx.repo.lineage_eggs(ctx.user_id):
        if egg["status"] != "hatched":
            continue
        for parent_id in (egg["parent_a_id"], egg["parent_b_id"]):
            try:
                parent, child, _ = _eligible(ctx, parent_id, egg["child_pet_id"])
            except GameError:
                continue
            entries.append((parent, child))
    page = paginate(entries, parts[1] if len(parts) == 2 else "1", TITLE, f"{TITLE} 亲子 {route.id}", 6)
    lines = [f"{route.name} · 合格亲子 {len(entries)} 对 · 第 {page.number}/{page.total} 页。"]
    links = []
    for parent, child in page.entries:
        lines.append(f"{parent.name}（#{parent.pet_id}）与{child.name}（#{child.pet_id}）")
        links.append(InlineCommand(len(lines) - 1, "伴游预览", f"{TITLE} 预览 {route.id} {parent.pet_id} {child.pet_id}"))
    if not entries:
        lines.append("尚无可同行的真实直接亲子；先培育孵化，并让双宠恢复在册且无未处理派遣。")
    return Reply(TITLE, tuple(lines), (*page.navigation, f"{TITLE} 路线", "灵宠谱系")[:4], tuple(links))


def _start_check(ctx: Context) -> None:
    _clock(ctx)
    run = _load(ctx)
    if run and ctx.now < run["expires_at"]:
        raise GameError("已有一程伴游进行中，请先完成或取消。")
    used, limit = _quota(ctx)
    if used >= limit:
        raise GameError("本周两程名额已用尽，取消或到期不返还。")


def preview(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 3:
        raise GameError(f"格式：{TITLE} 预览 路线 亲本编号 后代编号。")
    route = _route(ctx, parts[0])
    parent, child, egg = _eligible(ctx, pet_id(parts[1]), pet_id(parts[2]))
    content = ctx.content.family_outings
    state = {"food_name": ctx.content.items[content.food_item].name}
    lines = [f"{route.name} · {parent.name}与{child.name} · 真实孵化凭证 #{egg['egg_record_id']}",
             "三段同行，出发只占本周名额，不预扣阶段成本。24 小时内完成，取消或到期不退已付成本及名额。"]
    lines.extend(f"每段{choice.name}：{_cost(choice.model_dump(), state)}；本程默契 +{choice.rapport}。" for choice in content.choices)
    lines.extend(f"默契至少 {tier.rapport} · {tier.name}：原双宠各羁绊经验 +{tier.bond_exp}。" for tier in content.tiers)
    commands = []
    try:
        _start_check(ctx)
    except GameError as error:
        lines.append(str(error))
    else:
        commands.append(f"{TITLE} 出发 {route.id} {parent.pet_id} {child.pet_id} {beijing_week(ctx.now)[0]}")
    return Reply(TITLE + " · 预览", tuple(lines), (*commands, f"{TITLE} 路线", "灵宠谱系"))


def start(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 4 or parts[3] != str(beijing_week(ctx.now)[0]):
        raise GameError("出发入口已过期，请重新预览本周伴游。")
    _start_check(ctx)
    route = _route(ctx, parts[0])
    parent, child, egg = _eligible(ctx, pet_id(parts[1]), pet_id(parts[2]))
    content = ctx.content.family_outings
    state = {"version": 1, "route": route.model_dump(mode="json"),
             "rules": {**content.rules.model_dump(), "weekly_starts": _quota(ctx)[1]},
             "choices": [choice.model_dump() for choice in content.choices],
             "tiers": [tier.model_dump() for tier in content.tiers], "food_item": content.food_item,
             "food_name": ctx.content.items[content.food_item].name,
             "parent": {"pet_id": parent.pet_id, "name": parent.name, "species_id": parent.species_id},
             "child": {"pet_id": child.pet_id, "name": child.name, "species_id": child.species_id}, "egg": egg}
    old = _load(ctx)
    if old:
        ctx.repo.conn.execute("UPDATE family_outing_runs SET status='expired',updated_at=? WHERE trip_id=?", (ctx.now, old["trip_id"]))
    run = {"trip_id": sha256(ctx.operation_id.encode()).hexdigest()[:16], "parent_id": parent.pet_id,
           "child_id": child.pet_id, "egg_record_id": egg["egg_record_id"], "started_at": ctx.now,
           "updated_at": ctx.now, "expires_at": ctx.now + content.rules.duration, "steps_done": 0,
           "rapport": 0, "status": "active", "snapshot": state}
    reply = _render(ctx, run)
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, {"kind": KIND, "trip_id": run["trip_id"]}, reply)
    ctx.repo.conn.execute(
        "INSERT INTO family_outing_runs(trip_id,user_id,parent_id,child_id,egg_record_id,route_id,week_start,"
        "start_operation_id,status,started_at,updated_at,expires_at,snapshot,reply) VALUES (?,?,?,?,?,?,?,?,'active',?,?,?,?,?)",
        (run["trip_id"], ctx.user_id, parent.pet_id, child.pet_id, egg["egg_record_id"], route.id,
         beijing_week(ctx.now)[0], ctx.operation_id, ctx.now, ctx.now, run["expires_at"], _json(state), _json(asdict(reply))),
    )
    return reply


def _record(ctx: Context, run: dict, reply: Reply) -> None:
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, {"kind": KIND, "trip_id": run["trip_id"]}, reply)
    ctx.repo.conn.execute(
        "UPDATE family_outing_runs SET steps_done=?,rapport=?,status=?,updated_at=?,reply=? WHERE user_id=? AND trip_id=?",
        (run["steps_done"], run["rapport"], run["status"], ctx.now, _json(asdict(reply)), ctx.user_id, run["trip_id"]),
    )


def _action_run(ctx: Context, parts: list[str], *, choosing: bool = False) -> dict:
    ctx.player()
    if len(parts) != (3 if choosing else 1) or not ID.fullmatch(parts[0]):
        raise GameError("伴游入口参数无效，请重新打开当前行程。")
    run = _load(ctx, parts[0])
    if run is None:
        raise GameError("这程伴游不存在或不属于你。")
    if run["status"] != "active":
        raise GameError("这程伴游已经结束。")
    _clock(ctx)
    if choosing and parts[1] != str(run["steps_done"] + 1):
        raise GameError("同行步骤已过期，请重新打开当前行程。")
    return run


def _expire(ctx: Context, run: dict) -> Reply | None:
    if ctx.now < run["expires_at"]:
        return None
    run["status"] = "expired"
    reply = Reply(TITLE, ("伴游的 24 小时期限已到，已花成本与周名额不退；未完程，无羁绊奖励。",), (TITLE, f"{TITLE} 记录"))
    _record(ctx, run, reply)
    return reply


def choose(ctx: Context, parts: list[str]) -> Reply:
    run = _action_run(ctx, parts, choosing=True)
    if expired := _expire(ctx, run):
        return expired
    state = run["snapshot"]
    choice = next((choice for choice in state["choices"] if parts[2] == choice["id"]), None)
    if choice is None:
        raise GameError("没有这项同行选择，请重新打开当前行程。")
    parent, child = _pet(ctx, run["parent_id"]), _pet(ctx, run["child_id"])
    for pet, cost in ((parent, choice["parent_energy"]), (child, choice["child_energy"])):
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        if pet.energy < cost:
            raise GameError(f"{pet.name}精力不足，需要 {cost}；本段尚未发生。")
    if choice["food"]:
        ctx.repo.consume_item(ctx.user_id, state["food_item"], choice["food"])
    parent.energy -= choice["parent_energy"]
    child.energy -= choice["child_energy"]
    stage = state["route"]["stages"][run["steps_done"]]
    story = _story(stage["outcomes"][choice["id"]], state)
    run["steps_done"] += 1
    run["rapport"] += choice["rapport"]
    lines = [f"第 {run['steps_done']}/3 段 · {stage['name']} · {choice['name']}", story,
             f"已付：{_cost(choice, state)}；本程默契 +{choice['rapport']}，累计 {run['rapport']}。"]
    receipt = None
    if run["steps_done"] == 3:
        tier = max((tier for tier in state["tiers"] if tier["rapport"] <= run["rapport"]), key=lambda tier: tier["rapport"])
        receipt = {"tier": tier, "rapport": run["rapport"]}
        for key, pet in (("parent", parent), ("child", child)):
            before = bond_levels.exp(ctx, pet.pet_id)
            after = bond_levels.add_exp(ctx, pet.pet_id, tier["bond_exp"])
            receipt[key] = {"pet_id": pet.pet_id, "before": before, "after": after, "gain": after - before}
            lines.append(f"{state[key]['name']}（#{pet.pet_id}）羁绊经验 +{after - before}（{before} → {after}）。")
        run["status"] = "completed"
        lines.append(f"{tier['name']} · 已完程，双宠收益已结算；故事永久保留。")
        commands = (TITLE, f"{TITLE} 记录", "灵宠羁绊", "灵宠谱系")
    else:
        next_lines, commands = _next(run)
        lines.extend(next_lines)
    reply = Reply(TITLE + (" · 完程" if receipt else " · 同行"), tuple(lines), commands)
    _record(ctx, run, reply)
    ctx.repo.conn.execute("INSERT INTO family_outing_steps VALUES (?,?,?,?,?,?)",
                          (run["trip_id"], run["steps_done"], choice["id"], ctx.operation_id, ctx.now,
                           _json({"stage_name": stage["name"], "choice": choice, "story": story, "rapport": run["rapport"]})))
    if receipt is not None:
        ctx.repo.conn.execute("INSERT INTO family_outing_rewards VALUES (?,?,?,?,?)",
                              (run["trip_id"], ctx.user_id, ctx.operation_id, ctx.now, _json(receipt)))
    ctx.repo.invalidate_ready(ctx.user_id)
    return reply


def cancel(ctx: Context, parts: list[str]) -> Reply:
    run = _action_run(ctx, parts)
    if expired := _expire(ctx, run):
        return expired
    run["status"] = "cancelled"
    reply = Reply(TITLE, ("伴游已取消；已花精力、灵食及本周名额不退，未完程不发羁绊奖励。",), (TITLE, f"{TITLE} 记录"))
    _record(ctx, run, reply)
    return reply


def history(ctx: Context, argument: str) -> Reply:
    ctx.player()
    rows = ctx.repo.conn.execute("SELECT * FROM family_outing_runs WHERE user_id=? ORDER BY started_at DESC,trip_id DESC", (ctx.user_id,)).fetchall()
    page = paginate(rows, argument or "1", TITLE, f"{TITLE} 记录", 6)
    lines = [f"共 {len(rows)} 程 · 第 {page.number}/{page.total} 页。"]
    links = []
    for row in page.entries:
        state = json.loads(row["snapshot"])
        status = "expired" if row["status"] == "active" and ctx.now >= row["expires_at"] else row["status"]
        lines.append(f"{state['route']['name']} · {state['parent']['name']}与{state['child']['name']} · {STATES[status]} · {_time(row['started_at'])}")
        links.append(InlineCommand(len(lines) - 1, "同行故事", f"{TITLE} 详情 {row['trip_id']}"))
    return Reply(TITLE + " · 记录", tuple(lines), (*page.navigation, f"{TITLE} 路线", "灵宠谱系")[:4], tuple(links))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return overview(ctx)
    if parts == ["路线"]:
        return overview(ctx, routes=True)
    actions = {"亲子": pairs, "预览": preview, "出发": start, "选择": choose, "取消": cancel}
    if parts[0] in actions:
        return actions[parts[0]](ctx, parts[1:])
    if parts[0] == "记录":
        return history(ctx, " ".join(parts[1:]))
    if len(parts) == 2 and parts[0] == "详情" and ID.fullmatch(parts[1]):
        ctx.player()
        run = _load(ctx, parts[1])
        if run is None:
            raise GameError("这程伴游不存在或不属于你。")
        return _render(ctx, run)
    raise GameError(f"格式：{TITLE} [路线|亲子 路线 [页码]|预览 路线 亲本 后代|记录 [页码]]；从行程页选择具体操作。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = _load(ctx, user_id=user_id)
    if run is None:
        return "亲子伴游：当前无在途行程"
    if ctx.now >= run["expires_at"]:
        return "亲子伴游：行程已到期，可关闭后查看本周名额"
    return f"亲子伴游：{run['snapshot']['route']['name']} · 已同行 {run['steps_done']}/3 段"


def today_state(ctx: Context, user_id: str) -> str | None:
    run = _load(ctx, user_id=user_id)
    if run is None or ctx.now < run["updated_at"]:
        return None
    return objective_line(ctx, user_id)
