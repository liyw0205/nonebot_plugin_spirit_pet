"""Friend-only shared cooking for two named pets."""

from datetime import datetime
from hashlib import sha256
import sqlite3

from pydantic import ValidationError

from ..application.context import Context
from ..domain.cuisine_coop_state import COOK_TOGETHER_SECONDS, CuisineCoopSnapshot
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.state import Pet
from ..utils.arguments import named, quantity
from ..utils.energy import add_energy, restore_energy
from ..utils.time import BEIJING, beijing_day
from . import cuisine, friends, pet_targets

TITLE = "灵宠合膳"
PAGE_SIZE = 5
FORMAT = "灵宠合膳 预览 菜名 伙伴编号 好友UID"
STATES = {
    "pending": "待好友选宠并投入",
    "ready": "待主人完成",
    "finished": "已完成",
    "rejected": "已拒绝并退款",
    "cancelled": "已取消并退款",
    "expired": "已到期并退款",
}


def _validate(ctx: Context, data: dict | None) -> CuisineCoopSnapshot | None:
    if data is None:
        return None
    try:
        run = CuisineCoopSnapshot.model_validate(data)
    except (ValidationError, TypeError, ValueError) as exc:
        raise GameError("合膳项目快照损坏，双方资源与伙伴进度保留；请联系管理员核对存档。") from exc
    missing = set(run.ingredients) | {run.item_id}
    if missing - set(ctx.content.items):
        raise GameError("合膳快照引用的物品内容缺失，资源与进度保留；请联系管理员核对存档。")
    if ctx.content.items[run.item_id].kind != "consumable":
        raise GameError("合膳成品快照已不再是可食用单膳，资源与进度保留；请联系管理员核对。")
    return run


def _latest(ctx: Context, user_id: str | None = None, *, active_only: bool = False) -> CuisineCoopSnapshot | None:
    try:
        row = ctx.repo.latest_cuisine_coop_action(user_id or ctx.user_id, active_only=active_only)
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("合膳项目记录损坏，未写入任何状态；请联系管理员核对存档。") from exc
    return _validate(ctx, row["snapshot"]) if row else None


def active(ctx: Context, user_id: str | None = None) -> CuisineCoopSnapshot | None:
    run = _latest(ctx, user_id, active_only=True)
    return run if run is not None and run.status in {"pending", "ready"} else None


def _project(ctx: Context, value: str) -> CuisineCoopSnapshot:
    project_id = quantity(value, 9_223_372_036_854_775_807)
    try:
        row = ctx.repo.cuisine_coop_project(ctx.user_id, project_id)
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("合膳项目记录损坏，未写入任何状态；请联系管理员核对存档。") from exc
    run = _validate(ctx, row["snapshot"]) if row else None
    if run is None:
        raise GameError("没有找到属于你的合膳项目。")
    return run


def _pet(ctx: Context, user_id: str, value: str, action: str) -> Pet:
    if user_id == ctx.user_id:
        pet = pet_targets.named_pet(ctx, value, action, refresh_energy=False)
    else:
        raise ValueError("pets can only be selected by their owner")
    if ctx.repo.active_expedition(pet.pet_id) is not None:
        raise GameError(f"{pet.name}正在外出派遣，归来后才能参与合膳。")
    return pet


def _pet_for(ctx: Context, user_id: str, pet_id: int) -> Pet:
    pet = next((candidate for candidate in ctx.repo.owned_pets(user_id) if candidate.pet_id == pet_id), None)
    if pet is None:
        raise GameError("合膳指定伙伴已不在该主人名册；项目保留，可取消并退款。")
    if ctx.repo.active_expedition(pet_id) is not None:
        raise GameError(f"{pet.name}正在外出派遣，归来后才能完成合膳；项目保留。")
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    return pet


def _ingredient_cost(ctx: Context, run: CuisineCoopSnapshot) -> str:
    parts = [f"灵石 {run.stones}"] if run.stones else []
    parts.extend(f"{run.ingredient_names[item]} ×{amount}" for item, amount in run.ingredients.items())
    return "、".join(parts) or "无材料成本"


def _owned(ctx: Context, user_id: str, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _shortage(ctx: Context, user_id: str, dish) -> str | None:
    player = ctx.repo.player(user_id)
    if player is None:
        return "参与者尚未结契。"
    if player.stones < dish.stones:
        return f"灵石不足：每人需 {dish.stones}，当前 {player.stones}。"
    for item_id, amount in dish.ingredients.items():
        owned = _owned(ctx, user_id, item_id)
        if owned < amount:
            return f"{ctx.content.items[item_id].name}不足：每人需 {amount}，当前 {owned}。"
    return None


def _terms(ctx: Context, parts: list[str]):
    if len(parts) != 3:
        raise GameError(f"格式：{FORMAT}；双方各投入一份菜谱成本。")
    player = ctx.player()
    dish = named(ctx.content.cuisine, parts[0])
    if dish.item is None:
        raise GameError("合膳只接受产出单人份成品的既有菜谱，不含全体宴席。")
    if cuisine.level(ctx) < dish.level:
        raise GameError(f"厨艺不足：{dish.name}需要厨艺 {dish.level} 级，当前 {cuisine.level(ctx)} 级。")
    pet = _pet(ctx, ctx.user_id, parts[1], "合膳")
    target = friends._target(ctx, parts[2], player)
    if not friends.linked(ctx, ctx.user_id, target.user_id):
        raise GameError("合膳需要双方已经成为好友，请先完成结交。")
    for owner in (ctx.user_id, target.user_id):
        run = active(ctx, owner)
        if run is not None:
            raise GameError("你或对方已有进行中的合膳，请先完成、拒绝、取消或等待退款。")
        latest = _latest(ctx, owner)
        if latest is not None and ctx.now < latest.updated_at:
            raise GameError("系统时间早于最近合膳操作，请等待时钟恢复。")
    shortage = _shortage(ctx, ctx.user_id, dish)
    if shortage:
        raise GameError(f"主人{shortage}")
    return dish, pet, target


def _make_snapshot(ctx: Context, dish, pet: Pet, target, project_id: int) -> CuisineCoopSnapshot:
    return CuisineCoopSnapshot(
        project_id=project_id,
        owner_id=ctx.user_id,
        helper_id=target.user_id,
        owner_pet_id=pet.pet_id,
        owner_pet_name=pet.name,
        dish_id=dish.id,
        dish_name=dish.name,
        item_id=dish.item,
        item_name=ctx.content.items[dish.item].name,
        ingredients=dict(dish.ingredients),
        ingredient_names={item_id: ctx.content.items[item_id].name for item_id in dish.ingredients},
        stones=dish.stones,
        heat=dish.heat,
        effects=cuisine._dish_effects(ctx, dish),
        status="pending",
        event="start",
        started_at=ctx.now,
        expires_at=ctx.now + COOK_TOGETHER_SECONDS,
        updated_at=ctx.now,
    )


def _pay_cost(ctx: Context, user_id: str, run: CuisineCoopSnapshot) -> None:
    player = ctx.repo.player(user_id)
    if player is None:
        raise GameError("参与者尚未结契。")
    if player.stones < run.stones:
        raise GameError(f"灵石不足：每人需 {run.stones}，当前 {player.stones}。")
    missing = [
        f"{run.ingredient_names[item]} {amount - _owned(ctx, user_id, item)}"
        for item, amount in run.ingredients.items() if _owned(ctx, user_id, item) < amount
    ]
    if missing:
        raise GameError(f"合膳材料不足：还需{'、'.join(missing)}。")
    player.stones -= run.stones
    for item, amount in run.ingredients.items():
        ctx.repo.consume_item(user_id, item, amount)


def _refund(ctx: Context, user_id: str, run: CuisineCoopSnapshot) -> list[str]:
    player = ctx.repo.player(user_id)
    if player is None:
        raise GameError("合膳参与者已离开，暂不能退还资源。")
    player.stones += run.stones
    lines = [f"灵石 +{run.stones}"] if run.stones else []
    for item, amount in run.ingredients.items():
        ctx.repo.add_item(user_id, item, amount)
        lines.append(f"{run.ingredient_names[item]} +{amount}")
    return lines


def _record(ctx: Context, run: CuisineCoopSnapshot, reply: Reply) -> Reply:
    ctx.repo.record_cuisine_coop_action(
        ctx.operation_id, ctx.user_id, ctx.now, run.model_dump(), reply,
    )
    return reply


def _display(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    return player.uid_label if player else "已离去的修士"


def _detail(ctx: Context, run: CuisineCoopSnapshot) -> Reply:
    mine = run.owner_id == ctx.user_id
    own_pet_id = run.owner_pet_id if mine else run.helper_pet_id
    own_pet_name = run.owner_pet_name if mine else run.helper_pet_name
    other_id = run.helper_id if mine else run.owner_id
    other_pet = run.helper_pet_name if mine else run.owner_pet_name
    expired = run.status in {"pending", "ready"} and ctx.now >= run.expires_at
    state = "已到期，待退款" if expired else STATES[run.status]
    deadline = datetime.fromtimestamp(run.expires_at, BEIJING).strftime("%Y-%m-%d %H:%M")
    own_state = "尚未选宠/投入" if own_pet_id is None else f"{own_pet_name}（编号 {own_pet_id}）已投入"
    other_state = "尚未选宠/投入" if other_pet is None else f"{other_pet} 已投入"
    lines = [
        f"项目 {run.project_id} · {state} · 道友 {_display(ctx, other_id)}。",
        f"菜谱：{run.dish_name} ×2；你的伙伴：{own_state}；对方伙伴：{other_state}。",
        f"每人投入 {_ingredient_cost(ctx, run)}，各用灶火 {run.heat}；完成时双方伙伴各获 {_effect_text(run.effects)}。",
        f"截止 {deadline}（北京时间）；灶火仅在完成日扣除，拒绝/取消/到期只退已付灵石与材料。",
    ]
    commands: list[str] = []
    links = []
    if expired:
        commands.append(f"{TITLE} 退款 {run.project_id}")
    elif run.status == "pending":
        if mine:
            commands.append(f"{TITLE} 取消 {run.project_id}")
        else:
            links.append(InlineCommand(1, "选伙伴并同意", f"{TITLE} 同意 {run.project_id} "))
            commands.append(f"{TITLE} 拒绝 {run.project_id}")
    elif run.status == "ready" and mine:
        commands.extend((f"{TITLE} 完成 {run.project_id}", f"{TITLE} 取消 {run.project_id}"))
    elif run.status == "finished":
        lines.append("两位指定伙伴各食一份，成长与双方厨艺进度已同事务记录；没有额外物品奖励。")
    elif run.status in {"rejected", "cancelled", "expired"}:
        refunds = run.refunds or {}
        own_refund = refunds.get("owner" if mine else "helper", [])
        lines.append(f"你的投入已退回：{'、'.join(own_refund) or '无'}。")
    commands.extend((f"{TITLE} 记录", "灵宠膳房", "灵宠好友"))
    return Reply(f"{TITLE} · 项目 {run.project_id}", tuple(lines), tuple(commands[:4]), tuple(links))


def preview(ctx: Context, parts: list[str]) -> Reply:
    dish, pet, target = _terms(ctx, parts)
    cost = [f"灵石 {dish.stones}"] if dish.stones else []
    cost.extend(f"{ctx.content.items[item].name} ×{amount}" for item, amount in dish.ingredients.items())
    command = f"{TITLE} 发起 {dish.name} {pet.pet_id} {target.uid}"
    return Reply(TITLE + " · 预览", (
        f"与 {target.uid_label} 合做 {dish.name}：你指定 {pet.name}（编号 {pet.pet_id}），对方同意时指定自己的伙伴。",
        f"双方各投入一份成本：{'、'.join(cost) or '无灵石与材料'}；完成时各扣灶火 {dish.heat}，双方伙伴各获 {_effect_text(cuisine._dish_effects(ctx, dish))}。",
        "邀请有效 24 小时；拒绝、取消、到期会退还已付灵石与材料。灶火只在完成日扣除。",
    ), (command, TITLE, "灵宠膳房", "灵宠好友"))


def start(ctx: Context, parts: list[str]) -> Reply:
    dish, pet, target = _terms(ctx, parts)
    project_id = max(1, int(sha256(f"cuisine-coop:{ctx.user_id}:{ctx.operation_id}".encode()).hexdigest()[:14], 16))
    run = _make_snapshot(ctx, dish, pet, target, project_id)
    _pay_cost(ctx, ctx.user_id, run)
    reply = Reply(TITLE, (
        f"已邀请 {target.uid_label} 合做 {run.dish_name}，项目号 {project_id}。",
        f"你已投入一份成本 {_ingredient_cost(ctx, run)}；对方同意时投入自己的份额并选择伙伴。",
        f"请对方发送 {TITLE} 同意 {project_id} <伙伴编号>；有效 24 小时。",
    ), (TITLE, "灵宠好友", "灵宠膳房"))
    return _record(ctx, run, reply)


def _expire(ctx: Context, run: CuisineCoopSnapshot) -> Reply:
    refunds = {"owner": _refund(ctx, run.owner_id, run)}
    if run.status == "ready":
        refunds["helper"] = _refund(ctx, run.helper_id, run)
    ended = CuisineCoopSnapshot.model_validate({
        **run.model_dump(), "status": "expired", "event": "expire", "updated_at": ctx.now,
        "refunds": refunds,
    })
    return _record(ctx, ended, Reply(TITLE, (
        f"合膳项目 {run.project_id} 已到期，双方已支付的灵石与材料已退回，灶火未扣。",
    ), (TITLE, "灵宠膳房", "灵宠好友")))


def accept(ctx: Context, project_value: str, pet_value: str) -> Reply:
    run = _project(ctx, project_value)
    if ctx.user_id != run.helper_id:
        raise GameError("只有受邀好友本人可以同意合膳。")
    if run.status != "pending":
        raise GameError("该合膳项目已经处理，不能重复同意。")
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近合膳操作，请等待时钟恢复；项目保留。")
    if ctx.now >= run.expires_at:
        return _expire(ctx, run)
    if not friends.linked(ctx, run.owner_id, run.helper_id):
        raise GameError("双方已解除好友，不能同意合膳；发起者可取消退款。")
    pet = _pet(ctx, ctx.user_id, pet_value, "合膳")
    _pay_cost(ctx, ctx.user_id, run)
    ready = CuisineCoopSnapshot.model_validate({
        **run.model_dump(), "helper_pet_id": pet.pet_id, "helper_pet_name": pet.name,
        "status": "ready", "event": "accept", "updated_at": ctx.now,
    })
    return _record(ctx, ready, Reply(TITLE, (
        f"已同意项目 {run.project_id}：你指定 {pet.name}（编号 {pet.pet_id}），并投入一份成本 {_ingredient_cost(ctx, run)}。",
        "请主人完成合膳；双方灶火只在完成日扣除。",
    ), (TITLE, "灵宠膳房", "我的灵宠")))


def reject(ctx: Context, project_value: str) -> Reply:
    run = _project(ctx, project_value)
    if ctx.user_id != run.helper_id:
        raise GameError("只有受邀好友本人可以拒绝合膳。")
    if run.status != "pending":
        raise GameError("该合膳项目已经处理，不能重复拒绝。")
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近合膳操作，请等待时钟恢复；项目保留。")
    if ctx.now >= run.expires_at:
        return _expire(ctx, run)
    refunds = {"owner": _refund(ctx, run.owner_id, run)}
    ended = CuisineCoopSnapshot.model_validate({
        **run.model_dump(), "status": "rejected", "event": "reject", "updated_at": ctx.now,
        "refunds": refunds,
    })
    return _record(ctx, ended, Reply(TITLE, (
        f"已拒绝项目 {run.project_id}，主人已付的一份灵石与材料已退回。",
    ), (TITLE, "灵宠好友")))


def cancel(ctx: Context, project_value: str) -> Reply:
    run = _project(ctx, project_value)
    if ctx.user_id != run.owner_id:
        raise GameError("只有发起者可以取消合膳。")
    if run.status not in {"pending", "ready"}:
        raise GameError("该合膳项目已经处理，不能重复取消。")
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近合膳操作，请等待时钟恢复；项目保留。")
    if ctx.now >= run.expires_at:
        return _expire(ctx, run)
    refunds = {"owner": _refund(ctx, run.owner_id, run)}
    if run.status == "ready":
        refunds["helper"] = _refund(ctx, run.helper_id, run)
    ended = CuisineCoopSnapshot.model_validate({
        **run.model_dump(), "status": "cancelled", "event": "cancel", "updated_at": ctx.now,
        "refunds": refunds,
    })
    return _record(ctx, ended, Reply(TITLE, (
        f"合膳项目 {run.project_id} 已取消，双方已付灵石与材料全额退回；灶火未扣。",
    ), (TITLE, "灵宠膳房", "灵宠好友")))


def _spend_heat(ctx: Context, user_id: str, amount: int) -> None:
    quest_id = f"{cuisine.HEAT_PREFIX}{beijing_day(ctx.now)}"
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (user_id, quest_id, amount),
    )


def complete(ctx: Context, project_value: str) -> Reply:
    run = _project(ctx, project_value)
    if ctx.user_id != run.owner_id:
        raise GameError("只有发起者可以完成合膳。")
    if run.status != "ready":
        raise GameError("好友尚未选宠并投入成本，合膳还不能完成。")
    if ctx.now < run.updated_at:
        raise GameError("系统时间早于最近合膳操作，请等待时钟恢复；项目保留。")
    if ctx.now >= run.expires_at:
        return _expire(ctx, run)
    if not friends.linked(ctx, run.owner_id, run.helper_id):
        raise GameError("双方已解除好友，合膳不能完成；你可取消并退还双方投入。")
    owner_pet = _pet_for(ctx, run.owner_id, run.owner_pet_id)
    helper_pet = _pet_for(ctx, run.helper_id, run.helper_pet_id)
    for user_id in (run.owner_id, run.helper_id):
        left = cuisine.heat_left(ctx, user_id)
        if left < run.heat:
            raise GameError(f"{_display(ctx, user_id)}今日灶火不足：完成合膳需 {run.heat}，当前剩 {left}；项目保留。")

    _spend_heat(ctx, run.owner_id, run.heat)
    _spend_heat(ctx, run.helper_id, run.heat)
    for pet in (owner_pet, helper_pet):
        add_energy(pet, run.effects.energy, ctx.now)
        pet.exp += run.effects.exp
        pet.affinity = min(100, pet.affinity + run.effects.affinity)
    ctx.repo.invalidate_ready(run.owner_id)
    ctx.repo.invalidate_ready(run.helper_id)
    for user_id in (run.owner_id, run.helper_id):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
            (user_id, f"{cuisine.DISH_PREFIX}{run.dish_id}"),
        )
    settlement = {
        "owner": [f"{run.owner_pet_name}：{_effect_text(run.effects)}"],
        "helper": [f"{run.helper_pet_name}：{_effect_text(run.effects)}"],
    }
    finished = CuisineCoopSnapshot.model_validate({
        **run.model_dump(), "status": "finished", "event": "complete", "updated_at": ctx.now,
        "finished_at": ctx.now, "settlement": settlement,
    })
    return _record(ctx, finished, Reply(TITLE, (
        f"项目 {run.project_id} 合膳完成：{run.dish_name} ×2。",
        f"主人伙伴 {run.owner_pet_name} {_effect_text(run.effects)}；好友伙伴 {run.helper_pet_name} {_effect_text(run.effects)}。",
        f"双方各消耗灶火 {run.heat}；今日剩余 {_display(ctx, run.owner_id)} {cuisine.heat_left(ctx, run.owner_id)}、{_display(ctx, run.helper_id)} {cuisine.heat_left(ctx, run.helper_id)}。",
        "双方该菜谱厨艺进度各 +1；没有额外物品或经济奖励。",
    ), (TITLE, "灵宠膳房", "灵宠目标")))


def _effect_text(effects) -> str:
    parts = []
    if effects.energy:
        parts.append(f"精力 +{effects.energy}")
    if effects.exp:
        parts.append(f"修为 +{effects.exp}")
    if effects.affinity:
        parts.append(f"亲密 +{effects.affinity}")
    return "、".join(parts) or "无成长效果"


def _history(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) > 1:
        raise GameError(f"格式：{TITLE} 记录 [页码]。")
    number = quantity(parts[0], 999) if parts else 1
    try:
        rows = ctx.repo.cuisine_coop_history(ctx.user_id)
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("合膳历史记录损坏；未修改资源或伙伴进度，请联系管理员核对存档。") from exc
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if number > pages:
        raise GameError(f"合膳记录共 {pages} 页。")
    selected = rows[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]
    lines = [f"共 {len(rows)} 项已处理合膳 · 第 {number}/{pages} 页。"]
    links = []
    for entry in selected:
        run = _validate(ctx, entry["snapshot"])
        role = "主人" if run.owner_id == ctx.user_id else "好友"
        pet_name = run.owner_pet_name if role == "主人" else run.helper_pet_name or "未选宠"
        lines.append(f"项目 {run.project_id} · {run.dish_name} · {role}伙伴 {pet_name} · {STATES[run.status]}。")
        links.append(InlineCommand(len(lines) - 1, "查看详情", f"{TITLE} 详情 {run.project_id}"))
    commands = []
    if number > 1:
        commands.append(f"{TITLE} 记录 {number - 1}")
    if number < pages:
        commands.append(f"{TITLE} 记录 {number + 1}")
    return Reply(TITLE + " · 记录", tuple(lines), (*commands, TITLE, "灵宠膳房"), tuple(links))


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("先领养伙伴，再与好友各出一份单膳，共同照料指定伙伴。",),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    run = active(ctx)
    if run is not None:
        return _detail(ctx, run)
    return Reply(TITLE, (
        "与好友各出一份既有单膳菜谱的材料和灵石，指定各自伙伴；完成时两宠各食一份。",
        "只支持产出单人份成品的菜谱，不含宴席。每人同时只能参与一个项目；期限 24 小时。",
        "拒绝、取消或到期返还已付材料与灵石；灶火只在完成日从双方当日预算扣除。",
        f"{FORMAT}。",
    ), (f"{TITLE} 记录", "灵宠膳房", "灵宠好友", "我的灵宠"))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return page(ctx)
    action, rest = parts[0], parts[1:]
    if action == "记录":
        return _history(ctx, rest)
    if action == "预览":
        return preview(ctx, rest)
    if action == "发起":
        return start(ctx, rest)
    if action == "同意" and len(rest) == 2:
        return accept(ctx, rest[0], rest[1])
    if action == "拒绝" and len(rest) == 1:
        return reject(ctx, rest[0])
    if action == "取消" and len(rest) == 1:
        return cancel(ctx, rest[0])
    if action == "完成" and len(rest) == 1:
        return complete(ctx, rest[0])
    if action == "退款" and len(rest) == 1:
        run = _project(ctx, rest[0])
        if ctx.now < run.updated_at:
            raise GameError("系统时间早于最近合膳操作，请等待时钟恢复；项目保留。")
        if run.status not in {"pending", "ready"} or ctx.now < run.expires_at:
            raise GameError("合膳项目尚未到期或已处理。")
        return _expire(ctx, run)
    if action == "详情" and len(rest) == 1:
        return _detail(ctx, _project(ctx, rest[0]))
    raise GameError(
        f"格式：{FORMAT}，或 {TITLE} 发起 菜名 伙伴编号 好友UID / 同意 项目号 伙伴编号 / 拒绝、取消、完成、退款、详情 项目号 / 记录 页码。"
    )


def objective_line(ctx: Context, user_id: str) -> str:
    run = active(ctx, user_id)
    if run is None:
        return "合膳：暂无进行中的项目"
    status = "已到期，待退款" if ctx.now >= run.expires_at else STATES[run.status]
    role = "主人" if run.owner_id == user_id else "受邀好友"
    return f"合膳：项目 {run.project_id} · {role} · {status}"


__all__ = ["TITLE", "active", "dispatch", "objective_line"]
