"""Discoveries come from successful dig receipts; rewards share their transaction."""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.tracking_reward_content import TrackingReward
from ..utils.arguments import named, quantity
from .rewards import grant

TITLE = "灵宠寻踪图录"
CLAIM_PREFIX = "tracking_reward_"


def discoveries(ctx: Context, user_id: str) -> dict[str, set[int]]:
    # A survey knows the hidden target too; only a successful terminal dig is evidence.
    rows = ctx.repo.conn.execute(
        "SELECT DISTINCT json_extract(snapshot,'$.map.id') AS map_id, "
        "json_extract(snapshot,'$.picked') AS site FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')='tracking' "
        "AND json_extract(snapshot,'$.status')='finished' "
        "AND json_extract(snapshot,'$.event')='dig' AND json_type(snapshot,'$.found')='true' "
        "AND json_type(snapshot,'$.picked')='integer' "
        "AND json_type(snapshot,'$.target')='integer' "
        "AND json_extract(snapshot,'$.picked')=json_extract(snapshot,'$.target')", (user_id,),
    )
    result = {map_id: set() for map_id in ctx.content.tracking_maps}
    for row in rows:
        route = ctx.content.tracking_maps.get(row["map_id"])
        if route is not None and 1 <= row["site"] <= len(route.sites):
            result[route.id].add(row["site"])
    return result


def claim_id(map_id: str, threshold: int) -> str:
    return f"{CLAIM_PREFIX}{map_id}_{threshold}"


def _entries(ctx: Context, map_id: str):
    return sorted((entry for entry in ctx.content.tracking_rewards.values() if entry.map_id == map_id),
                  key=lambda entry: entry.threshold)


def _records(ctx: Context, user_id: str):
    return {row["quest_id"]: row for row in ctx.repo.conn.execute(
        "SELECT quest_id, claimed FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, CLAIM_PREFIX + "*"),
    )}


def _available(ctx: Context, entry) -> bool:
    try:
        TrackingReward.model_validate(entry.model_dump())
    except ValueError:
        return False
    return all(item in ctx.content.items for item in entry.items)


def _reward_text(ctx: Context, entry) -> str:
    if not _available(ctx, entry):
        return "奖励暂不可用"
    parts = [f"灵石 {entry.stones}"] if entry.stones else []
    parts.extend(f"{ctx.content.items[item].name} {amount}" for item, amount in entry.items.items())
    return "、".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) > 1:
        raise GameError("格式：灵宠寻踪图录 [地图名]；领奖用 灵宠寻踪领奖 地图名 档位。")
    route = named(ctx.content.tracking_maps, parts[0]) if parts else None
    registered = ctx.repo.player(ctx.user_id) is not None
    found = discoveries(ctx, ctx.user_id) if registered else {}
    records = _records(ctx, ctx.user_id) if registered else {}
    lines = ["成功挖掘的地点记入图录；同一地图同一地点只记一次，勘察、未寻获和放弃不计。"]
    links = []
    for entry_map in (route,) if route else ctx.content.tracking_maps.values():
        sites = found.get(entry_map.id, set())
        lines.append(f"{entry_map.name} · 已寻获 {len(sites)}/{len(entry_map.sites)} 处")
        if route is None:
            links.append(InlineCommand(len(lines) - 1, "查看地点", f"{TITLE} {entry_map.name}"))
        else:
            for number, name in enumerate(entry_map.sites, 1):
                lines.append(f"{number} 号 · {name} · " + ("已寻获" if number in sites else "未寻获"))
        for entry in _entries(ctx, entry_map.id):
            record = records.get(claim_id(entry_map.id, entry.threshold))
            if record is not None:
                status = "已领取" if record["claimed"] else "领取记录异常"
            elif not registered:
                status = "未结契"
            elif len(sites) < entry.threshold:
                status = f"还差 {entry.threshold - len(sites)} 处"
            else:
                status = "可领取"
            lines.append(f"{entry.threshold} 处 · {entry.name} · {_reward_text(ctx, entry)} · {status}")
            if status == "可领取" and _available(ctx, entry):
                links.append(InlineCommand(len(lines) - 1, "领取集录赏",
                                           f"灵宠寻踪领奖 {entry_map.name} {entry.threshold}"))
    if not registered:
        lines.append("尚未结契，先领养伙伴，再通过寻踪寻找各地藏物。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    commands = ("灵宠寻踪", "灵宠背包", "灵宠帮助 血脉与道具")
    if route is not None:
        commands = (TITLE, *commands)
    return Reply(TITLE, tuple(lines), commands, tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠寻踪领奖 地图名 档位，例如 灵宠寻踪领奖 竹溪旧径 1。")
    route = named(ctx.content.tracking_maps, parts[0])
    threshold = quantity(parts[1], len(route.sites))
    entry = next((entry for entry in _entries(ctx, route.id) if entry.threshold == threshold), None)
    if entry is None:
        raise GameError("此地图没有该档集录赏，请查看 灵宠寻踪图录。")
    player = ctx.player()
    key = claim_id(route.id, threshold)
    record = _records(ctx, player.user_id).get(key)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"{route.name} {threshold} 处奖励已经领取。")
        raise GameError("寻踪图录领取记录异常，请联系管理员检查存档。")
    count = len(discoveries(ctx, player.user_id)[route.id])
    if count < threshold:
        raise GameError(f"{route.name} 仅寻获 {count} 处，尚未达到 {threshold} 处。")
    if not _available(ctx, entry):
        raise GameError("奖励定义暂不可用，本次未领取；请稍后再试。")
    reward = Reward(exp=Range(minimum=0, maximum=0),
                    stones=Range(minimum=entry.stones, maximum=entry.stones),
                    items={item: Range(minimum=amount, maximum=amount) for item, amount in entry.items.items()})
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute("INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1)",
                          (player.user_id, key, count))
    return Reply(TITLE, (f"{route.name}「{entry.name}」已领取 · 已寻获 {count} 处。", *result),
                 (f"{TITLE} {route.name}", "灵宠背包", "灵宠寻踪"))


def objective_line(ctx: Context, user_id: str) -> str:
    found, records = discoveries(ctx, user_id), _records(ctx, user_id)
    pending = sum(len(found[entry.map_id]) >= entry.threshold
                  and claim_id(entry.map_id, entry.threshold) not in records and _available(ctx, entry)
                  for entry in ctx.content.tracking_rewards.values())
    return f"寻踪图录：已寻获 {sum(map(len, found.values()))} 处 · 可领 {pending} 档"
