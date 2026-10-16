from ...application.context import Context
from ...domain.content import Range, Reward
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import named
from ..rewards import grant
from .common import Season, current_season, rating

CLAIM_PREFIX = "arena_tier_"


def claim_id(season_id: str, tier_id: str) -> str:
    return f"{CLAIM_PREFIX}{season_id}_{tier_id}"


def claimed(ctx: Context, user_id: str, season_id: str, tier_id: str) -> bool:
    """A tier achievement reward is claimed once per season."""
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(season_id, tier_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def season_rating(ctx: Context, user_id: str, season_id: str) -> int:
    """Read-only rating lookup, so read-only pages never create a season row."""
    row = ctx.repo.conn.execute(
        "SELECT rating FROM season_entries WHERE season_id=? AND user_id=?", (season_id, user_id),
    ).fetchone()
    return row["rating"] if row else ctx.content.arena.initial_rating


def tier_of(season: Season, score: int):
    return max((tier for tier in season.rules.tiers if tier.minimum_rating <= score),
               key=lambda tier: tier.minimum_rating)


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


def _state(ctx: Context, user_id: str, season: Season, tier, score: int) -> str:
    if claimed(ctx, user_id, season.season_id, tier.id):
        return "已领取"
    if score >= tier.minimum_rating:
        return "可领取"
    return f"还差 {tier.minimum_rating - score} 分"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠段位奖励 不接受参数，直接发送即可。")
    season = current_season(ctx)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠段位奖励", (
            "本赛季积分达到某一档位后，可以在这里领取该档的一次性达成奖励。",
            f"共 {len(season.rules.tiers)} 档，奖励随档位递增；每档每季只能领取一次，换季重新可领。",
            "尚未结契，先完成领养，再去论剑。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    score = rating(ctx, season, player.user_id)
    lines, links = [], []
    for tier in season.rules.tiers:
        reward = ctx.content.arena_tier_rewards[tier.id]
        state = _state(ctx, player.user_id, season, tier, score)
        lines.append(f"{tier.name} · {tier.minimum_rating} 分起 · {_reward_text(ctx, reward)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取段位奖励", f"灵宠段位领奖 {tier.name}"))
    lines.append(f"赛季 {season.season_id} · 当前积分 {score} · 当前档位 {tier_of(season, score).name}。")
    return Reply(f"灵宠段位奖励 · {season.season_id}", tuple(lines),
                 ("灵宠赛季", "灵宠赛季奖励", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    season = current_season(ctx)
    tier = named({entry.id: entry for entry in season.rules.tiers}, arg)
    reward = ctx.content.arena_tier_rewards[tier.id]
    if claimed(ctx, player.user_id, season.season_id, tier.id):
        raise GameError(f"{tier.name}的段位奖励本赛季已领取，换季后再来。")
    score = rating(ctx, season, player.user_id)
    if score < tier.minimum_rating:
        raise GameError(f"积分不足：当前 {score} 分，{tier.name}需要 {tier.minimum_rating} 分。")
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"段位奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, _grant_reward(reward), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, claim_id(season.season_id, tier.id)),
    )
    return Reply("段位奖励已领取", (
        f"{season.season_id} · {tier.name} · 当前积分 {score}。", *result,
    ), ("灵宠段位奖励", "灵宠赛季", "灵宠目标"))
