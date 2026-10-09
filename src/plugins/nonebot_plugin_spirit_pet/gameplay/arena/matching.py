from ...application.context import Context
from ...domain.models import GameError, Reply
from ...utils.arguments import quantity
from ...utils.time import beijing_day
from .common import current_season, rating
from .eligibility import check_participant

PAGE_SIZE = 5


def candidates(ctx: Context, arg: str) -> Reply:
    page = quantity(arg or "1", 999)
    season = current_season(ctx)
    pet = check_participant(ctx, season, ctx.user_id)
    rules = season.rules
    # Filter before LIMIT so unavailable players never consume candidate slots.
    rows = ctx.repo.conn.execute(
        "SELECT p.dao_name, t.name, t.layer, COALESCE(e.rating,:initial) AS rating "
        "FROM players p JOIN pets t ON t.pet_id=p.active_pet_id "
        "LEFT JOIN season_entries e ON e.user_id=p.user_id AND e.season_id=:season "
        "WHERE p.user_id!=:me AND t.realm=:realm "
        "AND NOT EXISTS (SELECT 1 FROM active_pet_slots s "
        "JOIN pets member ON member.pet_id=s.pet_id "
        "WHERE s.user_id=p.user_id AND member.realm!=t.realm) "
        "AND ABS(COALESCE(e.rating,:initial)-:rating)<=:gap "
        "AND (SELECT COUNT(*) FROM pvp_results r WHERE r.season_id=:season AND r.day=:day "
        "AND ((r.challenger_id=:me AND r.target_id=p.user_id) "
        "OR (r.target_id=:me AND r.challenger_id=p.user_id)))<:pair_daily "
        "AND (SELECT COUNT(*) FROM pvp_results r WHERE r.season_id=:season "
        "AND ((r.challenger_id=:me AND r.target_id=p.user_id) "
        "OR (r.target_id=:me AND r.challenger_id=p.user_id)))<:pair_season "
        "ORDER BY p.dao_name COLLATE NOCASE LIMIT :limit OFFSET :offset",
        {"initial": rules.initial_rating, "season": season.season_id, "me": ctx.user_id,
         "realm": pet.realm, "rating": rating(ctx, season, ctx.user_id), "gap": rules.max_rating_gap,
         "day": beijing_day(ctx.now),
         "pair_daily": rules.pair_daily_matches, "pair_season": rules.pair_season_matches,
         "limit": PAGE_SIZE + 1, "offset": (page - 1) * PAGE_SIZE},
    ).fetchall()
    if page > 1 and not rows:
        raise GameError("该页暂无候选对手。")
    visible = rows[:PAGE_SIZE]
    lines = tuple(
        f"{row['dao_name']} · {row['name']} · {ctx.content.realms[pet.realm].name} {row['layer']}层"
        f" · 积分 {row['rating']}" for row in visible
    ) or ("暂无符合条件的候选对手。",)
    commands = [f"灵宠论剑 {row['dao_name']}" for row in visible]
    if page > 1:
        commands.append(f"灵宠匹配 {page - 1}")
    if len(rows) > PAGE_SIZE:
        commands.append(f"灵宠匹配 {page + 1}")
    return Reply(f"论剑候选 · {season.season_id} · 第{page}页", lines + ("直接挑战对方当前出战灵宠的镜像，无需对方在线。",), tuple(commands))
