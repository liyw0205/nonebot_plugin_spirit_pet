from sqlite3 import Row

from ..application.context import Context
from ..domain.expedition_state import RewardSnapshot
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from .quests import advance


def catalog(ctx: Context, arg: str) -> Reply:
    tasks = ctx.content.expeditions
    if arg and not arg.isdecimal():
        task = named(tasks, arg)
        realm = next(realm.name for realm in ctx.content.realms if realm.id == task.min_realm)
        reward = task.reward
        return Reply(f"山海委托 · {task.name}", (
            task.description,
            f"{realm}起 · 精力 {task.energy} · 行程 {ctx.config.spirit_pet_expedition_duration} 秒",
            f"修为 {reward.exp.minimum}-{reward.exp.maximum} · 灵石 {reward.stones.minimum}-{reward.stones.maximum}",
            *(f"{ctx.content.items[key].name}：{bounds.minimum}-{bounds.maximum}"
              for key, bounds in reward.items.items()),
            "每人同时一项；完成后归来领奖，提前召回无奖励且不退精力。",
        ), (f"灵宠派遣 {task.name}", "灵宠行程", "灵宠委托"))
    page = paginate(tasks.values(), arg, "山海委托", "灵宠委托")
    return Reply(f"山海委托 {page.number}/{page.total}", tuple(
        f"{task.name} · {next(r.name for r in ctx.content.realms if r.id == task.min_realm)}起"
        f" · 精力 {task.energy} · {ctx.config.spirit_pet_expedition_duration} 秒"
        for task in page.entries
    ), (*(f"灵宠委托 {task.name}" for task in page.entries), *page.navigation, "灵宠行程"))


def _owned(ctx: Context, arg: str) -> Row:
    ctx.player()
    job_id = quantity(arg, 9_223_372_036_854_775_807)
    row = ctx.repo.conn.execute(
        "SELECT * FROM expeditions WHERE job_id=? AND user_id=?", (job_id, ctx.user_id),
    ).fetchone()
    if row is None:
        raise GameError("没有属于你的这项行程。")
    return row


def _describe(ctx: Context, row: Row) -> Reply:
    pet = ctx.repo.pet(row["pet_id"])
    commands = []
    if row["state"] == "running":
        if ctx.now >= row["finishes_at"]:
            state = "已完成，待归来领取；领取前仍占用灵宠。"
            commands.append(f"灵宠归来 {row['job_id']}")
        else:
            state = f"外出中，剩余 {row['finishes_at'] - ctx.now} 秒。"
            commands.append(f"灵宠召回 {row['job_id']}")
        commands.append(f"灵宠行程 {row['job_id']}")
    else:
        state = "奖励已领取。" if row["state"] == "claimed" else "已提前召回，无奖励，已消耗精力不退。"
    return Reply("灵宠行程", (
        f"行程 {row['job_id']} · {row['task_name']} · 灵宠：{pet.name}", state,
    ), (*commands, "灵宠委托", "灵宠列表"))


def status(ctx: Context, arg: str) -> Reply:
    ctx.player()
    row = _owned(ctx, arg) if arg else ctx.repo.conn.execute(
        "SELECT * FROM expeditions WHERE user_id=? ORDER BY job_id DESC LIMIT 1", (ctx.user_id,),
    ).fetchone()
    if row is None:
        return Reply("灵宠行程", ("尚无委托行程。",), ("灵宠委托", "灵宠列表"))
    return _describe(ctx, row)


def start(ctx: Context, arg: str) -> Reply:
    ctx.player()
    conn = ctx.repo.conn
    prior = conn.execute(
        "SELECT * FROM expeditions WHERE source_operation_id=?", (ctx.operation_id,),
    ).fetchone()
    # Retained journeys outlive the generic seven-day reply cache.
    if prior:
        if prior["user_id"] != ctx.user_id:
            raise GameError("该派遣消息已被处理，不能复用。")
        return _describe(ctx, prior)
    if conn.execute("SELECT 1 FROM expeditions WHERE user_id=? AND state='running'", (ctx.user_id,)).fetchone():
        raise GameError("已有外出委托，请先查看灵宠行程并归来或召回。")
    previous = conn.execute(
        "SELECT settled_at FROM expeditions WHERE user_id=? ORDER BY job_id DESC LIMIT 1", (ctx.user_id,),
    ).fetchone()
    if previous and previous["settled_at"] is not None and ctx.now < previous["settled_at"]:
        raise GameError("当前时间早于上次行程结算，请稍后再派遣。")
    task = named(ctx.content.expeditions, arg)
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == task.min_realm)
    if pet.realm < minimum:
        raise GameError(f"{task.name}需要{ctx.content.realms[minimum].name}境界。")
    if pet.energy < task.energy:
        raise GameError(f"{pet.name}精力不足，需要 {task.energy} 点。")
    reward = task.reward
    snapshot = RewardSnapshot(
        exp=ctx.rng.randint(reward.exp.minimum, reward.exp.maximum),
        stones=ctx.rng.randint(reward.stones.minimum, reward.stones.maximum),
        items={key: ctx.rng.randint(bounds.minimum, bounds.maximum) for key, bounds in reward.items.items()},
    )
    duration = ctx.config.spirit_pet_expedition_duration
    cursor = conn.execute(
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, started_at, "
        "finishes_at, state, reward_snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)",
        (ctx.user_id, pet.pet_id, task.id, task.name, ctx.operation_id, ctx.now, ctx.now + duration,
         snapshot.model_dump_json()),
    )
    pet.energy -= task.energy
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵宠启程", (
        f"{pet.name}出发执行{task.name}，行程 {cursor.lastrowid}。",
        f"精力 -{task.energy}，预计 {duration} 秒后完成；届时须主动归来领奖。",
        "外出及待领奖期间不能参战或养成；可切换其他闲置灵宠。",
    ), (f"灵宠行程 {cursor.lastrowid}", f"灵宠召回 {cursor.lastrowid}", "灵宠列表"))


def _require_running(row: Row) -> None:
    if row["state"] != "running":
        raise GameError("该行程已领取奖励或已召回，不能重复结算。")


def claim(ctx: Context, arg: str) -> Reply:
    if not arg:
        return status(ctx, "")
    row = _owned(ctx, arg)
    _require_running(row)
    if ctx.now < row["finishes_at"]:
        raise GameError(f"行程尚未完成，还需 {row['finishes_at'] - ctx.now} 秒。")
    snapshot = RewardSnapshot.model_validate_json(row["reward_snapshot"])
    if set(snapshot.items) - set(ctx.content.items):
        raise GameError("行程奖励所需的物品定义缺失，请联系管理员恢复内容后再领取；奖励尚未结算。")
    pet = ctx.repo.pet(row["pet_id"])
    player = ctx.player()
    ctx.repo.conn.execute(
        "UPDATE expeditions SET state='claimed', settled_at=? WHERE job_id=?", (ctx.now, row["job_id"]),
    )
    pet.exp += snapshot.exp
    player.stones += snapshot.stones
    lines = [f"{pet.name}完成{row['task_name']}，行程 {row['job_id']}。",
             f"{pet.name}修为 +{snapshot.exp}，灵石 +{snapshot.stones}。"]
    for key, amount in snapshot.items.items():
        ctx.repo.add_item(ctx.user_id, key, amount)
        if amount:
            lines.append(f"{ctx.content.items[key].name} +{amount}")
    advance(ctx, "expedition")
    return Reply("委托归来", tuple(lines), ("灵宠委托", "灵宠列表", "灵宠背包"))


def cancel(ctx: Context, arg: str) -> Reply:
    if not arg:
        return status(ctx, "")
    row = _owned(ctx, arg)
    _require_running(row)
    if ctx.now >= row["finishes_at"]:
        raise GameError(f"行程已经完成，请发送 灵宠归来 {row['job_id']} 领取奖励。")
    if ctx.now < row["started_at"]:
        raise GameError("当前时间早于出发时间，请稍后再召回。")
    ctx.repo.conn.execute(
        "UPDATE expeditions SET state='cancelled', settled_at=? WHERE job_id=?", (ctx.now, row["job_id"]),
    )
    pet = ctx.repo.pet(row["pet_id"])
    return Reply("灵宠召回", (
        f"{pet.name}已从{row['task_name']}提前返回，行程 {row['job_id']}。",
        "本次没有奖励，出发时消耗的精力不退。",
    ), ("灵宠委托", "我的灵宠"))
