"""Three-week standings derived only from linked family duel runs."""

from datetime import date, datetime
import json

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.family_duel_content import LEAGUE_SECONDS, league_start
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from ..utils.time import BEIJING, beijing_week
from .rewards import grant
from .pet_targets import pet_id

TITLE = "灵宠亲子合战"
PAGE_SIZE = 6
RANK_PAGE_SIZE = 10


def _config(ctx: Context):
    return ctx.content.family_duel_league


def current_start(ctx: Context) -> int | None:
    week = beijing_week(ctx.now)[0]
    anchor = _anchor(ctx)
    if week < anchor:
        return None
    return anchor + ((week - anchor) // LEAGUE_SECONDS) * LEAGUE_SECONDS


def _anchor(ctx: Context) -> int:
    row = ctx.repo.conn.execute(
        "SELECT MIN(season_start) AS season_start FROM family_duel_league_seasons",
    ).fetchone()
    if row is not None and row["season_start"] is not None:
        return int(row["season_start"])
    return _config(ctx).first_season_start


def _season(ctx: Context, start: int):
    row = ctx.repo.conn.execute(
        "SELECT * FROM family_duel_league_seasons WHERE season_start=?", (start,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def finalize_ended(ctx: Context) -> None:
    ctx.repo.conn.execute(
        "UPDATE family_duel_league_seasons SET finalized_at=ends_at "
        "WHERE ends_at<=? AND finalized_at IS NULL", (ctx.now,),
    )


def _rules(ctx: Context, start: int) -> dict:
    row = _season(ctx, start)
    if row is not None:
        snapshot = json.loads(row["snapshot"])
        return snapshot["rules"]
    return _config(ctx).model_dump(mode="json")


def _snapshot(ctx: Context) -> dict:
    return {"rules": _config(ctx).model_dump(mode="json"),
            "rotation": list(ctx.content.family_duel_rotation)}


def duel_id_for_week(ctx: Context, week_start: int) -> str | None:
    if not hasattr(ctx, "repo"):
        return None
    anchor = _anchor(ctx)
    if week_start < anchor:
        return None
    season_start = anchor + ((week_start - anchor) // LEAGUE_SECONDS) * LEAGUE_SECONDS
    row = _season(ctx, season_start)
    if row is None:
        return None
    rotation = json.loads(row["snapshot"])["rotation"]
    week_index = (week_start - int(row["season_start"])) // 604800
    return rotation[week_index]


def _date(start: int) -> str:
    return datetime.fromtimestamp(start, BEIJING).date().isoformat()


def _parse_date(value: str) -> int:
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise GameError("赛季日期格式为周一日期，例如 2026-12-07。") from exc
    start = int(datetime(day.year, day.month, day.day, tzinfo=BEIJING).timestamp())
    if league_start(start) != start:
        raise GameError("赛季日期必须是与三场轮换对齐的周一。")
    return start


def _visible_start(ctx: Context, value: str | None = None) -> int:
    current = current_start(ctx)
    start = current if value is None else _parse_date(value)
    if start is None or start < _anchor(ctx):
        raise GameError(f"联赛将于 {_date(_anchor(ctx))} 开放报名。")
    season = _season(ctx, start)
    if season is None:
        if current is None or start > current:
            raise GameError("该赛季尚未开始。")
        raise GameError("该赛季尚无报名，暂时没有可查看的联赛记录。")
    return start


def entry_for_week(ctx: Context, week_start: int):
    anchor = _anchor(ctx)
    if week_start < anchor:
        return None
    start = anchor + ((week_start - anchor) // LEAGUE_SECONDS) * LEAGUE_SECONDS
    return ctx.repo.conn.execute(
        "SELECT * FROM family_duel_league_entries WHERE season_start=? AND user_id=?",
        (start, ctx.user_id),
    ).fetchone()


def record_run(ctx: Context, week_start: int, run_id: str) -> None:
    entry = entry_for_week(ctx, week_start)
    if entry is None:
        return
    ctx.repo.conn.execute(
        "INSERT INTO family_duel_league_runs(season_start,user_id,week_start,run_id) VALUES (?,?,?,?)",
        (league_start(week_start), ctx.user_id, week_start, run_id),
    )


def _participants(ctx: Context, start: int) -> list[dict]:
    rules = _rules(ctx, start)
    points = {item["id"]: item["points"] for item in rules["ratings"]}
    high_id = max(rules["ratings"], key=lambda item: item["points"])["id"]
    entries = ctx.repo.conn.execute(
        "SELECT e.user_id, i.id+9999 AS uid, e.parent_id, e.child_id, e.egg_record_id, e.registered_at, "
        "r.week_start, r.run_id, r.duel_id, r.outcome, r.rating_id, r.rounds, r.started_at, r.snapshot "
        "FROM family_duel_league_entries e JOIN player_identity i USING(user_id) "
        "LEFT JOIN family_duel_league_runs lr ON lr.season_start=e.season_start AND lr.user_id=e.user_id "
        "LEFT JOIN family_duel_runs r ON r.user_id=lr.user_id AND r.run_id=lr.run_id "
        "WHERE e.season_start=? ORDER BY i.id",
        (start,),
    ).fetchall()
    by_user: dict[str, dict] = {}
    for row in entries:
        participant = by_user.setdefault(row["user_id"], {
            "user_id": row["user_id"], "uid": int(row["uid"]), "parent_id": int(row["parent_id"]),
            "child_id": int(row["child_id"]), "egg_record_id": int(row["egg_record_id"]),
            "registered_at": int(row["registered_at"]), "points": 0, "high_ratings": 0,
            "wins": 0, "matches": 0, "weeks": [], "results": [],
        })
        if row["run_id"] is None:
            continue
        match = {
            "week_start": int(row["week_start"]), "run_id": row["run_id"], "duel_id": row["duel_id"],
            "outcome": row["outcome"], "rating_id": row["rating_id"], "rounds": int(row["rounds"]),
            "started_at": int(row["started_at"]), "snapshot": json.loads(row["snapshot"]),
            "points": points.get(row["rating_id"], 0),
        }
        participant["results"].append(match)
        participant["matches"] += 1
        participant["points"] += match["points"]
        participant["high_ratings"] += int(row["rating_id"] == high_id)
        participant["wins"] += int(row["outcome"] == "won")
    for item in by_user.values():
        item["results"].sort(key=lambda match: match["week_start"])
        item["weeks"] = [next((match for match in item["results"] if match["week_start"] == start + i * 604800), None)
                         for i in range(3)]
        item["finished"] = item["matches"] >= rules["minimum_matches"]
        item["rank"] = None
    finished = sorted(
        (item for item in by_user.values() if item["finished"]),
        key=lambda item: (-item["points"], -item["high_ratings"], -item["wins"], -item["matches"], item["uid"]),
    )
    for rank, item in enumerate(finished, 1):
        item["rank"] = rank
    return sorted(by_user.values(), key=lambda item: (item["rank"] is None, item["rank"] or 0, item["uid"]))


def _rating_name(match: dict) -> str:
    rating_id = match["rating_id"]
    duel = match["snapshot"]["duel"]
    return next((rating["name"] for rating in duel["ratings"] if rating["id"] == rating_id), "未获评级")


def _season_end(start: int) -> int:
    return start + LEAGUE_SECONDS


def _summary(ctx: Context, start: int) -> tuple[list[str], list[dict]]:
    rules = _rules(ctx, start)
    participants = _participants(ctx, start)
    finishers = sum(item["finished"] for item in participants)
    season = _season(ctx, start)
    status = "最终榜" if ctx.now >= _season_end(start) or season["finalized_at"] is not None else "暂定榜"
    score_line = "、".join(f"{rating['name']} {rating['points']} 分" for rating in rules["ratings"])
    lines = [f"赛季 {_date(start)} 至 {_date(_season_end(start) - 1)} · {status} · 已报名 {len(participants)} 人。",
             f"三周轮换各一次：{score_line}；按高档次数、胜场、完赛场数、UID 决胜。",
             f"最低完赛 {rules['minimum_matches']} 场 · 合格完赛 {finishers} 人。",
             _prize_line(ctx, rules)]
    for item in participants[:10]:
        rank = f"第 {item['rank']} 名" if item["rank"] is not None else "未完赛"
        lines.append(f"{rank} · UID {item['uid']} · {item['points']} 分 · {item['matches']}/3 场")
    if len(participants) > 10:
        lines.append("更多报名者见分页榜单。")
    if not participants:
        lines.append("尚无人报名。")
    mine = next((item for item in participants if item["user_id"] == ctx.user_id), None)
    if mine is not None:
        pair = f"锁定 #{mine['parent_id']} + #{mine['child_id']} · 凭证 #{mine['egg_record_id']}"
        rank_text = f"第 {mine['rank']} 名" if mine["rank"] is not None else "未完赛"
        lines.append(f"你的组合：{pair}。")
        lines.append(f"你的赛季战绩：{mine['points']} 分 · {mine['matches']}/3 场 · "
                     f"{rank_text}。")
    elif ctx.now < start + 604800:
        lines.append("首周可使用本人真实孵化的直接亲子报名；报名后组合固定。")
    if ctx.now >= _season_end(start) and mine is not None:
        claim = ctx.repo.conn.execute(
            "SELECT rank FROM family_duel_league_claims WHERE season_start=? AND user_id=?", (start, ctx.user_id),
        ).fetchone()
        if claim:
            lines.append(f"名次奖励：第 {claim['rank']} 名，已领取。")
        elif _claim_window(ctx, start) and _reward_rank(ctx, start, participants, mine) is not None:
            lines.append(f"名次奖励：第 {mine['rank']} 名，可领取。")
        elif _claim_window(ctx, start):
            lines.append("本季报名或合格完赛人数不足，未开放名次奖励。")
        else:
            lines.append("名次奖励领取期已结束。")
    return lines, participants


def _prize_line(ctx: Context, rules: dict) -> str:
    parts = []
    for prize in rules["prizes"]:
        items = "、".join(f"{ctx.content.items[key].name} ×{amount}"
                          for key, amount in prize["items"].items())
        reward = f"灵石 {prize['stones']}" + (f"、{items}" if items else "")
        parts.append(f"第 {prize['rank']} 名：{reward}")
    return "前三奖励（合格人数不足两人不开）：" + "；".join(parts) + "。"


def _claim_window(ctx: Context, start: int) -> bool:
    rules = _rules(ctx, start)
    return _season_end(start) <= ctx.now < _season_end(start) + rules["claim_weeks"] * 604800


def _reward_rank(ctx: Context, start: int, participants: list[dict], mine: dict) -> int | None:
    rules = _rules(ctx, start)
    finishers = sum(item["finished"] for item in participants)
    if len(participants) < rules["minimum_finishers"] or finishers < rules["minimum_finishers"]:
        return None
    return mine["rank"] if mine["finished"] and mine["rank"] is not None and mine["rank"] <= 3 else None


def overview(ctx: Context) -> Reply:
    current = current_start(ctx)
    if current is None:
        start = _anchor(ctx)
        season = _season(ctx, start)
        if season is not None and season["finalized_at"] is not None:
            lines, _ = _summary(ctx, start)
            return Reply(TITLE + " · 三周联赛", tuple(lines),
                         (f"{TITLE} 联赛 榜单 {_date(start)} 1",
                          f"{TITLE} 联赛 往期", TITLE))
        return Reply(TITLE + " · 三周联赛",
                     (f"首个赛季于 {_date(start)} 开始，首周开放报名。", "按三场真实轮换战的评级积分排名，赛季结束后有一周联赛周期领奖。"),
                     (TITLE, f"{TITLE} 亲子", "灵宠帮助 对战与赛季"))
    season = _season(ctx, current)
    if season is None:
        if beijing_week(ctx.now)[0] == current:
            message = f"本赛季于 {_date(current)} 开始；首周开放报名，联赛记录将在首次报名时建立。"
        else:
            message = f"本赛季 {_date(current)} 至 {_date(_season_end(current) - 1)}，尚未有人报名。"
        return Reply(TITLE + " · 三周联赛", (message, "以本人真实直接亲子报名；旧战绩不回填。"),
                     (f"{TITLE} 联赛 报名", f"{TITLE} 亲子", TITLE))
    lines, participants = _summary(ctx, current)
    mine = next((item for item in participants if item["user_id"] == ctx.user_id), None)
    links = []
    if mine is not None and ctx.now >= _season_end(current) and _claim_window(ctx, current):
        rank = _reward_rank(ctx, current, participants, mine)
        claim = ctx.repo.conn.execute(
            "SELECT 1 FROM family_duel_league_claims WHERE season_start=? AND user_id=?", (current, ctx.user_id),
        ).fetchone()
        if rank and not claim:
            links.append(InlineCommand(len(lines) - 1, "领取名次奖励",
                                       f"{TITLE} 联赛 领奖 {_date(current)}"))
    links.append(InlineCommand(len(lines) - 1, "赛季榜单", f"{TITLE} 联赛 榜单 {_date(current)} 1"))
    links.append(InlineCommand(len(lines) - 1, "我的周战绩", f"{TITLE} 联赛 战历 {_date(current)}"))
    return Reply(TITLE + " · 三周联赛", tuple(lines),
                 (f"{TITLE} 联赛 榜单 {_date(current)} 1", f"{TITLE} 联赛 战历 {_date(current)}",
                  f"{TITLE} 联赛 报名", TITLE), tuple(links[:4]))


def registration_page(ctx: Context, page_number: int = 1) -> Reply:
    ctx.player()
    current = current_start(ctx)
    if current is None or beijing_week(ctx.now)[0] != current:
        raise GameError("当前不是赛季报名周；仅赛季首周可锁定亲子组合。")
    existing = ctx.repo.conn.execute(
        "SELECT 1 FROM family_duel_league_entries WHERE season_start=? AND user_id=?", (current, ctx.user_id),
    ).fetchone()
    if existing:
        entry = ctx.repo.conn.execute(
            "SELECT parent_id,child_id,egg_record_id FROM family_duel_league_entries "
            "WHERE season_start=? AND user_id=?", (current, ctx.user_id),
        ).fetchone()
        return Reply(TITLE + " · 联赛报名",
                     (f"已锁定 #{entry['parent_id']} + #{entry['child_id']} · 凭证 #{entry['egg_record_id']}。",
                      "赛季组合不可更改；本周战斗前报名有效，之后不可补报。"),
                     (f"{TITLE} 预览 {entry['parent_id']} {entry['child_id']} {beijing_week(ctx.now)[0]}",
                      f"{TITLE} 联赛 榜单 {_date(current)} 1", f"{TITLE} 联赛 战历 {_date(current)}"))
    from .family_duel import _eligible, _run
    start = beijing_week(ctx.now)[0]
    if _run(ctx, ctx.user_id, start) is not None:
        raise GameError("你已参加本周亲子合战，不能补报名本赛季。")
    pairs = []
    for egg in ctx.repo.lineage_eggs(ctx.user_id):
        for parent_id in (int(egg["parent_a_id"]), int(egg["parent_b_id"])):
            try:
                parent, child, _ = _eligible(ctx, parent_id, int(egg["child_pet_id"]))
            except GameError:
                continue
            pairs.append((parent, child))
    page = paginate(pairs, str(page_number), TITLE + " · 联赛报名", f"{TITLE} 联赛 报名", PAGE_SIZE)
    lines = [f"本季 {_date(current)} 开始 · 第 1 周开放报名 · 合格亲子 {len(pairs)} 对。"]
    links = []
    for parent, child in page.entries:
        lines.append(f"{parent.name}（#{parent.pet_id}）+ {child.name}（#{child.pet_id}）")
        links.append(InlineCommand(len(lines) - 1, "锁定报名",
                                   f"{TITLE} 联赛 报名 {current} {parent.pet_id} {child.pet_id}"))
    if not pairs:
        lines.append("目前没有可报名的本人真实直接亲子组合。")
    return Reply(TITLE + " · 联赛报名", tuple(lines),
                 (*page.navigation, TITLE, f"{TITLE} 亲子", "灵宠谱系")[:4], tuple(links))


def register(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 3:
        raise GameError(f"格式：{TITLE} 联赛 报名 赛季周起点 亲本编号 后代编号。")
    current = current_start(ctx)
    week = beijing_week(ctx.now)[0]
    if current is None or current != week or parts[0] != str(current):
        raise GameError("仅赛季首周可报名；赛季中不能补报。")
    from .family_duel import _eligible, _run
    if _run(ctx, ctx.user_id, week) is not None:
        raise GameError("你已参加本周亲子合战，不能补报名本赛季。")
    finalize_ended(ctx)
    parent, child, egg = _eligible(ctx, pet_id(parts[1]), pet_id(parts[2]))
    existing = ctx.repo.conn.execute(
        "SELECT 1 FROM family_duel_league_entries WHERE season_start=? AND user_id=?", (current, ctx.user_id),
    ).fetchone()
    if existing:
        raise GameError("你本赛季已报名，锁定组合不能更改。")
    season = _season(ctx, current)
    if season is None:
        snapshot = _snapshot(ctx)
        ctx.repo.conn.execute(
            "INSERT INTO family_duel_league_seasons(season_start,ends_at,created_at,snapshot) VALUES (?,?,?,?)",
            (current, _season_end(current), ctx.now, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))),
        )
    ctx.repo.conn.execute(
        "INSERT INTO family_duel_league_entries(season_start,user_id,parent_id,child_id,egg_record_id,registered_at) "
        "VALUES (?,?,?,?,?,?)",
        (current, ctx.user_id, parent.pet_id, child.pet_id, egg["egg_record_id"], ctx.now),
    )
    reply = Reply(TITLE + " · 联赛报名",
                  (f"已锁定 {parent.name}（#{parent.pet_id}）与 {child.name}（#{child.pet_id}）。",
                   f"真实孵化凭证 #{egg['egg_record_id']} · 赛季 {_date(current)} 至 {_date(_season_end(current)-1)}。",
                   "本周战斗前报名有效；之后三周只计入这一组合每周唯一的真实合战结果。"),
                  (TITLE, f"{TITLE} 联赛 榜单 {_date(current)} 1", f"{TITLE} 亲子"))
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": "family_duel_league_register", "season_start": current,
         "parent_id": parent.pet_id, "child_id": child.pet_id, "egg_record_id": egg["egg_record_id"]}, reply,
    )
    return reply


def standings_page(ctx: Context, start: int, page_number: int) -> Reply:
    if page_number < 1:
        raise GameError("页码必须从 1 开始。")
    participants = _participants(ctx, start)
    page_command = f"{TITLE} 联赛 榜单 {_date(start)}"
    page = paginate(participants, str(page_number), TITLE + " · 联赛榜单", page_command, RANK_PAGE_SIZE)
    lines = [f"赛季 {_date(start)} · 第 {page.number}/{page.total} 页。"]
    for item in page.entries:
        rank = f"第 {item['rank']} 名" if item["rank"] else "未完赛"
        lines.append(f"{rank} · UID {item['uid']} · {item['points']} 分 · {item['matches']}/3 场")
    if not participants:
        lines.append("尚无人报名。")
    body, _ = _summary(ctx, start)
    lines.extend(body[:2])
    return Reply(TITLE + " · 联赛榜单", tuple(lines),
                 (*page.navigation, f"{TITLE} 联赛 战历 {_date(start)}", f"{TITLE} 联赛 往期", TITLE)[:4])


def personal_record(ctx: Context, start: int) -> Reply:
    item = next((row for row in _participants(ctx, start) if row["user_id"] == ctx.user_id), None)
    if item is None:
        raise GameError("你尚未报名该赛季，不能查看其他玩家的私人战绩。")
    rank_text = f"第 {item['rank']} 名" if item["rank"] else "未完赛"
    lines = [f"赛季 {_date(start)} · 锁定 #{item['parent_id']} + #{item['child_id']} · 凭证 #{item['egg_record_id']}。",
             f"积分 {item['points']} · {item['matches']}/3 场 · "
             f"{rank_text}。"]
    for index, match in enumerate(item["weeks"], 1):
        if match is None:
            lines.append(f"第 {index} 周：未参战 · 0 分。")
        else:
            lines.append(f"第 {index} 周：{match['duel_id']} · {match['outcome']} · "
                         f"{_rating_name(match)} · +{match['points']} 分 · {match['rounds']} 回合。")
    return Reply(TITLE + " · 联赛战历", tuple(lines),
                 (f"{TITLE} 联赛 榜单 {_date(start)} 1", f"{TITLE} 记录", TITLE))


def archive_page(ctx: Context, page_number: int) -> Reply:
    if page_number < 1:
        raise GameError("页码必须从 1 开始。")
    rows = ctx.repo.conn.execute(
        "SELECT season_start,ends_at FROM family_duel_league_seasons "
        "ORDER BY season_start DESC",
    ).fetchall()
    page = paginate(rows, str(page_number), TITLE + " · 联赛往期", f"{TITLE} 联赛 往期", PAGE_SIZE)
    lines = [f"共 {len(rows)} 个已开启赛季 · 第 {page.number}/{page.total} 页。"]
    links = []
    for row in page.entries:
        start = int(row["season_start"])
        lines.append(f"{_date(start)} 至 {_date(int(row['ends_at']) - 1)}")
        links.append(InlineCommand(len(lines) - 1, "查看赛季", f"{TITLE} 联赛 赛季 {_date(start)}"))
    if not rows:
        lines.append("尚无已开启的联赛赛季。")
    return Reply(TITLE + " · 联赛往期", tuple(lines),
                 (*page.navigation, f"{TITLE} 联赛", TITLE)[:4], tuple(links))


def claim(ctx: Context, start: int) -> Reply:
    ctx.player()
    if not _claim_window(ctx, start):
        raise GameError("名次奖励仅可在赛季结束后的下一个三周赛季内领取。")
    finalize_ended(ctx)
    participants = _participants(ctx, start)
    mine = next((item for item in participants if item["user_id"] == ctx.user_id), None)
    if mine is None:
        raise GameError("你未报名该赛季，不能领取名次奖励。")
    already = ctx.repo.conn.execute(
        "SELECT 1 FROM family_duel_league_claims WHERE season_start=? AND user_id=?", (start, ctx.user_id),
    ).fetchone()
    if already:
        raise GameError("本赛季名次奖励已领取。")
    rank = _reward_rank(ctx, start, participants, mine)
    if rank is None:
        return Reply(TITLE + " · 联赛结算",
                     ("本赛季完赛人数不足，或你的名次未进入前三，没有开放名次奖励。",),
                     (f"{TITLE} 联赛 榜单 {_date(start)} 1", f"{TITLE} 联赛 战历 {_date(start)}"))
    rules = _rules(ctx, start)
    prize = next(item for item in rules["prizes"] if item["rank"] == rank)
    reward = Reward(exp=Range(minimum=0, maximum=0),
                    stones=Range(minimum=prize["stones"], maximum=prize["stones"]),
                    items={key: Range(minimum=amount, maximum=amount)
                           for key, amount in prize["items"].items()})
    lines = grant(ctx, reward)
    reply = Reply(TITLE + " · 联赛结算",
                  (f"赛季 {_date(start)} · 最终第 {rank} 名 · 一次性奖励已到账。", *lines),
                  (f"{TITLE} 联赛", f"{TITLE} 联赛 战历", TITLE))
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": "family_duel_league_claim", "season_start": start, "rank": rank,
         "reward_snapshot": prize}, reply,
    )
    ctx.repo.conn.execute(
        "INSERT INTO family_duel_league_claims(season_start,user_id,rank,operation_id,claimed_at,reward_snapshot) "
        "VALUES (?,?,?,?,?,?)",
        (start, ctx.user_id, rank, ctx.operation_id, ctx.now,
         json.dumps({"prize": prize, "granted": lines}, ensure_ascii=False, separators=(",", ":"))),
    )
    return reply


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return overview(ctx)
    if parts[0] == "报名":
        if len(parts) == 1:
            return registration_page(ctx)
        if len(parts) == 2 and parts[1].isdecimal():
            return registration_page(ctx, int(parts[1]))
        return register(ctx, parts[1:])
    if len(parts) == 1 and parts[0] == "战历":
        start = _visible_start(ctx)
        return personal_record(ctx, start)
    if len(parts) == 2 and parts[0] == "战历":
        return personal_record(ctx, _visible_start(ctx, parts[1]))
    if parts[0] == "往期" and len(parts) <= 2:
        try:
            page = int(parts[1]) if len(parts) == 2 else 1
        except ValueError as exc:
            raise GameError("往期页码必须是正整数。") from exc
        return archive_page(ctx, page)
    if len(parts) == 2 and parts[0] == "领奖":
        return claim(ctx, _parse_date(parts[1]))
    if len(parts) in (2, 3) and parts[0] == "榜单":
        start = _visible_start(ctx, parts[1]) if len(parts) == 3 or not parts[1].isdecimal() else _visible_start(ctx)
        page_text = parts[-1]
        try:
            page = int(page_text)
        except ValueError as exc:
            raise GameError("榜单页码必须是正整数。") from exc
        return standings_page(ctx, start, page)
    if len(parts) == 2 and parts[0] == "赛季":
        start = _visible_start(ctx, parts[1])
        return standings_page(ctx, start, 1)
    raise GameError(f"格式：{TITLE} 联赛 [报名 [亲本 后代]|榜单 页码|战历|领奖 赛季周一日期]。")


def read_only(argument: str) -> bool:
    parts = argument.split()
    if not parts:
        return True
    if parts[0] != "联赛":
        return False
    return len(parts) == 1 or parts[1] in {"榜单", "战历", "赛季", "往期"} or (
        parts[1] == "报名" and (len(parts) == 2 or (len(parts) == 3 and parts[2].isdecimal()))
    )


def objective_line(ctx: Context, user_id: str) -> str:
    current = current_start(ctx)
    if current is None:
        return f"亲子合战联赛：{_date(_config(ctx).first_season_start)} 开放首季报名"
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM family_duel_league_entries WHERE season_start=? AND user_id=?", (current, user_id),
    ).fetchone()
    if row:
        return f"亲子合战联赛：已锁定本季组合 · {(_date(current))}"
    if beijing_week(ctx.now)[0] == current:
        return "亲子合战联赛：报名周开放，锁定真实直接亲子组合"
    return f"亲子合战联赛：本季报名已关闭 · {_date(current)}"


def today_state(ctx: Context, user_id: str) -> str | None:
    current = current_start(ctx)
    if current is None or beijing_week(ctx.now)[0] != current:
        return None
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM family_duel_league_entries WHERE season_start=? AND user_id=?", (current, user_id),
    ).fetchone()
    if row:
        return None
    from .family_duel import _run
    if _run(ctx, user_id, current) is not None:
        return None
    return "亲子合战联赛报名周：在本周战斗前锁定直接亲子组合"
