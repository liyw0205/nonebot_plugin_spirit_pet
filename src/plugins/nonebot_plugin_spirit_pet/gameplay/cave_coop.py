"""Two-player cave construction contracts, stored as durable duel snapshots."""

from datetime import datetime
from hashlib import sha256
import sqlite3

from pydantic import ValidationError

from ..application.context import Context
from ..domain.cave_coop_content import CaveCoopSnapshot
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from ..utils.time import BEIJING
from . import cave, friends

TITLE = "灵宠洞府共建"
COMMAND = "灵宠洞府 共建"
PAGE_SIZE = 5
STAGES = {
    "pending": "待好友贡献", "ready": "待主人完工", "finished": "已完工",
    "rejected": "已拒绝", "cancelled": "已取消", "expired": "已过期",
    "invalidated": "设施等级变更，已终止",
}


def _project_id(ctx: Context) -> int:
    return max(1, int(sha256(f"cave-coop:{ctx.user_id}:{ctx.operation_id}:{ctx.now}".encode()).hexdigest()[:14], 16))


def _owned(ctx: Context, user_id: str, item_id: str) -> int:
    row = ctx.repo.conn.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id)).fetchone()
    return int(row["quantity"]) if row else 0


def _validate_snapshot(ctx: Context, run: dict) -> dict:
    payload = {key: value for key, value in run.items() if key != "kind"}
    try:
        snapshot = CaveCoopSnapshot.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise GameError("共建项目快照损坏，资源与进度未变；请联系管理员核对存档。") from exc
    if snapshot.facility not in ctx.content.cave:
        raise GameError("共建设施快照与当前目录不匹配，进度保留且未结算；请联系管理员核对。")
    facility = ctx.content.cave[snapshot.facility]
    if snapshot.facility_level < snapshot.project.min_level or snapshot.facility_level >= facility.max_level:
        raise GameError("共建设施等级快照已失效，进度保留且未结算；请联系管理员核对。")
    referenced_items = set(snapshot.owner_cost_paid.items) | set(snapshot.helper_items)
    for reward in (snapshot.project.owner_reward, snapshot.project.helper_reward):
        referenced_items.update(reward.items)
    if referenced_items - set(ctx.content.items):
        raise GameError("共建物品快照缺少当前目录引用，进度保留且未结算；请联系管理员核对。")
    if snapshot.expires_at != snapshot.started_at + snapshot.project.hours * 3600:
        raise GameError("共建期限快照无效，资源与进度未变；请联系管理员核对存档。")
    return run


def _cost_text(ctx: Context, costs: dict[str, int], stones: int = 0) -> str:
    parts = [f"灵石 {stones}"] if stones else []
    parts.extend(f"{ctx.content.items[item].name} ×{amount}" for item, amount in costs.items())
    return "、".join(parts) or "无"


def _reward_text(ctx: Context, reward) -> str:
    if not isinstance(reward, dict):
        reward = reward.model_dump()
    parts = [f"灵石 {reward['stones']['minimum']}"] if reward["stones"]["minimum"] else []
    parts.extend(f"{ctx.content.items[item].name} ×{bounds['minimum']}" for item, bounds in reward.get("items", {}).items())
    return "、".join(parts) or "无"


def _active(ctx: Context, user_id: str | None = None) -> dict | None:
    try:
        row = ctx.repo.latest_cave_coop_action(user_id or ctx.user_id, active_only=True)
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise GameError("共建项目记录损坏，未写入任何状态；请联系管理员核对存档。") from exc
    return _validate_snapshot(ctx, row["snapshot"]) if row else None


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    run = _active(ctx, user_id)
    return run if run is not None and ctx.now < run["expires_at"] else None


def _record(
    ctx: Context, run: dict, reply: Reply, *, operation_id: str | None = None,
) -> Reply:
    ctx.repo.record_cave_coop_action(operation_id or ctx.operation_id, ctx.user_id, ctx.now, run, reply)
    return reply


def _refund(ctx: Context, user_id: str, cost: dict) -> list[str]:
    player = ctx.repo.player(user_id)
    if player is None:
        raise GameError("共建参与者已离开，暂不能返还项目成本。")
    player.stones += int(cost["stones"])
    lines = [f"灵石 +{cost['stones']}"] if cost["stones"] else []
    for item_id, amount in cost["items"].items():
        if item_id not in ctx.content.items:
            raise GameError("共建材料内容缺失，项目成本尚未返还。")
        ctx.repo.add_item(user_id, item_id, int(amount))
        lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return lines


def _expire(ctx: Context, run: dict, *, operation_id: str | None = None) -> Reply:
    refunds = {"owner": _refund(ctx, run["owner_id"], run["owner_cost_paid"])}
    if run["stage"] == "ready":
        refunds["helper"] = _refund(ctx, run["helper_id"], {"stones": 0, "items": run["helper_items"]})
    run.update(status="expired", stage="expired", event="expire", updated_at=ctx.now)
    run["refunds"] = refunds
    reply = Reply(
        TITLE,
        (f"项目 {run['project_id']} 已过期，未发放终章奖励；已退回双方已支付资源，请重新发起共建。",),
        (COMMAND, "灵宠洞府"),
    )
    return _record(ctx, run, reply, operation_id=operation_id)


def _expire_if_needed(ctx: Context, user_id: str | None = None) -> bool:
    run = _active(ctx, user_id)
    if run is None or ctx.now < run["expires_at"]:
        return False
    _expire(ctx, run, operation_id=f"cave-coop-expire-{run['project_id']}")
    return True


def _project(ctx: Context, project_id: int, *, helper_only: bool = False) -> dict:
    run = _active(ctx)
    if run is None or run["project_id"] != project_id:
        raise GameError("没有找到属于你的进行中共建项目。")
    if helper_only and run["helper_id"] != ctx.user_id:
        raise GameError("这项共建不是发给你的。")
    if not helper_only and run["owner_id"] != ctx.user_id:
        raise GameError("只有项目主人可以执行此操作。")
    if ctx.now < run["updated_at"]:
        raise GameError("系统时间早于最近共建操作，请等待时钟恢复；项目进度保留。")
    return run


def _pay(ctx: Context, user_id: str, reward: dict) -> list[str]:
    player = ctx.repo.player(user_id)
    if player is None:
        raise GameError("共建参与者已离开，暂不能结算。")
    stones = int(reward["stones"]["minimum"])
    player.stones += stones
    lines = [f"灵石 +{stones}"] if stones else []
    for item_id, bounds in reward.get("items", {}).items():
        amount = int(bounds["minimum"])
        if item_id not in ctx.content.items:
            raise GameError("共建奖励内容缺失，双方奖励尚未发放。")
        if amount:
            ctx.repo.add_item(user_id, item_id, amount)
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return lines


def _page_line(ctx: Context, run: dict) -> str:
    owner = ctx.repo.player(run["owner_id"])
    helper = ctx.repo.player(run["helper_id"])
    owner_label = owner.uid_label if owner else "已离去的修士"
    helper_label = helper.uid_label if helper else "已离去的修士"
    return f"项目 {run['project_id']} · {run['project_name']} · {owner_label} × {helper_label} · {STAGES[run['stage']]}"


def page(ctx: Context, argument: str = "") -> Reply:
    if argument.strip():
        raise GameError(f"格式：{COMMAND} [发起 设施 UID|同意 项目号|拒绝 项目号|取消 项目号|完工 项目号|记录 页码]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴才能参与洞府共建。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    active = _active(ctx)
    lines = ["共建需要互为好友：主人支付灵石与材料，受邀者贡献材料，主人完工后双方各得一份奖励。"]
    links = []
    if active and ctx.now >= active["expires_at"]:
        lines.append(f"项目 {active['project_id']} 已过期，可重新发起共建。")
    elif active:
        lines.append(_page_line(ctx, active))
        project_id = active["project_id"]
        if active["owner_id"] == ctx.user_id and active["stage"] == "ready":
            links.append(InlineCommand(len(lines) - 1, "完工", f"{COMMAND} 完工 {project_id}"))
        elif active["owner_id"] == ctx.user_id and active["stage"] == "pending":
            links.append(InlineCommand(len(lines) - 1, "取消", f"{COMMAND} 取消 {project_id}"))
        elif active["helper_id"] == ctx.user_id and active["stage"] == "pending":
            links.append(InlineCommand(len(lines) - 1, "同意", f"{COMMAND} 同意 {project_id}"))
            links.append(InlineCommand(len(lines) - 1, "拒绝", f"{COMMAND} 拒绝 {project_id}"))
        lines.append(f"截止：{datetime.fromtimestamp(active['expires_at'], BEIJING):%Y-%m-%d %H:%M}（北京时间）。")
    for project in sorted(ctx.content.cave_coop.values(), key=lambda item: item.id):
        facility = ctx.content.cave[project.facility]
        current = cave.level_of(ctx, facility)
        if current >= facility.max_level:
            state_text = "设施已满级"
        else:
            state_text = f"设施 Lv{current}→Lv{current + 1} · 主人成本 {_cost_text(ctx, project.owner_cost.items, project.owner_cost.stones)} · 共建者成本 {_cost_text(ctx, project.helper_items)}"
        lines.append(f"{project.name} · {state_text} · {project.hours} 小时"
                     f" · 主人奖励 {_reward_text(ctx, project.owner_reward)}"
                     f" · 共建者奖励 {_reward_text(ctx, project.helper_reward)}")
    lines.append(f"发起示例：{COMMAND} 发起 灵泉 10001。完成后设施提升一级，记录永久保留。")
    return Reply(TITLE, tuple(lines), (f"{COMMAND} 记录", "灵宠好友", "灵宠洞府", "灵宠目标"), tuple(links))


def start(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if len(parts) not in (2, 3):
        raise GameError(f"格式：{COMMAND} 发起 <设施> <好友UID>。")
    player = ctx.player()
    _expire_if_needed(ctx)
    if _active(ctx):
        raise GameError("你已有进行中的共建项目，请先完成、取消或等待对方处理。")
    facility_match = next((f.id for f in ctx.content.cave.values() if parts[0] in (f.id, f.name)), None)
    project = next((p for p in ctx.content.cave_coop.values() if p.facility == facility_match), None)
    if project is None:
        project = named(ctx.content.cave_coop, parts[0])
    target = ctx.repo.player_by_uid(" ".join(parts[1:]))
    if target is None or target.user_id == ctx.user_id:
        raise GameError("请填写有效的好友 UID，不能邀请自己。")
    if not friends.linked(ctx, ctx.user_id, target.user_id):
        raise GameError("只有互为好友的修士才能共建，请先完成好友关系。")
    _expire_if_needed(ctx, target.user_id)
    if _active(ctx, target.user_id):
        raise GameError("对方已有进行中的共建项目，请稍后再邀请。")
    facility = ctx.content.cave[project.facility]
    current = cave.level_of(ctx, facility)
    if current >= facility.max_level:
        raise GameError(f"{facility.name}已满级，不能重复共建。")
    if current < project.min_level:
        raise GameError(f"{project.name}需要设施至少达到 Lv{project.min_level}。")
    missing = [f"{ctx.content.items[item].name} {amount - _owned(ctx, ctx.user_id, item)}" for item, amount in project.owner_cost.items.items() if _owned(ctx, ctx.user_id, item) < amount]
    if player.stones < project.owner_cost.stones:
        raise GameError(f"主人灵石不足：需要 {project.owner_cost.stones}。")
    if missing:
        raise GameError(f"主人材料不足：还需{'、'.join(missing)}。")
    player.stones -= project.owner_cost.stones
    for item_id, amount in project.owner_cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    run = {"snapshot_version": 1, "status": "pending", "stage": "pending", "event": "start", "project_id": _project_id(ctx),
           "project_name": project.name, "project": project.model_dump(), "owner_id": ctx.user_id,
           "helper_id": target.user_id, "facility": project.facility, "facility_level": current,
           "owner_cost_paid": project.owner_cost.model_dump(), "helper_items": project.helper_items,
           "started_at": ctx.now, "expires_at": ctx.now + project.hours * 3600, "updated_at": ctx.now}
    return _record(ctx, run, Reply(TITLE, (
        f"已发起 {project.name}，项目号 {run['project_id']}。",
        f"已支付主人成本 {_cost_text(ctx, project.owner_cost.items, project.owner_cost.stones)}。",
        f"请 {target.uid_label} 发送 {COMMAND} 同意 {run['project_id']}。",
        f"对方贡献 {_cost_text(ctx, project.helper_items)}，有效 {project.hours} 小时。",
    ), (COMMAND, "灵宠好友", "灵宠洞府")))


def accept(ctx: Context, argument: str) -> Reply:
    project_id = quantity(argument, 9_223_372_036_854_775_807)
    run = _project(ctx, project_id, helper_only=True)
    if ctx.now >= run["expires_at"]:
        return _expire(ctx, run)
    if run["stage"] != "pending":
        raise GameError("该项目已经处理，不能重复同意。")
    if not friends.linked(ctx, run["owner_id"], ctx.user_id):
        raise GameError("你们已不是好友，不能贡献共建材料。")
    if cave.level_of(ctx, ctx.content.cave[run["facility"]], run["owner_id"]) != run["facility_level"]:
        raise GameError("主人已单独升级设施，请让主人取消项目；你的材料未扣除。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    missing = [f"{ctx.content.items[item].name} {amount - _owned(ctx, ctx.user_id, item)}" for item, amount in run["helper_items"].items() if _owned(ctx, ctx.user_id, item) < amount]
    if missing:
        raise GameError(f"贡献材料不足：还需{'、'.join(missing)}。")
    for item_id, amount in run["helper_items"].items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    run.update(status="ready", stage="ready", event="accept", contributor_id=ctx.user_id, updated_at=ctx.now)
    return _record(ctx, run, Reply(TITLE, (
        f"已同意项目 {run['project_id']}，贡献 {_cost_text(ctx, run['helper_items'])}。",
        f"请主人发送 {COMMAND} 完工 {run['project_id']}；完工时同时发放双方奖励。",
    ), (COMMAND, "灵宠洞府")))


def reject(ctx: Context, argument: str) -> Reply:
    project_id = quantity(argument, 9_223_372_036_854_775_807)
    run = _project(ctx, project_id, helper_only=True)
    if ctx.now >= run["expires_at"]:
        return _expire(ctx, run)
    if run["stage"] != "pending":
        raise GameError("该项目已经处理，不能重复拒绝。")
    cost = run["owner_cost_paid"]
    refunds = {"owner": _refund(ctx, run["owner_id"], cost)}
    run.update(status="rejected", stage="rejected", event="reject", updated_at=ctx.now, refunds=refunds)
    return _record(ctx, run, Reply(TITLE, (f"已拒绝项目 {run['project_id']}，主人成本已全额退回。",), (COMMAND, "灵宠好友")))


def cancel(ctx: Context, argument: str) -> Reply:
    project_id = quantity(argument, 9_223_372_036_854_775_807)
    run = _project(ctx, project_id)
    if ctx.now >= run["expires_at"]:
        return _expire(ctx, run)
    if run["stage"] != "pending":
        raise GameError("对方已贡献材料，项目只能完工，不能取消。")
    cost = run["owner_cost_paid"]
    refunds = {"owner": _refund(ctx, ctx.user_id, cost)}
    run.update(status="cancelled", stage="cancelled", event="cancel", updated_at=ctx.now, refunds=refunds)
    return _record(ctx, run, Reply(TITLE, (f"项目 {run['project_id']} 已取消，主人成本已退回。",), (COMMAND, "灵宠洞府")))


def complete(ctx: Context, argument: str) -> Reply:
    project_id = quantity(argument, 9_223_372_036_854_775_807)
    run = _project(ctx, project_id)
    if ctx.now >= run["expires_at"]:
        return _expire(ctx, run)
    if run["stage"] != "ready":
        raise GameError("共建者尚未贡献材料，项目还不能完工。")
    facility = ctx.content.cave[run["facility"]]
    if cave.level_of(ctx, facility) != run["facility_level"]:
        refunds = {
            "owner": _refund(ctx, run["owner_id"], run["owner_cost_paid"]),
            "helper": _refund(ctx, run["helper_id"], {"stones": 0, "items": run["helper_items"]}),
        }
        run.update(status="invalidated", stage="invalidated", event="invalidate", updated_at=ctx.now, refunds=refunds)
        return _record(ctx, run, Reply(
            TITLE,
            (f"项目 {run['project_id']} 的设施等级已被其他操作改变，已退还双方成本与贡献；请重新发起。",),
            (COMMAND, "灵宠洞府"),
        ))
    next_level = run["facility_level"] + 1
    cave._upsert(ctx, cave._level_key(facility.id), next_level)
    owner_lines = _pay(ctx, ctx.user_id, run["project"]["owner_reward"])
    helper_lines = _pay(ctx, run["helper_id"], run["project"]["helper_reward"])
    run.update(status="finished", stage="finished", event="complete", finished_at=ctx.now,
               updated_at=ctx.now, final_reward={"owner": owner_lines, "helper": helper_lines, "facility_level": next_level})
    return _record(ctx, run, Reply(TITLE, (
        f"项目 {run['project_id']} 完工：{facility.name}提升至 Lv{next_level}。",
        f"主人奖励：{'、'.join(owner_lines) or '无'}。",
        f"共建者奖励：{'、'.join(helper_lines) or '无'}。",
    ), (COMMAND, "灵宠洞府", "灵宠目标")))


def history(ctx: Context, argument: str) -> Reply:
    entries = ctx.repo.cave_coop_history(ctx.user_id)
    page_data = paginate(entries, argument, TITLE + "记录", f"{COMMAND} 记录", PAGE_SIZE)
    lines = [f"第 {page_data.number}/{page_data.total} 页 · 共 {len(entries)} 项。"]
    for entry in page_data.entries:
        run = _validate_snapshot(ctx, entry["snapshot"])
        when = datetime.fromtimestamp(int(run["started_at"]), BEIJING).strftime("%Y-%m-%d %H:%M")
        role = "主人" if run["owner_id"] == ctx.user_id else "共建者"
        result = run.get("final_reward") or run.get("refunds") or {}
        rewards = result.get("owner" if role == "主人" else "helper", [])
        suffix = f" · {'、'.join(rewards)}" if rewards else ""
        lines.append(f"项目 {run['project_id']} · {run['project_name']} · {role} · {STAGES[run['stage']]} · {when}{suffix}")
    return Reply(f"{TITLE}记录 {page_data.number}/{page_data.total}", tuple(lines), (*page_data.navigation, COMMAND, "灵宠洞府"))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return page(ctx)
    head, rest = parts[0], " ".join(parts[1:])
    if head == "发起":
        return start(ctx, rest)
    if head == "同意":
        return accept(ctx, rest)
    if head == "拒绝":
        return reject(ctx, rest)
    if head == "取消":
        return cancel(ctx, rest)
    if head == "完工":
        return complete(ctx, rest)
    if head == "记录":
        return history(ctx, rest)
    raise GameError(f"格式：{COMMAND} [发起 设施 UID|同意 项目号|拒绝 项目号|取消 项目号|完工 项目号|记录 页码]。")


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx, user_id)
    if run is None:
        return "洞府共建：暂无进行中的项目"
    role = "主人" if run["owner_id"] == user_id else "共建者"
    return f"洞府共建：项目 {run['project_id']} · {role} · {STAGES[run['stage']]}"


__all__ = ["TITLE", "dispatch", "objective_line", "state"]
