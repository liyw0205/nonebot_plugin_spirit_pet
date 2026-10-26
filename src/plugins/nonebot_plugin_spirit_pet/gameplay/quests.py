from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day
from . import battle_pass
from .rewards import grant


def refresh(ctx: Context, user_id: str | None = None):
    player = ctx.player(user_id)
    today = beijing_day(ctx.now)
    if today > player.quest_day:
        # Only daily quests reset here: other one-time claim families share this table.
        daily = tuple(ctx.content.quests)
        placeholders = ",".join("?" for _ in daily)
        ctx.repo.conn.execute(
            f"DELETE FROM quest_progress WHERE user_id=? AND quest_id IN ({placeholders})",
            (player.user_id, *daily),
        )
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
    links = []
    claimable = []
    for index, quest in enumerate(ctx.content.quests.values()):
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
        if state == "可领取":
            command = f"灵宠领奖 {quest.name}"
            claimable.append(command)
            links.append(InlineCommand(index, "领取奖励", command))
    return Reply("每日任务", tuple(lines), tuple(claimable), tuple(links))


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
    # Battle pass EXP only once per day, when the whole daily board is claimed.
    daily = tuple(ctx.content.quests)
    placeholders = ", ".join("?" for _ in daily)
    done = ctx.repo.conn.execute(
        f"SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 AND quest_id IN ({placeholders})",
        (player.user_id, *daily),
    ).fetchone()[0]
    lines = [f"{quest.name}已完成。", *result]
    if done == len(daily) and battle_pass.claim_daily_clear(ctx, player.user_id):
        lines.append(f"今日任务全清，战令经验 +{battle_pass.ACTIVITY_EXP['daily_all_clear']}。")
    return Reply("任务领奖", tuple(lines))
