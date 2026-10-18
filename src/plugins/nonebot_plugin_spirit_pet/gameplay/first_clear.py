from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from .rewards import grant
from .sweep import _cleared

PAGE_SIZE = 5
CLAIM_PREFIX = "first_clear_"


def claim_id(dungeon_id: str) -> str:
    return CLAIM_PREFIX + dungeon_id


def claimed(ctx: Context, user_id: str, dungeon_id: str) -> bool:
    """A first-clear reward is claimed once and never expires."""
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(dungeon_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward(ctx: Context, dungeon):
    return dungeon.first_clear


def _summary(ctx: Context, dungeon) -> str:
    reward = _reward(ctx, dungeon)
    parts = [f"灵石 {reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}"
        for item, bounds in reward.items.items()
    )
    return "，".join(parts)


def _state(ctx: Context, user_id: str, dungeon) -> str:
    if claimed(ctx, user_id, dungeon.id):
        return "已领取"
    return "可领取" if _cleared(ctx, dungeon.id) else "未通关"


def catalog(ctx: Context, arg: str) -> Reply:
    entries = tuple(ctx.content.dungeons.values())
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠秘境首通共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠秘境首通", (
            "每处秘境首次通关后，可在这里领取一份一次性首通奖励。",
            f"共 {len(entries)} 处秘境，奖励按境界递增；组队秘境同样按真实胜利判定。",
            "尚未结契，先完成领养，再挑战秘境。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    selected = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = []
    links = []
    for dungeon in selected:
        state = _state(ctx, player.user_id, dungeon)
        tag = "组队" if dungeon.team else "单人"
        lines.append(f"{dungeon.name}（{tag}）· {_summary(ctx, dungeon)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取首通奖励", f"灵宠秘境首通领奖 {dungeon.name}",
            ))
    remaining = sum(
        1 for dungeon in entries
        if _cleared(ctx, dungeon.id) and not claimed(ctx, player.user_id, dungeon.id)
    )
    lines.append(f"共 {len(entries)} 处秘境，尚有 {remaining} 处可领取。")
    commands = []
    if page > 1:
        commands.append(f"灵宠秘境首通 {page - 1}")
    if page < pages:
        commands.append(f"灵宠秘境首通 {page + 1}")
    commands.extend(("灵宠秘境", "灵宠秘境战绩", "灵宠目标"))
    return Reply(f"灵宠秘境首通 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    dungeon = named(ctx.content.dungeons, arg)
    if dungeon.first_clear is None:
        raise GameError("该秘境没有首通奖励。")
    if claimed(ctx, player.user_id, dungeon.id):
        raise GameError(f"{dungeon.name}的首通奖励已领取，不能重复领取。")
    if not _cleared(ctx, dungeon.id):
        raise GameError(f"尚未通关{dungeon.name}，请先发送 灵宠挑战 {dungeon.name}。")
    result = grant(ctx, dungeon.first_clear, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, claim_id(dungeon.id)),
    )
    return Reply("秘境首通奖励", (
        f"{dungeon.name}首通奖励已领取。", *result,
    ), ("灵宠秘境首通", "灵宠秘境", "灵宠目标"))
