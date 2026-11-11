"""Visible route planning, a bounded basket, and atomic return settlement."""

from dataclasses import replace

from ..application.context import Context
from ..domain.herbalism_content import home_costs, neighbors
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.time import beijing_day
from . import bond_levels

ENERGY = 8
CAPACITY = 2
DAY_KEY = "herbalism_day"


def _progress(ctx: Context, key: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _write(ctx: Context, key: str, value: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress", (ctx.user_id, key, value),
    )


def _day(ctx: Context) -> int:
    return int(beijing_day(ctx.now).replace("-", ""))


def state(ctx: Context) -> dict | None:
    last = ctx.repo.latest_herbalism_action(ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _reason(ctx: Context, pet) -> str:
    if pet.user_id != ctx.user_id:
        return "本次采药伙伴归属异常，无法继续。"
    if _progress(ctx, f"released_{pet.pet_id}"):
        return "本次伙伴已归灵，请撤离药山。"
    if pet.archived:
        return "本次伙伴已封存，请复原后继续，或撤离药山。"
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition:
        status = "正在外出派遣" if ctx.now < expedition["finishes_at"] else "派遣已完成，奖励待领取"
        return f"本次伙伴{status}，请先查看 灵宠行程。"
    return ""


def _check_time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次采药操作，请等待时钟恢复。")


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_herbalism_action(ctx.operation_id, ctx.user_id, ctx.now,
                                    {**run, "updated_at": ctx.now}, reply)
    return reply


def _map_lines(route: dict, names: dict, picked: list[int], position: int) -> list[str]:
    costs = home_costs([site["cost"] for site in route["sites"]])
    lines = ["地点按三行三列排列，编号从左到右、从上到下；只走相邻横竖地点。"]
    for index, site in enumerate(route["sites"], 1):
        material = names[site["item_id"]] + f" ×1，采集耗 {site['harvest_cost']}" if site["item_id"] else "无采集物"
        if index in picked:
            material = "已采过，不能再采"
        lines.append(f"{index} {site['name']}" + (" · 当前位置" if index == position else "")
                     + f" · 进入耗 {site['cost']} · 最短返程 {costs[index - 1]} · {material}")
    return lines


def preview(ctx: Context, name: str) -> Reply:
    route = named(ctx.content.herb_routes, name)
    names = {site.item_id: ctx.content.items[site.item_id].name for site in route.sites if site.item_id}
    lines = [route.description, f"脚程 {route.budget} · 药篓 {CAPACITY} 格 · 入口为 1 号。",
             *_map_lines(route.model_dump(), names, [], 1)]
    return Reply(route.name, tuple(lines), ("灵宠采药",),
                 (InlineCommand(1, "选择此山", f"灵宠采药 出发 {route.name}"),))


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    route, position, left = run["route"], run["position"], run["remaining"]
    costs = home_costs([site["cost"] for site in route["sites"]])
    token = f"{run['day']} {run['revision']}"
    lines = [*prefix, f"{route['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）",
             f"脚程剩余 {left}/{route['budget']} · 最短返程需 {costs[position - 1]} · 药篓 {len(run['basket'])}/{CAPACITY}。",
             *_map_lines(route, run["names"], run["picked"], position)]
    links = []
    for index, entry in enumerate(run["basket"], 1):
        lines.append(f"药篓 {index}：{run['names'][entry['item_id']]} ×1（采自 {entry['site']} 号）。")
        links.append(InlineCommand(len(lines) - 1, "弃置此份", f"灵宠采药 弃置 {index} {token}"))
    if not run["basket"]:
        lines.append("药篓为空；只有带回材料才增加羁绊。")
    commands = []
    site = route["sites"][position - 1]
    if (site["item_id"] and position not in run["picked"] and len(run["basket"]) < CAPACITY
            and left >= site["harvest_cost"] + costs[position - 1]):
        commands.append(f"灵宠采药 采集 {token}")
    if position == 1:
        commands.append(f"灵宠采药 返程 {token}")
    for adjacent in neighbors(position):
        cost = route["sites"][adjacent - 1]["cost"]
        if cost + costs[adjacent - 1] <= left:
            commands.append(f"灵宠采药 移动 {adjacent} {token}")
    reason = _reason(ctx, ctx.repo.pet(run["pet_id"]))
    if ctx.now < run["updated_at"]:
        reason = "时间早于上次采药操作，请等待时钟恢复。"
    if reason:
        lines.append(reason)
        commands, links = [], []
        links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                      InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    if len(commands) > 4:
        extra = commands.pop()
        lines.append("另一个相邻方向也可通行。")
        links.append(InlineCommand(len(lines) - 1, f"前往 {extra.split()[2]} 号", extra))
    lines.append("回到 1 号入口再返程，药篓才入袋；撤离舍弃全部材料，开局精力不退。")
    links.append(InlineCommand(len(lines) - 1, "撤离药山", f"灵宠采药 撤离 {token}"))
    return Reply("灵宠采药 · 山中", tuple(lines), tuple(commands), tuple(links))


def page(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠采药", ("先领养一位伙伴，再一起进山采药。", "看清地形，留足返程脚程，带回药篓材料。"),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = state(ctx)
    if run:
        return _run_page(ctx, run)
    ready = _progress(ctx, DAY_KEY) < _day(ctx)
    reason = "尚未选择出战伙伴，请先查看灵宠列表。"
    if player.active_pet_id is not None:
        pet = replace(ctx.repo.pet(player.active_pet_id))
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        reason = _reason(ctx, pet)
        if not reason and pet.energy < ENERGY:
            reason = f"{pet.name}精力不足，需要 {ENERGY} 点，当前 {pet.energy}。"
    lines = [f"每日开局一次 · 开局精力 {ENERGY} · 药篓最多 {CAPACITY} 份材料。",
             "今日可出发。" if ready else "今日已出发，或日期早于上次出发。",
             "移动消耗目的地脚程，采集另耗脚程；每次操作均保留最短返程预算。",
             "回到入口返程才发放药篓；带回材料时原伙伴羁绊经验 +6，空篓或撤离无成长。"]
    links = []
    for route in ctx.content.herb_routes.values():
        lines.append(f"{route.name} · 脚程 {route.budget} · {route.description}")
        links.append(InlineCommand(len(lines) - 1, "查看地形", f"灵宠采药 预览 {route.name}"))
    lines.append("带回的种子可播种，灵粮、草籽与矿石也可按既有丹方炼制。")
    links.extend((InlineCommand(len(lines) - 1, "采药手记", "灵宠采药 手记"),
                  InlineCommand(len(lines) - 1, "最近记录", "灵宠采药 记录"),
                  InlineCommand(len(lines) - 1, "查看丹方", "灵宠炼丹")))
    if reason:
        lines.append(reason)
        links.extend((InlineCommand(len(lines) - 1, "查看伙伴", "灵宠列表"),
                      InlineCommand(len(lines) - 1, "查看行程", "灵宠行程")))
    return Reply("灵宠采药", tuple(lines),
                 tuple(f"灵宠采药 出发 {route.name}" for route in ctx.content.herb_routes.values())
                 if ready and not reason else (), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    last = ctx.repo.latest_herbalism_action(ctx.user_id)
    if last:
        _check_time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有一次采药行程，请继续或撤离后再出发。")
    route = named(ctx.content.herb_routes, name)
    if _progress(ctx, DAY_KEY) >= _day(ctx):
        raise GameError("今天已出发采药，或日期早于上次出发，请明日再来。")
    pet = ctx.pet()
    reason = _reason(ctx, pet)
    if reason:
        raise GameError(reason)
    if pet.energy < ENERGY:
        raise GameError(f"{pet.name}精力不足，需要 {ENERGY} 点。")
    pet.energy -= ENERGY
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run = {"status": "active", "event": "start", "route": route.model_dump(),
           "names": {site.item_id: ctx.content.items[site.item_id].name for site in route.sites if site.item_id},
           "pet_id": pet.pet_id, "pet_name": pet.name, "position": 1, "remaining": route.budget,
           "picked": [], "basket": [], "path": [1], "day": _day(ctx), "revision": 1,
           "started_at": ctx.now, "updated_at": ctx.now}
    _write(ctx, DAY_KEY, run["day"])
    return _record(ctx, run, _run_page(ctx, run, (f"进山采药：精力 -{ENERGY}。",)))


def _finish(ctx: Context, run: dict, pet, abandon: bool) -> Reply:
    if not abandon and run["position"] != 1:
        raise GameError("尚未回到 1 号入口，请沿地图返回后再返程结算。")
    carried = [] if abandon else run["basket"]
    for entry in carried:
        if entry["item_id"] not in ctx.content.items:
            raise GameError(f"采药材料「{run['names'][entry['item_id']]}」暂不可用，返程未结算，请等待内容恢复。")
    for entry in carried:
        ctx.repo.add_item(ctx.user_id, entry["item_id"], 1)
        _write(ctx, f"herbalism_seen_{run['route']['id']}_{entry['site']}", 1)
    total = None
    if carried:
        before = bond_levels.current_level(ctx, pet.pet_id)
        total = bond_levels.add_exp(ctx, pet.pet_id, 6)
        ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
        for key in (f"herbalism_returns_{run['route']['id']}", f"herbalism_pet_{pet.pet_id}"):
            _write(ctx, key, _progress(ctx, key) + 1)
        key = f"herbalism_best_{run['route']['id']}"
        _write(ctx, key, max(_progress(ctx, key), len(carried)))
    run.update(status="abandoned" if abandon else "finished", event="abandon" if abandon else "return")
    lines = [f"{run['route']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）",
             "路线：" + " → ".join(map(str, run["path"])),
             f"剩余脚程 {run['remaining']}/{run['route']['budget']} · 采过 {len(run['picked'])} 处。"]
    if abandon:
        lines.append("已撤离药山，药篓全部舍弃；未发放材料或成长，开局精力不退。")
    elif not carried:
        lines.append("已空篓返程，未发放材料或成长。")
    else:
        lines.append("药篓已入袋：" + "、".join(run["names"][entry["item_id"]] + " ×1" for entry in carried) + "。")
        lines.append(f"{run['pet_name']}羁绊经验 +6 · 累计 {total} · 等级 {before} → {bond_levels.level(total)}。")
    lines.append("手记仅记录实际带回的采集点；弃置或撤离不会补发。")
    return _record(ctx, run, Reply("采药撤离" if abandon else "采药返程", tuple(lines), ("灵宠采药", "灵宠背包"),
                                  (InlineCommand(len(lines) - 1, "采药手记", "灵宠采药 手记"),
                                   InlineCommand(len(lines) - 1, "查看丹方", "灵宠炼丹"),
                                   InlineCommand(len(lines) - 1, "查看灵田", "灵宠灵田"),
                                   InlineCommand(len(lines) - 1, "羁绊成长", "灵宠羁绊"))))


def act(ctx: Context, action: str, target: int | None, token: tuple[int, int] | None) -> Reply:
    ctx.player()
    run = state(ctx)
    if run is None:
        raise GameError("当前没有采药行程，请先出发。")
    _check_time(ctx, run)
    if token is not None and token != (run["day"], run["revision"]):
        raise GameError("这是旧行程或旧步骤的操作，请重新打开 灵宠采药 查看当前位置。")
    run["revision"] += 1
    if action == "撤离":
        return _finish(ctx, run, None, True)
    pet = ctx.repo.pet(run["pet_id"])
    reason = _reason(ctx, pet)
    if reason:
        raise GameError(reason)
    costs = home_costs([site["cost"] for site in run["route"]["sites"]])
    position = run["position"]
    if action == "返程":
        return _finish(ctx, run, pet, False)
    if action == "移动":
        if target not in neighbors(position):
            raise GameError("只能移动到当前位置横竖相邻的地点。")
        cost = run["route"]["sites"][target - 1]["cost"]
        if run["remaining"] < cost + costs[target - 1]:
            raise GameError(f"脚程不足：移动需 {cost}，到达后最短返程需 {costs[target - 1]}，当前仅余 {run['remaining']}。")
        run["remaining"] -= cost
        run["position"] = target
        run["path"].append(target)
        message = f"移动到 {target} 号，脚程 -{cost}。"
    elif action == "采集":
        site = run["route"]["sites"][position - 1]
        if not site["item_id"]:
            raise GameError("此处没有可采集的材料，请查看地图选择药草地点。")
        if position in run["picked"]:
            raise GameError("此处已经采集过，弃置也不会重新长出。")
        if len(run["basket"]) >= CAPACITY:
            raise GameError("药篓已满，最多装两份；可先弃置一份再采集。")
        cost = site["harvest_cost"]
        if run["remaining"] < cost + costs[position - 1]:
            raise GameError(f"脚程不足：采集需 {cost}，最短返程需 {costs[position - 1]}，当前仅余 {run['remaining']}。")
        run["remaining"] -= cost
        run["picked"].append(position)
        run["basket"].append({"site": position, "item_id": site["item_id"]})
        message = f"采得 {run['names'][site['item_id']]} ×1，暂存药篓，脚程 -{cost}。"
    else:
        if target is None or target > len(run["basket"]):
            raise GameError("该药篓格为空，请查看当前药篓后再弃置。")
        entry = run["basket"].pop(target - 1)
        message = f"已弃置 {run['names'][entry['item_id']]} ×1；原采集点不会恢复。"
    run["event"] = action
    return _record(ctx, run, _run_page(ctx, run, (message,)))


def journal(ctx: Context) -> Reply:
    lines = []
    for route in ctx.content.herb_routes.values():
        seen = sum(_progress(ctx, f"herbalism_seen_{route.id}_{index}") > 0 for index in range(1, 10))
        available = sum(site.item_id is not None for site in route.sites)
        lines.append(f"{route.name} · 已带回 {seen}/{available} 处 · 有获返程 {_progress(ctx, 'herbalism_returns_' + route.id)} 次"
                     + f" · 单次最多 {_progress(ctx, 'herbalism_best_' + route.id)}/{CAPACITY} 份。")
    player = ctx.repo.player(ctx.user_id)
    if player is not None and player.active_pet_id is not None:
        pet = ctx.repo.pet(player.active_pet_id)
        lines.append(f"当前伙伴 {pet.name}（编号 {pet.pet_id}）· 有获返程 {_progress(ctx, f'herbalism_pet_{pet.pet_id}')} 次。")
    return Reply("采药手记", tuple(lines), ("灵宠采药", "灵宠羁绊"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["手记"]:
        return journal(ctx)
    if parts == ["记录"]:
        last = ctx.repo.latest_herbalism_action(ctx.user_id, finished_only=True)
        return Reply("采药记录", Reply.from_data(last["reply"]).lines if last else ("还没有已结束的采药行程。",),
                     ("灵宠采药", "灵宠采药 手记"))
    if len(parts) == 2 and parts[0] in ("出发", "预览"):
        return start(ctx, parts[1]) if parts[0] == "出发" else preview(ctx, parts[1])
    if parts == ["地图"]:
        run = state(ctx)
        if run is None:
            raise GameError("当前没有采药行程，请先出发，或用 灵宠采药 预览 药山名 查看地形。")
        return _run_page(ctx, run)
    if parts[0] in ("移动", "弃置") and len(parts) in (2, 4):
        target = quantity(parts[1], 9 if parts[0] == "移动" else CAPACITY)
        token = (quantity(parts[2], 99999999), quantity(parts[3], 1000)) if len(parts) == 4 else None
        return act(ctx, parts[0], target, token)
    if parts[0] in ("采集", "返程", "撤离") and len(parts) in (1, 3):
        token = (quantity(parts[1], 99999999), quantity(parts[2], 1000)) if len(parts) == 3 else None
        return act(ctx, parts[0], None, token)
    raise GameError("格式：灵宠采药 [预览 药山名|出发 药山名|地图|移动 编号|采集|弃置 格号|返程|撤离|手记|记录]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx)
    if run:
        return f"采药：{run['route']['name']} · {run['position']} 号 · 脚程 {run['remaining']} · 药篓 {len(run['basket'])}/{CAPACITY}"
    return "采药：今日已出发" if _progress(ctx, DAY_KEY) >= _day(ctx) else "采药：今日可出发"
