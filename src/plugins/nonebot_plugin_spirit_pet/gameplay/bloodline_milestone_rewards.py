from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .rewards import grant

CLAIM_PREFIX = "bloodline_milestone_reward_"
PAGE_SIZE = 5
REWARD_ITEM = "bloodline_essence"
MILESTONES = (
    (1, 50, 1),
    (2, 100, 2),
    (3, 150, 3),
    (4, 250, 4),
)


def claim_id(pet_id: int, level: int) -> str:
    return f"{CLAIM_PREFIX}{pet_id}_{level}"


def claimed(ctx: Context, user_id: str, pet_id: int, level: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(pet_id, level)),
    ).fetchone()
    return bool(row and row["claimed"])


def _bloodline(ctx: Context, level: int):
    return ctx.content.bloodlines.get(level)


def _valid_level(ctx: Context, value) -> bool:
    return (
        type(value) is int
        and 0 <= value < len(ctx.content.bloodlines)
        and _bloodline(ctx, value) is not None
    )


def _reward(ctx: Context, milestone) -> Reward | None:
    _, stones, amount = milestone
    item = ctx.content.items.get(REWARD_ITEM)
    if item is None or item.kind != "material":
        return None
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={REWARD_ITEM: Range(minimum=amount, maximum=amount)},
    )


def _reward_text(ctx: Context, milestone) -> str:
    reward = _reward(ctx, milestone)
    if reward is None:
        return "奖励内容待修复"
    return f"奖励：灵石 {reward.stones.minimum}、{ctx.content.items[REWARD_ITEM].name} {milestone[2]}"


def _milestones(ctx: Context, user_id: str) -> list[dict]:
    pets = ctx.repo.conn.execute(
        "SELECT pet_id, name, bloodline, archived FROM pets WHERE user_id=? ORDER BY pet_id",
        (user_id,),
    ).fetchall()
    return [
        {"pet": pet, "milestone": milestone}
        for pet in pets
        for milestone in MILESTONES
    ]


def _state(ctx: Context, user_id: str, entry: dict) -> str:
    pet = entry["pet"]
    level = entry["milestone"][0]
    if not _valid_level(ctx, pet["bloodline"]):
        return "血脉数据异常"
    if _bloodline(ctx, level) is None:
        return "血脉定义异常"
    if claimed(ctx, user_id, pet["pet_id"], level):
        return "已领取"
    if pet["bloodline"] < level:
        return "未达成"
    return "可领取" if _reward(ctx, entry["milestone"]) is not None else "奖励待修复"


def summary(ctx: Context, user_id: str) -> str:
    entries = _milestones(ctx, user_id)
    reached = sum(
        entry["pet"]["bloodline"] >= entry["milestone"][0]
        for entry in entries
        if _valid_level(ctx, entry["pet"]["bloodline"])
    )
    available = sum(_state(ctx, user_id, entry) == "可领取" for entry in entries)
    return f"血脉进阶奖励：可领 {available} 项 · 已达成 {reached} 项"


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = []
        for milestone in MILESTONES:
            level = milestone[0]
            bloodline = _bloodline(ctx, level)
            name = bloodline.name if bloodline is not None else f"血脉 {level}"
            lines.append(f"{name} · {_reward_text(ctx, milestone)}")
        lines.append("尚未结契；陪伴伙伴进化可提升血脉。")
        return Reply("灵宠血脉赏 1/1", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    entries = _milestones(ctx, player.user_id)
    page = paginate(entries, arg, "灵宠血脉赏", "灵宠血脉赏", PAGE_SIZE)
    lines, links = [], []
    reached_count = claimed_count = 0
    for entry in page.entries:
        pet = entry["pet"]
        milestone = entry["milestone"]
        level = milestone[0]
        target = _bloodline(ctx, level)
        current = _bloodline(ctx, pet["bloodline"]) if _valid_level(ctx, pet["bloodline"]) else None
        state = _state(ctx, player.user_id, entry)
        if state == "已领取":
            claimed_count += 1
        if current is not None and pet["bloodline"] >= level:
            reached_count += 1
        archived = " · 已封存" if pet["archived"] else ""
        current_text = current.name if current is not None else "血脉数据异常"
        target_text = target.name if target is not None else f"血脉 {level}"
        lines.append(
            f"灵宠 {pet['pet_id']} · {pet['name']}{archived} · 当前{current_text} · "
            f"{target_text} · {_reward_text(ctx, milestone)} · {state}"
        )
        if state == "可领取" and target is not None:
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励",
                f"灵宠血脉领奖 {pet['pet_id']} {target.name}",
            ))

    if not entries:
        lines.append("尚无在册灵宠。")
    commands = [*page.navigation, "我的灵宠", "灵宠目标"]
    return Reply(
        f"灵宠血脉赏 {page.number}/{page.total}",
        (*lines, f"已达成 {reached_count} 项 · 本页已领取 {claimed_count} 项。"),
        tuple(commands), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠血脉领奖 宠物编号 血脉名。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    bloodline = next((entry for entry in ctx.content.bloodlines.values() if entry.name == parts[1]), None)
    milestone = next((entry for entry in MILESTONES if bloodline and entry[0] == bloodline.level), None)
    if milestone is None:
        raise GameError("未找到可领奖的血脉，请检查血脉名。")

    player = ctx.player()
    pet = ctx.repo.conn.execute(
        "SELECT name, bloodline FROM pets WHERE user_id=? AND pet_id=?",
        (player.user_id, pet_id),
    ).fetchone()
    if pet is None:
        raise GameError("没有属于你的这只灵宠。")
    if not _valid_level(ctx, pet["bloodline"]):
        raise GameError("该灵宠的血脉记录异常，请联系管理员检查存档。")
    level = milestone[0]
    if pet["bloodline"] < level:
        raise GameError(f"{pet['name']}尚未达到{bloodline.name}。")
    if claimed(ctx, player.user_id, pet_id, level):
        raise GameError(f"灵宠 {pet_id} 的{bloodline.name}进阶奖励已领取。")

    reward = _reward(ctx, milestone)
    if reward is None:
        raise GameError("血脉进阶奖励所需血脉精华定义缺失或类型错误，请联系管理员修复；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(pet_id, level), pet["bloodline"]),
    )
    return Reply("血脉进阶奖励", (
        f"灵宠 {pet_id} 达到{bloodline.name}的奖励已领取。", *result,
    ), ("灵宠血脉赏", "灵宠目标"))
