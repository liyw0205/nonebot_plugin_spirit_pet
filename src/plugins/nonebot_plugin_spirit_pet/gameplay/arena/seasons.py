import json
from datetime import datetime

from ...application.context import Context
from ...domain.arena_content import ArenaTier
from ...domain.models import GameError, Reply
from ...utils.arguments import quantity
from ...utils.time import BEIJING
from .common import Season, current_season, load_season, stats

CATALOG_PAGE_SIZE = 4
RANK_PAGE_SIZE = 5


def _tier(season: Season, score: int) -> ArenaTier:
    return max((tier for tier in season.rules.tiers if tier.minimum_rating <= score),
               key=lambda tier: tier.minimum_rating)


def _eligible(season: Season, state: dict[str, int]) -> bool:
    return (state["qualifying_matches"] >= season.rules.reward_matches
            and state["opponents"] >= season.rules.reward_opponents)


def _claimed(ctx: Context, season: Season) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM season_claims WHERE season_id=? AND user_id=?", (season.season_id, ctx.user_id),
    ).fetchone() is not None


def _reward_text(ctx: Context, tier: ArenaTier) -> str:
    return "、".join((f"灵石 {tier.stones}", *(
        f"{ctx.content.items[item_id].name if item_id in ctx.content.items else '缺失物品定义'} {amount}"
        for item_id, amount in tier.items.items()
    )))


def _rules_page(ctx: Context, season: Season, page: int) -> Reply:
    pages = (len(season.rules.tiers) + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE
    if page > pages:
        raise GameError(f"该赛季奖励档位共 {pages} 页。")
    tiers = season.rules.tiers[(page - 1) * CATALOG_PAGE_SIZE:page * CATALOG_PAGE_SIZE]
    commands = []
    if page > 1:
        commands.append(f"灵宠赛季奖励 规则 {season.season_id} 分页 {page - 1}")
    if page < pages:
        commands.append(f"灵宠赛季奖励 规则 {season.season_id} 分页 {page + 1}")
    commands.extend((f"灵宠赛季 {season.season_id}", "灵宠赛季奖励"))
    return Reply(f"赛季档位 · {season.season_id} {page}/{pages}", (
        f"需 {season.rules.reward_matches} 场有效胜负及 {season.rules.reward_opponents} 位不同有效对手；"
        "赛季结束后只领取最终积分对应的最高一档。",
        *(f"{tier.name} · {tier.minimum_rating} 分起 · {_reward_text(ctx, tier)}。" for tier in tiers),
    ), tuple(commands))


def status(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    current = current_season(ctx)
    season = load_season(ctx, arg) if arg else current
    state = stats(ctx, season, ctx.user_id)
    ended = ctx.now >= season.ends_at
    claimed = _claimed(ctx, season)
    eligible = _eligible(season, state)
    tier = _tier(season, state["rating"])
    start = datetime.fromtimestamp(season.starts_at, BEIJING).strftime("%Y-%m-%d %H:%M")
    end = datetime.fromtimestamp(season.ends_at, BEIJING).strftime("%Y-%m-%d %H:%M")
    reward_state = "已领取" if claimed else "可领取" if ended and eligible else "未达到领奖资格" if ended else "赛季未结束"
    realm = next((realm.name for realm in ctx.content.realms if realm.id == season.rules.min_realm), "原赛季指定境界")
    commands = [f"灵宠论剑榜 {season.season_id}", "灵宠赛季奖励", f"灵宠赛季奖励 规则 {season.season_id}"]
    if ended and eligible and not claimed:
        commands.append(f"灵宠赛季领奖 {season.season_id}")
    elif not ended:
        commands.append("灵宠匹配")
    return Reply(f"论剑赛季 · {season.season_id}", (
        f"北京时间 {start} 至 {end}，{'已结束' if ended else '进行中'}；结束时刻起不再计分。",
        f"{player.dao_name} · 积分 {state['rating']} · {state['wins']} 胜 {state['losses']} 负 {state['draws']} 平。",
        f"准入：双方同大境界且达到{realm}，分差不超过 {season.rules.max_rating_gap}；"
        f"每场挑战者精力 {season.rules.energy}，胜负转移最多 {season.rules.rating_delta} 分。",
        f"今日主动挑战 {state['today_matches']}/{season.rules.daily_matches} 场；平局占用场次但不增加奖励资格。",
        f"同对玩家每日最多 {season.rules.pair_daily_matches} 场，本季最多 {season.rules.pair_season_matches} 场。",
        f"领奖资格：主动挑战有效胜负 {state['qualifying_matches']}/{season.rules.reward_matches} 场，"
        f"不同有效对手 {state['opponents']}/{season.rules.reward_opponents} 位。",
        f"{'最终' if ended else '当前'}积分档位：{tier.name} · 奖励状态：{reward_state}。",
        f"该档奖励：{_reward_text(ctx, tier)}。",
        "镜像防守不扣资源、不增加领奖资格；新赛季积分与战绩独立，只查看不入榜。",
    ), tuple(commands))


def catalog(ctx: Context, arg: str) -> Reply:
    ctx.player()
    current = current_season(ctx)
    parts = arg.split()
    if parts and parts[0] == "规则":
        if len(parts) == 1:
            return _rules_page(ctx, current, 1)
        if len(parts) == 2:
            return _rules_page(ctx, load_season(ctx, parts[1]), 1)
        if len(parts) == 3 and parts[1] == "分页":
            return _rules_page(ctx, current, quantity(parts[2], 999999))
        if len(parts) == 4 and parts[2] == "分页":
            return _rules_page(ctx, load_season(ctx, parts[1]), quantity(parts[3], 999999))
        raise GameError("格式：灵宠赛季奖励 规则 [YYYY-MM] [分页 N]。")
    page = quantity(arg or "1", 999999)
    conn = ctx.repo.conn
    source = "FROM season_entries e JOIN seasons s USING(season_id) WHERE e.user_id=? AND s.ends_at<=?"
    params = (ctx.user_id, ctx.now)
    count = conn.execute("SELECT COUNT(*) " + source, params).fetchone()[0]
    pages = max(1, (count + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    if page > pages:
        raise GameError(f"赛季奖励共 {pages} 页。")
    if count == 0:
        return _rules_page(ctx, current, 1)
    rows = conn.execute(
        "SELECT s.season_id " + source + " ORDER BY s.starts_at DESC LIMIT ? OFFSET ?",
        (*params, CATALOG_PAGE_SIZE, (page - 1) * CATALOG_PAGE_SIZE),
    ).fetchall()
    lines, commands = [], []
    for row in rows:
        season = load_season(ctx, row["season_id"])
        state = stats(ctx, season, ctx.user_id)
        label = "已领取" if _claimed(ctx, season) else "可领取" if _eligible(season, state) else "未达到领奖资格"
        lines.append(f"{season.season_id} · 最终积分 {state['rating']} · {_tier(season, state['rating']).name} · {label}")
        commands.append(f"灵宠赛季 {season.season_id}")
    if page > 1:
        commands.append(f"灵宠赛季奖励 {page - 1}")
    if page < pages:
        commands.append(f"灵宠赛季奖励 {page + 1}")
    commands.extend(("灵宠赛季", "灵宠赛季奖励 规则"))
    return Reply(f"赛季奖励 {page}/{pages}", tuple(lines) or ("尚无已结束的参赛赛季。",), tuple(commands))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    current_season(ctx)
    season = load_season(ctx, arg)
    if ctx.now < season.ends_at:
        raise GameError("该赛季尚未结束，不能领取奖励。")
    if _claimed(ctx, season):
        raise GameError("该赛季奖励已领取，不能重复结算。")
    state = stats(ctx, season, ctx.user_id)
    if not _eligible(season, state):
        raise GameError(f"领奖需要 {season.rules.reward_matches} 场有效胜负和 "
                        f"{season.rules.reward_opponents} 位不同有效对手；平局不计入领奖资格。")
    tier = _tier(season, state["rating"])
    if set(tier.items) - set(ctx.content.items):
        raise GameError("赛季奖励所需的物品定义缺失，请联系管理员恢复后重试；奖励尚未领取。")
    snapshot = {"tier_id": tier.id, "tier_name": tier.name, "rating": state["rating"],
                "stones": tier.stones, "items": tier.items}
    ctx.repo.conn.execute(
        "INSERT INTO season_claims(season_id, user_id, reward_snapshot, claimed_at) VALUES (?, ?, ?, ?)",
        (season.season_id, ctx.user_id, json.dumps(snapshot, ensure_ascii=False), ctx.now),
    )
    player.stones += tier.stones
    for item_id, amount in tier.items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    return Reply("赛季奖励已领取", (
        f"{player.dao_name} · {season.season_id} · {tier.name} · 最终积分 {state['rating']}。",
        f"灵石 +{tier.stones}。",
        *(f"{ctx.content.items[item_id].name} +{amount}" for item_id, amount in tier.items.items()),
    ), ("灵宠赛季奖励", "灵宠赛季", "灵宠背包"))


def rank(ctx: Context, arg: str) -> Reply:
    current = current_season(ctx)
    parts = arg.split()
    season, page = current, 1
    if len(parts) == 1:
        season = load_season(ctx, parts[0])
    elif len(parts) == 2 and parts[0] == "分页":
        page = quantity(parts[1], 999999)
    elif len(parts) == 3 and parts[1] == "分页":
        season = load_season(ctx, parts[0])
        page = quantity(parts[2], 999999)
    elif parts:
        raise GameError("格式：灵宠论剑榜 [YYYY-MM] [分页 N]。")
    conn = ctx.repo.conn
    total = conn.execute("SELECT COUNT(*) FROM season_entries WHERE season_id=?", (season.season_id,)).fetchone()[0]
    pages = max(1, (total + RANK_PAGE_SIZE - 1) // RANK_PAGE_SIZE)
    if page > pages:
        raise GameError(f"该赛季论剑榜共 {pages} 页。")
    rows = conn.execute(
        "SELECT p.dao_name, e.rating, e.wins, e.losses, e.draws FROM season_entries e "
        "JOIN players p USING(user_id) WHERE e.season_id=? "
        "ORDER BY e.rating DESC, e.wins DESC, p.dao_name COLLATE NOCASE LIMIT ? OFFSET ?",
        (season.season_id, RANK_PAGE_SIZE, (page - 1) * RANK_PAGE_SIZE),
    ).fetchall()
    viewer = ctx.repo.player(ctx.user_id)
    commands = [f"灵宠论剑 {row['dao_name']}" for row in rows
                if season.season_id == current.season_id and (viewer is None or row['dao_name'] != viewer.dao_name)]
    if page > 1:
        commands.append(f"灵宠论剑榜 {season.season_id} 分页 {page - 1}")
    if page < pages:
        commands.append(f"灵宠论剑榜 {season.season_id} 分页 {page + 1}")
    commands.append("灵宠匹配" if season.season_id == current.season_id else f"灵宠赛季 {season.season_id}")
    return Reply(f"论剑榜 · {season.season_id} {page}/{pages}", tuple(
        f"{(page - 1) * RANK_PAGE_SIZE + index}. {row['dao_name']} · 积分 {row['rating']}"
        f" · {row['wins']} 胜 {row['losses']} 负 {row['draws']} 平"
        for index, row in enumerate(rows, 1)
    ) or ("该赛季暂无论剑战绩。",), tuple(commands))
