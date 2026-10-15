from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from .achievements import _metric
from .rewards import grant

MAIN_QUEST_PAGE_SIZE = 5


def _ordered(ctx: Context) -> list:
    return sorted(ctx.content.main_quests.values(), key=lambda quest: quest.order)


def _claimed(ctx: Context, user_id: str) -> set[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1", (user_id,),
    )
    return {row["quest_id"] for row in rows} & set(ctx.content.main_quests)


def _current(ctx: Context, user_id: str):
    """The first step that is neither claimed nor blocked by an unclaimed predecessor."""
    claimed = _claimed(ctx, user_id)
    return next((quest for quest in _ordered(ctx) if quest.id not in claimed), None)


def _state(ctx: Context, user_id: str, quest, claimed: set[str], current) -> tuple[str, int]:
    if quest.id in claimed:
        return "已完成", quest.target
    if current is not None and quest.id == current.id:
        value = _metric(ctx, user_id, quest.metric)
        return ("可领奖" if value >= quest.target else "进行中"), value
    return "未解锁", 0


def _reward_summary(ctx: Context, quest) -> str:
    parts = [f"灵石 {quest.reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}"
        for item, bounds in quest.reward.items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    lines = ["主线按序推进：达成当前一步并领取奖励，下一步才会解锁。"]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再踏上主线。")
        return Reply("灵宠主线", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    quests = _ordered(ctx)
    claimed = _claimed(ctx, player.user_id)
    current = _current(ctx, player.user_id)
    page = paginate(quests, arg, "灵宠主线", "灵宠主线", page_size=MAIN_QUEST_PAGE_SIZE)
    links = []
    for quest in page.entries:
        state, value = _state(ctx, player.user_id, quest, claimed, current)
        progress = f" · {value}/{quest.target}" if state in {"进行中", "可领奖"} else ""
        lines.append(
            f"{quest.order}. {quest.name} · {state}{progress} · {_reward_summary(ctx, quest)}"
        )
        if state == "可领奖":
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励", f"灵宠主线领奖 {quest.name}",
            ))
    if current is None:
        lines.append("主线已全部完成，感谢一路同行。")
    else:
        lines.append(f"当前目标：{current.name} · {current.description}")
    return Reply(
        f"灵宠主线 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "灵宠任务"), tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    quest = named(ctx.content.main_quests, arg)
    if quest.id in _claimed(ctx, player.user_id):
        raise GameError("该主线奖励已领取，不能重复领取。")
    current = _current(ctx, player.user_id)
    if current is None or current.id != quest.id:
        blocker = current.name if current is not None else "主线已全部完成"
        raise GameError(f"主线须按序推进，请先完成「{blocker}」。")
    value = _metric(ctx, player.user_id, quest.metric)
    if value < quest.target:
        raise GameError(
            f"主线尚未达成：{quest.description}（进度 {value}/{quest.target}）"
        )
    result = grant(ctx, quest.reward)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, quest.id, value),
    )
    following = next((item for item in _ordered(ctx) if item.order == quest.order + 1), None)
    lines = [f"{quest.name}已完成。", *result]
    lines.append(f"下一步：{following.name}。" if following else "主线已全部完成，感谢一路同行。")
    return Reply("主线奖励已领取", tuple(lines), ("灵宠主线", "灵宠任务"))
