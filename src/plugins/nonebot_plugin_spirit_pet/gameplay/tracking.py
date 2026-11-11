"""Two distance surveys and one excavation, with permanent per-action receipts."""

from dataclasses import replace

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.time import beijing_day
from . import bond_levels

ENERGY = 8
SURVEYS = 2
DAY_KEY = "tracking_day"


def _progress(ctx: Context, key: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _write(ctx: Context, key: str, value: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, value),
    )


def _day(ctx: Context) -> int:
    return int(beijing_day(ctx.now).replace("-", ""))


def state(ctx: Context) -> dict | None:
    last = ctx.repo.latest_tracking_action(ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def distance(first: int, second: int) -> int:
    a, b = divmod(first - 1, 4), divmod(second - 1, 4)
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def candidates(run: dict) -> list[int]:
    return [site for site in range(1, 17)
            if run["map"]["terrains"][site - 1] == run["terrain"]
            and all(distance(site, entry["site"]) == entry["distance"] for entry in run["surveys"])]


def _digging(run: dict) -> bool:
    return len(run["surveys"]) >= SURVEYS or len(candidates(run)) == 1


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_tracking_action(
        ctx.operation_id, ctx.user_id, ctx.now, {**run, "updated_at": ctx.now}, reply,
    )
    return reply


def _check_time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次寻踪，请等待时钟恢复后再操作。")


def _block_reason(ctx: Context, pet) -> str:
    if pet.user_id != ctx.user_id:
        return "本局伙伴归属异常，无法继续寻踪。"
    if _progress(ctx, f"released_{pet.pet_id}"):
        return "本局伙伴已归灵，无法复原，请放弃本局寻踪。"
    if pet.archived:
        return "本局伙伴已封存，请复原后继续，或放弃寻踪。"
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        status = "正在外出派遣" if ctx.now < expedition["finishes_at"] else "派遣已完成，奖励待领取"
        return f"本局伙伴{status}，请先查看 灵宠行程。"
    return ""


def _partner(ctx: Context, run: dict):
    pet = ctx.repo.pet(run["pet_id"])
    reason = _block_reason(ctx, pet)
    if reason:
        raise GameError(reason)
    return pet


def _run_page(ctx: Context, run: dict, page: int = 1, prefix: tuple[str, ...] = ()) -> Reply:
    remaining = candidates(run)
    digging = _digging(run)
    available = remaining if digging else [site for site in range(1, 17)
                                              if site not in {entry["site"] for entry in run["surveys"]}]
    pages = max(1, (len(available) + 3) // 4)
    if page > pages:
        raise GameError(f"当前地点共 {pages} 页。")
    action = "挖掘" if digging else "勘察"
    lines = [*prefix, f"{run['map']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）",
             f"初始线索：藏物沾有{run['map']['terrain_names'][run['terrain']]}。",
             f"已勘察 {len(run['surveys'])}/{SURVEYS} 次 · 候选地点：" + "、".join(map(str, remaining)) + "。",
             "距离按横竖步数相加，不走斜线；编号按每行四处，从左到右、从上到下排列。"]
    for entry in run["surveys"]:
        lines.append(f"已勘察 {entry['site']} 号：距藏物 {entry['distance']} 步。")
    lines.append("选择一处挖掘，仅有一次机会。" if digging else "选择勘察位置，伙伴会报告到藏物的准确距离；也可勘察已排除的位置。")
    lines.append(f"{action}地点 · 第 {page}/{pages} 页：")
    for site in available[(page - 1) * 4:page * 4]:
        row, col = divmod(site - 1, 4)
        terrain = run["map"]["terrain_names"][run["map"]["terrains"][site - 1]]
        lines.append(f"{site} 号 · {run['map']['sites'][site - 1]} · 第 {row + 1} 行第 {col + 1} 列 · {terrain}")
    commands = tuple(f"灵宠寻踪 {action} {site} {run['day']}" for site in available[(page - 1) * 4:page * 4])
    reason = _block_reason(ctx, ctx.repo.pet(run["pet_id"]))
    if ctx.now < run.get("updated_at", ctx.now):
        reason = "时间早于上次寻踪，请等待时钟恢复后再操作。"
    if reason:
        lines.append(reason)
        commands = ()
    links = []
    if page > 1:
        links.append(InlineCommand(len(lines) - 1, "上一页", f"灵宠寻踪 地图 {page - 1}"))
    if page < pages:
        links.append(InlineCommand(len(lines) - 1, "下一页", f"灵宠寻踪 地图 {page + 1}"))
    lines.append("本局已付精力；可跨日继续，放弃不退还。")
    links.append(InlineCommand(len(lines) - 1, "放弃本局", f"灵宠寻踪 放弃 {run['day']}"))
    lines.append("伙伴若被派遣或封存，归来或复原后可继续。")
    links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                  InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    return Reply("灵宠寻踪 · 挖掘" if digging else "灵宠寻踪 · 勘察", tuple(lines), commands, tuple(links))


def page(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠寻踪", ("尚未结契，先领养伙伴，再循着线索寻找藏物。",
                                  "三张地点图，两次距离勘察，一次挖掘。"), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = state(ctx)
    if run:
        return _run_page(ctx, run)
    day = _progress(ctx, DAY_KEY)
    ready = day < _day(ctx)
    reason = "尚未选择出战灵宠，请先打开名册。"
    if player.active_pet_id is not None:
        pet = replace(ctx.repo.pet(player.active_pet_id))
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        reason = _block_reason(ctx, pet)
        if not reason and pet.energy < ENERGY:
            reason = f"{pet.name}精力不足，需要 {ENERGY} 点，当前 {pet.energy}。"
    lines = [f"每天开局一次 · 开局精力 {ENERGY} · 今日" + ("可出发。" if ready else "已出发或时钟早于上次出发。"),
             "先凭气息排除一半地点，再选择最多两处勘察，依横竖距离缩小范围，最后挖掘一处。",
             "寻获：灵粮 ×1、原伙伴亲密 +2、羁绊经验 +8；未寻获：仅羁绊经验 +2。",
             "放弃不退款、不增加成长；每局的地图、线索和同行伙伴固定。"]
    for route in ctx.content.tracking_maps.values():
        lines.append(f"{route.name} · {route.description} · 已寻获 {_progress(ctx, 'tracking_found_' + route.id)} 次。")
    lines.append("可回顾最近结束的一局，或查看伙伴的羁绊成长。")
    links = [InlineCommand(len(lines) - 1, "寻踪记录", "灵宠寻踪 记录"),
             InlineCommand(len(lines) - 1, "羁绊成长", "灵宠羁绊")]
    if reason:
        lines.append(reason)
        links.extend((InlineCommand(len(lines) - 1, "查看名册", "灵宠列表"),
                      InlineCommand(len(lines) - 1, "查看行程", "灵宠行程")))
    return Reply("灵宠寻踪", tuple(lines),
                 tuple(f"灵宠寻踪 出发 {route.name}" for route in ctx.content.tracking_maps.values()) if ready and not reason else (), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    last = ctx.repo.latest_tracking_action(ctx.user_id)
    if last:
        _check_time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有一局寻踪，请继续或放弃后再出发。")
    route = named(ctx.content.tracking_maps, name)
    if _progress(ctx, DAY_KEY) >= _day(ctx):
        raise GameError("今天已出发寻踪，或日期早于上次出发，请明日再来。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    if pet.energy < ENERGY:
        raise GameError(f"{pet.name}精力不足，需要 {ENERGY} 点。")
    pet.energy -= ENERGY
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    target = ctx.rng.randint(1, 16)
    run = {"status": "active", "event": "start", "map": route.model_dump(),
           "pet_id": pet.pet_id, "pet_name": pet.name, "target": target,
           "terrain": route.terrains[target - 1], "surveys": [], "day": _day(ctx),
           "started_at": ctx.now}
    _write(ctx, DAY_KEY, _day(ctx))
    return _record(ctx, run, _run_page(ctx, run, prefix=(f"出发寻踪：精力 -{ENERGY}。",)))


def act(ctx: Context, action: str, site: int | None, day: int | None) -> Reply:
    ctx.player()
    run = state(ctx)
    if run is None:
        raise GameError("当前没有正在进行的寻踪，请先出发。")
    _check_time(ctx, run)
    if day is not None and day != run["day"]:
        raise GameError("这是旧局的操作，请重新打开 灵宠寻踪 查看本局。")
    if action == "放弃":
        run.update(status="abandoned", event="abandon")
        return _record(ctx, run, Reply("寻踪结束", (f"已放弃{run['map']['name']}，本局精力不退还。",
                                                   "未获得藏物或成长。"), ("灵宠寻踪",)))
    pet = _partner(ctx, run)
    if action == "勘察":
        if _digging(run):
            raise GameError("勘察已结束，请从候选地点中选择一处挖掘。")
        if any(entry["site"] == site for entry in run["surveys"]):
            raise GameError("已经勘察过该处，请换一个地点。")
        steps = distance(site, run["target"])
        run["surveys"].append({"site": site, "distance": steps})
        run["event"] = "survey"
        return _record(ctx, run, _run_page(ctx, run, prefix=(f"{pet.name}在 {site} 号嗅到踪迹：距藏物 {steps} 步。",)))
    if not _digging(run):
        raise GameError("请先勘察；用完两次机会或只剩一处候选时才能挖掘。")
    if site not in candidates(run):
        raise GameError("该处已被线索排除，请从候选地点中选择。")
    found = site == run["target"]
    if found and "spirit_food" not in ctx.content.items:
        raise GameError("寻踪奖励灵粮暂不可用，本次挖掘未结算。")
    before = bond_levels.current_level(ctx, pet.pet_id)
    gained = 8 if found else 2
    total = bond_levels.add_exp(ctx, pet.pet_id, gained)
    affinity_gain = min(2, 100 - pet.affinity) if found else 0
    if found:
        ctx.repo.add_item(ctx.user_id, "spirit_food", 1)
        pet.affinity += affinity_gain
        for key in ("tracking_found_" + run["map"]["id"], f"tracking_pet_found_{pet.pet_id}"):
            _write(ctx, key, _progress(ctx, key) + 1)
    key = f"tracking_pet_completed_{pet.pet_id}"
    _write(ctx, key, _progress(ctx, key) + 1)
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    run.update(status="finished", event="dig", picked=site, found=found)
    lines = [f"{run['map']['name']} · {pet.name}在 {site} 号挖掘：" + ("寻获藏物！" if found else "未寻获藏物。"),
             f"藏物在 {run['target']} 号 · {run['map']['sites'][run['target'] - 1]}。",
             f"勘察 {len(run['surveys'])}/{SURVEYS} 次 · 最终候选 {len(candidates(run))} 处。",
             f"灵粮 ×1 已入乾坤袋；亲密 +{affinity_gain}（{pet.affinity}/100）。" if found else "本局没有道具或亲密奖励。",
             f"{pet.name}羁绊经验 +{gained} · 累计 {total} · 等级 {before} → {bond_levels.level(total)}。",
             f"该伙伴已完成 {_progress(ctx, key)} 局 · 寻获 {_progress(ctx, f'tracking_pet_found_{pet.pet_id}')} 次。"]
    links = (InlineCommand(4, "查看羁绊", "灵宠羁绊"),)
    return _record(ctx, run, Reply("寻踪结算", tuple(lines), ("灵宠寻踪", "灵宠背包"), links))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_tracking_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply("寻踪记录", ("还没有已结束的寻踪记录。",), ("灵宠寻踪",))
    saved = Reply.from_data(last["reply"])
    return Reply("寻踪记录", saved.lines, ("灵宠寻踪", "灵宠羁绊"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["记录"]:
        return result(ctx)
    if len(parts) == 2 and parts[0] == "出发":
        return start(ctx, parts[1])
    if parts[0] == "地图" and len(parts) in (1, 2):
        run = state(ctx)
        if run is None:
            raise GameError("当前没有正在进行的寻踪，请先出发。")
        return _run_page(ctx, run, quantity(parts[1] if len(parts) == 2 else "1", 4))
    if parts[0] in ("勘察", "挖掘") and len(parts) in (2, 3):
        return act(ctx, parts[0], quantity(parts[1], 16), quantity(parts[2], 99999999) if len(parts) == 3 else None)
    if parts[0] == "放弃" and len(parts) in (1, 2):
        return act(ctx, "放弃", None, quantity(parts[1], 99999999) if len(parts) == 2 else None)
    raise GameError("格式：灵宠寻踪 [出发 地图名|地图 页码|勘察 编号|挖掘 编号|放弃|记录]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx)
    if run:
        return f"寻踪：{run['map']['name']} · 已勘察 {len(run['surveys'])}/{SURVEYS} · 候选 {len(candidates(run))} 处"
    return "寻踪：今日已出发" if _progress(ctx, DAY_KEY) >= _day(ctx) else "寻踪：今日可出发"
