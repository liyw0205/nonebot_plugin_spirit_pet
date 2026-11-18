"""A small, resumable three-node spirit-vein expedition."""

from datetime import datetime
from hashlib import sha256

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import BEIJING
from . import bond_levels
from .pet_targets import named_pet
from .release import released

TITLE = "灵宠灵脉"
KIND = "vein_expedition"
START_ENERGY = 10
STEP_ENERGY = 5
START_FOOD = 1
GUARD_FOOD = 1
RULE_VERSION = "vein-1"
PAGE_SIZE = 5


def _run_id(ctx: Context) -> int:
    value = int(sha256(f"{ctx.user_id}:{ctx.operation_id}:{ctx.now}".encode()).hexdigest()[:14], 16)
    return max(1, value)


def _realm_index(ctx: Context, realm_id: str) -> int:
    for index, realm in enumerate(ctx.content.realms):
        if realm.id == realm_id:
            return index
    raise GameError("灵脉境界门槛异常，暂不能开启。")


def _active(ctx: Context) -> dict | None:
    latest = ctx.repo.latest_vein_expedition_action(ctx.user_id, active_only=True)
    return latest["snapshot"] if latest else None


def state(ctx: Context) -> dict | None:
    return _active(ctx)


def _latest(ctx: Context) -> dict | None:
    latest = ctx.repo.latest_vein_expedition_action(ctx.user_id)
    return latest["snapshot"] if latest else None


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < int(run.get("updated_at", run.get("started_at", ctx.now))):
        raise GameError("系统时间早于最近灵脉操作，请等待时钟恢复；探勘进度保留。")


def _pet(ctx: Context, pet_id: int, *, refresh: bool = True):
    row = ctx.repo.conn.execute(
        "SELECT archived FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("本局绑定的伙伴不存在，无法继续；可放弃本局。")
    pet = ctx.repo.pet(pet_id)
    if released(ctx, pet_id):
        raise GameError(f"{pet.name}已归灵，本局只能放弃。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，请复原后继续，或放弃本局。")
    if refresh:
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    ctx.require_idle_pet(pet)
    return pet


def _reward_dump(ctx: Context, reward) -> dict:
    return reward.model_dump()


def _reward_values(ctx: Context, reward: dict) -> tuple[int, int, dict[str, int]]:
    if not isinstance(reward, dict) or not isinstance(reward.get("exp"), dict) or not isinstance(reward.get("stones"), dict):
        raise GameError("本局奖励快照损坏，暂不能结算；探勘进度保留。")
    exp = int(ctx.rng.randint(int(reward["exp"]["minimum"]), int(reward["exp"]["maximum"])))
    stones = int(ctx.rng.randint(int(reward["stones"]["minimum"]), int(reward["stones"]["maximum"])))
    items = {}
    for item_id, bounds in reward.get("items", {}).items():
        if item_id not in ctx.content.items:
            raise GameError(f"奖励材料 {item_id} 当前不可用，暂不能结算；探勘进度保留。")
        if not isinstance(bounds, dict):
            raise GameError("本局奖励快照损坏，暂不能结算；探勘进度保留。")
        items[item_id] = int(ctx.rng.randint(int(bounds["minimum"]), int(bounds["maximum"])))
    return exp, stones, items


def _reward_text(ctx: Context, reward: dict) -> str:
    parts = []
    if reward.get("exp", {}).get("maximum", 0):
        parts.append(f"修为 +{reward['exp']['minimum']}" if reward["exp"]["minimum"] == reward["exp"]["maximum"]
                     else f"修为 {reward['exp']['minimum']}-{reward['exp']['maximum']}")
    if reward.get("stones", {}).get("maximum", 0):
        parts.append(f"灵石 +{reward['stones']['minimum']}" if reward["stones"]["minimum"] == reward["stones"]["maximum"]
                     else f"灵石 {reward['stones']['minimum']}-{reward['stones']['maximum']}")
    for item_id, bounds in reward.get("items", {}).items():
        name = ctx.content.items[item_id].name if item_id in ctx.content.items else item_id
        text = f"{bounds['minimum']}" if bounds["minimum"] == bounds["maximum"] else f"{bounds['minimum']}-{bounds['maximum']}"
        parts.append(f"{name} ×{text}")
    return "、".join(parts) or "无"


def _node_dump(ctx: Context, route) -> list[dict]:
    return [
        {"name": node.name, "description": node.description, "material": node.material,
         "material_name": ctx.content.items[node.material].name}
        for node in route.nodes
    ]


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_vein_expedition_action(
        ctx.operation_id, ctx.user_id, ctx.now, {**run, "updated_at": ctx.now}, reply,
    )
    return reply


def _route_page(ctx: Context, route) -> Reply:
    lines = [
        route.description,
        f"三段节点 · 开局精力 {START_ENERGY} · 每段精力 {STEP_ENERGY} · 开局灵粮 {START_FOOD}",
        f"护脉每段额外灵粮 {GUARD_FOOD}，至少一次护脉才提高终章奖励。",
        f"基础终章：{_reward_text(ctx, _reward_dump(ctx, route.reward))}",
        f"护脉终章：{_reward_text(ctx, _reward_dump(ctx, route.guarded_reward))}",
    ]
    for index, node in enumerate(route.nodes, 1):
        lines.append(f"第{index}段 {node.name} · {node.description} · 采集 {ctx.content.items[node.material].name} ×1")
    return Reply(route.name, tuple(lines), (TITLE,))


def catalog(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴才能探勘灵脉。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = _active(ctx)
    if run:
        return _run_page(ctx, run)
    lines = [
        "三段路线会冻结节点、伙伴、奖励和规则版本，可跨日、重启与清缓存继续。",
        "每局开局消耗 10 精力与 1 灵粮；采集得当前节点材料，护脉额外消耗 1 灵粮并提高终章奖励，绕行不取节点材料。",
    ]
    commands, links = [], []
    for route in sorted(ctx.content.vein_routes.values(), key=lambda item: item.id):
        minimum = ctx.content.realms[_realm_index(ctx, route.min_realm)].name
        lines.append(f"{route.name} · {minimum}可入 · 三段 · 终章 {_reward_text(ctx, _reward_dump(ctx, route.reward))}")
        commands.append(f"{TITLE} 开启 {route.name} 伙伴 {player.active_pet_id or 1}")
        links.append(InlineCommand(len(lines) - 1, "查看路线", f"{TITLE} 预览 {route.name}"))
    lines.append("当前无进行中的探勘；主动放弃不退款但会保留历史。")
    links.extend((InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"),
                  InlineCommand(len(lines) - 1, "查看目标", "灵宠目标")))
    return Reply(TITLE, tuple(lines), tuple(commands), tuple(links))


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    index = len(run["actions"])
    lines = [
        *prefix,
        f"第 {run['run_id']} 局 · {run['route']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）",
        f"进度 {index}/3 · 已耗精力 {run['energy_spent']} · 已耗灵粮 {run['food_spent']}",
    ]
    for offset, node in enumerate(run["nodes"][index:], index + 1):
        lines.append(f"第{offset}段 {node['name']} · {node['description']} · 采集 {node['material_name']} ×1")
    lines.append(f"已采集：{'、'.join(run['collected']) if run['collected'] else '无'}。")
    commands = []
    try:
        _time(ctx, run)
        pet = _pet(ctx, run["pet_id"], refresh=False)
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        if pet.energy < STEP_ENERGY:
            raise GameError(f"{pet.name}精力不足，需要 {STEP_ENERGY} 点才能继续。")
    except GameError as exc:
        lines.append(str(exc))
    else:
        for action in ("采集", "护脉", "绕行"):
            commands.append(f"{TITLE} 前进 {run['run_id']} {action}")
    lines.append("完成第三段后一次结算终章灵石、奖励材料和伙伴羁绊；放弃不退款。")
    links = (InlineCommand(len(lines) - 1, "放弃本局", f"{TITLE} 放弃 {run['run_id']}"),
             InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"))
    return Reply(f"{TITLE} · 进行中", tuple(lines), tuple(commands), links)


def start(ctx: Context, route_name: str, selector: str) -> Reply:
    player = ctx.player()
    if _active(ctx):
        raise GameError("已有进行中的灵脉探勘，请先完成或放弃当前局。")
    latest = _latest(ctx)
    if latest:
        _time(ctx, latest)
    route = named(ctx.content.vein_routes, route_name)
    pet = named_pet(ctx, selector, "灵脉探勘")
    ctx.require_idle_pet(pet)
    if released(ctx, pet.pet_id):
        raise GameError(f"{pet.name}已归灵，不能参与探勘。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，请复原后再出发。")
    if pet.realm < _realm_index(ctx, route.min_realm):
        raise GameError(f"{pet.name}境界不足，{route.name}需要{ctx.content.realms[_realm_index(ctx, route.min_realm)].name}。")
    if pet.energy < START_ENERGY:
        raise GameError(f"{pet.name}精力不足，需要 {START_ENERGY} 点。")
    if (ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) < START_FOOD):
        raise GameError("灵粮不足，开局需要 1 份；本局尚未建立。")
    ctx.repo.consume_item(ctx.user_id, "spirit_food", START_FOOD)
    pet.energy -= START_ENERGY
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run = {
        "status": "active", "event": "start", "rule_version": RULE_VERSION,
        "run_id": _run_id(ctx), "route": route.model_dump(), "pet_id": pet.pet_id,
        "pet_name": pet.name, "nodes": _node_dump(ctx, route), "actions": [],
        "collected": [], "energy_spent": START_ENERGY, "food_spent": START_FOOD,
        "reward": _reward_dump(ctx, route.reward), "guarded_reward": _reward_dump(ctx, route.guarded_reward),
        "bond": route.bond, "started_at": ctx.now, "updated_at": ctx.now,
    }
    reply = _run_page(ctx, run, (f"灵脉探勘开启：精力 -{START_ENERGY}、灵粮 -{START_FOOD}。",))
    return _record(ctx, run, reply)


def _finish(ctx: Context, run: dict, pet) -> Reply:
    guarded = any(item["action"] == "护脉" for item in run["actions"])
    reward = run["guarded_reward"] if guarded else run["reward"]
    exp, stones, items = _reward_values(ctx, reward)
    pet.exp += exp
    player = ctx.player()
    player.stones += stones
    for item_id, amount in items.items():
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
    total_bond = bond_levels.add_exp(ctx, pet.pet_id, run["bond"])
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run.update(status="finished", event="finish", final_reward={
        "exp": exp, "stones": stones, "items": items, "guarded": guarded,
    })
    lines = [
        f"第 {run['run_id']} 局 · {run['route']['name']} · {pet.name}探勘完成。",
        "动作：" + "、".join(item["action"] for item in run["actions"]),
        f"终章{'护脉' if guarded else '基础'}奖励：修为 +{exp}、灵石 +{stones}",
    ]
    lines.extend(f"{ctx.content.items[item_id].name} +{amount}" for item_id, amount in items.items() if amount)
    lines.append(f"{pet.name}羁绊经验 +{run['bond']} · 累计 {total_bond}。")
    return _record(ctx, run, Reply(TITLE + " · 完成", tuple(lines), (TITLE, "灵宠背包", "灵宠羁绊"),
                                    (InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"),)))


def advance(ctx: Context, run_id: int, action: str) -> Reply:
    run = _active(ctx)
    if run is None:
        raise GameError("当前没有进行中的灵脉探勘，请先查看灵宠灵脉。")
    _time(ctx, run)
    if run_id != run["run_id"]:
        raise GameError("这是旧局号，请重新打开 灵宠灵脉 查看当前进度。")
    if action not in {"采集", "护脉", "绕行"}:
        raise GameError("本段只能选择采集、护脉或绕行。")
    if len(run["actions"]) >= 3:
        raise GameError("本局已经完成，不能重复推进。")
    pet = _pet(ctx, run["pet_id"])
    if pet.energy < STEP_ENERGY:
        raise GameError(f"{pet.name}精力不足，需要 {STEP_ENERGY} 点；本段尚未写入。")
    if action == "护脉":
        if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) < GUARD_FOOD:
            raise GameError("灵粮不足，护脉需要 1 份；本段尚未写入。")
        ctx.repo.consume_item(ctx.user_id, "spirit_food", GUARD_FOOD)
        run["food_spent"] += GUARD_FOOD
    pet.energy -= STEP_ENERGY
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    node = run["nodes"][len(run["actions"])]
    if action == "采集":
        if node["material"] not in ctx.content.items:
            raise GameError(f"节点材料 {node['material']} 当前不可用；本段未扣除资源。")
        ctx.repo.add_item(ctx.user_id, node["material"], 1)
        run["collected"].append(node["material_name"])
    run["energy_spent"] += STEP_ENERGY
    run["actions"].append({"step": len(run["actions"]) + 1, "action": action,
                           "node": node["name"], "material": node["material"] if action == "采集" else None})
    if len(run["actions"]) == 3:
        return _finish(ctx, run, pet)
    message = f"第{len(run['actions'])}段已选择{action} · 精力 -{STEP_ENERGY}。"
    if action == "护脉":
        message += "灵粮 -1，终章奖励已提升。"
    elif action == "采集":
        message += f"获得 {node['material_name']} ×1。"
    else:
        message += "本段不取材料，但保留探勘进度。"
    return _record(ctx, run, _run_page(ctx, run, (message,)))


def abandon(ctx: Context, run_id: int) -> Reply:
    run = _active(ctx)
    if run is None:
        raise GameError("当前没有进行中的灵脉探勘。")
    _time(ctx, run)
    if run_id != run["run_id"]:
        raise GameError("这是旧局号，请重新打开 灵宠灵脉 查看当前进度。")
    run.update(status="abandoned", event="abandon")
    return _record(ctx, run, Reply(TITLE + " · 放弃", (
        f"第 {run_id} 局已放弃，已付精力 {run['energy_spent']}、灵粮 {run['food_spent']} 均不退。",
        "已采集材料保留；未结算终章奖励与羁绊，历史记录已保存。",
    ), (TITLE, "灵宠背包"), (InlineCommand(1, "查看记录", f"{TITLE} 记录"),)))


def history(ctx: Context, argument: str) -> Reply:
    entries = ctx.repo.vein_expedition_history(ctx.user_id)
    page = paginate(entries, argument, TITLE + "记录", f"{TITLE} 记录", PAGE_SIZE)
    lines = [f"第 {page.number}/{page.total} 页 · 共 {len(entries)} 局。"]
    for entry in page.entries:
        run = entry["snapshot"]
        status = "完成" if run["status"] == "finished" else "放弃"
        when = datetime.fromtimestamp(int(run["started_at"]), BEIJING).strftime("%Y-%m-%d %H:%M")
        actions = "、".join(action["action"] for action in run.get("actions", [])) or "尚未推进"
        lines.append(f"第 {run['run_id']} 局 · {run['route']['name']} · {run['pet_name']} · {status} · {when}")
        lines.append(f"动作：{actions} · 采集：{'、'.join(run.get('collected', [])) or '无'}")
        if run.get("final_reward"):
            reward = run["final_reward"]
            lines.append(f"终章：灵石 +{reward['stones']} · {'护脉奖励' if reward.get('guarded') else '基础奖励'}")
    commands = [*page.navigation, TITLE]
    return Reply(f"{TITLE}记录 {page.number}/{page.total}", tuple(lines), tuple(commands))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "预览" and len(parts) == 2:
        return _route_page(ctx, named(ctx.content.vein_routes, parts[1]))
    if parts[0] == "记录" and len(parts) <= 2:
        return history(ctx, parts[1] if len(parts) == 2 else "")
    if parts[0] == "开启" and len(parts) == 4 and parts[2] == "伙伴":
        return start(ctx, parts[1], parts[3])
    if parts[0] == "前进" and len(parts) == 3:
        return advance(ctx, quantity(parts[1], 9_223_372_036_854_775_807), parts[2])
    if parts[0] == "放弃" and len(parts) == 2:
        return abandon(ctx, quantity(parts[1], 9_223_372_036_854_775_807))
    raise GameError("格式：灵宠灵脉 [预览 路线|开启 路线 伙伴 编号|前进 局号 采集/护脉/绕行|放弃 局号|记录 页码]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = _active(ctx)
    if run is not None:
        return f"灵脉探勘：{run['route']['name']} · 第{len(run['actions']) + 1}/3段 · 局号 {run['run_id']}"
    latest = _latest(ctx)
    if latest is not None:
        return f"灵脉探勘：最近{('完成' if latest['status'] == 'finished' else '放弃')}第 {latest['run_id']} 局"
    return "灵脉探勘：三段路线待开启"


__all__ = ["TITLE", "catalog", "dispatch", "history", "objective_line", "state"]
