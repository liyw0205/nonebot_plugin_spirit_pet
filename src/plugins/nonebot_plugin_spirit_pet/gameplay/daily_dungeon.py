from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from .rewards import grant

# Today's wins are found by scanning recent battle records, so the window only
# bounds the query; the Beijing day filter below is what defines "today".
WIN_SCAN_WINDOW = 172800
FIRST_CLAIM = "featured_first"
THIRD_CLAIM = "featured_third"
CLAIM_KINDS = {"首胜": FIRST_CLAIM, "三胜": THIRD_CLAIM}


def solo_dungeons(content) -> list:
    return [dungeon for dungeon in content.dungeons.values() if not dungeon.team]


def day_ordinal(now: int) -> int:
    return date.fromisoformat(beijing_day(now)).toordinal()


def featured_dungeon(content, now: int):
    """Today's featured solo dungeon: a pure function of the Beijing day."""
    dungeons = solo_dungeons(content)
    return dungeons[day_ordinal(now) % len(dungeons)]


def wins_today(ctx: Context, user_id: str, dungeon_id: str) -> int:
    today = beijing_day(ctx.now)
    rows = ctx.repo.conn.execute(
        "SELECT b.played_at FROM battle_records b JOIN battle_participants p USING(battle_id) "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? AND b.winner_side=p.side "
        "AND b.played_at>=?",
        (user_id, dungeon_id, ctx.now - WIN_SCAN_WINDOW),
    )
    return sum(1 for row in rows if beijing_day(row["played_at"]) == today)


def _requirement(claim_id: str) -> int:
    return 1 if claim_id == FIRST_CLAIM else 3


def _reward(ctx: Context, claim_id: str):
    rule = ctx.content.rules.daily_featured
    return rule.first if claim_id == FIRST_CLAIM else rule.third


def claimed_today(ctx: Context, user_id: str, claim_id: str) -> bool:
    """A claim counts for today only when its stored day matches the current one."""
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id),
    ).fetchone()
    return bool(row and row["claimed"] and row["progress"] == day_ordinal(ctx.now))


def _summary(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}-{reward.stones.maximum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}-{bounds.maximum}"
        for item, bounds in reward.items.items()
    )
    return "，".join(parts)


def _state(ctx: Context, user_id: str, claim_id: str, wins: int) -> str:
    if claimed_today(ctx, user_id, claim_id):
        return "已领取"
    need = _requirement(claim_id)
    return "可领取" if wins >= need else f"未达成（今日已胜 {wins}/{need} 场）"


def catalog(ctx: Context, arg: str) -> Reply:
    dungeon = featured_dungeon(ctx.content, ctx.now)
    realm = next(item.name for item in ctx.content.realms if item.id == dungeon.min_realm)
    lines = [f"今日秘境：{dungeon.name} · {realm}起 · 精力 {dungeon.energy}"]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        for kind, claim_id in CLAIM_KINDS.items():
            need = _requirement(claim_id)
            lines.append(f"{kind}奖励（当日第 {need} 胜）：{_summary(ctx, _reward(ctx, claim_id))}")
        lines.append("尚未结契，先完成领养，再挑战今日秘境。")
        lines.append("每日 00:00（北京时间）轮换一处单人秘境，达成后回到本页领奖。")
        return Reply("今日秘境", tuple(lines), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))

    wins = wins_today(ctx, player.user_id, dungeon.id)
    links = []
    for kind, claim_id in CLAIM_KINDS.items():
        need = _requirement(claim_id)
        state = _state(ctx, player.user_id, claim_id, wins)
        lines.append(
            f"{kind}奖励（当日第 {need} 胜）：{_summary(ctx, _reward(ctx, claim_id))} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, f"领取{kind}奖励", f"灵宠今日秘境领奖 {kind}",
            ))
    lines.append("每日 00:00（北京时间）轮换一处单人秘境，达成后回到本页领奖。")
    minimum = next(index for index, item in enumerate(ctx.content.realms) if item.id == dungeon.min_realm)
    if any(pet.realm >= minimum for pet in ctx.repo.active_pets(player.user_id)):
        links.insert(0, InlineCommand(0, "前往挑战", f"灵宠挑战 {dungeon.name}"))
    else:
        lines.append(f"出战伙伴尚未达到{realm}，可先提升境界，或查看其他秘境。")
    return Reply("今日秘境", tuple(lines), ("灵宠秘境", "灵宠任务"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    kind = arg.strip()
    claim_id = CLAIM_KINDS.get(kind)
    if claim_id is None:
        raise GameError("格式：灵宠今日秘境领奖 首胜，或 灵宠今日秘境领奖 三胜。")
    if claimed_today(ctx, player.user_id, claim_id):
        raise GameError("今日这份奖励已领取，明日再来。")
    dungeon = featured_dungeon(ctx.content, ctx.now)
    wins = wins_today(ctx, player.user_id, dungeon.id)
    need = _requirement(claim_id)
    if wins < need:
        raise GameError(f"今日在{dungeon.name}已胜 {wins} 场，还需 {need - wins} 场才能领取。")
    result = grant(ctx, _reward(ctx, claim_id), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id, day_ordinal(ctx.now)),
    )
    return Reply("今日秘境奖励", (
        f"{kind}奖励已领取。", *result, f"今日在{dungeon.name}已胜 {wins} 场。",
    ), ("灵宠今日秘境", "灵宠秘境"))
