from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from .rewards import grant

PAGE_SIZE = 5
CLAIM_PREFIX = "stage_stars_"
FULL_STARS = 3


def claim_id(stars: int) -> str:
    return f"{CLAIM_PREFIX}{stars}"


def claimed(ctx: Context, user_id: str, stars: int) -> bool:
    """A star milestone is claimed once and never expires."""
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(stars)),
    ).fetchone()
    return bool(row and row["claimed"])


def best_rounds(ctx: Context, user_id: str, stage_id: str) -> int | None:
    """Fewest rounds this player needed to win the stage, or None if never won."""
    row = ctx.repo.conn.execute(
        "SELECT MIN(r.rounds) AS rounds FROM battle_records AS r "
        "JOIN battle_participants AS p ON p.battle_id = r.battle_id "
        "WHERE p.user_id=? AND r.kind='pve_stage' AND r.battle_key=? AND r.winner_side = p.side",
        (user_id, stage_id),
    ).fetchone()
    return None if row is None or row["rounds"] is None else int(row["rounds"])


def stars_for(ctx: Context, stage, rounds: int | None) -> int:
    """Rate a clear by rounds taken, counting the allowance per enemy."""
    if rounds is None:
        return 0
    rule = ctx.content.rules.stage_star_rounds
    enemies = max(1, len(stage.enemies))
    if rounds <= rule.three * enemies:
        return FULL_STARS
    if rounds <= rule.two * enemies:
        return FULL_STARS - 1
    return FULL_STARS - 2


def stars(ctx: Context, user_id: str, stage) -> int:
    return stars_for(ctx, stage, best_rounds(ctx, user_id, stage.id))


def total(ctx: Context, user_id: str) -> int:
    return sum(stars(ctx, user_id, stage) for stage in ctx.content.stages.values())


def star_text(value: int) -> str:
    return "★" * value + "☆" * (FULL_STARS - value)


def detail_line(ctx: Context, user_id: str, stage) -> str:
    """One line for the stage detail page: rating and best round count."""
    rounds = best_rounds(ctx, user_id, stage.id)
    if rounds is None:
        return "评价：尚未通关"
    return f"评价：{star_text(stars_for(ctx, stage, rounds))} · 最好 {rounds} 回合"


def _reward_text(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in reward.items.items()
    )
    return "，".join(parts)


def _grant_reward(reward) -> Reward:
    """The content reward is fixed, so the granted range is a single value."""
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=reward.stones, maximum=reward.stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in reward.items.items()},
    )


def _milestone_state(ctx: Context, user_id: str, milestone, reached: int) -> str:
    if claimed(ctx, user_id, milestone.stars):
        return "已领取"
    return "可领取" if reached >= milestone.stars else f"还差 {milestone.stars - reached} 星"


def catalog(ctx: Context, arg: str) -> Reply:
    stages = sorted(ctx.content.stages.values(), key=lambda stage: stage.order)
    pages = max(1, (len(stages) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠关卡星级共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠关卡星级", (
            "每次通关章节关卡都会按回合数得到 1-3 星评价，累计星数可领取里程碑奖励。",
            f"共 {len(stages)} 关、满分 {FULL_STARS * len(stages)} 星；同一关取历史最好成绩。",
            "尚未结契，先完成领养，再去闯关。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    reached = total(ctx, player.user_id)
    selected = stages[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = [
        f"{stage.order}. {stage.name} · {star_text(stars(ctx, player.user_id, stage))}"
        for stage in selected
    ]
    lines.append(f"共 {len(stages)} 关，当前 {reached}/{FULL_STARS * len(stages)} 星。")
    links = []
    for milestone in sorted(ctx.content.stage_star_rewards):
        reward = ctx.content.stage_star_rewards[milestone]
        state = _milestone_state(ctx, player.user_id, reward, reached)
        lines.append(f"{milestone} 星 · {_reward_text(ctx, reward)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取星级奖励", f"灵宠关卡星级领奖 {milestone}",
            ))
    commands = []
    if page > 1:
        commands.append(f"灵宠关卡星级 {page - 1}")
    if page < pages:
        commands.append(f"灵宠关卡星级 {page + 1}")
    commands.extend(("灵宠关卡", "灵宠关卡战绩", "灵宠目标"))
    return Reply(f"灵宠关卡星级 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    stars_wanted = quantity(arg.strip(), 10_000)
    reward = ctx.content.stage_star_rewards.get(stars_wanted)
    if reward is None:
        raise GameError("没有这一档星级奖励，请查看 灵宠关卡星级。")
    if claimed(ctx, player.user_id, stars_wanted):
        raise GameError(f"{stars_wanted} 星奖励已领取，不能重复领取。")
    reached = total(ctx, player.user_id)
    if reached < stars_wanted:
        raise GameError(f"星级不足：当前 {reached} 星，需要 {stars_wanted} 星。")
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"星级奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, _grant_reward(reward), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, claim_id(stars_wanted)),
    )
    return Reply("关卡星级奖励", (
        f"{stars_wanted} 星奖励已领取（当前 {reached} 星）。", *result,
    ), ("灵宠关卡星级", "灵宠关卡", "灵宠目标"))
