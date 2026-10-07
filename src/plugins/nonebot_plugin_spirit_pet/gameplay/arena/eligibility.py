from ...application.context import Context
from ...domain.models import GameError
from ...domain.state import Pet
from ...utils.time import beijing_day
from .common import Season, rating


def check_participant(ctx: Context, season: Season, user_id: str) -> Pet:
    player, pet = ctx.player(user_id), ctx.pet(user_id)
    minimum = next((index for index, realm in enumerate(ctx.content.realms) if realm.id == season.rules.min_realm), None)
    if minimum is None:
        raise GameError("赛季准入所需的境界定义缺失，请联系管理员恢复后重试。")
    if pet.realm < minimum:
        raise GameError(f"{player.dao_name}境界不足，论剑需达到{ctx.content.realms[minimum].name}。")
    ctx.check_action(player, pet, "pvp", season.rules.energy, ctx.config.spirit_pet_pvp_cooldown)
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM pvp_results WHERE season_id=? AND day=? "
        "AND challenger_id=?",
        (season.season_id, beijing_day(ctx.now), user_id),
    ).fetchone()[0]
    if count >= season.rules.daily_matches:
        raise GameError(f"{player.dao_name}今日论剑次数已用尽。")
    return pet


def check_ranked(ctx: Context, season: Season, first: str, second: str) -> tuple[Pet, Pet]:
    if first == second:
        raise GameError("不能向自己发起论剑。")
    if season.closed_at is not None or not season.starts_at <= ctx.now < season.ends_at:
        raise GameError("该赛季已结束，请重新发起论剑。")
    left = check_participant(ctx, season, first)
    target = ctx.player(second)
    if target.active_pet_id is None:
        raise GameError("该道友尚未选择出战灵宠。")
    right = ctx.repo.pet(target.active_pet_id)
    if left.realm != right.realm:
        raise GameError("论剑双方需处于相同大境界。")
    if abs(rating(ctx, season, first) - rating(ctx, season, second)) > season.rules.max_rating_gap:
        raise GameError(f"论剑双方积分差不能超过 {season.rules.max_rating_gap}。")
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(day=?),0) AS today FROM pvp_results "
        "WHERE season_id=? AND ((challenger_id=? AND target_id=?) OR (challenger_id=? AND target_id=?))",
        (beijing_day(ctx.now), season.season_id, first, second, second, first),
    ).fetchone()
    if row["today"] >= season.rules.pair_daily_matches:
        raise GameError("双方今日已结算至同对论剑上限，可改为切磋。")
    if row["total"] >= season.rules.pair_season_matches:
        raise GameError("双方本赛季同对论剑次数已用尽，可改为切磋。")
    return left, right
