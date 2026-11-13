"""Three-stage pill blending with frozen recipes and permanent action receipts."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import beijing_day
from . import alchemy, counters

TITLE = "灵宠丹炉"
DAY_KEY = "pill_furnace_day"
RULE = {"stability": 5, "capacity": 6, "stress": [0, 1, 1], "single": 3, "double": 6,
        "moves": {"温养": [1, 0], "催灵": [3, -2], "调和": [0, 2]}}
STAGES = ("化材", "凝液", "结丹")


def _day(ctx: Context) -> int:
    return int(beijing_day(ctx.now).replace("-", ""))


def _used_day(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, DAY_KEY),
    ).fetchone()
    return int(row["progress"]) if row else 0


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_furnace_action(user_id or ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_furnace_action(ctx.operation_id, ctx.user_id, ctx.now,
                                  {**run, "updated_at": ctx.now}, reply)
    return reply


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次丹炉操作，请等待时钟恢复；原炉进度保留。")


def _forecast(run: dict, move: str) -> tuple[int, int]:
    power, stability = run["rule"]["moves"][move]
    return (run["power"] + power,
            min(run["rule"]["capacity"], run["stability"] + stability)
            - run["rule"]["stress"][run["step"] - 1])


def _command(run: dict, move: str) -> str:
    return f"{TITLE} {move} 炉 {run['run_id']} 步 {run['step']}"


def _rules(rule: dict) -> tuple[str, ...]:
    return (
        f"每段先配伍，再扣本段燥性（{' / '.join(map(str, rule['stress']))}）；稳定上限{rule['capacity']}，降至0即毁丹。",
        f"三段结束且稳定大于0：药力≥{rule['double']}得双份，≥{rule['single']}得一份，其余无丹。",
        "；".join(f"{move}：药力{delta[0]:+d}、稳定{delta[1]:+d}"
                 for move, delta in rule["moves"].items()) + "。每段只能选一次。",
    )


def _active_page(run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    lines = [*prefix, f"{run['recipe']['name']} · 第{run['step']}/3段 {STAGES[run['step'] - 1]}",
             f"药力{run['power']} · 稳定{run['stability']}/{run['rule']['capacity']}。",
             *_rules(run["rule"])]
    links = []
    for move in run["rule"]["moves"]:
        power, stability = _forecast(run, move)
        outcome = "，本段会毁丹" if stability <= 0 else ""
        lines.append(f"{move} → 药力{power}、稳定{max(0, stability)}{outcome}。")
        links.append(InlineCommand(len(lines) - 1, move, _command(run, move)))
    lines.append("丹材和灵石已在开炉时扣除；弃炉不退还。离线不会自动推进，继续旧炉不占今日开炉机会。")
    links.append(InlineCommand(len(lines) - 1, "弃炉", _command(run, "弃炉")))
    return Reply(TITLE + " · 炉中", tuple(lines), (TITLE, "灵宠背包", "灵宠炼丹"), tuple(links))


def _shortage(ctx: Context, entry) -> str | None:
    missing = [f"{ctx.content.items[key].name}缺{need - alchemy._owned(ctx, key)}"
               for key, need in entry.materials.items() if alchemy._owned(ctx, key) < need]
    if ctx.player().stones < entry.stones:
        missing.append(f"灵石不足：需要{entry.stones}，当前{ctx.player().stones}")
    return "材料不足：" + "、".join(missing) if missing else None


def _blocked(ctx: Context, entry) -> str | None:
    if ctx.repo.player(ctx.user_id) is None:
        return "尚未结契，请先完成领养。"
    last = ctx.repo.latest_furnace_action(ctx.user_id)
    if last and ctx.now < last["snapshot"]["updated_at"]:
        return "时间早于上次丹炉操作，请等待时钟恢复。"
    if last and last["snapshot"]["status"] == "active":
        return "已有一炉正在配伍，请继续或弃炉后再开炉。"
    if _used_day(ctx) > _day(ctx):
        return "系统日期早于开炉记录，请等待日期恢复。"
    if _used_day(ctx) == _day(ctx):
        return "今日已开炉；每日北京时间00:00恢复一次机会。"
    return _shortage(ctx, entry)


def preview(ctx: Context, name: str) -> Reply:
    entry = named(ctx.content.alchemy, name)
    product = ctx.content.items[entry.item_id]
    lines = [entry.description, f"开炉消耗：{alchemy.cost_text(ctx, entry)}。",
             f"一份{product.name}×{entry.yield_}，双份×{entry.yield_ * 2}；{alchemy.effect_text(ctx, entry)}。",
             f"初始药力0、稳定{RULE['stability']}；每日一次开炉，与即时炼丹独立。",
             *_rules(RULE)]
    reason = _blocked(ctx, entry)
    lines.append(reason or "材料齐备，今日可开炉；三段按选择结丹，无随机判定。")
    links = [InlineCommand(1, "进山采药", "灵宠采药")]
    for item_id in entry.materials:
        item = ctx.content.items[item_id]
        if item.price is not None:
            links.append(InlineCommand(1, f"查看{item.name}", f"灵宠商店 {item.name}"))
    if reason is None:
        links.append(InlineCommand(len(lines) - 1, "开炉", f"{TITLE} 开炉 {entry.name}"))
    elif ctx.repo.player(ctx.user_id) is None:
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE + " · 丹方", tuple(lines), (TITLE, "灵宠炼丹", "灵宠背包"), tuple(links))


def page(ctx: Context) -> Reply:
    run = state(ctx)
    if run:
        return _active_page(run)
    lines = ["按一份丹方开炉，三段配伍决定单份、双份或毁丹；每人每日一次开炉。",
             "开炉不要求伙伴出战，丹药入包后仍由使用或突破入口选择伙伴。",
             *_rules(RULE)]
    links = []
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，可先预览丹方，领养后准备丹材开炉。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        lines.append(objective_line(ctx, ctx.user_id))
    for entry in alchemy.recipes(ctx):
        lines.append(f"{entry.name} · {alchemy.cost_text(ctx, entry)} · {alchemy.effect_text(ctx, entry)}。")
        links.append(InlineCommand(len(lines) - 1, "预览丹方", f"{TITLE} 预览 {entry.name}"))
    return Reply(TITLE, tuple(lines), ("灵宠炼丹", TITLE + " 成品", "灵宠背包"), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    entry = named(ctx.content.alchemy, name)
    reason = _blocked(ctx, entry)
    if reason:
        raise GameError(reason)
    last = ctx.repo.latest_furnace_action(ctx.user_id)
    product = ctx.content.items[entry.item_id]
    run = {"run_id": max(ctx.now, last["snapshot"]["run_id"] + 1 if last else 1),
           "status": "active", "event": "start", "step": 1, "power": 0,
           "stability": RULE["stability"], "rule": {**RULE, "moves": dict(RULE["moves"])},
           "recipe": {"id": entry.id, "name": entry.name, "item": product.id,
                      "kind": product.kind, "yield": entry.yield_, "product": product.name,
                      "effect": alchemy.effect_text(ctx, entry), "cost": alchemy.cost_text(ctx, entry)},
           "started_at": ctx.now, "history": []}
    ctx.player().stones -= entry.stones
    for item_id, need in entry.materials.items():
        ctx.repo.consume_item(ctx.user_id, item_id, need)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, DAY_KEY, _day(ctx)),
    )
    return _record(ctx, run, _active_page(run, (f"已开炉：{entry.name}，消耗{run['recipe']['cost']}。",)))


def act(ctx: Context, move: str, guard: tuple[int, int] | None) -> Reply:
    ctx.player()
    run = state(ctx)
    if run is None:
        raise GameError("当前没有正在配伍的丹炉，请先预览丹方并开炉。")
    _time(ctx, run)
    if guard is not None and guard != (run["run_id"], run["step"]):
        raise GameError("该炉步骤已过期，请查看当前丹炉；原炉进度未改变。")
    run["event"] = move
    if move == "弃炉":
        run.update(status="abandoned", portions=0)
        reply = Reply(TITLE + " · 弃炉", (f"已放弃{run['recipe']['name']}，丹材、灵石和今日机会不退还。",
                                        "没有产物，不累计炼丹次数。"), (TITLE, "灵宠炼丹"))
        return _record(ctx, run, reply)
    run["power"], run["stability"] = _forecast(run, move)
    summary = f"第{run['step']}段{move}：药力{run['power']}，稳定{max(0, run['stability'])}。"
    run["history"].append(summary)
    if run["stability"] > 0 and run["step"] < 3:
        run["step"] += 1
        return _record(ctx, run, _active_page(run, (summary,)))
    return _finish(ctx, run)


def _finish(ctx: Context, run: dict) -> Reply:
    rule, recipe = run["rule"], run["recipe"]
    portions = (2 if run["power"] >= rule["double"] else 1 if run["power"] >= rule["single"] else 0)
    if run["stability"] <= 0:
        portions = 0
    amount = recipe["yield"] * portions
    links = []
    lines = [*run["history"]]
    if amount:
        product = ctx.content.items.get(recipe["item"])
        if product is None or product.kind != recipe["kind"]:
            raise GameError("原丹方产物暂不可用，本段未结算；原炉与已付材料保留，请稍后再试。")
        ctx.repo.add_item(ctx.user_id, recipe["item"], amount)
        counters.bump(ctx, "alchemy_brews")
        lines.append(f"{recipe['product']}×{amount}已入乾坤袋；每份{recipe['effect']}。")
        command = (f"灵宠突破 {recipe['product']}" if recipe["kind"] == "breakthrough"
                   else f"灵宠使用 {recipe['product']} 1")
        links.append(InlineCommand(len(lines) - 1, "使用丹药", command))
        lines.append("本炉计一次成功炼丹，可查看成就和今日赏金进度。")
    else:
        lines.append("本炉毁丹，无产物、不累计炼丹次数；已付丹材、灵石和机会不退还。")
    run.update(status="finished", portions=amount)
    return _record(ctx, run, Reply(TITLE + " · 成品", tuple(lines),
                                  (TITLE, "灵宠背包", "灵宠炼丹"), tuple(links)))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_furnace_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply(TITLE + " · 成品", ("还没有结束的丹炉记录。",), (TITLE,))
    saved = Reply.from_data(last["reply"])
    return Reply(TITLE + " · 成品回顾", saved.lines, (TITLE, "灵宠背包"), saved.inline_commands)


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["成品"]:
        return result(ctx)
    if len(parts) == 2 and parts[0] in ("预览", "开炉"):
        return preview(ctx, parts[1]) if parts[0] == "预览" else start(ctx, parts[1])
    guard = None
    if len(parts) == 5 and parts[1] == "炉" and parts[3] == "步":
        guard = (quantity(parts[2], 9999999999999999), quantity(parts[4], 3))
        parts = parts[:1]
    if len(parts) == 1 and parts[0] in (*RULE["moves"], "弃炉"):
        return act(ctx, parts[0], guard)
    raise GameError("格式：灵宠丹炉 [预览 丹方|开炉 丹方|温养|催灵|调和|弃炉|成品]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx, user_id)
    if run:
        return f"丹炉：{run['recipe']['name']}第{run['step']}/3段 · 药力{run['power']} · 稳定{run['stability']}"
    return "丹炉：今日已开炉" if _used_day(ctx, user_id) >= _day(ctx) else "丹炉：今日可开炉，三段配伍"
