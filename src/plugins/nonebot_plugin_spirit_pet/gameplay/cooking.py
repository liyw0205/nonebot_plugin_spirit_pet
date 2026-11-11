"""Three-stage fire control using existing recipes, heat and meal items.

Paid pots and replies live in the append-only action ledger. Each action saves
the complete pot, including the original recipe output and temperature targets.
Only completed portions contribute to the existing cuisine mastery counters.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import cuisine

ACTIONS = {"旺火": 20, "文火": 0, "离火": -20}
STAGES = ("温锅", "熟化", "收火")
TOTAL = "cooking_total"
PERFECT = "cooking_perfect"
BEST = "cooking_best_"


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


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_cooking_action(user_id or ctx.user_id)
    if last is None or last["snapshot"]["status"] != "active":
        return None
    return last["snapshot"]


def _record(ctx: Context, pot: dict, reply: Reply) -> Reply:
    ctx.repo.record_cooking_action(
        ctx.operation_id, ctx.user_id, ctx.now, {**pot, "updated_at": ctx.now}, reply,
    )
    return reply


def _forecast(pot: dict, action: str) -> tuple[int, int]:
    temperature = max(0, min(100, pot["temperature"] + ACTIONS[action] + pot["wind"]))
    distance = abs(temperature - pot["targets"][pot["turn"] - 1])
    score = 2 if distance <= 5 else 1 if distance <= 15 else 0
    return temperature, score


def _pot_reply(pot: dict, prefix: tuple[str, ...] = ()) -> Reply:
    turn = pot["turn"]
    target = pot["targets"][turn - 1]
    lines = [
        *prefix,
        f"{pot['dish']['name']} · 第 {turn}/3 段：{STAGES[turn - 1]}",
        f"当前炉温 {pot['temperature']} · 本段目标 {target} · 风势 {pot['wind']:+d}。",
        f"累计火候分 {pot['score']}/6；偏差 ≤5 得 2 分，≤15 得 1 分，其余 0 分。",
        "三段目标：" + " → ".join(map(str, pot["targets"])) + "。",
        "成色：5-6 分佳膳 2 份，3-4 分成膳 1 份，0-2 分焦糊无产物。",
    ]
    links = []
    for action, delta in ACTIONS.items():
        temperature, score = _forecast(pot, action)
        lines.append(f"{action}（{delta:+d}）：炉温 → {temperature}，本段 +{score} 分。")
        links.append(InlineCommand(len(lines) - 1, action, f"灵宠掌勺 {action}"))
    lines.append("材料与灶火已在开锅时扣除；收灶放弃不退还。")
    links.append(InlineCommand(len(lines) - 1, "收灶", "灵宠掌勺 收灶"))
    return Reply("灵宠掌勺 · 锅中", tuple(lines),
                 ("灵宠膳房", "灵宠掌勺 成品", "灵宠目标"), tuple(links))


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠掌勺", (
            "尚未结契，先完成领养，再与伙伴分享亲手做的灵膳。",
            "三段火候：按炉温、目标与风势选择旺火、文火或离火，成色决定成膳份数。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    pot = state(ctx)
    if pot is not None:
        return _pot_reply(pot)
    lines = [
        f"厨艺 {cuisine.level(ctx)} 级 · 今日灶火 {cuisine.heat_left(ctx)}/"
        f"{ctx.content.rules.cuisine.daily_heat}。",
        f"已完成 {_progress(ctx, TOTAL)} 锅 · 佳膳 {_progress(ctx, PERFECT)} 锅。",
        "每锅三段，自选火候；与即时烹饪共用材料、灵石和灶火，每次只开一锅。",
        "5-6 分得 2 份，3-4 分得 1 份，0-2 分焦糊；只有成膳才增加菜谱熟练。",
    ]
    links = []
    for dish in cuisine.dishes(ctx):
        if dish.item is None:
            continue
        status = cuisine._state(ctx, dish)
        lines.append(
            f"{dish.name} · 厨艺 {dish.level} 级 · 灶火 {dish.heat} · "
            f"{cuisine._cost_text(ctx, dish)} · 最高 {_progress(ctx, BEST + dish.id)}/6 分 · {status}"
        )
        if status == "可烹饪":
            links.append(InlineCommand(len(lines) - 1, "开锅", f"灵宠掌勺 开锅 {dish.name}"))
    lines.append("宴席沿用膳房即时烹饪；成膳放进乾坤袋，可使用后温养当前伙伴。")
    return Reply("灵宠掌勺", tuple(lines), ("灵宠膳房", "灵宠掌勺 成品", "灵宠目标"), tuple(links))


def _check_time(ctx: Context, snapshot: dict) -> None:
    if ctx.now < snapshot["updated_at"]:
        raise GameError("时间早于上次掌勺，请等待时钟恢复后再操作。")


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    last = ctx.repo.latest_cooking_action(ctx.user_id)
    if last is not None:
        _check_time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有一锅正在掌勺，请继续调火或收灶后再开锅。")
    dish = named(ctx.content.cuisine, name)
    if dish.item is None:
        raise GameError("掌勺只接受单膳，宴席请用 灵宠烹饪。")
    if cuisine.level(ctx) < dish.level:
        raise GameError(f"厨艺不足：{dish.name}需要厨艺 {dish.level} 级。")
    if cuisine.heat_left(ctx) < dish.heat:
        raise GameError(f"今日灶火不足：需要 {dish.heat} 点。")
    shortage = cuisine._shortage(ctx, dish, 1)
    if shortage:
        raise GameError(shortage)
    ctx.player().stones -= dish.stones
    for item_id, amount in dish.ingredients.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    cuisine.spend_heat(ctx, dish.heat)
    base = 40 + (dish.level - 1) * 2
    pot = {
        "status": "active", "event": "start", "turn": 1, "score": 0,
        "temperature": ctx.rng.randint(base - 10, base + 10),
        "wind": ctx.rng.randint(-1, 1) * 5,
        "targets": [base, base + 20, base],
        "dish": {"id": dish.id, "name": dish.name, "item": dish.item,
                 "stones": dish.stones, "ingredients": dict(dish.ingredients), "heat": dish.heat},
        "started_at": ctx.now,
    }
    return _record(ctx, pot, _pot_reply(pot, (
        f"已开锅：{dish.name}，消耗 {cuisine._cost_text(ctx, dish)}、灶火 {dish.heat}。",
    )))


def act(ctx: Context, action: str) -> Reply:
    ctx.player()
    pot = state(ctx)
    if pot is None:
        raise GameError("当前没有正在掌勺的锅，请先到 灵宠掌勺 开锅。")
    _check_time(ctx, pot)
    if action == "收灶":
        pot.update(status="abandoned", event="abandon")
        return _record(ctx, pot, Reply("掌勺收灶", (
            f"已放弃{pot['dish']['name']}，本锅材料、灵石与灶火不退还。",
            "未产出灵膳，不增加厨艺或成膳记录。",
        ), ("灵宠掌勺", "灵宠膳房")))
    temperature, gained = _forecast(pot, action)
    pot["temperature"] = temperature
    pot["score"] += gained
    pot["event"] = action
    summary = f"第 {pot['turn']} 段选择{action}：炉温 {temperature}，火候 +{gained}，累计 {pot['score']}/6 分。"
    if pot["turn"] < 3:
        pot["turn"] += 1
        pot["wind"] = ctx.rng.randint(-1, 1) * 5
        return _record(ctx, pot, _pot_reply(pot, (summary,)))
    return _finish(ctx, pot, summary)


def _finish(ctx: Context, pot: dict, summary: str) -> Reply:
    score = pot["score"]
    portions = 2 if score >= 5 else 1 if score >= 3 else 0
    grade = "佳膳" if portions == 2 else "成膳" if portions else "焦糊"
    dish = pot["dish"]
    before = cuisine.level(ctx)
    if portions:
        if dish["item"] not in ctx.content.items:
            raise GameError("原配方的成膳道具暂不可用，本段未结算，请稍后再试。")
        ctx.repo.add_item(ctx.user_id, dish["item"], portions)
        key = cuisine.DISH_PREFIX + dish["id"]
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
            "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=progress+excluded.progress",
            (ctx.user_id, key, portions),
        )
    _write(ctx, TOTAL, _progress(ctx, TOTAL) + 1)
    if portions == 2:
        _write(ctx, PERFECT, _progress(ctx, PERFECT) + 1)
    _write(ctx, BEST + dish["id"], max(score, _progress(ctx, BEST + dish["id"])))
    pot.update(status="finished", portions=portions, grade=grade)
    lines = [summary, f"{dish['name']} · {grade} · 火候 {score}/6 分。"]
    links = []
    if portions:
        item = ctx.content.items[dish["item"]]
        lines.append(f"{item.name} ×{portions} 已入乾坤袋，可给当前伙伴使用。")
        links.append(InlineCommand(len(lines) - 1, "享用灵膳", f"灵宠使用 {item.name} 1"))
    else:
        lines.append("本锅焦糊，无产物，不增加菜谱熟练；已付资源不退还。")
    after = cuisine.level(ctx)
    if after > before:
        lines.append(f"厨艺提升：{before} 级 → {after} 级。")
    lines.append(f"厨艺 {after} 级 · 已掌握 {cuisine.mastered(ctx)}/{len(ctx.content.cuisine)} 道。")
    return _record(ctx, pot, Reply("掌勺成品", tuple(lines),
                                  ("灵宠掌勺", "灵宠背包", "灵宠膳房"), tuple(links)))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_cooking_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply("掌勺成品回顾", ("还没有已结束的掌勺记录。",), ("灵宠掌勺",))
    saved = Reply.from_data(last["reply"])
    return Reply("掌勺成品回顾", saved.lines, ("灵宠掌勺", "灵宠背包", "灵宠膳房"))


def dispatch(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text:
        return page(ctx)
    if text == "成品":
        return result(ctx)
    if text in ACTIONS or text == "收灶":
        return act(ctx, text)
    if text.startswith("开锅 ") and text[3:].strip():
        return start(ctx, text[3:].strip())
    raise GameError("格式：灵宠掌勺 [开锅 菜名|旺火|文火|离火|收灶|成品]。")


def objective_line(ctx: Context, user_id: str) -> str:
    pot = state(ctx, user_id)
    if pot is not None:
        return f"掌勺：{pot['dish']['name']}第 {pot['turn']}/3 段 · 火候 {pot['score']}/6 分"
    return f"掌勺：已完成 {_progress(ctx, TOTAL, user_id)} 锅 · 佳膳 {_progress(ctx, PERFECT, user_id)} 锅"
