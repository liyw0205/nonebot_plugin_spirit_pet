"""A daily three-step practice that consumes a real cooked meal.

The active round is kept in the durable duel-action journal. This keeps each
step replayable after a restart while the existing transaction wrapper provides
the operation-id and concurrent-message guard.
"""

import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from . import bond_levels, cuisine

TITLE = "灵宠膳房研修"
KIND = "cuisine_practice"
DAY_PREFIX = "cuisine_practice_day_"
TOTAL_KEY = "cuisine_practice_total"
PERFECT_KEY = "cuisine_practice_perfect"
MIN_CUISINE_LEVEL = 2
ENERGY_COST = 8
ACTIONS = ("稳火", "添香", "收盘")
STAGES = ("备料", "调味", "呈盘")

# Each recipe has a deterministic ideal sequence. A wrong choice is still a
# valid step, but earns no points; no random result can be changed by replay.
IDEAL = {
    "rice_porridge": ("稳火", "添香", "收盘"),
    "herb_soup": ("添香", "稳火", "收盘"),
    "lotus_pastry": ("稳火", "收盘", "添香"),
    "grain_cake": ("添香", "收盘", "稳火"),
    "moon_cake": ("收盘", "稳火", "添香"),
}
REWARDS = {
    0: ("失手", 0, 0, 0, 0),
    2: ("合格", 15, 4, 6, 0),
    4: ("合格", 15, 4, 6, 0),
    6: ("佳作", 30, 8, 12, 1),
}


def _key(day: str) -> str:
    return f"{DAY_PREFIX}{day}"


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _increment(ctx: Context, key: str, amount: int = 1) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (ctx.user_id, key, amount),
    )


def _latest(ctx: Context, user_id: str | None = None) -> dict | None:
    row = ctx.repo.conn.execute(
        "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')=? ORDER BY action_id DESC LIMIT 1",
        (user_id or ctx.user_id, KIND),
    ).fetchone()
    if row is None:
        return None
    try:
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GameError("研修记录损坏，请联系管理员检查存档。") from exc


def _active(ctx: Context) -> dict | None:
    latest = _latest(ctx)
    if latest is None or latest["snapshot"].get("status") != "active":
        return None
    return latest["snapshot"]


def _record(ctx: Context, state: dict, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {**state, "kind": KIND, "updated_at": ctx.now}, reply,
    )
    return reply


def _check_clock(ctx: Context, state: dict) -> None:
    if ctx.now < state.get("updated_at", state.get("started_at", ctx.now)):
        raise GameError("时间早于上次研修，请等待时钟恢复后再操作。")


def _meal_dishes(ctx: Context):
    return [dish for dish in cuisine.dishes(ctx) if dish.item is not None]


def _meal_count(ctx: Context, item_id: str) -> int:
    return cuisine.owned_item(ctx, ctx.user_id, item_id)


def _render_state(state: dict, prefix: tuple[str, ...] = ()) -> Reply:
    step = state["step"]
    expected = state["ideal"][step]
    lines = [
        *prefix,
        f"{state['dish_name']}研修 · 第 {step + 1}/3 段：{STAGES[step]}",
        f"当前得分 {state['score']}/6 · 本段理想操作为「{expected}」；三段后按 0/2/4/6 分结算。",
        "可选：" + "、".join(ACTIONS),
    ]
    links = tuple(
        InlineCommand(len(lines) - 1, action, f"{TITLE} {action}")
        for action in ACTIONS
    )
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠膳房", "灵宠目标"), links)


def _started_today(ctx: Context) -> bool:
    day = beijing_day(ctx.now)
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, _key(day)),
    ).fetchone()
    return row is not None


def _future_record(ctx: Context) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')=? "
        "AND created_at>? LIMIT 1", (ctx.user_id, KIND, ctx.now),
    ).fetchone() is not None


def catalog(ctx: Context) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    lines = [
        f"厨艺至少 {MIN_CUISINE_LEVEL} 级；每天一局，开局消费一份已有单膳与伙伴 {ENERGY_COST} 点精力。",
        "三段依次选择稳火、添香或收盘；理想操作每段得 2 分，合格 2/4 分，佳作 6 分。",
    ]
    if player is None:
        lines.append("尚未结契，先完成领养；本页只读且不会创建存档。")
        return Reply(TITLE, tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    active = _active(ctx)
    if active is not None:
        lines.append(f"当前进行中：{active['dish_name']}，第 {active['step'] + 1}/3 段。")
        page = _render_state(active, tuple(lines))
        return Reply(page.title, page.lines, (*page.commands, f"{TITLE} 放弃", f"{TITLE} 记录"), page.inline_commands)

    lines.append(f"今日名额：{'已使用' if _started_today(ctx) else '可开启'} · 累计完成 {_progress(ctx, TOTAL_KEY)} 局 · 佳作 {_progress(ctx, PERFECT_KEY)} 局。")
    for dish in _meal_dishes(ctx):
        count = _meal_count(ctx, dish.item)
        state = f"可研修（库存 {count}）" if count else "缺少成品"
        lines.append(f"{dish.name} · 厨艺 {dish.level} 级 · 库存 {count} · {state}")
    links = tuple(
        InlineCommand(index, "开始研修", f"{TITLE} 开始 {dish.name}")
        for index, dish in enumerate(_meal_dishes(ctx), start=3)
        if _meal_count(ctx, dish.item)
        and cuisine.level(ctx) >= max(MIN_CUISINE_LEVEL, dish.level)
        and not _started_today(ctx)
    )
    return Reply(TITLE, tuple(lines), ("灵宠膳房", "灵宠背包", "灵宠目标", f"{TITLE} 记录"), links)


def start(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    if _active(ctx) is not None:
        raise GameError("已有一局膳房研修进行中，请继续操作或发送灵宠膳房研修 放弃。")
    if _future_record(ctx):
        raise GameError("系统日期早于研修记录，请等待日期恢复。")
    if _started_today(ctx):
        raise GameError("今日研修名额已用完，明日 00:00（北京时间）再来。")
    if cuisine.level(ctx) < MIN_CUISINE_LEVEL:
        raise GameError(f"厨艺不足：研修需要厨艺 {MIN_CUISINE_LEVEL} 级，当前 {cuisine.level(ctx)} 级。")
    dish = named(ctx.content.cuisine, arg.strip())
    if dish.item is None:
        raise GameError("研修只接受已有单膳成品，宴席菜不能作为研修材料。")
    if cuisine.level(ctx) < dish.level:
        raise GameError(f"厨艺不足：{dish.name}需要厨艺 {dish.level} 级，当前 {cuisine.level(ctx)} 级。")
    if _meal_count(ctx, dish.item) < 1:
        raise GameError(f"背包中没有{dish.name}，请先用灵宠烹饪或灵宠掌勺制作。")
    if pet.energy < ENERGY_COST:
        raise GameError(f"伙伴精力不足：研修需要 {ENERGY_COST} 点，当前 {pet.energy} 点。")
    ctx.repo.consume_item(ctx.user_id, dish.item, 1)
    pet.energy -= ENERGY_COST
    day = beijing_day(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
        (ctx.user_id, _key(day)),
    )
    state = {
        "status": "active", "step": 0, "score": 0, "choices": [],
        "day": day, "dish_id": dish.id, "dish_name": dish.name,
        "item_id": dish.item, "pet_id": pet.pet_id, "pet_name": pet.name,
        "ideal": list(IDEAL.get(dish.id, ACTIONS)), "started_at": ctx.now,
    }
    ctx.repo.invalidate_ready(ctx.user_id)
    return _record(ctx, state, _render_state(state, (
        f"已消耗 {dish.name} ×1、伙伴精力 -{ENERGY_COST}；今日名额已锁定。",
    )))


def _finish(ctx: Context, state: dict, summary: str) -> Reply:
    grade, pet_exp, affinity, bond, food = REWARDS[state["score"]]
    pet = ctx.repo.pet(state["pet_id"])
    if pet.user_id != ctx.user_id or pet.archived:
        raise GameError("研修伙伴已不可用，本次未结算，请先恢复伙伴。")
    pet.exp += pet_exp
    pet.affinity = min(100, pet.affinity + affinity)
    if bond:
        bond_levels.add_exp(ctx, pet.pet_id, bond)
    _increment(ctx, TOTAL_KEY)
    if state["score"] == 6:
        _increment(ctx, PERFECT_KEY)
    if food:
        ctx.repo.add_item(ctx.user_id, "spirit_food", food)
    ctx.repo.invalidate_ready(ctx.user_id)
    state.update(status="finished", grade=grade, pet_exp=pet_exp, affinity=affinity, bond=bond, food=food)
    lines = [summary, f"{state['dish_name']}研修结算：{grade} · 得分 {state['score']}/6。"]
    if pet_exp or affinity or bond:
        lines.append(f"{pet.name}成长：修为 +{pet_exp}、亲密 +{affinity}、羁绊经验 +{bond}。")
    if food:
        lines.append("佳作奖励：灵粮 +1。")
    lines.append(f"累计完成 {_progress(ctx, TOTAL_KEY)} 局 · 佳作 {_progress(ctx, PERFECT_KEY)} 局。")
    return _record(ctx, state, Reply(TITLE, tuple(lines), ("灵宠膳房", "灵宠羁绊", "灵宠目标", f"{TITLE} 记录")))


def act(ctx: Context, action: str) -> Reply:
    ctx.player()
    state = _active(ctx)
    if state is None:
        raise GameError("当前没有进行中的膳房研修，请先发送灵宠膳房研修。")
    _check_clock(ctx, state)
    if action == "放弃":
        state.update(status="abandoned")
        return _record(ctx, state, Reply(TITLE, (
            f"已放弃{state['dish_name']}研修；已消费的成品、精力和今日名额均不退还。",
        ), (TITLE, "灵宠膳房", "灵宠目标")))
    if action not in ACTIONS:
        raise GameError("格式：灵宠膳房研修 稳火|添香|收盘；也可发送 放弃 或 记录。")
    expected = state["ideal"][state["step"]]
    gained = 2 if action == expected else 0
    step = state["step"]
    state["score"] += gained
    state["choices"].append(action)
    state["step"] += 1
    summary = f"第 {step + 1} 段选择{action}：本段 +{gained} 分，累计 {state['score']}/6。"
    if state["step"] < 3:
        return _record(ctx, state, _render_state(state, (summary,)))
    return _finish(ctx, state, summary)


def history(ctx: Context) -> Reply:
    latest = _latest(ctx)
    if latest is None:
        return Reply(TITLE + " · 记录", ("尚无膳房研修记录。",), (TITLE, "灵宠帮助"))
    state = latest["snapshot"]
    if state.get("status") == "active":
        lines = (f"{state['dish_name']}研修进行中 · 第 {state['step'] + 1}/3 段 · 得分 {state['score']}/6。",)
    elif state.get("status") == "abandoned":
        lines = (f"{state['dish_name']}研修已放弃；本局没有成长或奖励。",)
    else:
        lines = (
            f"{state['dish_name']}研修：{state.get('grade', '未知')} · 得分 {state.get('score', 0)}/6。",
            f"伙伴：{state.get('pet_name', '未知')} · 选择：{'、'.join(state.get('choices', ())) or '无'}。",
            f"结算成长：修为 +{state.get('pet_exp', 0)}、亲密 +{state.get('affinity', 0)}、羁绊 +{state.get('bond', 0)}。",
            f"累计完成 {_progress(ctx, TOTAL_KEY)} 局 · 佳作 {_progress(ctx, PERFECT_KEY)} 局。",
        )
    return Reply(TITLE + " · 记录", lines, (TITLE, "灵宠膳房", "灵宠目标"))


def objective_line(ctx: Context, user_id: str) -> str:
    active = _active(ctx) if user_id == ctx.user_id else None
    total = _progress(ctx, TOTAL_KEY, user_id)
    perfect = _progress(ctx, PERFECT_KEY, user_id)
    day = beijing_day(ctx.now)
    used = bool(ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (user_id, _key(day)),
    ).fetchone())
    return f"膳房研修：{'进行中' if active else ('今日已用' if used else '今日可开')} · 累计 {total} 局 · 佳作 {perfect} 局"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "开始":
        if len(parts) < 2:
            raise GameError("格式：灵宠膳房研修 开始 菜名。")
        return start(ctx, " ".join(parts[1:]))
    if parts[0] == "记录" and len(parts) == 1:
        return history(ctx)
    if len(parts) == 1 and parts[0] in (*ACTIONS, "放弃"):
        return act(ctx, parts[0])
    raise GameError("格式：灵宠膳房研修 [开始 菜名|稳火|添香|收盘|放弃|记录]。")


__all__ = ["ACTIONS", "dispatch", "objective_line"]
