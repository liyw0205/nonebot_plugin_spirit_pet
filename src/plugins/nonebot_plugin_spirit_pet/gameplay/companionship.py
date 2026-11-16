from datetime import date, timedelta

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.state import Player
from ..utils.time import beijing_day
from .economy import _recovery_available
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
    name = f"{pet.name}（编号 {pet.pet_id}）" if arg else pet.name
    scene = SCENES[ctx.rng.randint(0, len(SCENES) - 1)].format(name=name)
    player.last_bond_day = today
    player.current_bond_streak = streak
    player.best_bond_streak = max(player.best_bond_streak, streak)
    pet.affinity += gained
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    advance(ctx, "bond")
    from .bond_levels import add_exp
    add_exp(ctx, pet.pet_id, 10)
    from .mood import care
    care(ctx, pet)
    affinity = f"亲密 +{gained}（{pet.affinity}/100）；每日互动次数已用尽。" if gained else (
        "亲密已满，本次陪伴不再增加；每日互动次数已用尽。"
    )
    lines = (
        scene,
        affinity,
        f"连续陪伴：当前 {streak} 天 · 最佳 {player.best_bond_streak} 天。",
    )
    if arg:
        links = [InlineCommand(0, "查看整备", f"灵宠整备 {pet.pet_id}")]
        food = ctx.content.items["spirit_food"]
        if ctx.repo.inventory(ctx.user_id).get(food.id, 0) > 0 and _recovery_available(food.effects, pet):
            links.append(InlineCommand(1, "喂养这位伙伴", f"灵宠喂养 {pet.pet_id}"))
        return Reply("灵宠相伴", lines, ("灵宠任务", "灵宠陪伴奖励"), tuple(links))
    return Reply("灵宠相伴", lines, ("我的灵宠", "灵宠任务", "灵宠喂养", "灵宠陪伴奖励"))
