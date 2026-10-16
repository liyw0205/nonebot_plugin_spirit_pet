from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .rewards import grant

CLAIM_PREFIX = "lineage_awakening_reward_"
PAGE_SIZE = 5
REWARD_ITEM = "bloodline_essence"
REWARD_STONES = 100
REWARD_AMOUNT = 1


def claim_id(pet_id: int, lineage_id: str) -> str:
    return f"{CLAIM_PREFIX}{pet_id}_{lineage_id}"


def claimed(ctx: Context, user_id: str, pet_id: int, lineage_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(pet_id, lineage_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def _branch(ctx: Context, pet):
    branch_id = pet["lineage_id"]
    branch = ctx.content.lineages.get(branch_id) if branch_id else None
    if (
        branch is None
        or branch.species_id != pet["species_id"]
        or type(pet["bloodline"]) is not int
        or pet["bloodline"] not in ctx.content.bloodlines
        or pet["bloodline"] < branch.min_bloodline
    ):
        return None
    return branch


def _reward(ctx: Context) -> Reward | None:
    item = ctx.content.items.get(REWARD_ITEM)
    if item is None or item.kind != "material":
        return None
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=REWARD_STONES, maximum=REWARD_STONES),
        items={REWARD_ITEM: Range(minimum=REWARD_AMOUNT, maximum=REWARD_AMOUNT)},
    )


def _reward_text(ctx: Context) -> str:
    if _reward(ctx) is None:
        return "奖励内容待修复"
    return f"奖励：灵石 {REWARD_STONES}、{ctx.content.items[REWARD_ITEM].name} {REWARD_AMOUNT}"


def _pets(ctx: Context, user_id: str):
    return ctx.repo.conn.execute(
        "SELECT pet_id, name, species_id, bloodline, lineage_id, archived "
        "FROM pets WHERE user_id=? ORDER BY pet_id",
        (user_id,),
    ).fetchall()


def _state(ctx: Context, user_id: str, pet) -> str:
    if pet["lineage_id"] is None:
        return "尚未选择"
    branch = _branch(ctx, pet)
    if branch is None:
        return "分支数据异常"
    if claimed(ctx, user_id, pet["pet_id"], branch.id):
        return "已领取"
    return "可领取" if _reward(ctx) is not None else "奖励待修复"


def summary(ctx: Context, user_id: str) -> str:
    pets = _pets(ctx, user_id)
    available = sum(_state(ctx, user_id, pet) == "可领取" for pet in pets)
    selected = sum(_branch(ctx, pet) is not None for pet in pets)
    return f"血脉分支觉醒礼：可领 {available} 项 · 已选分支 {selected} 只"


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = (
            "选定血脉分支后可领取一次觉醒礼。",
            f"{_reward_text(ctx)}。",
            "尚未结契；结契并达到灵血后可查看可选分支。",
        )
        return Reply("灵宠分支赏 1/1", lines, ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    pets = _pets(ctx, player.user_id)
    page = paginate(pets, arg, "灵宠分支赏", "灵宠分支赏", PAGE_SIZE)
    lines, links = [], []
    available = claimed_count = 0
    for pet in page.entries:
        state = _state(ctx, player.user_id, pet)
        branch = _branch(ctx, pet)
        if state == "可领取":
            available += 1
        if state == "已领取":
            claimed_count += 1
        current = ctx.content.bloodlines.get(pet["bloodline"])
        current_name = current.name if current is not None else "血脉数据异常"
        species = ctx.content.species.get(pet["species_id"])
        species_name = species.name if species is not None else "种族数据异常"
        branch_name = branch.name if branch is not None else (
            "未选择分支" if pet["lineage_id"] is None else "分支数据异常"
        )
        archived = " · 已封存" if pet["archived"] else ""
        lines.append(
            f"灵宠 {pet['pet_id']} · {pet['name']} · {species_name}{archived} · 当前{current_name} · "
            f"{branch_name} · {_reward_text(ctx)} · {state}"
        )
        if state == "可领取" and branch is not None:
            links.append(InlineCommand(
                len(lines) - 1, "领取觉醒礼",
                f"灵宠分支领奖 {pet['pet_id']} {branch.name}",
            ))

    if not pets:
        lines.append("尚无在册灵宠。")
    lines.append(f"本页可领 {available} 项 · 已领取 {claimed_count} 项。")
    commands = [*page.navigation, "我的灵宠", "灵宠目标"]
    return Reply(
        f"灵宠分支赏 {page.number}/{page.total}", tuple(lines), tuple(commands), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠分支领奖 宠物编号 分支名。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    branch = next((entry for entry in ctx.content.lineages.values() if entry.name == parts[1]), None)
    if branch is None:
        raise GameError("未找到该血脉分支。")

    player = ctx.player()
    pet = ctx.repo.conn.execute(
        "SELECT name, species_id, bloodline, lineage_id FROM pets WHERE user_id=? AND pet_id=?",
        (player.user_id, pet_id),
    ).fetchone()
    if pet is None:
        raise GameError("没有属于你的这只灵宠。")
    selected = _branch(ctx, pet)
    if selected is None:
        if pet["lineage_id"] is None:
            raise GameError("这只灵宠尚未选择血脉分支。")
        raise GameError("该灵宠的血脉分支记录异常，请联系管理员检查存档。")
    if selected.id != branch.id:
        raise GameError("该灵宠当前已选分支与此奖励不符，请刷新分支赏页面。")
    if claimed(ctx, player.user_id, pet_id, branch.id):
        raise GameError(f"灵宠 {pet_id} 的{branch.name}觉醒礼已领取。")

    reward = _reward(ctx)
    if reward is None:
        raise GameError("觉醒奖励所需血脉精华定义缺失或类型错误，请联系管理员修复；尚未领取。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(pet_id, branch.id), pet["bloodline"]),
    )
    return Reply("血脉分支觉醒礼", (
        f"灵宠 {pet_id} 的{branch.name}觉醒礼已领取。", *result,
    ), ("灵宠分支赏", "灵宠目标"))
