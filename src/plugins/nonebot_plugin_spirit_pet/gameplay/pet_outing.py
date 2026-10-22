from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.time import beijing_day
from .rewards import grant

PAGE_SIZE = 5
VALUE_PER_OUTING = 5
MILESTONES = (
    (10, "初出茅庐", 50, {"spirit_food": 1}),
    (30, "小有游历", 120, {"forge_ore": 1}),
    (70, "行万里路", 250, {"bloodline_essence": 1}),
    (120, "山海故人", 450, {"forge_ore": 3, "bloodline_essence": 2}),
    (200, "游历大家", 700, {"bloodline_essence": 4}),
)

DAY_PREFIX = "outing_day_"
VALUE_PREFIX = "outing_value_"
MILESTONE_PREFIX = "outing_milestone_"

SCENES = (
    "{name}在溪边追了一下午蝴蝶，回来时爪子还沾着水汽。",
    "{name}跟着你翻过山坡，远处的灵田在夕阳下发亮。",
    "{name}在林子里发现一窝灵果，兴冲冲地叼回来一颗。",
)


def _pet_by_number(ctx: Context, number: int):
    target = next((pet for pet in ctx.repo.owned_pets(ctx.user_id) if pet.pet_id == number), None)
    if target is None:
        raise GameError("没有属于你的这只灵宠。")
    return target


def _value_row(ctx: Context, pet_id: int):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{VALUE_PREFIX}{pet_id}"),
    ).fetchone()


def _value(ctx: Context, pet_id: int) -> int:
    row = _value_row(ctx, pet_id)
    return row["progress"] if row else 0


def _day_row(ctx: Context, day: str, pet_id: int):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{DAY_PREFIX}{day}_{pet_id}"),
    ).fetchone()


def _milestone_claimed(ctx: Context, pet_id: int, tier: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{MILESTONE_PREFIX}{pet_id}_{tier}"),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(milestone) -> Reward:
    _, _, stones, items = milestone
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def _reward_text(ctx: Context, milestone) -> str:
    _, _, stones, items = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in items.items()
    )
    return "，".join(parts)


def go_out(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = ctx.pet() if not arg.strip() else _pet_by_number(ctx, quantity(arg, 9_223_372_036_854_775_807))
    day = beijing_day(ctx.now)
    if _day_row(ctx, day, pet.pet_id) is not None:
        raise GameError(f"{pet.name}今天已经出游过了，明日再来。")
    ctx.require_idle_pet(pet)

    scene = SCENES[ctx.rng.randint(0, len(SCENES) - 1)].format(name=pet.name)
    lines = [scene]
    outing_reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=20, maximum=60),
        items={"spirit_food": Range(minimum=0, maximum=1)},
    )
    lines.extend(grant(ctx, outing_reward))
    total = _value(ctx, pet.pet_id) + VALUE_PER_OUTING
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{VALUE_PREFIX}{pet.pet_id}", total),
    )
    ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
        (ctx.user_id, f"{DAY_PREFIX}{day}_{pet.pet_id}"),
    )
    from .bond_levels import add_exp
    add_exp(ctx, pet.pet_id, 10)
    lines.append(f"游历值 +{VALUE_PER_OUTING}（累计 {total}）。")
    return Reply("灵宠出游", tuple(lines), ("灵宠游历赏", "我的灵宠", "灵宠任务"))


def catalog(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        raise GameError(f"灵宠游历赏共 {_total_pages(ctx)} 页。")
    page = quantity(arg or "1", 999999)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠游历赏", (
            "每只灵宠每天可以出游一次，出游累计游历值并解锁里程碑。",
            "尚未结契，先完成领养，再带伙伴出发。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    pets = ctx.repo.owned_pets(ctx.user_id)
    total_pages = max(1, (len(pets) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        raise GameError(f"灵宠游历赏共 {total_pages} 页。")
    selected = pets[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for pet in selected:
        total = _value(ctx, pet.pet_id)
        if _milestone_claimed(ctx, pet.pet_id, MILESTONES[-1][0]):
            state = "游历大家（全部完成）"
        else:
            state = f"游历值 {total}"
        lines.append(f"{pet.name}（编号 {pet.pet_id}）· {state}")
        for milestone in MILESTONES:
            threshold, name, _, _ = milestone
            if total >= threshold and not _milestone_claimed(ctx, pet.pet_id, threshold):
                lines.append(f"  可领取「{name}」· {_reward_text(ctx, milestone)}")
                links.append(InlineCommand(
                    len(lines) - 1, "领取游历奖励", f"灵宠游历领奖 {pet.pet_id} {threshold}",
                ))
                break
    return Reply(f"灵宠游历赏 {page}/{total_pages}", tuple(lines), ("灵宠出游", "我的灵宠"), tuple(links))


def _total_pages(ctx: Context) -> int:
    return max(1, (len(ctx.repo.owned_pets(ctx.user_id)) + PAGE_SIZE - 1) // PAGE_SIZE)


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠游历领奖 <宠物编号> <档位>。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    threshold = quantity(parts[1], 999999)
    milestone = next((m for m in MILESTONES if m[0] == threshold), None)
    if milestone is None:
        allowed = "、".join(str(m[0]) for m in MILESTONES)
        raise GameError(f"游历里程碑档位可选：{allowed}。")
    ctx.player()
    pet_row = ctx.repo.conn.execute(
        "SELECT name FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, pet_id),
    ).fetchone()
    if pet_row is None:
        raise GameError("没有属于你的这只灵宠。")
    total = _value(ctx, pet_id)
    if total < threshold:
        raise GameError(f"{pet_row['name']}的游历值为 {total}，尚未达成 {threshold}。")
    if _milestone_claimed(ctx, pet_id, threshold):
        raise GameError(f"{threshold} 游历值里程碑已领取。")
    result = grant(ctx, _reward(milestone), ctx.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (ctx.user_id, f"{MILESTONE_PREFIX}{pet_id}_{threshold}"),
    )
    return Reply("游历奖励", (
        f"{pet_row['name']}的「{milestone[1]}」游历奖励已领取。", *result,
    ), ("灵宠游历赏", "我的灵宠"))
