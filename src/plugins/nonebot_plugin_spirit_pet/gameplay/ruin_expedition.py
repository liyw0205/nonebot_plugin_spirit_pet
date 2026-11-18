"""Three-hall ruin exploration with a risk/reward choice at every hall."""

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

TITLE = "灵宠遗迹"
RULE_VERSION = "ruin-1"
KIND = "ruin_expedition"
PAGE_SIZE = 5
SAFE_FOOD = 1


def _run_id(ctx: Context) -> int:
    value = int(sha256(f"ruin:{ctx.user_id}:{ctx.operation_id}:{ctx.now}".encode()).hexdigest()[:14], 16)
    return max(1, value)


def _realm_index(ctx: Context, realm_id: str) -> int:
    for index, realm in enumerate(ctx.content.realms):
        if realm.id == realm_id:
            return index
    raise GameError("遗迹境界门槛异常，暂不能开启。")


def _active(ctx: Context) -> dict | None:
    row = ctx.repo.latest_ruin_expedition_action(ctx.user_id, active_only=True)
    return row["snapshot"] if row else None


def _latest(ctx: Context) -> dict | None:
    row = ctx.repo.latest_ruin_expedition_action(ctx.user_id)
    return row["snapshot"] if row else None


def state(ctx: Context) -> dict | None:
    """Read the active frozen run for digest pages without mutating state."""
    return _active(ctx)


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < int(run.get("updated_at", run.get("started_at", ctx.now))):
        raise GameError("系统时间早于最近遗迹操作，请等待时钟恢复；探秘进度保留。")


def _pet(ctx: Context, pet_id: int):
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
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    ctx.require_idle_pet(pet)
    return pet


def _reward_dump(reward) -> dict:
    return reward.model_dump()


def _reward_values(ctx: Context, reward: dict) -> tuple[int, int, dict[str, int]]:
    try:
        exp_range, stone_range = reward["exp"], reward["stones"]
        exp = int(ctx.rng.randint(int(exp_range["minimum"]), int(exp_range["maximum"])))
        stones = int(ctx.rng.randint(int(stone_range["minimum"]), int(stone_range["maximum"])))
        items = {}
        for item_id, bounds in reward.get("items", {}).items():
            if item_id not in ctx.content.items:
                raise KeyError(item_id)
            items[item_id] = int(ctx.rng.randint(int(bounds["minimum"]), int(bounds["maximum"])))
        return exp, stones, items
    except (KeyError, TypeError, ValueError) as exc:
        raise GameError("本局宝藏快照损坏或内容缺失，暂不能结算；进度保留。") from exc


def _reward_text(ctx: Context, reward: dict) -> str:
    parts = []
    if reward["exp"]["minimum"]:
        parts.append(f"修为 {reward['exp']['minimum']}-{reward['exp']['maximum']}")
    if reward["stones"]["minimum"]:
        parts.append(f"灵石 {reward['stones']['minimum']}-{reward['stones']['maximum']}")
    for item_id, bounds in reward.get("items", {}).items():
        name = ctx.content.items[item_id].name if item_id in ctx.content.items else item_id
        amount = str(bounds["minimum"]) if bounds["minimum"] == bounds["maximum"] else f"{bounds['minimum']}-{bounds['maximum']}"
        parts.append(f"{name} ×{amount}")
    return "、".join(parts) or "无"


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_ruin_expedition_action(
        ctx.operation_id, ctx.user_id, ctx.now, {**run, "updated_at": ctx.now}, reply,
    )
    return reply


def _site_page(ctx: Context, site) -> Reply:
    minimum = ctx.content.realms[_realm_index(ctx, site.min_realm)].name
    lines = [
        site.description,
        f"{minimum}可入 · 三厅 · 开局精力 {site.energy} · 开局灵粮 {site.food}",
        f"基础宝藏：{_reward_text(ctx, _reward_dump(site.reward))}",
        f"富集宝藏：{_reward_text(ctx, _reward_dump(site.rich_reward))}（风险达到 5）",
    ]
    for index, hall in enumerate(site.halls, 1):
        lines.append(f"第{index}厅 {hall.name} · {hall.description} · 取宝 {ctx.content.items[hall.treasure].name} ×1 · 风险 +{hall.risk}")
    return Reply(site.name, tuple(lines), (TITLE,))


def catalog(ctx: Context, argument: str = "") -> Reply:
    if argument.strip():
        raise GameError(f"格式：{TITLE} [预览 遗迹|开启 遗迹 伙伴 编号|前进 局号 取宝/稳行/撤退|放弃 局号|记录 页码]。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴才能探秘遗迹。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = _active(ctx)
    if run:
        return _run_page(ctx, run)
    lines = ["三厅遗迹会冻结伙伴、厅室、风险规则和宝藏快照，可跨日、重启与清缓存继续。"]
    links = []
    for site in sorted(ctx.content.ruins.values(), key=lambda item: item.id):
        minimum = ctx.content.realms[_realm_index(ctx, site.min_realm)].name
        lines.append(f"{site.name} · {minimum}可入 · 三厅 · 开局精力 {site.energy} · 富集宝藏 {_reward_text(ctx, _reward_dump(site.rich_reward))}")
        links.append(InlineCommand(len(lines) - 1, "查看遗迹", f"{TITLE} 预览 {site.name}"))
    lines.append("当前无进行中的遗迹；主动放弃不退款但会保留历史。")
    links.append(InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"))
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠目标"), tuple(links))


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    index = len(run["actions"])
    lines = [*prefix, f"第 {run['run_id']} 局 · {run['site']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）",
             f"进度 {index}/3 · 风险 {run['risk']} · 已耗精力 {run['energy_spent']} · 已耗灵粮 {run['food_spent']}"]
    for offset, hall in enumerate(run["halls"][index:], index + 1):
        lines.append(f"第{offset}厅 {hall['name']} · {hall['description']} · 取宝 {hall['treasure_name']} ×1")
    lines.append(f"已取宝：{'、'.join(run['collected']) if run['collected'] else '无'}。富集门槛：风险 5。")
    try:
        _time(ctx, run)
        pet = _pet(ctx, run["pet_id"])
        if pet.energy < 5:
            raise GameError(f"{pet.name}精力不足，需要 5 点才能继续。")
    except GameError as exc:
        lines.append(str(exc))
    else:
        for action in ("取宝", "稳行", "撤退"):
            lines.append(f"可选：{action}")
    lines.append("取宝获得本厅材料并增加风险；稳行消耗 1 灵粮并降低风险；撤退不返还成本。")
    links = (InlineCommand(len(lines) - 1, "放弃本局", f"{TITLE} 放弃 {run['run_id']}"),
             InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"))
    return Reply(f"{TITLE} · 进行中", tuple(lines), tuple(f"{TITLE} 前进 {run['run_id']} {action}" for action in ("取宝", "稳行", "撤退")), links)


def start(ctx: Context, site_name: str, selector: str) -> Reply:
    if _active(ctx):
        raise GameError("已有进行中的遗迹探秘，请先完成或放弃当前局。")
    latest = _latest(ctx)
    if latest:
        _time(ctx, latest)
    site = named(ctx.content.ruins, site_name)
    pet = named_pet(ctx, selector, "遗迹探秘")
    ctx.require_idle_pet(pet)
    if released(ctx, pet.pet_id):
        raise GameError(f"{pet.name}已归灵，不能参与探秘。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，请复原后再出发。")
    if pet.realm < _realm_index(ctx, site.min_realm):
        raise GameError(f"{pet.name}境界不足，{site.name}需要{ctx.content.realms[_realm_index(ctx, site.min_realm)].name}。")
    if pet.energy < site.energy:
        raise GameError(f"{pet.name}精力不足，需要 {site.energy} 点。")
    if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) < site.food:
        raise GameError(f"灵粮不足，开启需要 {site.food} 份；本局尚未建立。")
    ctx.repo.consume_item(ctx.user_id, "spirit_food", site.food)
    pet.energy -= site.energy
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    halls = [{"name": hall.name, "description": hall.description, "treasure": hall.treasure,
              "treasure_name": ctx.content.items[hall.treasure].name, "risk": hall.risk}
             for hall in site.halls]
    run = {"status": "active", "event": "start", "rule_version": RULE_VERSION,
           "run_id": _run_id(ctx), "site": site.model_dump(), "pet_id": pet.pet_id,
           "pet_name": pet.name, "halls": halls, "actions": [], "collected": [], "risk": 0,
           "energy_spent": site.energy, "food_spent": site.food, "reward": _reward_dump(site.reward),
           "rich_reward": _reward_dump(site.rich_reward), "bond": site.bond,
           "started_at": ctx.now, "updated_at": ctx.now}
    return _record(ctx, run, _run_page(ctx, run, (f"遗迹探秘开启：精力 -{site.energy}、灵粮 -{site.food}。",)))


def _finish(ctx: Context, run: dict, pet) -> Reply:
    rich = run["risk"] >= 5
    reward = run["rich_reward"] if rich else run["reward"]
    exp, stones, items = _reward_values(ctx, reward)
    pet.exp += exp
    ctx.player().stones += stones
    for item_id, amount in items.items():
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
    total_bond = bond_levels.add_exp(ctx, pet.pet_id, run["bond"])
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run.update(status="finished", event="finish", final_reward={"exp": exp, "stones": stones, "items": items, "rich": rich})
    lines = [f"第 {run['run_id']} 局 · {run['site']['name']} · {pet.name}探秘完成。",
             "动作：" + "、".join(item["action"] for item in run["actions"]),
             f"{'富集' if rich else '基础'}宝藏：修为 +{exp}、灵石 +{stones}"]
    lines.extend(f"{ctx.content.items[item_id].name} +{amount}" for item_id, amount in items.items() if amount)
    lines.append(f"{pet.name}羁绊经验 +{run['bond']} · 累计 {total_bond}。")
    return _record(ctx, run, Reply(TITLE + " · 完成", tuple(lines), (TITLE, "灵宠背包", "灵宠羁绊"),
                                    (InlineCommand(len(lines) - 1, "查看记录", f"{TITLE} 记录"),)))


def advance(ctx: Context, run_id: int, action: str) -> Reply:
    run = _active(ctx)
    if run is None:
        raise GameError("当前没有进行中的遗迹探秘，请先查看灵宠遗迹。")
    _time(ctx, run)
    if run_id != run["run_id"]:
        raise GameError("这是旧局号，请重新打开 灵宠遗迹 查看当前进度。")
    if action not in {"取宝", "稳行", "撤退"}:
        raise GameError("本厅只能选择取宝、稳行或撤退。")
    if len(run["actions"]) >= 3:
        raise GameError("本局已经完成，不能重复推进。")
    pet = _pet(ctx, run["pet_id"])
    if pet.energy < 5:
        raise GameError(f"{pet.name}精力不足，需要 5 点；本厅尚未写入。")
    hall = run["halls"][len(run["actions"])]
    if action == "稳行":
        if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) < SAFE_FOOD:
            raise GameError("灵粮不足，稳行需要 1 份；本厅尚未写入。")
        ctx.repo.consume_item(ctx.user_id, "spirit_food", SAFE_FOOD)
        run["food_spent"] += SAFE_FOOD
        run["risk"] = max(0, run["risk"] - 1)
    elif action == "取宝":
        if hall["treasure"] not in ctx.content.items:
            raise GameError("本厅宝物内容缺失；本厅未扣除资源。")
        ctx.repo.add_item(ctx.user_id, hall["treasure"], 1)
        run["collected"].append(hall["treasure_name"])
        run["risk"] += hall["risk"]
    pet.energy -= 5
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run["energy_spent"] += 5
    run["actions"].append({"hall": len(run["actions"]) + 1, "action": action, "name": hall["name"],
                           "treasure": hall["treasure"] if action == "取宝" else None})
    if len(run["actions"]) == 3:
        return _finish(ctx, run, pet)
    message = f"第{len(run['actions'])}厅已选择{action} · 精力 -5。"
    if action == "稳行":
        message += "灵粮 -1，风险降低。"
    elif action == "取宝":
        message += f"获得 {hall['treasure_name']} ×1，风险上升。"
    else:
        message += "本厅不取宝，风险保持。"
    return _record(ctx, run, _run_page(ctx, run, (message,)))


def abandon(ctx: Context, run_id: int) -> Reply:
    run = _active(ctx)
    if run is None:
        raise GameError("当前没有进行中的遗迹探秘。")
    _time(ctx, run)
    if run_id != run["run_id"]:
        raise GameError("这是旧局号，请重新打开 灵宠遗迹 查看当前进度。")
    run.update(status="abandoned", event="abandon")
    return _record(ctx, run, Reply(TITLE + " · 放弃", (f"第 {run_id} 局已放弃，已付精力 {run['energy_spent']}、灵粮 {run['food_spent']} 均不退。",
        "已取宝物保留；未结算终章宝藏与羁绊，历史记录已保存。"), (TITLE, "灵宠背包"),
        (InlineCommand(1, "查看记录", f"{TITLE} 记录"),)))


def history(ctx: Context, argument: str) -> Reply:
    entries = ctx.repo.ruin_expedition_history(ctx.user_id)
    page = paginate(entries, argument, TITLE + "记录", f"{TITLE} 记录", PAGE_SIZE)
    lines = [f"第 {page.number}/{page.total} 页 · 共 {len(entries)} 局。"]
    for entry in page.entries:
        run = entry["snapshot"]
        status = "完成" if run["status"] == "finished" else "放弃"
        when = datetime.fromtimestamp(int(run["started_at"]), BEIJING).strftime("%Y-%m-%d %H:%M")
        actions = "、".join(item["action"] for item in run.get("actions", [])) or "尚未推进"
        lines.append(f"第 {run['run_id']} 局 · {run['site']['name']} · {run['pet_name']} · {status} · {when}")
        lines.append(f"动作：{actions} · 取宝：{'、'.join(run.get('collected', [])) or '无'}")
        if run.get("final_reward"):
            lines.append(f"宝藏：灵石 +{run['final_reward']['stones']} · {'富集' if run['final_reward'].get('rich') else '基础'}")
    return Reply(f"{TITLE}记录 {page.number}/{page.total}", tuple(lines), (*page.navigation, TITLE))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "预览" and len(parts) == 2:
        return _site_page(ctx, named(ctx.content.ruins, parts[1]))
    if parts[0] == "记录" and len(parts) <= 2:
        return history(ctx, parts[1] if len(parts) == 2 else "")
    if parts[0] == "开启" and len(parts) == 4 and parts[2] == "伙伴":
        return start(ctx, parts[1], parts[3])
    if parts[0] == "前进" and len(parts) == 3:
        return advance(ctx, quantity(parts[1], 9_223_372_036_854_775_807), parts[2])
    if parts[0] == "放弃" and len(parts) == 2:
        return abandon(ctx, quantity(parts[1], 9_223_372_036_854_775_807))
    raise GameError(f"格式：{TITLE} [预览 遗迹|开启 遗迹 伙伴 编号|前进 局号 取宝/稳行/撤退|放弃 局号|记录 页码]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = _active(ctx)
    if run is not None:
        return f"遗迹探秘：{run['site']['name']} · 第{len(run['actions']) + 1}/3厅 · 局号 {run['run_id']}"
    latest = _latest(ctx)
    if latest is not None:
        return f"遗迹探秘：最近{'完成' if latest['status'] == 'finished' else '放弃'}第 {latest['run_id']} 局"
    return "遗迹探秘：三厅遗迹待开启"


__all__ = ["TITLE", "catalog", "dispatch", "history", "objective_line", "state"]
