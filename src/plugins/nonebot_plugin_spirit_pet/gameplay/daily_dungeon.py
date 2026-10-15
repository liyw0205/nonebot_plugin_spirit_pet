from datetime import date

from ..application.context import Context
from ..domain.models import InlineCommand, Reply
from ..utils.time import beijing_day
from .rewards import grant

# Today's wins are found by scanning recent battle records, so the window only
# bounds the query; the Beijing day filter below is what defines "today".
WIN_SCAN_WINDOW = 172800


def solo_dungeons(ctx: Context) -> list:
    return [dungeon for dungeon in ctx.content.dungeons.values() if not dungeon.team]


def featured(ctx: Context, now: int | None = None):
    """Today's featured solo dungeon: a pure function of the Beijing day."""
    dungeons = solo_dungeons(ctx)
    ordinal = date.fromisoformat(beijing_day(ctx.now if now is None else now)).toordinal()
    return dungeons[ordinal % len(dungeons)]


def wins_today(ctx: Context, user_id: str, dungeon_id: str) -> int:
    today = beijing_day(ctx.now)
    rows = ctx.repo.conn.execute(
        "SELECT b.played_at FROM battle_records b JOIN battle_participants p USING(battle_id) "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? AND b.winner_side=p.side "
        "AND b.played_at>=?",
        (user_id, dungeon_id, ctx.now - WIN_SCAN_WINDOW),
    )
    return sum(1 for row in rows if beijing_day(row["played_at"]) == today)


def bonus(ctx: Context, user_id: str, dungeon) -> tuple[str, ...]:
    """Grant today's featured bonus when this win crosses the first or third win.

    Called before the battle record for this run is written, so the win count is
    the number of earlier wins today.
    """
    if dungeon.id != featured(ctx).id:
        return ()
    prior = wins_today(ctx, user_id, dungeon.id)
    rule = ctx.content.rules.daily_featured
    if prior == 0:
        return (f"今日首胜：{'，'.join(grant(ctx, rule.first, user_id))}",)
    if prior == 2:
        return (f"今日三胜：{'，'.join(grant(ctx, rule.third, user_id))}",)
    return ()


def _summary(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}-{reward.stones.maximum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}-{bounds.maximum}"
        for item, bounds in reward.items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    dungeon = featured(ctx)
    realm = next(item.name for item in ctx.content.realms if item.id == dungeon.min_realm)
    rule = ctx.content.rules.daily_featured
    lines = [
        f"今日秘境：{dungeon.name} · {realm}起 · 精力 {dungeon.energy}",
        f"首胜奖励：{_summary(ctx, rule.first)}",
        f"三胜奖励：{_summary(ctx, rule.third)}",
    ]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再挑战今日秘境。")
        lines.append("每日 00:00（北京时间）轮换一处单人秘境，当日首胜与三胜各发一份奖励。")
        return Reply("今日秘境", tuple(lines), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))

    wins = wins_today(ctx, player.user_id, dungeon.id)
    lines.append(
        f"今日已胜 {wins} 场 · 首胜奖励 {'已领取' if wins >= 1 else '未领取'}"
        f" · 三胜奖励 {'已领取' if wins >= 3 else '未领取'}"
    )
    lines.append("每日 00:00（北京时间）轮换一处单人秘境，当日首胜与三胜各发一份奖励。")
    minimum = next(index for index, item in enumerate(ctx.content.realms) if item.id == dungeon.min_realm)
    ready = any(pet.realm >= minimum for pet in ctx.repo.active_pets(player.user_id))
    links = []
    if ready:
        links.append(InlineCommand(0, "前往挑战", f"灵宠挑战 {dungeon.name}"))
    else:
        lines.append(f"出战伙伴尚未达到{realm}，可先提升境界，或查看其他秘境。")
    return Reply("今日秘境", tuple(lines), ("灵宠秘境", "灵宠任务"), tuple(links))
