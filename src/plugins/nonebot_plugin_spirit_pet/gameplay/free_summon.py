from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from . import weekly_quests
from .pets import summon

CLAIM = "free_summon_weekly"
DRAW_COUNT = 10
PAGE_BUTTONS = ("灵宠列表", "我的灵宠", "灵宠图鉴")


def available(ctx: Context, user_id: str) -> bool:
    """The free ten-pull resets with the Beijing week, like the weekly goals."""
    return not weekly_quests.claimed_this_week(ctx, user_id, CLAIM)


def _state(ctx: Context, user_id: str) -> str:
    return "可领取" if available(ctx, user_id) else "本周已领取"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠每周召唤 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    pool = ctx.content.pools["standard"]
    lines = [
        f"每周可免费召唤 {DRAW_COUNT} 只灵宠，不消耗灵石；标准池十连有珍稀保底。",
        "每周一 00:00（北京时间）重置，未领取不会累积。",
    ]
    if player is None:
        lines.append("尚未结契，先完成领养，再领取每周免费召唤。")
        return Reply("每周免费召唤", tuple(lines), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))
    state = _state(ctx, player.user_id)
    lines.insert(0, f"本周免费召唤：{state}。")
    links = ()
    if state == "可领取":
        links = (InlineCommand(0, "领取免费十连", "灵宠每周召唤领取"),)
    lines.append(f"名册上限 {ctx.config.spirit_pet_max_pets} 只；召唤前请确认有空位。")
    return Reply("每周免费召唤", tuple(lines), PAGE_BUTTONS, links)


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if not available(ctx, player.user_id):
        raise GameError("本周免费召唤已领取，下周一再来。")
    reply = summon(ctx, str(DRAW_COUNT), free=True)
    start, _ = beijing_week(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, CLAIM, start),
    )
    return Reply("每周免费召唤", ("本周免费十连已领取。", *reply.lines), PAGE_BUTTONS)
