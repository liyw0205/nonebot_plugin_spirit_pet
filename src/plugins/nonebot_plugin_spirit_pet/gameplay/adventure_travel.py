"""A paid, resumable route through unresolved adventure echoes."""

from datetime import datetime
from hashlib import sha256

from ..application.context import Context
from ..domain.content import Encounter
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.time import BEIJING, cooldown_left
from . import echoes
from .quests import advance

TITLE = "灵宠山海远行"
ENERGY_PER_SCENE = 25


def state(ctx: Context) -> dict | None:
    last = ctx.repo.latest_adventure_travel_action(ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _echo_claimed(ctx: Context, user_id: str, encounter_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, echoes.claim_id(encounter_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def _unresolved(ctx: Context, route, user_id: str | None) -> list[Encounter]:
    return [
        ctx.content.encounters[encounter_id]
        for encounter_id in route.encounters
        if user_id is None or not _echo_claimed(ctx, user_id, encounter_id)
    ]


def _route(ctx: Context, name: str):
    return named(ctx.content.exploration_routes, name)


def _realm_index(ctx: Context, realm_id: str) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == realm_id)


def _partner(ctx: Context, run: dict | None = None, *, refresh_energy: bool = True):
    player = ctx.player()
    pet_id = run["pet_id"] if run else player.active_pet_id
    if pet_id is None:
        raise ctx.missing_pet()
    row = ctx.repo.conn.execute(
        "SELECT name, archived FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("原同行伙伴不存在；可退出当前行程。")
    from .release import released
    if released(ctx, pet_id):
        raise GameError(f"{row['name']}已归灵；可退出当前行程。")
    if row["archived"]:
        raise GameError(f"{row['name']}已封存，请复原后继续，或退出当前行程。")
    pet = ctx.repo.pet(pet_id)
    if refresh_energy:
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    ctx.require_idle_pet(pet)
    return pet


def _available_energy(ctx: Context, pet) -> int:
    restored = max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval
    return min(100, pet.energy + restored)


def _grant_reward(ctx: Context, run: dict, pet, reward) -> list[str]:
    player = ctx.player()
    exp = ctx.rng.randint(reward.exp.minimum, reward.exp.maximum)
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    if reward.exp.maximum:
        pet.exp += exp
    player.stones += stones
    lines = [f"修为 +{exp}，灵石 +{stones}"]
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        ctx.repo.add_item(player.user_id, item_id, amount)
        if amount:
            lines.append(f"{run['items'][item_id]['name']} +{amount}")
    return lines


def _check_rewards(ctx: Context, run: dict) -> None:
    for item_id, frozen in run["items"].items():
        current = ctx.content.items.get(item_id)
        if current is None or current.kind != frozen["kind"]:
            raise GameError(f"{frozen['name']}当前不可结算，请稍后重试；行程保留。")


def _command(run: dict, action: str, step: int | None = None) -> str:
    guard = f"局 {run['run_id']} 段 {step or len(run['history']) + 1}"
    return f"{TITLE} {action} {guard}"


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_adventure_travel_action(
        ctx.operation_id, ctx.user_id, ctx.now, {**run, "updated_at": ctx.now}, reply,
    )
    return reply


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次远行，请等待时钟恢复后再继续；行程保留。")


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    index = len(run["history"])
    scene = run["scenes"][index]
    lines = [
        *prefix,
        f"{run['route']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）。",
        f"已行 {index}/{len(run['scenes'])} 处 · 已支付精力 {run['energy']}。",
        f"奇闻：{scene['name']} · {scene['text']}",
    ]
    commands = []
    try:
        _time(ctx, run)
        _partner(ctx, run, refresh_energy=False)
    except GameError as exc:
        lines.append(str(exc))
    else:
        lines.append("选择一项回响，结算本处奇闻并继续：")
        for option in scene["options"]:
            lines.append(f"{option['label']}：{option['text']}")
            reward = option["reward"]
            lines.append(_reward_summary(run, reward))
            commands.append(_command(run, "选择", index + 1) + f" {option['id']}")
    lines.append("精力在启程时按待走场景数一次付清；退出不退款，已完成场景不会重复结算。")
    links = [InlineCommand(len(lines) - 1, "退出行程", _command(run, "退出", index + 1))]
    lines.append("行程绑定原伙伴；封存或派遣时暂停，复原或归来后可继续。")
    links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                  InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    return Reply(f"{TITLE} · 第{index + 1}处", tuple(lines), tuple(commands), tuple(links))


def catalog(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    run = state(ctx) if player else None
    lines = ["沿既有历练路线探访尚未回响的奇闻，每处择一回响；行程跨日与重启保留。"]
    links = []
    for route in ctx.content.exploration_routes.values():
        unresolved = _unresolved(ctx, route, player.user_id if player else None)
        lines.append(f"{route.name}：{route.description} · 可走 {len(unresolved)} 处 · 每处精力 {ENERGY_PER_SCENE}")
        links.append(InlineCommand(len(lines) - 1, "查看路线", f"{TITLE} 预览 {route.name}"))
    if run:
        lines.append(f"当前行程：{run['route']['name']}，已行 {len(run['history'])}/{len(run['scenes'])} 处。")
        links.append(InlineCommand(len(lines) - 1, "继续行程", TITLE))
    elif player is None:
        lines.append("尚未结契，先完成领养，再与伙伴同行。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), (f"{TITLE} 记录", "灵宠历练", "灵宠奇闻"), tuple(links))


def preview(ctx: Context, name: str) -> Reply:
    route = _route(ctx, name)
    player = ctx.repo.player(ctx.user_id)
    user_id = player.user_id if player else None
    scenes = _unresolved(ctx, route, user_id)
    realm = ctx.content.realms[_realm_index(ctx, route.min_realm)].name
    lines = [route.description, f"{realm}起 · 路线奇闻 {len(route.encounters)} 处 · 每处精力 {ENERGY_PER_SCENE}。",
             "启程时一次付清待走场景精力并开始历练冷却；每处获得原奇闻奖励和所选回响奖励。"]
    for encounter in (ctx.content.encounters[key] for key in route.encounters):
        state_label = "待走" if encounter in scenes else "已回响"
        choices = "、".join(option.label for option in encounter.options)
        lines.append(f"{encounter.name} · {state_label} · 可选：{choices}")
        for option in encounter.options:
            lines.append(f"{option.label}：" + _reward_summary(
                {"items": {key: value.model_dump() for key, value in ctx.content.items.items()}},
                option.reward.model_dump(),
            ))
    if player is None:
        lines.append("尚未结契；结契后可查看伙伴资格并启程。")
        links = (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),)
        commands = ()
    else:
        run = state(ctx)
        if run:
            lines.append("已有行程进行中，先完成或退出当前行程。")
            commands = (TITLE,)
        elif not scenes:
            lines.append("这条路线的奇闻都已回响，没有待走场景。")
            commands = ("灵宠奇闻", TITLE)
        else:
            energy = ENERGY_PER_SCENE * len(scenes)
            try:
                pet = _partner(ctx, refresh_energy=False)
                minimum = _realm_index(ctx, route.min_realm)
                if pet.realm < minimum:
                    raise GameError(f"{route.name}需要{ctx.content.realms[minimum].name}境界。")
                available = _available_energy(ctx, pet)
                lines.append(f"当前伙伴：{pet.name}（编号 {pet.pet_id}）· 可用精力 {available} · 启程需 {energy}。")
                remaining = cooldown_left(
                    player.last_explore, ctx.now, ctx.config.spirit_pet_explore_cooldown,
                )
                if remaining:
                    raise GameError(f"{pet.name}尚需调息 {remaining} 秒。")
                if available < energy:
                    raise GameError(f"{pet.name}精力不足，需要 {energy} 点。")
                commands = (f"{TITLE} 启程 {route.name}",)
            except GameError as exc:
                lines.append(str(exc))
                commands = ()
        links = ()
    return Reply(f"{TITLE} · {route.name}", tuple(lines), commands, links)


def start(ctx: Context, name: str) -> Reply:
    player = ctx.player()
    route = _route(ctx, name)
    last = ctx.repo.latest_adventure_travel_action(ctx.user_id)
    if last:
        _time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有山海远行进行中，请继续或退出当前行程。")
    pet = _partner(ctx)
    minimum = _realm_index(ctx, route.min_realm)
    if pet.realm < minimum:
        raise GameError(f"{route.name}需要{ctx.content.realms[minimum].name}境界。")
    scenes = _unresolved(ctx, route, player.user_id)
    if not scenes:
        raise GameError("这条路线的奇闻都已回响，没有待走场景。")
    energy = ENERGY_PER_SCENE * len(scenes)
    ctx.check_action(player, pet, "explore", energy, ctx.config.spirit_pet_explore_cooldown)
    run = {
        "status": "active",
        "run_id": sha256(ctx.operation_id.encode()).hexdigest()[:16],
        "route": route.model_dump(),
        "scenes": [scene.model_dump() for scene in scenes],
        "items": {
            item_id: ctx.content.items[item_id].model_dump()
            for scene in scenes for reward in (scene.reward, *(option.reward for option in scene.options))
            for item_id in reward.items
        },
        "pet_id": pet.pet_id,
        "pet_name": pet.name,
        "energy": energy,
        "history": [],
        "started_at": ctx.now,
        "updated_at": ctx.now,
    }
    pet.energy -= energy
    player.last_explore = ctx.now
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    advance(ctx, "explore")
    return _record(ctx, run, _run_page(ctx, run, (f"{pet.name}精力 -{energy}；路线冷却已开始。",)))


def _active(ctx: Context, guard: list[str]) -> dict:
    ctx.player()
    last = ctx.repo.latest_adventure_travel_action(ctx.user_id)
    if not last:
        raise GameError("当前没有山海远行，请先查看路线并启程。")
    run = last["snapshot"]
    _time(ctx, run)
    if len(guard) != 4 or guard[0] != "局" or guard[2] != "段":
        raise GameError("局段参数格式：局 <局号> 段 <处数>。")
    step = quantity(guard[3], 5)
    if guard[1] != run["run_id"]:
        raise GameError("这是另一趟山海远行的旧入口，请查看当前行程。")
    if step != len(run["history"]) + 1:
        raise GameError("这处奇闻已经处理，请查看当前行程。")
    if run["status"] != "active":
        raise GameError("该趟山海远行已结束，请查看记录或选择新路线。")
    return run


def choose(ctx: Context, guard: list[str], option_id: str) -> Reply:
    run = _active(ctx, guard)
    pet = _partner(ctx, run)
    index = len(run["history"])
    encounter = Encounter.model_validate(run["scenes"][index])
    option = next((entry for entry in encounter.options if entry.id == option_id or entry.label == option_id), None)
    if option is None:
        labels = "、".join(entry.label for entry in encounter.options)
        raise GameError(f"{encounter.name}没有这个选项；可选：{labels}。")
    if _echo_claimed(ctx, ctx.user_id, encounter.id):
        raise GameError(f"{encounter.name}已回响，请退出当前行程；未完成处不发奖。")
    _check_rewards(ctx, run)

    discovered = ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
        (ctx.user_id, encounter.id, ctx.now),
    ).rowcount == 1
    reward_lines = _grant_reward(ctx, run, pet, encounter.reward)
    reward_lines.extend(_grant_reward(ctx, run, pet, option.reward))
    if encounter.reward.exp.maximum or option.reward.exp.maximum:
        ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    option_index = encounter.options.index(option) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (ctx.user_id, echoes.claim_id(encounter.id), option_index),
    )
    run["history"].append({
        "encounter_id": encounter.id,
        "encounter_name": encounter.name,
        "option_id": option.id,
        "option_label": option.label,
        "discovered": discovered,
        "rewards": reward_lines,
    })
    if len(run["history"]) == len(run["scenes"]):
        run["status"] = "finished"
        lines = [f"{run['route']['name']} · 同行 {run['pet_name']}。", "本趟行程已完成："]
        for entry in run["history"]:
            lines.append(f"{entry['encounter_name']} · {entry['option_label']}" + (" · 新发现" if entry["discovered"] else ""))
            lines.extend(entry["rewards"])
        reply = Reply("山海远行完成", tuple(lines), (TITLE, "灵宠奇闻", "灵宠奇闻奖励", "灵宠背包"))
    else:
        lines = [f"{encounter.name} · {option.label}", option.text]
        if discovered:
            lines.append("新奇闻已收入灵宠奇闻。")
        lines.extend(reward_lines)
        reply = _run_page(ctx, run, tuple(lines))
    return _record(ctx, run, reply)


def _reward_summary(run: dict, reward: dict) -> str:
    def interval(bounds):
        return str(bounds["minimum"]) if bounds["minimum"] == bounds["maximum"] else f"{bounds['minimum']}-{bounds['maximum']}"

    parts = [f"灵石 {interval(reward['stones'])}"]
    if reward["exp"]["maximum"]:
        parts.append(f"修为 {interval(reward['exp'])}")
    parts.extend(f"{run['items'][key]['name']} {interval(bounds)}" for key, bounds in reward["items"].items())
    return " · ".join(parts)


def quit_run(ctx: Context, guard: list[str]) -> Reply:
    run = _active(ctx, guard)
    run["status"] = "abandoned"
    return _record(ctx, run, Reply("山海远行已止", (
        f"{run['route']['name']} · 已完成 {len(run['history'])}/{len(run['scenes'])} 处。",
        "已支付精力不退还；已完成的奇闻和回响奖励保留，未完成场景不结算。",
    ), (TITLE, "灵宠奇闻", "灵宠历练")))


def record(ctx: Context) -> Reply:
    last = ctx.repo.latest_adventure_travel_action(ctx.user_id)
    if not last:
        return Reply(TITLE + "记录", ("尚无山海远行记录。",), (TITLE, "灵宠历练"))
    run = last["snapshot"]
    status = {"active": "进行中", "finished": "已完成", "abandoned": "已退出"}[run["status"]]
    lines = [f"{run['route']['name']} · {status} · 同行 {run['pet_name']}（编号 {run['pet_id']}）。",
             f"已行 {len(run['history'])}/{len(run['scenes'])} 处 · 支付精力 {run['energy']} · 最近更新 {datetime.fromtimestamp(run['updated_at'], BEIJING).strftime('%Y-%m-%d %H:%M')}。"]
    for entry in run["history"]:
        lines.append(f"{entry['encounter_name']} · {entry['option_label']}" + (" · 新发现" if entry["discovered"] else ""))
        lines.extend(entry["rewards"])
    commands = [TITLE, "灵宠奇闻"]
    if run["status"] == "active":
        commands.insert(0, _command(run, "退出", len(run["history"]) + 1))
    return Reply(TITLE + "记录", tuple(lines), tuple(commands))


def locked_encounter(ctx: Context, user_id: str, encounter_id: str) -> bool:
    last = ctx.repo.latest_adventure_travel_action(user_id)
    if not last or last["snapshot"]["status"] != "active":
        return False
    run = last["snapshot"]
    completed = {entry["encounter_id"] for entry in run["history"]}
    return encounter_id not in completed and any(
        scene["id"] == encounter_id for scene in run["scenes"]
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        run = state(ctx)
        return _run_page(ctx, run) if run else catalog(ctx)
    if parts[0] == "预览" and len(parts) == 2:
        return preview(ctx, parts[1])
    if parts[0] == "启程" and len(parts) == 2:
        return start(ctx, parts[1])
    if parts[0] == "记录" and len(parts) == 1:
        return record(ctx)
    if parts[0] == "选择" and len(parts) == 6:
        return choose(ctx, parts[1:5], parts[5])
    if parts[0] == "退出" and len(parts) == 5:
        return quit_run(ctx, parts[1:5])
    if len(parts) == 1:
        return preview(ctx, parts[0])
    raise GameError(
        f"格式：{TITLE} [路线名|预览 路线名|启程 路线名|记录|选择 局 局号 段 处数 选项|退出 局 局号 段 处数]。"
    )
