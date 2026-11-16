from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day, cooldown_left
from . import battle_pass
from .rewards import grant


def refresh(ctx: Context, user_id: str | None = None):
    player = ctx.player(user_id)
    today = beijing_day(ctx.now)
    if today < player.quest_day:
        raise GameError("系统日期早于每日任务记录，请等待日期恢复。")
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


def _next_step(ctx: Context, event: str) -> tuple[str, str, str]:
    choices = {
        "sign": ("领取仙缘", "灵宠签到", ""),
        "explore": ("选择路线", "灵宠历练", ""),
        "expedition": ("查看行程", "灵宠行程", ""),
        "pve": ("选择秘境", "灵宠秘境", ""),
        "pvp": ("寻找对手", "灵宠论剑榜", ""),
    }
    if event in choices:
        return choices[event]
    player = ctx.player()
    if player.active_pet_id is None:
        return "选择伙伴", "灵宠列表", "尚未出战，先从名册选择伙伴"
    pet = ctx.repo.pet(player.active_pet_id)
    if pet.archived:
        return "复原伙伴", f"灵宠复原 {pet.pet_id}", f"{pet.name}已封存，先复原"
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        state = "正在派遣" if ctx.now < expedition["finishes_at"] else "派遣奖励待领取"
        return "查看行程", "灵宠行程", f"{pet.name}{state}"
    if event == "train":
        remaining = cooldown_left(player.last_train, ctx.now, ctx.config.spirit_pet_train_cooldown)
        if remaining:
            return "查看整备", f"灵宠整备 {pet.pet_id}", f"还需调息 {remaining} 秒"
        from .cultivation import _available_energy
        if _available_energy(ctx, pet) < ctx.content.rules.training_energy:
            return "查看整备", f"灵宠整备 {pet.pet_id}", "精力不足，先补充或休息"
        return "开始修炼", f"灵宠修炼 {pet.pet_id}", ""
    if event == "feed":
        if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) <= 0:
            return "购置灵粮", "灵宠商店 灵粮", "灵粮不足"
        return "喂养伙伴", f"灵宠喂养 {pet.pet_id}", ""
    if event == "bond":
        if player.last_bond_day >= beijing_day(ctx.now):
            return "查看陪伴奖励", "灵宠陪伴奖励", "今日已相伴，明日再来"
        return "陪伴伙伴", f"灵宠互动 {pet.pet_id}", ""
    return "查看养成条件", f"灵宠整备 {pet.pet_id}", ""


def quests(ctx: Context, arg: str) -> Reply:
    if arg:
        raise GameError("灵宠任务 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("每日任务", ("尚未结契，先完成领养，再参加每日任务。",),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    today = beijing_day(ctx.now)
    if today < player.quest_day:
        return Reply("每日任务", ("系统日期早于每日任务记录，请等待日期恢复。",), ("灵宠目标",))
    quest_ids = tuple(ctx.content.quests)
    placeholders = ",".join("?" for _ in quest_ids)
    rows = {
        row["quest_id"]: row for row in ctx.repo.conn.execute(
            f"SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id=?"
            f" AND quest_id IN ({placeholders})",
            (player.user_id, *quest_ids),
        )
    } if today == player.quest_day else {}
    lines = []
    links = []
    linked = set()
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
            command = f"灵宠领奖 {quest.name} 日 {today}"
            links.append(InlineCommand(index, "领取奖励", command))
        elif state == "进行中":
            label, command, note = _next_step(ctx, quest.event)
            if note:
                lines[-1] += f" · {note}"
            if command not in linked:
                links.append(InlineCommand(index, label, command))
                linked.add(command)
    return Reply("每日任务", tuple(lines), ("灵宠主线", "灵宠周常", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    name, separator, day = arg.rpartition(" 日 ")
    today = beijing_day(ctx.now)
    if separator and day != today:
        raise GameError("这条每日任务领取入口已经跨日，请重新查看灵宠任务。")
    player = refresh(ctx)
    quest = named(ctx.content.quests, name if separator else arg)
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (player.user_id, quest.id),
    ).fetchone()
    if row is None or row["progress"] < quest.target:
        raise GameError("任务尚未完成。")
    receipt_key = f"daily_claim_{today}_{quest.id}"
    receipt = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?", (player.user_id, receipt_key),
    ).fetchone()
    if row["claimed"] or receipt:
        raise GameError("该任务奖励今日已领取。")
    result = grant(ctx, quest.reward)
    ctx.repo.conn.execute(
        "UPDATE quest_progress SET claimed=1 WHERE user_id=? AND quest_id=?", (player.user_id, quest.id),
    )
    ctx.repo.conn.execute("INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
                          (player.user_id, receipt_key))
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
    reply = Reply("任务领奖", tuple(lines), ("灵宠任务", "灵宠周常 4", "灵宠目标"))
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now,
        {"kind": "daily_quest_claim", "day": today, "quest_id": quest.id}, reply)
    return reply
