"""Four-week race league standings, archive and one-week settlement claims."""

import json
from datetime import date, datetime

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING, beijing_day, beijing_week
from .race import time_text
from .rewards import grant

WEEK_SECONDS = 7 * 86_400
SEASON_WEEKS = 4
SEASON_SECONDS = SEASON_WEEKS * WEEK_SECONDS
PAGE_SIZE = 6
RANKING_PAGE_SIZE = 10
POINTS = {1: 12, 2: 8, 3: 5}


def _config(ctx: Context):
    row = ctx.repo.conn.execute(
        "SELECT enabled_at, first_week_start FROM race_league_config WHERE singleton=1"
    ).fetchone()
    if row is None:
        raise GameError("竞速联赛尚未初始化，请联系管理员检查存档。")
    return int(row["enabled_at"]), int(row["first_week_start"])


def season_start_for_week(first_week_start: int, week_start: int) -> int | None:
    if week_start < first_week_start:
        return None
    return first_week_start + ((week_start - first_week_start) // SEASON_SECONDS) * SEASON_SECONDS


def current_season_start(ctx: Context) -> int | None:
    _, first_week_start = _config(ctx)
    return season_start_for_week(first_week_start, beijing_week(ctx.now)[0])


def _label(timestamp: int) -> str:
    return beijing_day(timestamp)


def _date_range(start: int) -> str:
    end = start + SEASON_SECONDS - 1
    return f"{_label(start)} 至 {_label(end)}"


def _parse_start(value: str) -> int:
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise GameError("赛季编号格式：灵宠竞速联赛 2026-11-23（必须是周一日期）。") from exc
    start = int(datetime(day.year, day.month, day.day, tzinfo=BEIJING).timestamp())
    if beijing_week(start)[0] != start:
        raise GameError("赛季编号必须是周一的日期，例如 2026-11-23。")
    return start


def _season_start(ctx: Context, value: str) -> int:
    _, first_week_start = _config(ctx)
    start = _parse_start(value)
    current = current_season_start(ctx)
    if start < first_week_start or (start - first_week_start) % SEASON_SECONDS:
        raise GameError("该日期不是联赛赛季起始周；联赛从启用后的首个完整赛周开始。")
    if current is None or start > current:
        raise GameError("该赛季尚未开始，不能查看未来联赛数据。")
    return start


def _track_name(ctx: Context, track_id: str) -> str:
    entry = ctx.content.races.get(track_id)
    return entry.name if entry else track_id


def standings(ctx: Context, season_start: int) -> list[dict]:
    end = season_start + SEASON_SECONDS
    rows = ctx.repo.conn.execute(
        "SELECT identity.id + 9999 AS uid, best.user_id, best.week_start, "
        "best.track_id, best.best_tenths "
        "FROM race_track_bests best JOIN player_identity identity USING(user_id) "
        "WHERE best.week_start>=? AND best.week_start<? "
        "ORDER BY best.week_start, best.track_id, best.best_tenths, identity.id",
        (season_start, end),
    ).fetchall()
    by_user: dict[str, dict] = {}
    previous_key = None
    rank = 0
    for row in rows:
        key = (int(row["week_start"]), row["track_id"])
        rank = rank + 1 if key == previous_key else 1
        previous_key = key
        points = POINTS.get(rank, 1 if rank <= 10 else 0)
        user = by_user.setdefault(row["user_id"], {
            "user_id": row["user_id"], "uid": int(row["uid"]), "points": 0,
            "champions": 0, "podiums": 0, "weeks": [0] * SEASON_WEEKS,
            "results": {},
        })
        week_index = (int(row["week_start"]) - season_start) // WEEK_SECONDS
        user["points"] += points
        user["weeks"][week_index] += points
        user["champions"] += int(rank == 1)
        user["podiums"] += int(rank <= 3)
        user["results"][key] = {
            "rank": rank, "time": int(row["best_tenths"]), "points": points,
        }
    ordered = sorted(
        by_user.values(),
        key=lambda item: (-item["points"], -item["champions"], -item["podiums"], item["uid"]),
    )
    for position, item in enumerate(ordered, 1):
        item["rank"] = position
    return ordered


def _season_line(ctx: Context, season_start: int) -> tuple[str, list[dict]]:
    current = current_season_start(ctx)
    final = current is not None and season_start < current
    status = "已结算" if final else "暂定"
    rows = standings(ctx, season_start)
    lines = [
        f"赛季：{_date_range(season_start)} · {status}",
        "积分按每周三条赛道分别排名：12 / 8 / 5 / 1 分。",
    ]
    if rows:
        lines.append("总榜（积分 · 冠军数 · 前三数）：")
        lines.extend(
            f"{item['rank']}. UID {item['uid']} · {item['points']} 分 · "
            f"{item['champions']} 冠 · {item['podiums']} 次前三"
            for item in rows[:10]
        )
    else:
        lines.append("本赛季尚无联赛成绩。")
    mine = next((item for item in rows if item["user_id"] == ctx.user_id), None)
    if mine is None:
        lines.append("你本赛季尚未留下联赛成绩。")
    else:
        lines.append(f"你的赛季名次：第 {mine['rank']} 名 · {mine['points']} 分。")
        for week_index in range(SEASON_WEEKS):
            week_start = season_start + week_index * WEEK_SECONDS
            details = []
            for (record_week, track_id), result in sorted(mine["results"].items()):
                if record_week == week_start:
                    details.append(
                        f"{_track_name(ctx, track_id)}第{result['rank']}（{result['points']}分，"
                        f"{time_text(result['time'])}）"
                    )
            suffix = "、".join(details) if details else "未参赛，0 分"
            lines.append(f"第 {week_index + 1} 周：{mine['weeks'][week_index]} 分 · {suffix}")
    return "\n".join(lines), rows


def _claimable_start(ctx: Context) -> int | None:
    current = current_season_start(ctx)
    if current is None:
        return None
    current_week = beijing_week(ctx.now)[0]
    if current == current_week and current > _config(ctx)[1]:
        return current - SEASON_SECONDS
    return None


def _claim_row(ctx: Context, user_id: str, season_start: int):
    return ctx.repo.conn.execute(
        "SELECT rank, claimed_at, reward_snapshot FROM race_league_claims "
        "WHERE season_start=? AND user_id=?",
        (season_start, user_id),
    ).fetchone()


def _season_reply(ctx: Context, season_start: int) -> Reply:
    body, rows = _season_line(ctx, season_start)
    lines = body.split("\n")
    links = []
    claimable = _claimable_start(ctx)
    mine = next((item for item in rows if item["user_id"] == ctx.user_id), None)
    if claimable == season_start and mine is not None and mine["rank"] <= 3:
        claim = _claim_row(ctx, ctx.user_id, season_start)
        state = "已领取" if claim else "可领取"
        lines.append(f"你的结算奖励：第 {mine['rank']} 名 · {state}。")
        if claim is None:
            links.append(InlineCommand(
                len(lines) - 1, "领取联赛奖励", f"灵宠联赛领奖 {_label(season_start)}",
            ))
    elif mine is not None and mine["rank"] <= 3 and season_start < (current_season_start(ctx) or 0):
        claim = _claim_row(ctx, ctx.user_id, season_start)
        lines.append(f"你的最终名次：第 {mine['rank']} 名 · " + ("已领取。" if claim else "领奖期已过。"))
    if season_start != current_season_start(ctx):
        links.append(InlineCommand(len(lines) - 1, "当前赛季", "灵宠竞速联赛"))
    rank_command = "灵宠竞速联赛"
    if season_start != current_season_start(ctx):
        rank_command += f" {_label(season_start)}"
    rank_command += " 榜单 1"
    lines.append("完整赛季排行可分页查看。")
    links.append(InlineCommand(len(lines) - 1, "查看总榜", rank_command))
    lines.append("往期赛季与结算记录可从档案查看。")
    links.append(InlineCommand(len(lines) - 1, "往期赛季", "灵宠竞速联赛 往期"))
    return Reply(
        "灵宠竞速联赛", tuple(lines),
        ("灵宠竞速", "灵宠竞速榜", "灵宠竞速奖励", "灵宠帮助"), tuple(links),
    )


def _ranking_page(ctx: Context, season_start: int, page: int) -> Reply:
    if page < 1:
        raise GameError("页码必须从 1 开始。")
    rows = standings(ctx, season_start)
    pages = max(1, (len(rows) + RANKING_PAGE_SIZE - 1) // RANKING_PAGE_SIZE)
    if page > pages:
        raise GameError(f"该赛季联赛榜单只有 {pages} 页。")
    visible = rows[(page - 1) * RANKING_PAGE_SIZE: page * RANKING_PAGE_SIZE]
    status = "已结算" if season_start < (current_season_start(ctx) or 0) else "暂定"
    lines = [
        f"竞速联赛总榜 · {_date_range(season_start)} · {status} · 第 {page}/{pages} 页"
        f"（共 {len(rows)} 人）",
    ]
    if visible:
        lines.extend(
            f"{item['rank']}. UID {item['uid']} · {item['points']} 分 · "
            f"{item['champions']} 冠 · {item['podiums']} 次前三 · "
            f"周次积分 {'/'.join(map(str, item['weeks']))}"
            for item in visible
        )
    else:
        lines.append("本赛季尚无联赛成绩。")
    command = "灵宠竞速联赛"
    if season_start != current_season_start(ctx):
        command += f" {_label(season_start)}"
    links = []
    navigation = []
    if page > 1:
        navigation.append((page - 1, "上一页"))
    if page < pages:
        navigation.append((page + 1, "下一页"))
    if navigation:
        lines.append("翻页：" + " / ".join(
            f"{command} 榜单 {target}" for target, _ in navigation
        ))
        links.extend(
            InlineCommand(
                len(lines) - 1, label, f"{command} 榜单 {target}",
            )
            for target, label in navigation
        )
    return Reply(
        "竞速联赛总榜", tuple(lines),
        ("灵宠竞速联赛", "灵宠竞速", "灵宠帮助"), tuple(links),
    )


def _archive(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if len(parts) > 2:
        raise GameError("格式：灵宠竞速联赛 往期 [页码]。")
    page = 1
    if len(parts) == 2:
        try:
            page = int(parts[1])
        except ValueError as exc:
            raise GameError("格式：灵宠竞速联赛 往期 [页码]。") from exc
    if page < 1:
        raise GameError("页码必须从 1 开始。")
    _, first_week_start = _config(ctx)
    current = current_season_start(ctx)
    seasons = []
    if current is not None:
        seasons = [
            start for start in range(first_week_start, current, SEASON_SECONDS)
            if start + SEASON_SECONDS <= ctx.now
        ]
        seasons.sort(reverse=True)
    pages = max(1, (len(seasons) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"往期联赛只有 {pages} 页。")
    lines = [f"往期竞速联赛（第 {page}/{pages} 页，每页 {PAGE_SIZE} 季）："]
    links = []
    for start in seasons[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        rows = standings(ctx, start)
        if rows:
            winner = rows[0]
            lines.append(
                f"{_date_range(start)} · 冠军 UID {winner['uid']} · {winner['points']} 分 · "
                f"共 {len(rows)} 人"
            )
        else:
            lines.append(f"{_date_range(start)} · 无人参赛")
        links.append(InlineCommand(len(lines) - 1, "查看赛季", f"灵宠竞速联赛 {_label(start)}"))
    if not seasons:
        lines.append("还没有已结算的联赛赛季。")
    if pages > 1:
        navigation = []
        if page > 1:
            navigation.append(f"灵宠竞速联赛 往期 {page - 1}")
        if page < pages:
            navigation.append(f"灵宠竞速联赛 往期 {page + 1}")
        lines.append("翻页：" + " / ".join(navigation))
        if page > 1:
            links.append(InlineCommand(len(lines) - 1, "上一页", navigation[0]))
        if page < pages:
            links.append(InlineCommand(len(lines) - 1, "下一页", navigation[-1]))
    return Reply(
        "灵宠竞速联赛 · 往期", tuple(lines),
        ("灵宠竞速联赛", "灵宠竞速", "灵宠帮助"), tuple(links),
    )


def dispatch(ctx: Context, argument: str) -> Reply:
    value = argument.strip()
    if value == "往期" or value.startswith("往期 "):
        return _archive(ctx, value)
    parts = value.split()
    if parts and parts[0] == "榜单":
        current = current_season_start(ctx)
        if current is None:
            raise GameError("首个完整赛周尚未开始，当前没有联赛榜单。")
        if len(parts) > 2:
            raise GameError("格式：灵宠竞速联赛 榜单 [页码]。")
        page = 1
        if len(parts) == 2:
            try:
                page = int(parts[1])
            except ValueError as exc:
                raise GameError("格式：灵宠竞速联赛 榜单 [页码]。") from exc
        return _ranking_page(ctx, current, page)
    if len(parts) >= 2 and parts[1] == "榜单":
        if len(parts) > 3:
            raise GameError("格式：灵宠竞速联赛 <赛季起始周> 榜单 [页码]。")
        season_start = _season_start(ctx, parts[0])
        page = 1
        if len(parts) == 3:
            try:
                page = int(parts[2])
            except ValueError as exc:
                raise GameError("格式：灵宠竞速联赛 <赛季起始周> 榜单 [页码]。") from exc
        return _ranking_page(ctx, season_start, page)
    current = current_season_start(ctx)
    if not value:
        if current is None:
            first_week_start = _config(ctx)[1]
            return Reply("灵宠竞速联赛", (
                f"联赛已启用，首个完整赛周从 {_label(first_week_start)} 开始。",
                "启用前的旧周成绩不会回填。",
            ), ("灵宠竞速", "灵宠竞速榜", "灵宠帮助"))
        return _season_reply(ctx, current)
    return _season_reply(ctx, _season_start(ctx, value))


def claim(ctx: Context, argument: str) -> Reply:
    eligible_start = _claimable_start(ctx)
    if eligible_start is None:
        raise GameError("当前不是联赛领奖期；前三名仅可在赛季结束后的下一个自然周领取。")
    value = argument.strip()
    if value and _parse_start(value) != eligible_start:
        raise GameError("只能领取最近结束赛季的联赛奖励；更早赛季不补发。")
    player = ctx.player()
    if _claim_row(ctx, player.user_id, eligible_start) is not None:
        raise GameError("本赛季联赛奖励已经领取。")
    rows = standings(ctx, eligible_start)
    mine = next((item for item in rows if item["user_id"] == player.user_id), None)
    if mine is None:
        raise GameError("你本赛季没有参赛，没有可领取的联赛奖励。")
    rank = mine["rank"]
    if rank > 3:
        raise GameError(f"你本赛季第 {rank} 名，未进入前三，没有可领取的联赛奖励。")
    prize = ctx.content.race_league_prizes.get(rank)
    if prize is None or any(item_id not in ctx.content.items for item_id in prize.items):
        raise GameError("联赛奖励定义缺失；尚未领取。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=prize.stones, maximum=prize.stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in prize.items.items()},
    )
    result = grant(ctx, reward, player.user_id)
    snapshot = json.dumps(
        {"rank": rank, "stones": prize.stones, "items": dict(sorted(prize.items.items()))},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO race_league_claims(season_start, user_id, rank, claimed_at, reward_snapshot) "
        "VALUES (?, ?, ?, ?, ?)",
        (eligible_start, player.user_id, rank, ctx.now, snapshot),
    )
    return Reply("竞速联赛奖励", (
        f"{_date_range(eligible_start)} · 第 {rank} 名 · {mine['points']} 分。",
        *result,
        "赛季联赛奖励已领取；单周竞速奖励独立结算，不受本次领取影响。",
    ), ("灵宠竞速联赛", "灵宠竞速奖励", "灵宠目标"))


def objective_line(ctx: Context, user_id: str) -> str:
    current = current_season_start(ctx)
    if current is None:
        return f"竞速联赛：首个完整赛周 {_label(_config(ctx)[1])} 开启"
    claimable = _claimable_start(ctx)
    if claimable is not None and _claim_row(ctx, user_id, claimable) is None:
        mine = next((item for item in standings(ctx, claimable) if item["user_id"] == user_id), None)
        if mine is not None and mine["rank"] <= 3:
            return f"竞速联赛：上季第 {mine['rank']} 名，奖励可领"
    mine = next((item for item in standings(ctx, current) if item["user_id"] == user_id), None)
    if mine is None:
        return "竞速联赛：本季尚未参赛"
    return f"竞速联赛：本季 {mine['points']} 分 · 第 {mine['rank']} 名 · 暂定"


__all__ = ["claim", "current_season_start", "dispatch", "objective_line", "season_start_for_week", "standings"]
