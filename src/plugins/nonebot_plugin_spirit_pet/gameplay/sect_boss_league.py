"""Three-week standings derived exclusively from the sect boss damage ledger."""

import json
from dataclasses import asdict
from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING, WEEK_SECONDS
from . import sects
from .rewards import grant

SEASON_WEEKS = 3
SEASON_SECONDS = SEASON_WEEKS * WEEK_SECONDS
PAGE_SIZE = 8


def season_start(timestamp: int, first_start: int) -> int | None:
    if timestamp < first_start:
        return None
    return first_start + (timestamp - first_start) // SEASON_SECONDS * SEASON_SECONDS


def _start_for(ctx: Context, timestamp: int) -> int | None:
    return season_start(timestamp, _anchor(ctx))


def _anchor(ctx: Context) -> int:
    anchor = ctx.repo.conn.execute(
        "SELECT MIN(season_start) AS season_start FROM sect_boss_league_seasons",
    ).fetchone()["season_start"]
    if anchor is None:
        anchor = ctx.content.sect_boss_league.first_season_start
    return int(anchor)


def _season_row(ctx: Context, start: int):
    return ctx.repo.conn.execute(
        "SELECT * FROM sect_boss_league_seasons WHERE season_start=?", (start,),
    ).fetchone()


def _snapshot(ctx: Context) -> str:
    return json.dumps(
        ctx.content.sect_boss_league.model_dump(mode="json"),
        ensure_ascii=False, separators=(",", ":"),
    )


def _rules(row):
    return json.loads(row["snapshot"])


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, BEIJING).date().isoformat()


def _finalize_due(ctx: Context) -> None:
    ctx.repo.conn.execute(
        "UPDATE sect_boss_league_seasons SET finalized_at=ends_at "
        "WHERE finalized_at IS NULL AND ends_at<=?", (ctx.now,),
    )


def _leader_rows(ctx: Context, season, sect_id: str) -> list[dict]:
    start = int(season["season_start"])
    rules = _rules(season)
    cap = int(rules["points_per_week"])
    entries = ctx.repo.conn.execute(
        "SELECT e.*, i.id AS stable_id FROM sect_boss_league_entries e "
        "JOIN player_identity i ON i.user_id=e.user_id "
        "WHERE e.season_start=? AND e.sect_id=?",
        (start, sect_id),
    ).fetchall()
    rows = []
    for entry in entries:
        weekly = ctx.repo.conn.execute(
            "SELECT a.week_start,SUM(a.damage) AS damage,w.max_hp "
            "FROM sect_boss_attacks a JOIN sect_boss_weeks w "
            "ON w.week_start=a.week_start AND w.sect_id=a.sect_id "
            "WHERE a.user_id=? AND a.sect_id=? AND a.week_start>=? AND a.week_start<? "
            "AND a.created_at>=? GROUP BY a.week_start,w.max_hp",
            (entry["user_id"], sect_id, start, start + SEASON_SECONDS, entry["registered_at"]),
        ).fetchall()
        points_by_week = {}
        total_damage = 0
        active_weeks = 0
        for week in weekly:
            damage = int(week["damage"])
            max_hp = int(week["max_hp"])
            points_by_week[int(week["week_start"])] = min(cap, damage * cap // max_hp)
            total_damage += damage
            active_weeks += damage > 0
        score = sum(points_by_week.values())
        rows.append({
            "user_id": entry["user_id"], "sect_id": sect_id,
            "uid": int(entry["public_uid"]), "stable_id": int(entry["stable_id"]),
            "score": score, "active_weeks": active_weeks,
            "best_week": max(points_by_week.values(), default=0),
            "damage": total_damage, "weekly": points_by_week,
            "complete": active_weeks >= int(rules["minimum_weeks"]),
        })
    return sorted(rows, key=lambda row: (
        -row["score"], -row["active_weeks"], -row["best_week"], -row["damage"], row["uid"],
    ))


def _qualified(rows: list[dict], season) -> list[dict]:
    rules = _rules(season)
    eligible = [row for row in rows if row["complete"]]
    if len(eligible) < int(rules["minimum_entrants"]):
        return []
    return eligible[:3]


def _sect_progress(ctx: Context, season) -> list[dict]:
    start = int(season["season_start"])
    cap = int(_rules(season)["points_per_week"])
    rows = []
    for sect_id, sect in sorted(ctx.content.sects.items()):
        defeats = 0
        normalized = 0
        for week_start in range(start, start + SEASON_SECONDS, WEEK_SECONDS):
            week = ctx.repo.conn.execute(
                "SELECT max_hp,state FROM sect_boss_weeks WHERE week_start=? AND sect_id=?",
                (week_start, sect_id),
            ).fetchone()
            if week is None:
                continue
            if week["state"] == "defeated":
                defeats += 1
            damage = ctx.repo.conn.execute(
                "SELECT COALESCE(SUM(damage),0) AS damage FROM sect_boss_attacks "
                "WHERE week_start=? AND sect_id=?", (week_start, sect_id),
            ).fetchone()["damage"]
            normalized += min(cap, int(damage) * cap // int(week["max_hp"]))
        rows.append({"sect_id": sect_id, "name": sect.name, "defeats": defeats, "progress": normalized})
    return sorted(rows, key=lambda row: (-row["defeats"], -row["progress"], row["sect_id"]))


def _resolve_season(ctx: Context, value: str | None):
    if value is None:
        start = _start_for(ctx, ctx.now)
        if start is None:
            return None
    elif value.isdecimal():
        start = int(value)
    else:
        try:
            timestamp = int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=BEIJING).timestamp())
        except ValueError as error:
            raise GameError("赛季请使用 Unix 周起点或北京时间日期。") from error
        start = _start_for(ctx, timestamp)
        if start is None or _date(start) != value:
            raise GameError("日期不在任何已配置赛季内。")
    if start < _anchor(ctx) or season_start(start, _anchor(ctx)) != start:
        raise GameError("赛季起点无效。")
    row = _season_row(ctx, start)
    if row is None:
        raise GameError("该赛季尚无有效报名记录。")
    return row


def register(ctx: Context, arg: str = "") -> Reply:
    ctx.player()
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("先拜入师门，再锁定共讨联赛门派。")
    parts = arg.split()
    if len(parts) not in {0, 2}:
        raise GameError("格式：灵宠师门 共讨 联赛 报名 [赛季起点 门派]。")
    start = _start_for(ctx, ctx.now)
    if start is None:
        raise GameError("共讨联赛尚未开放。")
    if len(parts) == 2 and (not parts[0].isdecimal() or int(parts[0]) != start or parts[1] != sect.id):
        raise GameError("报名入口已过期或门派已变化，请重新打开联赛页面。")
    if not start <= ctx.now < start + WEEK_SECONDS:
        raise GameError("仅可在赛季首周报名；不能补报名或变更已锁定门派。")
    existing = ctx.repo.conn.execute(
        "SELECT sect_id FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (start, ctx.user_id),
    ).fetchone()
    if existing is not None:
        raise GameError(f"本赛季已锁定{ctx.content.sects[existing['sect_id']].name}，不能重复报名。")
    if ctx.repo.conn.execute(
        "SELECT 1 FROM sect_boss_attacks WHERE user_id=? AND week_start=? LIMIT 1",
        (ctx.user_id, start),
    ).fetchone() is not None:
        raise GameError("本周已经参加共讨，不能补报名。")
    _finalize_due(ctx)
    season = _season_row(ctx, start)
    if season is not None and season["finalized_at"] is not None:
        raise GameError("该赛季已结算，不能回拨补报名。")
    if season is None:
        ctx.repo.conn.execute(
            "INSERT INTO sect_boss_league_seasons(season_start,ends_at,created_at,snapshot,finalized_at) "
            "VALUES (?,?,?,?,NULL)",
            (start, start + SEASON_SECONDS, ctx.now, _snapshot(ctx)),
        )
    identity = ctx.repo.conn.execute(
        "SELECT id FROM player_identity WHERE user_id=?", (ctx.user_id,),
    ).fetchone()
    ctx.repo.conn.execute(
        "INSERT INTO sect_boss_league_entries(season_start,user_id,sect_id,public_uid,operation_id,registered_at) "
        "VALUES (?,?,?,?,?,?)",
        (start, ctx.user_id, sect.id, int(identity["id"]), ctx.operation_id, ctx.now),
    )
    return Reply("师门共讨联赛 · 报名成功", (
        f"已锁定{sect.name}参加 {_date(start)} 至 {_date(start + SEASON_SECONDS)} 三周联赛。",
        "积分仅统计报名后本门共讨实际伤害；转派不会转移资格或贡献。",
    ), ("灵宠师门 共讨 联赛", "灵宠师门 共讨 联赛 榜"))


def _overview(ctx: Context, season) -> Reply:
    start = int(season["season_start"]) if season is not None else _start_for(ctx, ctx.now)
    lines = []
    links = []
    if start is None:
        first = ctx.content.sect_boss_league.first_season_start
        lines.append(f"首个共讨联赛将于北京时间 {_date(first)} 开始。")
        return Reply("师门共讨联赛", tuple(lines), ("灵宠师门 共讨", "灵宠帮助"))
    end = start + SEASON_SECONDS
    if season is None:
        lines.append(f"赛季 {_date(start)} 至 {_date(end)}；报名与规则快照只在首位有效报名者操作时建立。")
    else:
        phase = (
            "已结算" if season["finalized_at"] is not None else
            "待结算" if ctx.now >= end else "进行中"
        )
        lines.append(f"赛季 {_date(start)} 至 {_date(end)} · {phase}。")
    rules = _rules(season) if season is not None else ctx.content.sect_boss_league.model_dump(mode="json")
    cap = int(rules["points_per_week"])
    lines.append(
        f"每周最高 {cap} 分；至少有效参赛 {rules['minimum_weeks']} 周，"
        "个人榜按积分、参赛周、单周最佳、实际伤害和 UID 排序。"
    )
    current_start = _start_for(ctx, ctx.now)
    entry = None
    if season is not None:
        entry = ctx.repo.conn.execute(
            "SELECT * FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
            (start, ctx.user_id),
        ).fetchone()
    if entry is not None:
        lines.append(f"我已锁定{ctx.content.sects[entry['sect_id']].name}。")
    elif current_start == start and start <= ctx.now < start + WEEK_SECONDS:
        sect = sects.current(ctx)
        if sect is None:
            lines.append("拜入师门后可报名；报名会永久锁定本赛季门派。")
        else:
            attacked = ctx.repo.conn.execute(
                "SELECT 1 FROM sect_boss_attacks WHERE user_id=? AND week_start=? LIMIT 1",
                (ctx.user_id, start),
            ).fetchone()
            if attacked:
                lines.append("本周已有共讨攻击，不能补报名。")
            else:
                lines.append(f"首周可锁定{sect.name}报名。")
                links.append(InlineCommand(
                    len(lines) - 1, "锁定门派报名",
                    f"灵宠师门 共讨 联赛 报名 {start} {sect.id}",
                ))
    else:
        lines.append("报名仅在首周开放；未报名成员的共讨仍按原规则进行。")
    if season is not None:
        progress = _sect_progress(ctx, season)
        lines.append("四门派进度：" + "；".join(
            f"{row['name']} {row['defeats']}/3 次击败 · {row['progress']}/{3 * cap} 归一分"
            for row in progress
        ))
        links.append(InlineCommand(len(lines) - 1, "四门派进度榜", f"灵宠师门 共讨 联赛 门派榜 {start}"))
        if entry is not None:
            rows = _leader_rows(ctx, season, entry["sect_id"])
            own = next((row for row in rows if row["user_id"] == ctx.user_id), None)
            if own is not None:
                lines.append(
                    f"我的积分 {own['score']} · 有效参赛 {own['active_weeks']}/3 周 · "
                    f"{'完赛' if own['complete'] else '未完赛'}。"
                )
                links.append(InlineCommand(len(lines) - 1, "个人门派榜", f"灵宠师门 共讨 联赛 榜 {start}"))
            if start + SEASON_SECONDS <= ctx.now < start + 2 * SEASON_SECONDS:
                eligible = _qualified(rows, season)
                rank = next((index for index, row in enumerate(eligible, 1) if row["user_id"] == ctx.user_id), None)
                claimed = ctx.repo.conn.execute(
                    "SELECT 1 FROM sect_boss_league_claims WHERE season_start=? AND user_id=?",
                    (start, ctx.user_id),
                ).fetchone()
                if rank is not None and claimed is None:
                    lines.append(f"赛季最终第 {rank} 名奖励已开放领取。")
                    links.append(InlineCommand(
                        len(lines) - 1, "领取赛季奖励", f"灵宠师门 共讨 联赛 领奖 {start} {rank}",
                    ))
    if season is None:
        lines.append("本季榜单会在首位有效报名后建立；可先查看有记录的往期赛季。")
        links.append(InlineCommand(len(lines) - 1, "往期赛季", "灵宠师门 共讨 联赛 历史"))
    else:
        lines.append("查看个人门派积分榜、逐周战历和已结束赛季。")
        links.append(InlineCommand(len(lines) - 1, "我的联赛战历", f"灵宠师门 共讨 联赛 战历 {start}"))
    current = _start_for(ctx, ctx.now)
    previous = current - SEASON_SECONDS if current is not None else None
    if previous is not None and (season is None or previous != int(season["season_start"])):
        rank = claimable(ctx, ctx.user_id)
        if rank is not None:
            lines.append(f"上一赛季第 {rank} 名奖励已开放领取。")
            links.append(InlineCommand(
                len(lines) - 1, "领取上一赛季奖励",
                f"灵宠师门 共讨 联赛 领奖 {previous} {rank}",
            ))
    return Reply("师门共讨联赛", tuple(lines), ("灵宠师门 共讨", "灵宠目标"), tuple(links))


def page(ctx: Context, arg: str = "") -> Reply:
    parts = arg.split()
    if len(parts) > 1:
        raise GameError("格式：灵宠师门 共讨 联赛 [赛季起点]。")
    ctx.player()
    if parts:
        return _overview(ctx, _resolve_season(ctx, parts[0]))
    start = _start_for(ctx, ctx.now)
    season = _season_row(ctx, start) if start is not None else None
    return _overview(ctx, season)


def ranking(ctx: Context, arg: str = "") -> Reply:
    parts = arg.split()
    if len(parts) > 2:
        raise GameError("格式：灵宠师门 共讨 联赛 榜 [赛季起点] [页码]。")
    ctx.player()
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("先拜入师门后查看个人门派榜。")
    season = _resolve_season(ctx, parts[0] if parts else None)
    if season is None:
        raise GameError("当前尚无已开始赛季。")
    entry = ctx.repo.conn.execute(
        "SELECT sect_id FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (season["season_start"], ctx.user_id),
    ).fetchone()
    if entry is None:
        raise GameError("本赛季尚未报名，个人联赛榜不包含未报名成员。")
    page_no = parts[-1] if len(parts) == 2 else "1"
    if not page_no.isdecimal() or int(page_no) < 1:
        raise GameError("页码必须是正整数。")
    rows = _leader_rows(ctx, season, sect.id)
    page_num = int(page_no)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page_num > pages:
        raise GameError(f"榜单共 {pages} 页。")
    visible = rows[(page_num - 1) * PAGE_SIZE:page_num * PAGE_SIZE]
    qualified = {row["user_id"]: rank for rank, row in enumerate(_qualified(rows, season), 1)}
    lines = [f"{sect.name}共讨联赛榜 {page_num}/{pages} · {_date(season['season_start'])} 起。"]
    for rank, row in enumerate(visible, (page_num - 1) * PAGE_SIZE + 1):
        complete = "完赛" if row["complete"] else "未完赛"
        prize_rank = qualified.get(row["user_id"])
        reward = f" · 奖励第 {prize_rank}" if prize_rank else ""
        lines.append(
            f"{rank}. UID {row['uid'] + 9999} · {row['score']} 分 · {row['active_weeks']}/3 周 · "
            f"{complete} · 实伤 {row['damage']}{reward}"
        )
    if not visible:
        lines.append("本赛季暂无报名成员。")
    own_rank = next((i for i, row in enumerate(rows, 1) if row["user_id"] == ctx.user_id), None)
    if own_rank:
        lines.append(f"我的榜单位置：第 {own_rank}。")
    return Reply("师门共讨联赛 · 个人榜", tuple(lines), ("灵宠师门 共讨 联赛",))


def sect_ranking(ctx: Context, arg: str = "") -> Reply:
    parts = arg.split()
    if len(parts) > 1:
        raise GameError("格式：灵宠师门 共讨 联赛 门派榜 [赛季起点]。")
    ctx.player()
    season = _resolve_season(ctx, parts[0] if parts else None)
    if season is None:
        raise GameError("当前尚无已开始赛季。")
    cap = int(_rules(season)["points_per_week"])
    lines = [f"四门派进度榜 · {_date(season['season_start'])} 起。"]
    for rank, row in enumerate(_sect_progress(ctx, season), 1):
        lines.append(
            f"{rank}. {row['name']} · 击败 {row['defeats']}/3 周 · {row['progress']}/{3 * cap} 归一分"
        )
    return Reply("师门共讨联赛 · 门派榜", tuple(lines), ("灵宠师门 共讨 联赛",))


def history(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 共讨 联赛 历史。")
    ctx.player()
    rows = ctx.repo.conn.execute(
        "SELECT season_start,ends_at,finalized_at FROM sect_boss_league_seasons ORDER BY season_start DESC",
    ).fetchall()
    lines = ["有报名记录的师门共讨联赛赛季："]
    links = []
    for row in rows[:PAGE_SIZE]:
        lines.append(
            f"{_date(row['season_start'])} 至 {_date(row['ends_at'])} · "
            f"{'已结算' if row['finalized_at'] else '未结算'}。"
        )
        links.append(InlineCommand(len(lines) - 1, "查看赛季", f"灵宠师门 共讨 联赛 {row['season_start']}"))
    if not rows:
        lines.append("尚无已建立的赛季记录。")
    return Reply("师门共讨联赛 · 往期", tuple(lines), ("灵宠师门 共讨 联赛",), tuple(links))


def battle_history(ctx: Context, arg: str = "") -> Reply:
    parts = arg.split()
    if len(parts) > 1:
        raise GameError("格式：灵宠师门 共讨 联赛 战历 [赛季起点]。")
    ctx.player()
    season = _resolve_season(ctx, parts[0] if parts else None)
    if season is None:
        raise GameError("当前尚无已开始赛季。")
    entry = ctx.repo.conn.execute(
        "SELECT * FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (season["season_start"], ctx.user_id),
    ).fetchone()
    if entry is None:
        raise GameError("本赛季尚未报名，没有个人联赛战历。")
    rows = _leader_rows(ctx, season, entry["sect_id"])
    own = next(row for row in rows if row["user_id"] == ctx.user_id)
    lines = [f"锁定门派：{ctx.content.sects[entry['sect_id']].name} · UID {own['uid'] + 9999}。"]
    for week_start in range(int(season["season_start"]), int(season["ends_at"]), WEEK_SECONDS):
        score = own["weekly"].get(week_start, 0)
        damage = ctx.repo.conn.execute(
            "SELECT COALESCE(SUM(a.damage),0) AS damage,w.max_hp "
            "FROM sect_boss_weeks w LEFT JOIN sect_boss_attacks a "
            "ON a.week_start=w.week_start AND a.sect_id=w.sect_id AND a.user_id=? AND a.created_at>=? "
            "WHERE w.week_start=? AND w.sect_id=? GROUP BY w.max_hp",
            (ctx.user_id, entry["registered_at"], week_start, entry["sect_id"]),
        ).fetchone()
        if damage is None:
            lines.append(f"{_date(week_start)} · 尚无本门首领记录 · 0 分。")
        else:
            lines.append(
                f"{_date(week_start)} · 实伤 {damage['damage']}/{damage['max_hp']} · {score} 分。"
            )
    lines.append(f"合计 {own['score']} 分 · {'完赛' if own['complete'] else '未完赛'}。")
    return Reply("师门共讨联赛 · 个人战历", tuple(lines), ("灵宠师门 共讨 联赛 榜",))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        raise GameError("格式：灵宠师门 共讨 联赛 领奖 <赛季起点> <名次>。")
    start, requested_rank = map(int, parts)
    prior = ctx.repo.conn.execute(
        "SELECT user_id,reply FROM sect_boss_league_claims WHERE operation_id=?", (ctx.operation_id,),
    ).fetchone()
    if prior is not None:
        if prior["user_id"] != ctx.user_id:
            raise GameError("该领奖操作已由其他身份使用。")
        return Reply.from_data(json.loads(prior["reply"]))
    _finalize_due(ctx)
    season = _resolve_season(ctx, str(start))
    if season is None or not start + SEASON_SECONDS <= ctx.now < start + 2 * SEASON_SECONDS:
        raise GameError("仅可在赛季结束后的紧接三周领取。")
    ctx.player()
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("领奖时仍须属于赛季锁定门派。")
    entry = ctx.repo.conn.execute(
        "SELECT * FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (start, ctx.user_id),
    ).fetchone()
    if entry is None:
        raise GameError("本赛季尚未报名。")
    if entry["sect_id"] != sect.id:
        raise GameError("当前门派与赛季锁定门派不同，不能领取。")
    if ctx.repo.conn.execute(
        "SELECT 1 FROM sect_boss_league_claims WHERE season_start=? AND user_id=?", (start, ctx.user_id),
    ).fetchone() is not None:
        raise GameError("本赛季奖励已经领取。")
    rows = _leader_rows(ctx, season, sect.id)
    qualified = _qualified(rows, season)
    actual_rank = next((rank for rank, row in enumerate(qualified, 1) if row["user_id"] == ctx.user_id), None)
    if actual_rank is None:
        raise GameError("未达到有效完赛周数或本门报名人数不足，不产生名次奖励。")
    if requested_rank != actual_rank:
        raise GameError(f"当前有效名次为第 {actual_rank}，领奖参数与结算名次不符。")
    prize = next((prize for prize in _rules(season)["prizes"] if prize["rank"] == actual_rank), None)
    if prize is None:
        raise GameError("该名次没有赛季奖励。")
    from ..domain.content import Range, Reward

    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=prize["stones"], maximum=prize["stones"]),
        items={item: Range(minimum=amount, maximum=amount) for item, amount in prize["items"].items()},
    )
    granted = grant(ctx, reward)
    reply = Reply(
        "师门共讨联赛奖励",
        (f"最终第 {actual_rank} 名已领取：{'，'.join(granted)}。",),
        ("灵宠师门 共讨 联赛", "我的灵宠"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO sect_boss_league_claims(season_start,user_id,sect_id,rank,operation_id,claimed_at,"
        "reward_snapshot,reply) VALUES (?,?,?,?,?,?,?,?)",
        (start, ctx.user_id, sect.id, actual_rank, ctx.operation_id, ctx.now,
         json.dumps(prize, ensure_ascii=False, separators=(",", ":")),
         json.dumps(asdict(reply), ensure_ascii=False, separators=(",", ":"))),
    )
    return reply


def claimable(ctx: Context, user_id: str) -> int | None:
    current = _start_for(ctx, ctx.now)
    if current is None:
        return None
    start = current - SEASON_SECONDS
    if not start + SEASON_SECONDS <= ctx.now < start + 2 * SEASON_SECONDS:
        return None
    season = _season_row(ctx, start)
    if season is None:
        return None
    entry = ctx.repo.conn.execute(
        "SELECT sect_id FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (start, user_id),
    ).fetchone()
    if entry is None or sects.current(ctx, user_id) is None or sects.current(ctx, user_id).id != entry["sect_id"]:
        return None
    if ctx.repo.conn.execute(
        "SELECT 1 FROM sect_boss_league_claims WHERE season_start=? AND user_id=?",
        (start, user_id),
    ).fetchone() is not None:
        return None
    rows = _leader_rows(ctx, season, entry["sect_id"])
    return next(
        (rank for rank, row in enumerate(_qualified(rows, season), 1) if row["user_id"] == user_id),
        None,
    )


def before_challenge(ctx: Context, week_start: int, sect_id: str) -> None:
    _finalize_due(ctx)
    start = _start_for(ctx, week_start)
    if start is None:
        return
    season = _season_row(ctx, start)
    if season is not None and season["finalized_at"] is not None:
        raise GameError("该联赛赛季已结算，不能追加任何共讨伤害。")


def objective_line(ctx: Context, user_id: str) -> str | None:
    start = _start_for(ctx, ctx.now)
    if start is None:
        return None
    entry = ctx.repo.conn.execute(
        "SELECT sect_id FROM sect_boss_league_entries WHERE season_start=? AND user_id=?",
        (start, user_id),
    ).fetchone()
    if entry is None:
        if start <= ctx.now < start + WEEK_SECONDS and sects.current(ctx, user_id) is not None:
            if ctx.repo.conn.execute(
                "SELECT 1 FROM sect_boss_attacks WHERE user_id=? AND week_start=? LIMIT 1",
                (user_id, start),
            ).fetchone() is not None:
                return "师门共讨联赛：本周已有攻击，不能补报名"
            return "师门共讨联赛：首周可报名并锁定门派"
        return "师门共讨联赛：本季尚未报名"
    season = _season_row(ctx, start)
    rows = _leader_rows(ctx, season, entry["sect_id"])
    own = next((row for row in rows if row["user_id"] == user_id), None)
    if own is None:
        return "师门共讨联赛：报名已锁定"
    return f"师门共讨联赛：{own['score']} 分 · 有效 {own['active_weeks']}/3 周"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    command, rest = parts[0], " ".join(parts[1:])
    if command == "报名":
        return register(ctx, rest)
    if command in {"榜", "个人榜"}:
        return ranking(ctx, rest)
    if command in {"门派榜", "进度榜"}:
        return sect_ranking(ctx, rest)
    if command == "战历":
        return battle_history(ctx, rest)
    if command in {"历史", "往期"}:
        return history(ctx, rest)
    if command == "领奖":
        return claim(ctx, rest)
    return page(ctx, command)
