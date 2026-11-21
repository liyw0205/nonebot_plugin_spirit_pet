"""Weekly shared habitat recovery, funded only by real wild encounters."""

import json

from ..application.context import Context
from ..content.catalog import Catalog
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.wild_habitat_content import WildHabitatEvent
from ..utils.time import beijing_day, beijing_week
from .rewards import grant

TITLE = "灵宠栖地共护"
WEEK_SECONDS = 7 * 86400
CLAIM_SECONDS = 14 * 86400
PAGE_SIZE = 5


def _event_for_week(content: Catalog, week_start: int) -> WildHabitatEvent:
    events = tuple(content.wild_habitat_events.values())
    return events[(week_start // WEEK_SECONDS) % len(events)]


def _stored_event(row) -> WildHabitatEvent:
    return WildHabitatEvent.model_validate(json.loads(row["event_snapshot"]))


def _week_info(ctx: Context, week_start: int) -> tuple[WildHabitatEvent, bool]:
    row = ctx.repo.conn.execute(
        "SELECT event_snapshot FROM wild_habitat_weeks WHERE week_start=?", (week_start,),
    ).fetchone()
    if row is None:
        return _event_for_week(ctx.content, week_start), False
    return _stored_event(row), True


def record_encounter(ctx: Context, run_id: int) -> bool:
    """Freeze the weekly event and credit a newly persisted encounter in its transaction."""
    run = ctx.repo.conn.execute(
        "SELECT run_id,operation_id,user_id,route_id,species_id,started_at "
        "FROM wild_capture_runs WHERE run_id=? AND operation_id=?",
        (run_id, ctx.operation_id),
    ).fetchone()
    if run is None:
        raise RuntimeError("wild habitat contribution requires its persisted encounter")
    start = beijing_week(int(run["started_at"]))[0]
    selected = _event_for_week(ctx.content, start)
    snapshot = json.dumps(selected.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO wild_habitat_weeks(week_start,event_id,route_id,event_snapshot,opened_at) "
        "VALUES (?,?,?,?,?)",
        (start, selected.id, selected.route, snapshot, int(run["started_at"])),
    )
    frozen = ctx.repo.conn.execute(
        "SELECT route_id FROM wild_habitat_weeks WHERE week_start=?", (start,),
    ).fetchone()
    if frozen["route_id"] != run["route_id"]:
        return False
    cursor = ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO wild_habitat_contributions"
        "(week_start,run_id,user_id,species_id,contributed_at) VALUES (?,?,?,?,?)",
        (start, run["run_id"], run["user_id"], run["species_id"], int(run["started_at"])),
    )
    return cursor.rowcount == 1


def _totals(ctx: Context, week_start: int) -> tuple[int, int]:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS pairs,COUNT(DISTINCT user_id) AS participants "
        "FROM wild_habitat_contributions WHERE week_start=?", (week_start,),
    ).fetchone()
    return int(row["pairs"]), int(row["participants"])


def _own_species(ctx: Context, week_start: int, user_id: str) -> set[str]:
    return {
        row["species_id"] for row in ctx.repo.conn.execute(
            "SELECT species_id FROM wild_habitat_contributions WHERE week_start=? AND user_id=?",
            (week_start, user_id),
        )
    }


def _claims(ctx: Context, week_start: int, user_id: str) -> set[str]:
    return {
        row["tier_id"] for row in ctx.repo.conn.execute(
            "SELECT tier_id FROM wild_habitat_claims WHERE week_start=? AND user_id=?",
            (week_start, user_id),
        )
    }


def _reward_label(ctx: Context, tier) -> str:
    bits = [f"灵石 {tier.reward.stones}"] if tier.reward.stones else []
    bits.extend(f"{ctx.content.items[item].name} {amount}" for item, amount in tier.reward.items.items())
    return "、".join(bits)


def _overview(ctx: Context, week_start: int) -> Reply:
    event, stored = _week_info(ctx, week_start)
    total, participants = _totals(ctx, week_start) if stored else (0, 0)
    player = ctx.repo.player(ctx.user_id)
    own = _own_species(ctx, week_start, ctx.user_id) if player and stored else set()
    claimed = _claims(ctx, week_start, ctx.user_id) if player and stored else set()
    route = ctx.content.exploration_routes[event.route]
    lines = [
        event.description,
        f"{beijing_day(week_start)} 起 · 路线 {route.name} · 共护进度 {total}/{event.goal_pairs} 组",
        f"参与修士 {participants} 人 · 你的首次物种贡献 {len(own)} 种。",
        "只统计本周真实野外遭遇中首次出现的玩家/物种组合。",
    ]
    links = []
    in_claim_window = week_start <= ctx.now < week_start + CLAIM_SECONDS
    for tier in event.tiers:
        met = total >= tier.contribution_pairs
        state = "已领取" if tier.id in claimed else (
            "可领取" if met and own and in_claim_window else
            "已达成" if met else f"待达成 {tier.contribution_pairs - total} 组"
        )
        lines.append(
            f"{tier.name} · {total}/{tier.contribution_pairs} 组 · "
            f"{_reward_label(ctx, tier)} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取共护奖励",
                f"{TITLE} 领奖 {week_start} {tier.id}",
            ))
    commands = [TITLE, f"灵宠历练 {route.name}", f"灵宠野外 调查 {route.name}", f"{TITLE} 历史"]
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契；可以查看全体进度，参与和领奖需先完成领养。")
    return Reply(f"栖地共护 · {event.name}", tuple(lines), tuple(commands), tuple(links))


def _history(ctx: Context, page: int) -> Reply:
    total = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_habitat_weeks",
    ).fetchone()[0])
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"栖地共护历史共 {pages} 页。")
    selected = ctx.repo.conn.execute(
        "SELECT week_start,event_snapshot FROM wild_habitat_weeks "
        "ORDER BY week_start DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    lines = [f"共 {total} 周活动记录 · 第 {page}/{pages} 页。", "历史仅展示全体总量和你的个人记录。"]
    links = []
    for row in selected:
        week_start = int(row["week_start"])
        event = _stored_event(row)
        total, participants = _totals(ctx, week_start)
        own_count = len(_own_species(ctx, week_start, ctx.user_id))
        lines.append(
            f"{beijing_day(week_start)} 起 · {event.name} · {total}/{event.goal_pairs} 组 · "
            f"{participants} 人参与 · 你贡献 {own_count} 种"
        )
        links.append(InlineCommand(len(lines) - 1, "查看本周", f"{TITLE} 周 {week_start}"))
    commands = [TITLE]
    if page > 1:
        commands.append(f"{TITLE} 历史 {page - 1}")
    if page < pages:
        commands.append(f"{TITLE} 历史 {page + 1}")
    return Reply(f"栖地共护历史 {page}/{pages}", tuple(lines), tuple(commands[:4]), tuple(links))


def _week_number(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise GameError("请填写有效的周起始时间。")
    number = int(value)
    if number < 0 or beijing_week(number)[0] != number:
        raise GameError("周起始时间必须是北京时间周一 00:00。")
    return number


def _claim(ctx: Context, week_start: int, tier_id: str) -> Reply:
    player = ctx.player()
    prior = ctx.repo.conn.execute(
        "SELECT user_id,reply FROM wild_habitat_claims WHERE operation_id=?", (ctx.operation_id,),
    ).fetchone()
    if prior is not None:
        if prior["user_id"] != player.user_id:
            raise GameError("该共护领奖操作已由其他身份处理，不能复用。")
        return Reply.from_data(json.loads(prior["reply"]))
    row = ctx.repo.conn.execute(
        "SELECT event_snapshot FROM wild_habitat_weeks WHERE week_start=?", (week_start,),
    ).fetchone()
    if row is None:
        raise GameError("该周没有真实栖地共护活动记录。")
    if not week_start <= ctx.now < week_start + CLAIM_SECONDS:
        raise GameError("栖地共护奖励只在活动周及其后一个自然周开放领取。")
    event = _stored_event(row)
    tier = next((tier for tier in event.tiers if tier.id == tier_id), None)
    if tier is None:
        raise GameError("该活动周没有这个共护档位。")
    if tier_id in _claims(ctx, week_start, player.user_id):
        raise GameError("该周共护档位已经领取。")
    if not _own_species(ctx, week_start, player.user_id):
        raise GameError("只有本周首次发现过目标路线物种的参与者可以领奖。")
    total, _ = _totals(ctx, week_start)
    if total < tier.contribution_pairs:
        raise GameError("全体首次物种贡献尚未达到该共护档位。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=tier.reward.stones, maximum=tier.reward.stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in tier.reward.items.items()},
    )
    granted = grant(ctx, reward, player.user_id)
    reply = Reply(
        "栖地共护奖励",
        (f"{event.name}·{tier.name}已领取。", *granted),
        (TITLE, f"{TITLE} 历史", "灵宠目标"),
    )
    reward_snapshot = json.dumps(tier.reward.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    reply_data = json.dumps({
        "title": reply.title,
        "lines": reply.lines,
        "commands": reply.commands,
        "inline_commands": reply.inline_commands,
    }, ensure_ascii=False)
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
        "kind": "wild_habitat_claim", "week_start": week_start, "event_id": event.id,
        "tier_id": tier.id, "reward": json.loads(reward_snapshot),
    }, reply)
    ctx.repo.conn.execute(
        "INSERT INTO wild_habitat_claims"
        "(week_start,user_id,tier_id,operation_id,claimed_at,reward_snapshot,reply) VALUES (?,?,?,?,?,?,?)",
        (week_start, player.user_id, tier.id, ctx.operation_id, ctx.now, reward_snapshot, reply_data),
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts or parts == ["当前"]:
        return _overview(ctx, beijing_week(ctx.now)[0])
    if parts[0] == "历史" and len(parts) <= 2:
        page = 1 if len(parts) == 1 else (
            int(parts[1]) if parts[1].isascii() and parts[1].isdecimal() and len(parts[1]) <= 6 else 0
        )
        if page < 1:
            raise GameError("历史页码必须是正整数。")
        return _history(ctx, page)
    if parts[0] == "周" and len(parts) == 2:
        return _overview(ctx, _week_number(parts[1]))
    if parts[0] == "领奖" and len(parts) == 3:
        return _claim(ctx, _week_number(parts[1]), parts[2])
    raise GameError(f"格式：{TITLE} [当前|历史 [页码]|周 周起始时间|领奖 周起始时间 档位ID]。")


def read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or parts[0] in {"当前", "历史", "周"}


def summary_line(ctx: Context, user_id: str) -> str:
    start = beijing_week(ctx.now)[0]
    event, stored = _week_info(ctx, start)
    total, _ = _totals(ctx, start) if stored else (0, 0)
    own_species = _own_species(ctx, start, user_id) if stored else set()
    own = len(own_species)
    claimed = _claims(ctx, start, user_id) if stored else set()
    in_claim_window = start <= ctx.now < start + CLAIM_SECONDS
    claimable = sum(
        bool(own_species) and in_claim_window
        and total >= tier.contribution_pairs and tier.id not in claimed
        for tier in event.tiers
    )
    suffix = f" · 可领 {claimable} 档" if claimable else ""
    return f"栖地共护：{event.name} {total}/{event.goal_pairs} 组 · 你的贡献 {own} 种{suffix}。"


def today_state(ctx: Context, user_id: str) -> tuple[str | None, str | None]:
    line = summary_line(ctx, user_id)
    if "可领 " in line:
        return line, None
    return None, line


def objective_line(ctx: Context, user_id: str) -> str:
    return summary_line(ctx, user_id)
