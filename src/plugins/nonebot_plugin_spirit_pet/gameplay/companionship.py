from datetime import date, timedelta

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..domain.state import Player
from ..utils.time import beijing_day
from .pet_targets import selected_pet
from .quests import advance

SCENES = (
    "{name}轻轻蹭过你的手心，灵契泛起温暖的微光。",
    "你与{name}并肩听风，熟悉的气息让彼此更加安心。",
    "{name}叼来一片灵叶与你分享，欢快地绕着你转了一圈。",
)


def active_bond_streak(player: Player, now: int) -> int:
    today = beijing_day(now)
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    if player.last_bond_day not in {today, yesterday}:
        return 0
    return player.current_bond_streak


def bond(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet = selected_pet(ctx, arg, "互动")
    today = beijing_day(ctx.now)
    if player.last_bond_day >= today:
        raise GameError("今日已与灵宠相伴，明日再来。（每日北京时间 00:00 刷新）")
    ctx.require_idle_pet(pet)

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    streak = player.current_bond_streak + 1 if player.last_bond_day == yesterday else 1
    gained = min(2, 100 - pet.affinity)
    scene = SCENES[ctx.rng.randint(0, len(SCENES) - 1)].format(name=pet.name)
    player.last_bond_day = today
    player.current_bond_streak = streak
    player.best_bond_streak = max(player.best_bond_streak, streak)
    pet.affinity += gained
    if pet.pet_id == player.active_pet_id:
        ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "bond")
    affinity = f"亲密 +{gained}（{pet.affinity}/100）；每日互动次数已用尽。" if gained else (
        "亲密已满，本次陪伴不再增加；每日互动次数已用尽。"
    )
    return Reply("灵宠相伴", (
        scene,
        affinity,
        f"连续陪伴：当前 {streak} 天 · 最佳 {player.best_bond_streak} 天。",
    ), ("我的灵宠", "灵宠任务", "灵宠喂养"))
