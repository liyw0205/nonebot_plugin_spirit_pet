"""Six adjacent-lane decisions with a fixed stamina budget and shared play quota."""

from hashlib import sha256

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.play_course_content import BASE_STAMINA, MAX_STAMINA, TILE_COST
from ..domain.play_game_content import PlayGame
from ..utils.arguments import quantity
from ..utils.table import table
from . import play_games
from .combat import pet_stats

TITLE = "灵宠跃障"
ENERGY = 8
LANES = ("左路", "中路", "右路")
TILES = {"fruit": "灵果", "meadow": "草坪", "low": "矮栏", "high": "高栏"}


def state(ctx: Context) -> dict | None:
    last = ctx.repo.latest_play_course_action(ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _course(ctx: Context, name: str):
    course = ctx.content.play_courses.get(name)
    if course is None:
        course = next((c for c in ctx.content.play_courses.values() if c.name == name), None)
    if course is None:
        raise GameError("没有这条跃障赛道，可选：" + "、".join(c.name for c in ctx.content.play_courses.values()) + "。")
    return course


def _energy(ctx: Context, pet) -> int:
    return min(100, pet.energy + max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval)


def _partner(ctx: Context, run: dict | None = None):
    owner = ctx.player()
    target = run["pet_id"] if run else owner.active_pet_id
    if target is None:
        raise ctx.missing_pet()
    row = ctx.repo.conn.execute(
        "SELECT name,archived FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, target),
    ).fetchone()
    if row is None:
        raise GameError("原跃障伙伴不存在，请退出本局；不能中途改换伙伴。")
    from .release import released
    if released(ctx, target):
        raise GameError(f"{row['name']}已归灵，请退出本局；不能中途改换伙伴。")
    if row["archived"]:
        raise GameError(f"{row['name']}已封存，请复原后继续跃障，或退出本局。")
    pet = ctx.repo.pet(target)
    ctx.require_idle_pet(pet)
    return pet


def _map(course: dict) -> tuple[str, ...]:
    return table(("段", *LANES), ((index, *(TILES[tile] for tile in row))
                                for index, row in enumerate(course["rows"], 1)))


def _command(run: dict, action: str) -> str:
    return f"{TITLE} {action} 局 {run['run_id']} 步 {len(run['history']) + 1}"


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_play_course_action(ctx.operation_id, ctx.user_id, ctx.now,
                                      {**run, "updated_at": ctx.now}, reply)
    return reply


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次跃障，请等待时钟恢复后再操作；赛道进度保留。")


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    index = len(run["history"])
    lines = [*prefix, f"{run['course']['name']} · 同行 {run['pet_name']}（编号 {run['pet_id']}）。",
             f"已过 {index}/6 段 · 当前{LANES[run['lane']]} · 耐力 {run['stamina']}/{run['rules']['maximum']} · 已采灵果 {run['fruit']}。",
             "每段最多换到相邻一路；采果耐力-1，矮栏-1，高栏-2，草坪+2（不超过上限）。",
             *_map(run["course"])]
    commands = []
    try:
        _time(ctx, run)
        _partner(ctx, run)
    except GameError as exc:
        lines.append(str(exc))
    else:
        lines.append(f"第 {index + 1} 段可达路线：")
        for lane, tile in enumerate(run["course"]["rows"][index]):
            if abs(lane - run["lane"]) > 1:
                continue
            cost = run["rules"]["costs"][tile]
            after = min(run["rules"]["maximum"], run["stamina"] - cost)
            effect = "耐力不足，将失手结束" if after < 0 else f"耐力将为 {after}"
            lines.append(f"{LANES[lane]} · {TILES[tile]} · {effect}" + ("，采果得分 +15。" if tile == "fruit" else "。"))
            commands.append(_command(run, "前进 " + LANES[lane]))
    lines.append("已付开局精力；中途离线不自动结算，退出不退费、不获成长或精通。")
    links = [InlineCommand(len(lines) - 1, "退出本局", _command(run, "退出"))]
    lines.append("原伙伴派遣或封存时暂停；归来或复原后可继续。")
    links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                  InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    return Reply(TITLE + " · 第" + str(index + 1) + "段", tuple(lines), tuple(commands), tuple(links))


def page(ctx: Context) -> Reply:
    run = state(ctx)
    if run:
        return _run_page(ctx, run)
    lines = ["六段三路赛道，从中路起步；相邻换道、采果与耐力恢复各有取舍。",
             "开局支付8精力，与三项嬉戏共用每日一局；精彩沿反应试炼发亲密、灵粮和羁绊，累计其精通。"]
    links = []
    for course in ctx.content.play_courses.values():
        lines.append(f"{course.name}：{course.description}")
        links.append(InlineCommand(len(lines) - 1, "预览赛道", f"{TITLE} 预览 {course.name}"))
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            play_games.require_day(ctx)
        except GameError as exc:
            lines.append(str(exc))
    return Reply(TITLE, tuple(lines), (TITLE + " 记录", "灵宠嬉戏", "我的灵宠"), tuple(links))


def preview(ctx: Context, name: str) -> Reply:
    course = _course(ctx, name)
    game = ctx.content.play_games["reaction"]
    lines = [course.description, *_map(course.model_dump()),
             "从中路起步，每段最多换到相邻一路。采果/矮栏耐力-1，高栏-2，草坪+2，上限6。",
             "初始耐力=4+防御每30点加1（最多加2），防御在出发时固定。",
             "过一段得10分，采一果另得15分，最高120；90分精彩、50分寻常，其余失手。",
             f"完成：亲密寻常+2、精彩+{3 + game.great_bonus}（上限100），羁绊经验+6，反应试炼精通+1。",
             "耐力不足立即失手：亲密+1、羁绊经验+6、精通+1，无道具；主动退出无成长。"]
    rewards = "、".join(f"{ctx.content.items[k].name}{v}" for k, v in game.great_items.items())
    lines.append("精彩道具：" + (rewards or "无") + "。")
    commands = []
    links = []
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            pet = _partner(ctx)
            defense = pet_stats(pet, ctx.content).defense
            lines.append(f"当前伙伴 {pet.name}（编号 {pet.pet_id}）· 可用精力 {_energy(ctx, pet)} · 防御 {defense} · 初始耐力 {BASE_STAMINA + min(2, defense // 30)}。")
            if state(ctx):
                raise GameError("已有跃障进行中，请继续或退出原赛道。")
            play_games.require_day(ctx)
            if _energy(ctx, pet) < ENERGY:
                raise GameError(f"{pet.name}精力不足：当前 {_energy(ctx, pet)}，开局需要 {ENERGY}。")
        except GameError as exc:
            lines.append(str(exc))
        else:
            commands.append(f"{TITLE} 出发 {course.name}")
    return Reply(TITLE + " · " + course.name, tuple(lines), (*commands, TITLE, "我的灵宠"), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    course = _course(ctx, name)
    last = ctx.repo.latest_play_course_action(ctx.user_id)
    if last:
        _time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有跃障进行中，请继续或退出原赛道。")
    play_games.require_day(ctx)
    pet = _partner(ctx)
    if _energy(ctx, pet) < ENERGY:
        raise GameError(f"{pet.name}精力不足：当前 {_energy(ctx, pet)}，开局需要 {ENERGY}。")
    from ..utils.energy import restore_energy
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    defense = pet_stats(pet, ctx.content).defense
    run = {"status": "active", "run_id": sha256(ctx.operation_id.encode()).hexdigest()[:16],
           "course": course.model_dump(), "game": ctx.content.play_games["reaction"].model_dump(),
           "pet_id": pet.pet_id, "pet_name": pet.name, "defense": defense,
           "rules": {"costs": TILE_COST.copy(), "maximum": MAX_STAMINA, "energy": ENERGY},
           "stamina": BASE_STAMINA + min(2, defense // 30), "lane": 1, "fruit": 0,
           "history": [], "started_at": ctx.now, "updated_at": ctx.now}
    pet.energy -= ENERGY
    play_games.reserve_day(ctx, ctx.content.play_games["reaction"])
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    return _record(ctx, run, _run_page(ctx, run, (f"{pet.name}精力 -{ENERGY}；本局占用今日嬉戏名额。",)))


def _active(ctx: Context, guard: list[str]) -> dict:
    ctx.player()
    last = ctx.repo.latest_play_course_action(ctx.user_id)
    if not last:
        raise GameError("当前没有跃障进行中，请先选择赛道出发。")
    run = last["snapshot"]
    if guard:
        if len(guard) != 4 or guard[0] != "局" or guard[2] != "步":
            raise GameError("局步参数格式：局 <局号> 步 <段数>。")
        step = quantity(guard[3], 7)
        if guard[1] != run["run_id"]:
            raise GameError("这是另一局跃障的旧入口，请查看当前赛道。")
        if step != len(run["history"]) + 1:
            raise GameError("这一步跃障已经执行，请查看当前段的路线。")
    if run["status"] != "active":
        raise GameError("该局跃障已结束，请查看记录或选择新赛道。")
    _time(ctx, run)
    return run


def advance(ctx: Context, lane_name: str, guard: list[str]) -> Reply:
    if lane_name not in LANES:
        raise GameError("路线可选：左路、中路、右路。")
    run = _active(ctx, guard)
    pet = _partner(ctx, run)
    lane = LANES.index(lane_name)
    if abs(lane - run["lane"]) > 1:
        raise GameError(f"当前位置是{LANES[run['lane']]}，每段只能留在原路或换到相邻一路。")
    tile = run["course"]["rows"][len(run["history"])][lane]
    cost = run["rules"]["costs"][tile]
    success = run["stamina"] >= cost
    run["history"].append({"lane": lane, "tile": tile, "before": run["stamina"], "success": success})
    run["lane"] = lane
    if success:
        run["stamina"] = min(run["rules"]["maximum"], run["stamina"] - cost)
        run["fruit"] += tile == "fruit"
    if success and len(run["history"]) < 6:
        return _record(ctx, run, _run_page(ctx, run, (f"通过{lane_name}{TILES[tile]}，耐力 {run['stamina']}。",)))
    run["status"] = "finished" if success else "failed"
    run["score"] = min(120, 60 + run["fruit"] * 15) if success else 0
    game = PlayGame.model_validate(run["game"])
    reward = play_games.settle(ctx, pet, game, run["score"])
    lines = [f"{run['course']['name']} · {run['pet_name']}（编号 {run['pet_id']}）",
             f"顺利过完6段，采果 {run['fruit']}，得分 {run['score']}/120。" if success else
             f"第{len(run['history'])}段{lane_name}{TILES[tile]}需要耐力{cost}，当前{run['stamina']}，本局失手。",
             *reward.lines, "原伙伴羁绊经验 +6；奖励沿反应试炼，未另发赛道奖励。"]
    links = (InlineCommand(len(lines) - 1, "查看羁绊", "灵宠羁绊"),)
    return _record(ctx, run, Reply("跃障结算", tuple(lines), (TITLE, "灵宠嬉戏 记录", "灵宠背包"), links))


def quit_run(ctx: Context, guard: list[str]) -> Reply:
    run = _active(ctx, guard)
    run["status"] = "quit"
    return _record(ctx, run, Reply("跃障退出", (f"已退出{run['course']['name']}，保留{len(run['history'])}段路线回顾。",
                                                   "不退开局精力，不增加亲密、羁绊、精通或道具；当日名额不恢复。"),
                                  (TITLE, TITLE + " 记录", "灵宠嬉戏")))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_play_course_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply(TITLE + "记录", ("还没有结束的跃障记录。",), (TITLE,))
    run = last["snapshot"]
    reply = Reply.from_data(last["reply"])
    route = " → ".join(LANES[entry["lane"]] + TILES[entry["tile"]] for entry in run["history"])
    return Reply(TITLE + "记录", (*reply.lines, "本局路线：" + (route or "未前进") + "。"),
                 (TITLE, "灵宠嬉戏 记录", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["记录"]:
        return result(ctx)
    if len(parts) == 2 and parts[0] in ("预览", "出发"):
        return preview(ctx, parts[1]) if parts[0] == "预览" else start(ctx, parts[1])
    if len(parts) >= 2 and parts[0] == "前进":
        return advance(ctx, parts[1], parts[2:])
    if parts[0] == "退出":
        return quit_run(ctx, parts[1:])
    raise GameError("格式：灵宠跃障 [预览/出发 赛道名 | 前进 左路/中路/右路 | 退出 | 记录]。")
