"""Five current-aware decisions, sharing the existing daily fishing allowance."""

from ..application.context import Context
from ..domain.angling_content import INITIAL_TENSION, LINE_LIMIT, MOVES
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import beijing_day
from . import fishing

TITLE = "灵宠遛鱼"


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_angling_action(user_id or ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次遛鱼操作，请等待时钟恢复；原竿进度保留。")


def _partner_reason(ctx: Context, run: dict) -> str:
    try:
        pet = ctx.repo.pet(run["pet_id"])
    except GameError:
        return "原伙伴已不在名册，请撤竿。"
    released = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"released_{pet.pet_id}"),
    ).fetchone()
    if pet.user_id != ctx.user_id or (released and released["progress"]):
        return "原伙伴已归灵或归属改变，请撤竿。"
    if pet.archived:
        return "原伙伴已封存，请复原后继续，或撤竿。"
    if ctx.repo.active_expedition(pet.pet_id):
        return "原伙伴正在派遣或奖励待领取，请先查看灵宠行程，或撤竿。"
    return ""


def _start_reason(ctx: Context, spot, bait) -> str:
    last = ctx.repo.latest_angling_action(ctx.user_id)
    if last:
        if ctx.now < last["snapshot"]["updated_at"]:
            return "时间早于上次遛鱼操作，请等待时钟恢复"
        if last["snapshot"]["status"] == "active":
            return "已有一竿遛鱼，请继续或撤竿"
    latest_day = ctx.repo.conn.execute(
        "SELECT MAX(quest_id) FROM quest_progress WHERE user_id=? AND quest_id GLOB 'fishing_day_????-??-??'",
        (ctx.user_id,),
    ).fetchone()[0]
    if latest_day and latest_day > fishing.CAST_PREFIX + beijing_day(ctx.now):
        return "日期早于已有垂钓记录，请等待日期恢复"
    return fishing.block_reason(ctx, spot, fishing.preview_pet(ctx), bait)


def _rules(rule: dict) -> tuple[str, ...]:
    return (
        f"初始牵引0、张力{rule['initial']}；每轮先选动作，再叠加水势。",
        "；".join(f"{name}：牵引{gain:+d}、张力{strain:+d}" for name, (gain, strain) in rule["moves"].items())
        + "。牵引最低为0。",
        f"张力≤0脱钩、≥{rule['limit']}断线，立即失手；完成五轮且牵引≥{rule['goal']}才入篓。",
        "离线不自动推进；失手或撤竿不退精力、饵料与竿数，不发鱼获或集齐奖励。",
    )


def _rule(course) -> dict:
    return {"initial": INITIAL_TENSION, "limit": LINE_LIMIT, "moves": dict(MOVES),
            "goal": course.goal, "pulls": list(course.pulls)}


def preview(ctx: Context, spot_name: str, bait_name: str = "") -> Reply:
    spot = fishing._spot(ctx, spot_name)
    bait = fishing.bait_for(ctx, spot, bait_name)
    course = ctx.content.angling_courses[spot.id]
    bait_label = bait.name if bait else "素饵"
    lines = [course.description,
             f"{spot.name} · 门槛{ctx.content.realms[spot.realm].name} · 精力{spot.energy} · 与垂钓共用每日三竿，今日剩{fishing.left_today(ctx)}竿。",
             f"{bait_label}：" + (f"{ctx.content.items[bait.cost_item].name}×{bait.cost_quantity}，持有{ctx.repo.inventory(ctx.user_id).get(bait.cost_item, 0)}。"
                               if bait else "无额外物品消耗。"),
             *_rules(_rule(course)),
             "五轮水势：" + " / ".join(f"{n:+d}" for n in course.pulls) + "。",
             "咬钩鱼获按下列权重在抛竿时固定；遛鱼成功才得到，不会额外重抽或加倍。"]
    weights = fishing.weights(spot, bait)
    for entry, weight in zip(spot.catches, weights):
        lines.append(f"{ctx.content.items[entry.item].name}×{entry.minimum}-{entry.maximum} · {weight}/{sum(weights)}。")
    reason = _start_reason(ctx, spot, bait)
    lines.append(f"暂不可抛竿：{reason}。" if reason else "已就绪，可抛竿后逐轮遛鱼。")
    links = []
    if not reason:
        links.append(InlineCommand(len(lines) - 1, "抛竿遛鱼", f"{TITLE} 抛竿 {spot.name} {bait_label}"))
    elif ctx.repo.player(ctx.user_id) is None:
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        links.append(InlineCommand(len(lines) - 1, "查看伙伴", "灵宠列表"))
    lines.append("可切换素饵、谷香饵、晶砂饵或灵光饵；偏向不保证钓中。")
    for option in (None, *ctx.content.fishing_baits.values()):
        if option and not any(entry.item in option.favored_items for entry in spot.catches):
            continue
        name = option.name if option else "素饵"
        if name != bait_label:
            links.append(InlineCommand(len(lines) - 1, name, f"{TITLE} 预览 {spot.name} {name}"))
    if bait:
        lines.append("饵料使用既有物品，抛竿时扣除。")
        links.append(InlineCommand(len(lines) - 1, "准备饵料", f"灵宠商店 {ctx.content.items[bait.cost_item].name}"))
    return Reply(TITLE + " · 水域", tuple(lines), (TITLE, f"灵宠垂钓 详情 {spot.name}", "灵宠背包"), tuple(links))


def _forecast(run: dict, move: str) -> tuple[int, int]:
    gain, strain = run["rule"]["moves"][move]
    return (max(0, run["progress"] + gain),
            run["tension"] + strain + run["rule"]["pulls"][run["step"] - 1])


def _command(run: dict, move: str) -> str:
    return f"{TITLE} {move} 竿 {run['run_id']} 步 {run['step']}"


def _active_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    lines = [*prefix, f"{run['spot_name']} / {run['bait_name']} · 原伙伴{run['pet_name']}（编号{run['pet_id']}）",
             f"第{run['step']}/5轮 · 牵引{run['progress']}/{run['rule']['goal']} · 张力{run['tension']}（须在1至{run['rule']['limit'] - 1}之间）。",
             "五轮水势：" + " / ".join(f"{n:+d}" for n in run["rule"]["pulls"]) + "。",
             *_rules(run["rule"])]
    reason = _partner_reason(ctx, run)
    if ctx.now < run["updated_at"]:
        reason = "时间早于上次遛鱼操作，请等待时钟恢复。"
    links = []
    for move in run["rule"]["moves"]:
        progress, tension = _forecast(run, move)
        outcome = "（会脱钩）" if tension <= 0 else "（会断线）" if tension >= run["rule"]["limit"] else ""
        if not outcome and run["step"] == 5:
            outcome = "（可入篓）" if progress >= run["rule"]["goal"] else "（牵引不足，会失手）"
        lines.append(f"{move} → 牵引{progress}、张力{tension}{outcome}。")
        if not reason:
            links.append(InlineCommand(len(lines) - 1, move, _command(run, move)))
    if reason:
        lines.append(reason)
        links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                      InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    lines.append("原竿可跨日继续，不再次扣费，也不会转给后来出战的伙伴。")
    links.append(InlineCommand(len(lines) - 1, "撤竿", _command(run, "撤竿")))
    return Reply(TITLE + " · 竿中", tuple(lines), (TITLE, "灵宠垂钓 鱼篓", "灵宠背包"), tuple(links))


def page(ctx: Context) -> Reply:
    run = state(ctx)
    if run:
        return _active_page(ctx, run)
    lines = ["抛竿后依水势逐轮收线、稳竿或放线；五轮牵到岸才得鱼获。",
             f"与灵宠垂钓共用每日三竿，今日剩{fishing.left_today(ctx)}竿；同时只留一竿遛鱼。"]
    links = []
    for spot in fishing.spots(ctx):
        course = ctx.content.angling_courses[spot.id]
        lines.append(f"{spot.name} · 牵引目标{course.goal} · {course.description}")
        links.append(InlineCommand(len(lines) - 1, "水势与择饵", f"{TITLE} 预览 {spot.name}"))
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，可先预览水域，领养后再与伙伴同行。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    return Reply(TITLE, tuple(lines), (TITLE + " 记录", "灵宠垂钓", "灵宠背包"), tuple(links))


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_angling_action(ctx.operation_id, ctx.user_id, ctx.now,
                                  {**run, "updated_at": ctx.now}, reply)
    return reply


def start(ctx: Context, spot_name: str, bait_name: str = "") -> Reply:
    ctx.player()
    spot = fishing._spot(ctx, spot_name)
    bait = fishing.bait_for(ctx, spot, bait_name)
    reason = _start_reason(ctx, spot, bait)
    if reason:
        raise GameError(reason + "。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    weights = fishing.weights(spot, bait)
    roll = ctx.rng.randint(1, sum(weights))
    cursor = 0
    for entry, weight in zip(spot.catches, weights):
        cursor += weight
        if roll <= cursor:
            picked = entry
            break
    product = ctx.content.items[picked.item]
    last = ctx.repo.latest_angling_action(ctx.user_id)
    run = {"status": "active", "event": "start", "step": 1, "progress": 0,
           "tension": INITIAL_TENSION, "rule": _rule(ctx.content.angling_courses[spot.id]),
           "run_id": max(ctx.now, last["snapshot"]["run_id"] + 1 if last else 1),
           "started_at": ctx.now, "updated_at": ctx.now, "history": [],
           "pet_id": pet.pet_id, "pet_name": pet.name, "spot_id": spot.id, "spot_name": spot.name,
           "bait_id": bait.id if bait else "plain", "bait_name": bait.name if bait else "素饵",
           "cost_item": bait.cost_item if bait else None,
           "cost_name": ctx.content.items[bait.cost_item].name if bait else "",
           "cost_quantity": bait.cost_quantity if bait else 0, "energy": spot.energy,
           "item_id": product.id, "item_name": product.name, "item_kind": product.kind,
           "amount": ctx.rng.randint(picked.minimum, picked.maximum), "weights": weights,
           "collections": [{"id": s.id, "name": s.name, "items": [c.item for c in s.catches]}
                           for s in fishing.spots(ctx)],
           "spot_bonus": fishing.SPOT_BONUS, "all_bonus": fishing.ALL_BONUS}
    pet.energy -= spot.energy
    if bait:
        ctx.repo.consume_item(ctx.user_id, bait.cost_item, bait.cost_quantity)
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=progress+1",
        (ctx.user_id, fishing.CAST_PREFIX + beijing_day(ctx.now)),
    )
    return _record(ctx, run, _active_page(ctx, run, (f"已抛竿：精力-{spot.energy}，占用今日一竿；鱼获尚未入袋。",)))


def _settle(ctx: Context, run: dict) -> list[str]:
    product = ctx.content.items.get(run["item_id"])
    if product is None or product.kind != run["item_kind"]:
        raise GameError("原鱼获物品暂不可用，本轮未结算，请等待内容恢复或撤竿。")
    # Collection definitions travel with the cast; later content edits cannot add requirements.
    bonuses = [*run["spot_bonus"][1], *run["all_bonus"][1]]
    if any(key not in ctx.content.items for key in bonuses):
        raise GameError("鱼获集齐奖励暂不可用，本轮未结算，请等待内容恢复或撤竿。")
    ctx.repo.add_item(ctx.user_id, run["item_id"], run["amount"])
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET claimed=1",
        (ctx.user_id, f"{fishing.CATCH_PREFIX}{run['spot_id']}_{run['item_id']}"),
    )
    lines = [f"{run['item_name']}×{run['amount']}已入乾坤袋，记入{run['spot_name']}鱼获。"]
    complete = []
    for collection in run["collections"]:
        found = all(fishing._voucher(ctx, f"{fishing.CATCH_PREFIX}{collection['id']}_{key}")
                    for key in collection["items"])
        complete.append(found)
        if found:
            lines.extend(fishing._pay(ctx, fishing.SET_PREFIX + collection["id"],
                                     *run["spot_bonus"], f"鱼获「{collection['name']}」集齐："))
    if all(complete):
        lines.extend(fishing._pay(ctx, fishing.SET_PREFIX + "all", *run["all_bonus"], "三处水系鱼获全齐："))
    return lines


def act(ctx: Context, move: str, guard: tuple[int, int] | None) -> Reply:
    ctx.player()
    run = state(ctx)
    if run is None:
        raise GameError("当前没有遛鱼中的竿，请先预览水域并抛竿。")
    _time(ctx, run)
    if guard is not None and guard != (run["run_id"], run["step"]):
        raise GameError("这是旧竿或旧步骤，请重新查看灵宠遛鱼；原竿进度未改变。")
    run["event"] = move
    if move == "撤竿":
        run["status"] = "abandoned"
        reason = "已主动撤竿，无鱼获；精力、饵料和开竿日次数不退。"
    else:
        reason = _partner_reason(ctx, run)
        if reason:
            raise GameError(reason)
        run["progress"], run["tension"] = _forecast(run, move)
        summary = f"第{run['step']}轮{move}：牵引{run['progress']}、张力{run['tension']}。"
        run["history"].append(summary)
        if run["tension"] <= 0 or run["tension"] >= run["rule"]["limit"]:
            run["status"] = "failed"
            reason = "鱼线松弛，脱钩失手。" if run["tension"] <= 0 else "鱼线绷断，失手。"
        elif run["step"] < len(run["rule"]["pulls"]):
            run["step"] += 1
            return _record(ctx, run, _active_page(ctx, run, (summary,)))
        else:
            run["status"] = "caught" if run["progress"] >= run["rule"]["goal"] else "failed"
            reason = "已牵到岸边，鱼获入篓。" if run["status"] == "caught" else "五轮结束仍未牵到岸，鱼已逃走。"
    lines = [f"{run['spot_name']} / {run['bait_name']} · 原伙伴{run['pet_name']}（编号{run['pet_id']}）",
             *run["history"], reason]
    if run["status"] == "caught":
        lines.extend(_settle(ctx, run))
    else:
        lines.append("未发放物品，不增加鱼获收集或集齐奖励；开竿成本不退。")
    lines.append("鱼获可用于喂养、播种、强化或服丹，具体用途见乾坤袋。")
    reply = Reply(TITLE + " · 结果", tuple(lines), (TITLE, "灵宠垂钓 鱼篓", "灵宠背包"),
                  (InlineCommand(len(lines) - 1, "查看灵田", "灵宠灵田"),
                   InlineCommand(len(lines) - 1, "喂养伙伴", f"灵宠喂养 {run['pet_id']}")))
    ctx.repo.record_fishing_cast(ctx.operation_id, ctx.user_id, ctx.now,
                                 {**run, "mode": "angling"}, reply)
    return _record(ctx, run, reply)


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_angling_action(ctx.user_id, finished_only=True)
    if not last:
        return Reply(TITLE + " · 记录", ("尚无结束的遛鱼记录。",), (TITLE,))
    saved = Reply.from_data(last["reply"])
    return Reply(TITLE + " · 记录", saved.lines, (TITLE, "灵宠垂钓 鱼篓", "灵宠背包"), saved.inline_commands)


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["记录"]:
        return result(ctx)
    if len(parts) in (2, 3) and parts[0] in ("预览", "抛竿"):
        return (preview if parts[0] == "预览" else start)(ctx, parts[1], parts[2] if len(parts) == 3 else "")
    guard = None
    if len(parts) == 5 and parts[1] == "竿" and parts[3] == "步":
        guard = (quantity(parts[2], 9999999999999999), quantity(parts[4], 5))
        parts = parts[:1]
    if len(parts) == 1 and parts[0] in (*MOVES, "撤竿"):
        return act(ctx, parts[0], guard)
    raise GameError("格式：灵宠遛鱼 [预览 水域 [饵料]|抛竿 水域 [饵料]|收线|稳竿|放线|撤竿|记录]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx, user_id)
    return (f"遛鱼：{run['spot_name']}第{run['step']}/5轮 · 牵引{run['progress']}/{run['rule']['goal']} · 张力{run['tension']}"
            if run else "遛鱼：五轮水势取舍，与垂钓共用今日竿数")
