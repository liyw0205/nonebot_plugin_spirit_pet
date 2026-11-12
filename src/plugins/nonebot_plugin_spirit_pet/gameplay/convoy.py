"""Three-stop cargo travel with frozen combat, real supplies and durable receipts."""

from hashlib import sha256

from ..application.context import Context
from ..domain.battle_content import Element
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.time import beijing_day
from . import bond_levels, mastery
from .combat import enemy_fighter, fight
from .fighter_state import pack, unpack
from .loadout import combatant
from .release import released

TITLE = "灵宠护航"
DAY_KEY = "convoy_day"
RULE = {"energy": 10, "food": 1, "cargo": 100, "repair": 25, "heal_percent": 35,
        "guard_attack_percent": 70, "guard_damage": 1, "lead_damage": 6,
        "stones": 60, "clean_cargo": 60, "clean_bonus": 30, "bond": 8}


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
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


def _food(ctx: Context) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'", (ctx.user_id,),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _partner(ctx: Context, run: dict | None = None):
    player = ctx.player()
    target = run["pet_id"] if run else player.active_pet_id
    if target is None:
        raise ctx.missing_pet()
    row = ctx.repo.conn.execute(
        "SELECT name,archived FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, target),
    ).fetchone()
    if row is None:
        raise GameError("原护航伙伴不存在，请撤回本局；不能中途改换伙伴。")
    if released(ctx, target):
        raise GameError(f"{row['name']}已归灵，请撤回本局；不能中途改换伙伴。")
    if row["archived"]:
        raise GameError(f"{row['name']}已封存，请复原后继续护航，或撤回本局。")
    pet = ctx.repo.pet(target)
    ctx.require_idle_pet(pet)
    if run:
        learned = mastery.progress(ctx, target)
        missing = [skill["name"] for skill in run["fighter"]["skills"] if skill["id"] not in learned]
        if missing:
            raise GameError("原护航灵术已遗忘：" + "、".join(missing) + "，请重新学会或撤回本局。")
    return pet


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次护航，请等待时钟恢复；本局进度保留。")


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_convoy_action(user_id or ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _command(run: dict, action: str) -> str:
    return f"{TITLE} {action} 局 {run['run_id']} 步 {run['step']}"


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_convoy_action(ctx.operation_id, ctx.user_id, ctx.now,
                                 {**run, "updated_at": ctx.now}, reply)
    return reply


def _items_text(run: dict, items: dict) -> str:
    return "、".join(f"{run['item_names'][key]}×{count}" for key, count in items.items()) or "无材料"


def _roads_text(run: dict, stop: dict) -> list[str]:
    lines = []
    for index, road in enumerate(stop["roads"], 1):
        enemies = [run["enemies"][key] for key in road["enemies"]]
        detail = "不战斗" if not enemies else "、".join(
            f"{enemy['name']}（气血{enemy['stats']['hp']}、攻击{enemy['stats']['attack']}、"
            f"防御{enemy['stats']['defense']}、速度{enemy['stats']['speed']}）" for enemy in enemies)
        lines.append(f"{index}号 {road['name']} · 路损{road['damage']} · {detail} · 抵达可得{_items_text(run, road['items'])}。")
    return lines


def _rules_text(rule: dict) -> tuple[str, ...]:
    return (f"绕行不战斗，仅扣路损；护卫以{rule['guard_attack_percent']}%攻击作战，货物每回合损{rule['guard_damage']}；"
            f"开路保持攻击，货物每回合损{rule['lead_damage']}。两种战法都另扣路损。",
            f"每站最多补给一次：灵粮×1，货物修复{rule['repair']}，伙伴本局气血恢复上限的{rule['heal_percent']}%。",
            f"三站均存活才发货：灵石{rule['stones']}、所选近道材料、原伙伴羁绊经验{rule['bond']}；"
            f"货物≥{rule['clean_cargo']}另得灵石{rule['clean_bonus']}，实际施法获原灵术熟练度。")


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    rule = run["rule"]
    stop = run["route"]["stops"][run["stop"]]
    unit = run["fighter"]
    lines = [*prefix, f"{run['route']['name']} · 同行{run['pet_name']}（编号{run['pet_id']}）",
             f"第{run['stop'] + 1}/3站 {stop['name']} · 货物{run['cargo']}/{rule['cargo']} · "
             f"伙伴气血{unit['hp']}/{unit['stats']['hp']}。",
             f"已装材料：{_items_text(run, run['items'])}；抵达前不入乾坤袋。",
             *_roads_text(run, stop), *_rules_text(rule)]
    commands = []
    try:
        _time(ctx, run)
        _partner(ctx, run)
    except GameError as exc:
        lines.append(str(exc))
    else:
        commands = [_command(run, "行进 1 绕行"), _command(run, "行进 2 护卫"), _command(run, "行进 2 开路")]
        if not run["supplied"] and _food(ctx) and (run["cargo"] < rule["cargo"] or unit["hp"] < unit["stats"]["hp"]):
            commands.append(_command(run, "补给"))
    lines.append("原伙伴派遣或封存时暂停；归来、复原后可继续。本局气血不改变日常满血战斗。")
    links = [InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
             InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")]
    lines.append(f"本站" + ("已补给" if run["supplied"] else "尚未补给") + f" · 灵粮库存{_food(ctx)}。离线不自动前进；撤回不退成本、不发货。")
    links.extend((InlineCommand(len(lines) - 1, "购买灵粮", "灵宠商店 灵粮"),
                  InlineCommand(len(lines) - 1, "撤回本局", _command(run, "撤回"))))
    return Reply(TITLE, tuple(lines), tuple(commands), tuple(links))


def _route_snapshot(ctx: Context, route) -> dict:
    enemies = {key for stop in route.stops for road in stop.roads for key in road.enemies}
    item_ids = {key for stop in route.stops for road in stop.roads for key in road.items}
    return {"route": route.model_dump(), "rule": dict(RULE),
            "enemies": {key: pack(enemy_fighter(ctx.content.enemies[key], ctx.content.skills)) for key in enemies},
            "item_names": {key: ctx.content.items[key].name for key in item_ids},
            "elements": {key: value.model_dump(mode="json") for key, value in ctx.content.elements.items()},
            "proficiency_per_use": ctx.content.rules.skill_proficiency_per_use}


def preview(ctx: Context, name: str) -> Reply:
    route = named(ctx.content.convoy_routes, name)
    run = _route_snapshot(ctx, route)
    lines = [route.description, f"每日一次 · 出发精力{RULE['energy']}、灵粮{RULE['food']} · 初始货物{RULE['cargo']}。",
             *_rules_text(RULE)]
    for stop in run["route"]["stops"]:
        lines.extend((stop["name"], *_roads_text(run, stop)))
    lines.append("出发后伙伴、装备、灵术、敌手、路况和报酬固定；中途换出战不转移本局。")
    return Reply(TITLE + " · 路线预览", tuple(lines), (f"{TITLE} 出发 {route.name}", TITLE),
                 (InlineCommand(1, "购买灵粮", "灵宠商店 灵粮"),))


def page(ctx: Context) -> Reply:
    run = state(ctx)
    if run:
        return _run_page(ctx, run)
    player = ctx.repo.player(ctx.user_id)
    lines = [f"三站择路护航 · 每日开局一次 · 出发精力{RULE['energy']}、灵粮{RULE['food']}。", *_rules_text(RULE)]
    links = []
    for route in ctx.content.convoy_routes.values():
        lines.append(f"{route.name} · {route.description} · 已抵达{_progress(ctx, 'convoy_done_' + route.id)}次。")
        links.append(InlineCommand(len(lines) - 1, "预览路线", f"{TITLE} 预览 {route.name}"))
    if player is None:
        lines.append("尚未结契，可先预览路线，再领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            pet = _partner(ctx)
            energy = min(100, pet.energy + max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval)
            lines.append(f"当前伙伴{pet.name} · 已抵达{_progress(ctx, f'convoy_pet_done_{pet.pet_id}')}次 · 精力{energy} · 灵粮{_food(ctx)} · 今日"
                         + ("已出发或日期早于上次出发。" if _progress(ctx, DAY_KEY) >= _day(ctx) else "可出发。"))
        except GameError as exc:
            lines.append(str(exc))
            links.append(InlineCommand(len(lines) - 1, "查看名册", "灵宠列表"))
    lines.append("补给从乾坤袋真实扣除灵粮；抵达材料可用于喂养、强化和血脉养成。")
    links.append(InlineCommand(len(lines) - 1, "购买灵粮", "灵宠商店 灵粮"))
    return Reply(TITLE, tuple(lines), (f"{TITLE} 记录", "灵宠背包", "灵宠羁绊"), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    route = named(ctx.content.convoy_routes, name)
    last = ctx.repo.latest_convoy_action(ctx.user_id)
    if last:
        _time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有护航进行中，请继续或撤回原路线。")
    pet = _partner(ctx)
    if _progress(ctx, DAY_KEY) >= _day(ctx):
        raise GameError("今天已出发护航，或日期早于上次出发，请等待下一个北京时间日期。")
    energy = min(100, pet.energy + max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval)
    if energy < RULE["energy"]:
        raise GameError(f"{pet.name}精力不足，护航需要{RULE['energy']}，当前{energy}。")
    if _food(ctx) < RULE["food"]:
        raise GameError("灵粮不足，护航出发需要1份；可在灵宠商店购买。")
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    unit = combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)
    pet.energy -= RULE["energy"]
    ctx.repo.consume_item(ctx.user_id, "spirit_food", RULE["food"])
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    _write(ctx, DAY_KEY, _day(ctx))
    run = {**_route_snapshot(ctx, route), "fighter": pack(unit), "pet_id": pet.pet_id, "pet_name": pet.name,
           "run_id": int(sha256((ctx.user_id + ':' + ctx.operation_id).encode()).hexdigest()[:13], 16) + 1,
           "status": "active", "stop": 0, "step": 1, "cargo": RULE["cargo"], "supplied": False,
           "items": {}, "history": [], "started_at": ctx.now, "updated_at": ctx.now}
    return _record(ctx, run, _run_page(ctx, run, (f"出发护航：精力-{RULE['energy']}、灵粮-{RULE['food']}。",)))


def _finish(ctx: Context, run: dict, status: str, reason: str) -> Reply:
    run["status"] = status
    lines = [f"{run['route']['name']} · 原伙伴{run['pet_name']} · {reason}",
             f"已走{run['stop']}/3站 · 剩余货物{run['cargo']}/{run['rule']['cargo']} · 伙伴气血{run['fighter']['hp']}。"]
    for entry in run["history"]:
        lines.append(entry["text"])
    if status == "arrived":
        pet = _partner(ctx, run)
        if any(key not in ctx.content.items for key in run["items"]):
            raise GameError("护航材料定义暂不可用，本次抵达未结算，请稍后重试。")
        for key, count in run["items"].items():
            ctx.repo.add_item(ctx.user_id, key, count)
        rule = run["rule"]
        stones = rule["stones"] + (rule["clean_bonus"] if run["cargo"] >= rule["clean_cargo"] else 0)
        ctx.player().stones += stones
        total = bond_levels.add_exp(ctx, pet.pet_id, rule["bond"])
        lines.append(f"抵达入袋：灵石+{stones} · {_items_text(run, run['items'])}；"
                     f"{pet.name}羁绊经验+{rule['bond']}（累计{total}）。")
        for key, count in run["fighter"]["skill_uses"].items():
            if count:
                level, proficiency, upgraded = mastery.study(ctx, pet.pet_id, key, count * run["proficiency_per_use"])
                skill_name = next(skill["name"] for skill in run["fighter"]["skills"] if skill["id"] == key)
                lines.append(f"{skill_name}实际施法{count}次 · 现{level}级 · 熟练度{proficiency}。")
        for key in ("convoy_done_" + run["route"]["id"], f"convoy_pet_done_{pet.pet_id}"):
            _write(ctx, key, _progress(ctx, key) + 1)
        ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    else:
        lines.append("本局不发货物、灵石或成长；已付精力、灵粮和今日名额不退。")
    return _record(ctx, run, Reply(TITLE + " · " + {"arrived": "抵达", "failed": "败退", "abandoned": "撤回"}[status],
                                  tuple(lines), (TITLE, "灵宠背包", "灵宠羁绊"),
                                  (InlineCommand(1, "查看原伙伴灵术", f"灵宠技能 伙伴 {run['pet_id']}"),)))


def act(ctx: Context, action: str, road_number: int | None, strategy: str | None,
        guard: tuple[int, int] | None) -> Reply:
    ctx.player()
    run = state(ctx)
    if run is None:
        raise GameError("当前没有护航，请先出发。")
    _time(ctx, run)
    if guard is not None and guard != (run["run_id"], run["step"]):
        raise GameError("这是旧局或旧步骤，请重新打开灵宠护航查看当前路线。")
    if action == "撤回":
        return _finish(ctx, run, "abandoned", "已主动撤回。")
    _partner(ctx, run)
    rule = run["rule"]
    if action == "补给":
        if run["supplied"]:
            raise GameError("本站已经补给过，请行进到下一站。")
        unit = run["fighter"]
        if run["cargo"] >= rule["cargo"] and unit["hp"] >= unit["stats"]["hp"]:
            raise GameError("货物和伙伴气血已满，不需要补给。")
        if not _food(ctx):
            raise GameError("灵粮不足，补给需要1份；本局进度保留。")
        ctx.repo.consume_item(ctx.user_id, "spirit_food", 1)
        run["cargo"] = min(rule["cargo"], run["cargo"] + rule["repair"])
        unit["hp"] = min(unit["stats"]["hp"], unit["hp"] + max(1, unit["stats"]["hp"] * rule["heal_percent"] // 100))
        run["supplied"] = True
        run["step"] += 1
        text = f"{run['route']['stops'][run['stop']]['name']}补给：灵粮-1，货物现{run['cargo']}、伙伴气血现{unit['hp']}。"
        run["history"].append({"action": "supply", "text": text})
        return _record(ctx, run, _run_page(ctx, run, (text,)))
    road = run["route"]["stops"][run["stop"]]["roads"][road_number - 1]
    if (not road["enemies"] and strategy != "绕行") or (road["enemies"] and strategy not in ("护卫", "开路")):
        raise GameError("缓道请选绕行，近道请选护卫或开路。")
    rounds = 0
    won = True
    unit = unpack(run["fighter"])
    history = ()
    if road["enemies"]:
        enemies = [unpack(run["enemies"][key]) for key in road["enemies"]]
        original_attack = unit.stats.attack
        if strategy == "护卫":
            unit.stats = unit.stats.model_copy(update={"attack": max(1, original_attack * rule["guard_attack_percent"] // 100)})
        battle = fight([unit], enemies, ctx.rng, {key: Element.model_validate(value) for key, value in run["elements"].items()})
        unit.stats = unit.stats.model_copy(update={"attack": original_attack})
        rounds = battle.rounds
        won = battle.winner == 0
        history = battle.history or battle.lines
    damage = road["damage"] + rounds * (rule["guard_damage"] if strategy == "护卫" else rule["lead_damage"])
    run["cargo"] = max(0, run["cargo"] - damage)
    run["fighter"] = pack(unit)
    run["stop"] += 1
    run["step"] += 1
    run["supplied"] = False
    text = f"第{run['stop']}站 {road['name']} · {strategy} · {rounds}回合 · " + ("通过" if won else "未战胜守敌") + f" · 货物-{damage}、伙伴气血{unit.hp}。"
    run["history"].append({"action": "travel", "road": road_number, "strategy": strategy,
                           "rounds": rounds, "won": won, "damage": damage, "battle": list(history), "text": text})
    if not won or unit.hp <= 0 or run["cargo"] <= 0:
        return _finish(ctx, run, "failed", "伙伴败退，护航中止。" if not won or unit.hp <= 0 else "货物损毁，护航中止。")
    for key, count in road["items"].items():
        run["items"][key] = run["items"].get(key, 0) + count
    if run["stop"] == len(run["route"]["stops"]):
        return _finish(ctx, run, "arrived", "货物平安抵达。")
    return _record(ctx, run, _run_page(ctx, run, (text,)))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_convoy_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply(TITLE + " · 记录", ("还没有结束的护航记录。",), (TITLE,))
    saved = Reply.from_data(last["reply"])
    return Reply(TITLE + " · 记录", saved.lines, (TITLE, "灵宠背包", "灵宠羁绊"), saved.inline_commands)


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["记录"]:
        return result(ctx)
    if len(parts) == 2 and parts[0] in ("预览", "出发"):
        return preview(ctx, parts[1]) if parts[0] == "预览" else start(ctx, parts[1])
    guard = None
    if "局" in parts:
        at = parts.index("局")
        if len(parts) != at + 4 or parts[at + 2] != "步":
            raise GameError("局步格式：局 编号 步 编号。")
        guard = (quantity(parts[at + 1], 9999999999999999), quantity(parts[at + 3], 99))
        parts = parts[:at]
    if len(parts) == 1 and parts[0] in ("补给", "撤回"):
        return act(ctx, parts[0], None, None, guard)
    if len(parts) == 3 and parts[0] == "行进":
        return act(ctx, "行进", quantity(parts[1], 2), parts[2], guard)
    raise GameError("格式：灵宠护航 [预览 路线|出发 路线|行进 路号 绕行/护卫/开路|补给|撤回|记录]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx, user_id)
    if run:
        return f"护航：{run['route']['name']} · 第{run['stop'] + 1}/3站 · 货物{run['cargo']}"
    return "护航：今日已出发" if _progress(ctx, DAY_KEY, user_id) >= _day(ctx) else "护航：三站择路，今日可出发"
