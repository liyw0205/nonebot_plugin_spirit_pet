from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .rewards import grant

CLAIM_PREFIX = "realm_milestone_reward_"
REWARD_ITEM = "exp_pill"
PAGE_SIZE = 5


def claim_id(pet_id: int, realm_id: str) -> str:
    return f"{CLAIM_PREFIX}{pet_id}_{realm_id}"


def claimed(ctx: Context, user_id: str, pet_id: int, realm_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(pet_id, realm_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(ctx: Context, realm_index: int) -> Reward | None:
    item = ctx.content.items.get(REWARD_ITEM)
    if item is None or item.kind != "consumable" or item.effects.exp <= 0:
        return None
    stones = realm_index * 10
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={REWARD_ITEM: Range(minimum=1, maximum=1)},
    )


def _summary(ctx: Context, realm_index: int) -> str:
    reward = _reward(ctx, realm_index)
    if reward is None:
        return "奖励内容待修复"
    return f"奖励：灵石 {reward.stones.minimum}、{ctx.content.items[REWARD_ITEM].name} 1"


def _milestones(ctx: Context, user_id: str) -> list[dict]:
    pets = ctx.repo.conn.execute(
        "SELECT pet_id, name, realm, archived FROM pets WHERE user_id=? ORDER BY pet_id",
        (user_id,),
    ).fetchall()
    result = []
    realms = ctx.content.realms
    for pet in pets:
        if not 0 <= pet["realm"] < len(realms):
            result.append({"pet": pet, "realm_index": None, "realm": None})
            continue
        for realm_index in range(1, pet["realm"] + 1):
            realm = realms[realm_index]
            result.append({"pet": pet, "realm_index": realm_index, "realm": realm})
    return result


def _state(ctx: Context, user_id: str, entry: dict) -> str:
    realm_index = entry["realm_index"]
    if realm_index is None:
        return "境界数据异常"
    if _reward(ctx, realm_index) is None:
        return "奖励待修复"
    return "已领取" if claimed(
        ctx, user_id, entry["pet"]["pet_id"], entry["realm"].id,
    ) else "可领取"


def claimable(ctx: Context, user_id: str) -> list[dict]:
    return [
        entry for entry in _milestones(ctx, user_id)
        if _state(ctx, user_id, entry) == "可领取"
    ]


def summary(ctx: Context, user_id: str) -> str:
    entries = _milestones(ctx, user_id)
    reached = sum(entry["realm_index"] is not None for entry in entries)
    available = sum(_state(ctx, user_id, entry) == "可领取" for entry in entries)
    return f"境界里程碑奖励：可领 {available} 项 · 已达成 {reached} 项"


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠境界赏 1/1", ("尚未结契，先完成领养，再陪伴伙伴踏入更高境界。",),
            ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )

    entries = _milestones(ctx, player.user_id)
    page = paginate(entries, arg, "灵宠境界赏", "灵宠境界赏", PAGE_SIZE)
    lines, links = [], []
    claimed_count = 0
    reached_count = sum(entry["realm_index"] is not None for entry in entries)
    for entry in page.entries:
        pet = entry["pet"]
        realm_index = entry["realm_index"]
        if realm_index is None:
            lines.append(f"灵宠 {pet['pet_id']} · {pet['name']} · 境界数据异常 · 暂不可领取")
            continue
        realm = entry["realm"]
        state = _state(ctx, player.user_id, entry)
        if state == "已领取":
            claimed_count += 1
        archived = " · 已封存" if pet["archived"] else ""
        lines.append(
            f"灵宠 {pet['pet_id']} · {pet['name']}{archived} · {realm.name} · "
            f"{_summary(ctx, realm_index)} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取境界奖励",
                f"灵宠境界领奖 {pet['pet_id']} {realm.name}",
            ))

    if not entries:
        lines.append("尚未达到凝气境。")
    commands = [*page.navigation, "我的灵宠", "灵宠目标"]
    return Reply(
        f"灵宠境界赏 {page.number}/{page.total}",
        (*lines, f"已达成 {reached_count} 项 · 本页已领取 {claimed_count} 项。"),
        tuple(commands), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        raise GameError("格式：灵宠境界领奖 宠物编号 境界名。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    realm = next((entry for entry in ctx.content.realms if entry.name == parts[1]), None)
    if realm is None or realm.id == ctx.content.realms[0].id:
        raise GameError("未找到可领奖的大境界，请检查境界名。")

    player = ctx.player()
    pet = ctx.repo.conn.execute(
        "SELECT name, realm, archived FROM pets WHERE user_id=? AND pet_id=?",
        (player.user_id, pet_id),
    ).fetchone()
    if pet is None:
        raise GameError("没有属于你的这只灵宠。")
    if not 0 <= pet["realm"] < len(ctx.content.realms):
        raise GameError("该灵宠的境界记录异常，请联系管理员检查存档。")
    realm_index = next(index for index, entry in enumerate(ctx.content.realms) if entry.id == realm.id)
    if pet["realm"] < realm_index:
        raise GameError(f"{pet['name']}尚未达到{realm.name}境界。")
    if claimed(ctx, player.user_id, pet_id, realm.id):
        raise GameError(f"灵宠 {pet_id} 的{realm.name}境界奖励已领取。")

    reward = _reward(ctx, realm_index)
    if reward is None:
        raise GameError("境界奖励所需蕴灵丹定义缺失或类型错误，请联系管理员修复；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1, claimed=1",
        (player.user_id, claim_id(pet_id, realm.id)),
    )
    return Reply("境界里程碑奖励", (
        f"灵宠 {pet_id} 踏入{realm.name}境界的奖励已领取。", *result,
    ), ("灵宠境界赏", "灵宠目标"))
