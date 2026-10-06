from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from .rewards import grant


def refresh(ctx: Context, user_id: str | None = None):
    player = ctx.player(user_id)
    today = beijing_day(ctx.now)
    if today > player.quest_day:
        ctx.repo.conn.execute("DELETE FROM quest_progress WHERE user_id=?", (player.user_id,))
        player.quest_day = today
    return player


def advance(ctx: Context, event: str, user_id: str | None = None):
    player = refresh(ctx, user_id)
    for quest in ctx.content.quests.values():
        if quest.event == event:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress) VALUES (?, ?, 1) "
                "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=min(progress+1, ?)",
                (player.user_id, quest.id, quest.target),
            )


def quests(ctx: Context, arg: str) -> Reply:
    player = refresh(ctx)
    rows = {
        row["quest_id"]: row for row in ctx.repo.conn.execute(
            "SELECT * FROM quest_progress WHERE user_id=?", (player.user_id,),
        )
    }
    lines = []
    for quest in ctx.content.quests.values():
        row = rows.get(quest.id)
        progress = row["progress"] if row else 0
        state = "已领取" if row and row["claimed"] else ("可领取" if progress >= quest.target else "进行中")
        reward = quest.reward
        items = "，".join(
            f"{ctx.content.items[item].name} {bounds.minimum}-{bounds.maximum}"
            for item, bounds in reward.items.items()
        )
        lines.append(
            f"{quest.name}：{progress}/{quest.target}（{state}）"
            f" · 灵石 {reward.stones.minimum}-{reward.stones.maximum}，{items}"
        )
    return Reply("每日任务", tuple(lines), tuple(f"灵宠领奖 {q.name}" for q in ctx.content.quests.values()))


def claim(ctx: Context, arg: str) -> Reply:
    player = refresh(ctx)
    quest = named(ctx.content.quests, arg)
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (player.user_id, quest.id),
    ).fetchone()
    if row is None or row["progress"] < quest.target:
        raise GameError("任务尚未完成。")
    if row["claimed"]:
        raise GameError("该任务奖励今日已领取。")
    result = grant(ctx, quest.reward)
    ctx.repo.conn.execute(
        "UPDATE quest_progress SET claimed=1 WHERE user_id=? AND quest_id=?", (player.user_id, quest.id),
    )
    return Reply("任务领奖", (f"{quest.name}已完成。", *result))
