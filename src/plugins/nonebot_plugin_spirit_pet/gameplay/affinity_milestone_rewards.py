from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .rewards import grant

CLAIM_PREFIX = "affinity_milestone_reward_"
PAGE_SIZE = 5
MILESTONES = (
    (25, "初识", 20, "spirit_food", 1, "consumable"),
    (50, "相知", 40, "affinity_pill", 1, "consumable"),
    (75, "默契", 60, "energy_pill", 1, "consumable"),
    (100, "同心", 100, "bloodline_essence", 2, "material"),
)


def claim_id(pet_id: int, threshold: int) -> str:
    return f"{CLAIM_PREFIX}{pet_id}_{threshold}"


def claimed(ctx: Context, user_id: str, pet_id: int, threshold: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(pet_id, threshold)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(ctx: Context, milestone) -> Reward | None:
    _, _, stones, item_id, amount, expected_kind = milestone
    item = ctx.content.items.get(item_id)
    if item is None or item.kind != expected_kind:
        return None
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount)},
    )


def _reward_text(ctx: Context, milestone) -> str:
    reward = _reward(ctx, milestone)
    if reward is None:
        return "奖励内容待修复"
    item_id, amount = milestone[3], milestone[4]
    return f"奖励：灵石 {reward.stones.minimum}、{ctx.content.items[item_id].name} {amount}"


def _milestones(ctx: Context, user_id: str) -> list[dict]:
    pets = ctx.repo.conn.execute(
        "SELECT pet_id, name, affinity, archived FROM pets WHERE user_id=? ORDER BY pet_id",
        (user_id,),
    ).fetchall()
    return [
        {"pet": pet, "milestone": milestone}
        for pet in pets
        for milestone in MILESTONES
    ]


def _valid_affinity(value) -> bool:
    return type(value) is int and 0 <= value <= 100


def _state(ctx: Context, user_id: str, entry: dict) -> str:
    pet = entry["pet"]
    threshold = entry["milestone"][0]
    if not _valid_affinity(pet["affinity"]):
        return "亲密数据异常"
    if claimed(ctx, user_id, pet["pet_id"], threshold):
        return "已领取"
    if pet["affinity"] < threshold:
        return "未达成"
    return "可领取" if _reward(ctx, entry["milestone"]) is not None else "奖励待修复"


def claimable(ctx: Context, user_id: str) -> list[dict]:
    return [
        entry for entry in _milestones(ctx, user_id)
        if _state(ctx, user_id, entry) == "可领取"
    ]


def summary(ctx: Context, user_id: str) -> str:
    entries = _milestones(ctx, user_id)
    reached = sum(
        entry["pet"]["affinity"] >= entry["milestone"][0]
        for entry in entries
        if _valid_affinity(entry["pet"]["affinity"])
    )
    available = sum(_state(ctx, user_id, entry) == "可领取" for entry in entries)
    return f"亲密里程碑奖励：可领 {available} 项 · 已达成 {reached} 项"


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            f"亲密 {milestone[0]} · {milestone[1]} · {_reward_text(ctx, milestone)}"
            for milestone in MILESTONES
        ]
        lines.append("尚未结契；与伙伴互动、喂养可逐步提升亲密。")
        return Reply("灵宠亲密赏 1/1", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    entries = _milestones(ctx, player.user_id)
    page = paginate(entries, arg, "灵宠亲密赏", "灵宠亲密赏", PAGE_SIZE)
    lines, links = [], []
    claimed_count = 0
    reached_count = 0
    for entry in page.entries:
        pet = entry["pet"]
        milestone = entry["milestone"]
        threshold, name = milestone[:2]
        state = _state(ctx, player.user_id, entry)
        valid_affinity = _valid_affinity(pet["affinity"])
        if state == "已领取":
            claimed_count += 1
        if valid_affinity and pet["affinity"] >= threshold:
            reached_count += 1
        archived = " · 已封存" if pet["archived"] else ""
        progress = (
            f"亲密 {pet['affinity']}/100" if valid_affinity else "亲密数据异常"
        )
        lines.append(
            f"灵宠 {pet['pet_id']} · {pet['name']}{archived} · {progress} · "
            f"{name} {threshold} · {_reward_text(ctx, milestone)} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励",
                f"灵宠亲密领奖 {pet['pet_id']} {threshold}",
            ))

    if not entries:
        lines.append("尚无在册灵宠。")
    commands = [*page.navigation, "我的灵宠", "灵宠目标"]
    return Reply(
        f"灵宠亲密赏 {page.number}/{page.total}",
        (*lines, f"已达成 {reached_count} 项 · 本页已领取 {claimed_count} 项。"),
        tuple(commands), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠亲密领奖 宠物编号 阈值。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == parts[1]), None)
    if milestone is None:
        allowed = "、".join(str(entry[0]) for entry in MILESTONES)
        raise GameError(f"阈值须为 {allowed} 之一。")

    player = ctx.player()
    pet = ctx.repo.conn.execute(
        "SELECT name, affinity FROM pets WHERE user_id=? AND pet_id=?",
        (player.user_id, pet_id),
    ).fetchone()
    if pet is None:
        raise GameError("没有属于你的这只灵宠。")
    if not _valid_affinity(pet["affinity"]):
        raise GameError("该灵宠的亲密记录异常，请联系管理员检查存档。")
    threshold, name = milestone[:2]
    if pet["affinity"] < threshold:
        raise GameError(f"{pet['name']}当前亲密 {pet['affinity']}/100，尚未达成 {threshold} 点里程碑。")
    if claimed(ctx, player.user_id, pet_id, threshold):
        raise GameError(f"灵宠 {pet_id} 的 {threshold} 点亲密奖励已领取。")

    reward = _reward(ctx, milestone)
    if reward is None:
        raise GameError("亲密里程碑奖励物品定义缺失或类型错误，请联系管理员修复；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(pet_id, threshold), pet["affinity"]),
    )
    return Reply("亲密成长奖励", (
        f"灵宠 {pet_id} 达到 {threshold} 点亲密里程碑「{name}」的奖励已领取。", *result,
    ), ("灵宠亲密赏", "灵宠目标"))
