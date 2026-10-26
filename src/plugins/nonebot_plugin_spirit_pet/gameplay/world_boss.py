"""Weekly world boss: a Beijing-week rotation of one shared enemy.

The boss is a pure function of the week: the enemy roster is indexed by the
week's Monday 00:00 Beijing timestamp, so every player sees the same boss and
the same rotation without any stored schedule. Threat is aggregated from
per-player rows in `quest_progress` (`world_boss_threat_<week>` per user),
because that table is foreign-keyed to real players; per-player challenge
counts and personal tiers derive from `battle_records` facts, and credentials
reuse the same prefix pattern. Schema 20 stays untouched.
"""

from ..application.context import Context
from ..domain.content import Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day, beijing_week
from .adventure import _enemy_detail
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .rewards import grant

BOSS_POOL = (
    "moon_wolf", "ice_guard", "venom_guard", "ancient_guard",
)
THREAT_PREFIX = "world_boss_threat_"
TIER_PREFIX = "world_boss_tier_"
REWARD_PREFIX = "world_boss_reward_"
# Win adds more threat than a loss: the server still advances when players
# lose, but victories are the intended engine of the weekly defeat.
WIN_THREAT = 12
LOSS_THREAT = 4
# Player personal tiers: wins within the boss week (Beijing), each once.
TIERS = ((1, 120, {"spirit_food": 2}), (3, 300, {"forge_ore": 2}), (7, 700, {"bloodline_essence": 2}))
BOSS_REWARD = Reward.model_validate({
    "exp": {"minimum": 50, "maximum": 50}, "stones": {"minimum": 200, "maximum": 200},
    "items": {"forge_ore": {"minimum": 2, "maximum": 2}},
})
# Server-wide defeat threshold: a handful of coordinated wins per week.
THREAT_GOAL = 60
CHALLENGES_PER_DAY = 3
# Scan window covers a whole Beijing week plus clock-skew margin; the week
# bounds below are what actually define "this week".
WIN_SCAN_WINDOW = 7 * 86400 + 3600
DAY_SCAN_WINDOW = 172800


def week_ordinal(timestamp: int) -> int:
    """Weeks elapsed since a fixed epoch Monday, as a stable rotation index."""
    start, _ = beijing_week(timestamp)
    return start // (7 * 86400)


def current_boss(content, now: int):
    """This week's world boss, deterministically chosen from the roster."""
    return content.enemies[BOSS_POOL[week_ordinal(now) % len(BOSS_POOL)]]


def battle_key(now: int) -> str:
    return f"world_boss_{week_ordinal(now)}"


def threat(ctx: Context, now: int | None = None) -> int:
    """Server-wide threat: sum of every player's contribution this week."""
    week = week_ordinal(now if now is not None else ctx.now)
    row = ctx.repo.conn.execute(
        "SELECT COALESCE(SUM(progress), 0) AS total FROM quest_progress "
        "WHERE quest_id=? AND claimed=0",
        (f"{THREAT_PREFIX}{week}",),
    ).fetchone()
    return row["total"]


def defeated(ctx: Context, now: int | None = None) -> bool:
    return threat(ctx, now) >= THREAT_GOAL


def add_threat(ctx: Context, user_id: str, amount: int) -> None:
    week = week_ordinal(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (user_id, f"{THREAT_PREFIX}{week}", amount),
    )


def challenges_today(ctx: Context, user_id: str) -> int:
    today = beijing_day(ctx.now)
    rows = ctx.repo.conn.execute(
        "SELECT b.played_at FROM battle_records b JOIN battle_participants p USING(battle_id) "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? AND b.played_at>=?",
        (user_id, battle_key(ctx.now), ctx.now - DAY_SCAN_WINDOW),
    )
    return sum(1 for row in rows if beijing_day(row["played_at"]) == today)


def wins_this_week(ctx: Context, user_id: str) -> int:
    start, end = beijing_week(ctx.now)
    rows = ctx.repo.conn.execute(
        "SELECT b.played_at FROM battle_records b JOIN battle_participants p USING(battle_id) "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? AND b.winner_side=p.side "
        "AND b.played_at>=?",
        (user_id, battle_key(ctx.now), ctx.now - WIN_SCAN_WINDOW),
    )
    return sum(1 for row in rows if start <= row["played_at"] < end)


def claimed(ctx: Context, user_id: str, prefix: str, week: int) -> bool:
    return _claimed_id(ctx, user_id, f"{prefix}{week}")


def _claimed_id(ctx: Context, user_id: str, quest_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (user_id, quest_id),
    ).fetchone()
    return row is not None


def _mark(ctx: Context, user_id: str, prefix: str, week: int, progress: int) -> None:
    _mark_id(ctx, user_id, f"{prefix}{week}", progress)


def _mark_id(ctx: Context, user_id: str, quest_id: str, progress: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (user_id, quest_id, progress),
    )


def tier_credential(week: int, wins: int) -> str:
    """Each win tier is its own weekly credential, so tiers never block each other."""
    return f"{TIER_PREFIX}{week}_{wins}"


def tier_claimed(ctx: Context, user_id: str, week: int, wins: int) -> bool:
    if _claimed_id(ctx, user_id, tier_credential(week, wins)):
        return True
    # Saves written before per-tier credentials only ever recorded the first
    # tier under the shared weekly key, so honour that row as tier 1 claimed.
    return wins == 1 and _claimed_id(ctx, user_id, f"{TIER_PREFIX}{week}")


def _tier_state(ctx: Context, user_id: str, week: int, wins: int) -> str:
    if tier_claimed(ctx, user_id, week, wins):
        return "已领取"
    actual = wins_this_week(ctx, user_id)
    if actual >= wins:
        return "可领取"
    return f"未达成（本周已胜 {actual}/{wins} 场）"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠首领 不接受参数，直接发送即可。")
    boss = current_boss(ctx.content, ctx.now)
    week = week_ordinal(ctx.now)
    progress = threat(ctx)
    lines = [
        f"本周首领：{boss.name} · 全服威胁 {progress}/{THREAT_GOAL}",
        "全服灵宠每胜一场便把首领向击退推进一步；威胁满额即被击退。",
        _enemy_detail(ctx, boss.id),
    ]
    links = []
    for wins, stones, items in TIERS:
        state = _tier_state(ctx, ctx.user_id, week, wins)
        lines.append(f"第 {wins} 档：灵石 {stones} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, f"领取第 {wins} 档", f"灵宠首领领奖 {wins}"))
    if defeated(ctx):
        if claimed(ctx, ctx.user_id, REWARD_PREFIX, week):
            lines.append("击退奖励：已领取。")
        else:
            lines.append("击退奖励：本周首领已被击退，可领取。")
            links.append(InlineCommand(len(lines) - 1, "领取击退奖励", "灵宠首领领奖 击退"))
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再挑战本周首领。")
        return Reply("灵宠首领", tuple(lines), ("灵宠帮助",), (
            InlineCommand(0, "开始领养", "灵宠领养 "),
        ))
    used = challenges_today(ctx, player.user_id)
    lines.append(f"今日挑战 {used}/{CHALLENGES_PER_DAY} 次 · 本周已胜 {wins_this_week(ctx, player.user_id)} 场。")
    if used >= CHALLENGES_PER_DAY:
        lines.append("今日挑战次数已用完，明日 00:00（北京时间）再战。")
    else:
        links.insert(0, InlineCommand(0, "挑战首领", "灵宠挑战首领"))
    return Reply("灵宠首领", tuple(lines), ("灵宠秘境", "灵宠任务", "灵宠帮助"), tuple(links))


def challenge(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠挑战首领 不接受参数，直接发送即可。")
    player, pet = ctx.player(), ctx.pet()
    boss = current_boss(ctx.content, ctx.now)
    if challenges_today(ctx, player.user_id) >= CHALLENGES_PER_DAY:
        raise GameError(f"今日首领挑战已达 {CHALLENGES_PER_DAY} 次，明日 00:00（北京时间）再战。")
    energy = ctx.content.rules.explore_energy
    ctx.check_action(player, pet, "pve", energy, ctx.config.spirit_pet_pve_cooldown)
    ally = combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)
    enemy = enemy_fighter(boss, ctx.content.skills)
    capture = capture_snapshot(ctx, ([ally], [enemy]), ([ctx.user_id], []))
    battle = fight([ally], [enemy], ctx.rng, ctx.content.elements)
    pet.energy -= energy
    player.last_pve = ctx.now
    lines = [f"{boss.name} · {battle.rounds} 回合", *battle.lines]
    lines.extend(award_mastery(
        ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
    ))
    if battle.winner == 0:
        add_threat(ctx, player.user_id, WIN_THREAT)
        lines.append(f"首领受到重创，全服威胁 +{WIN_THREAT}。")
    else:
        add_threat(ctx, player.user_id, LOSS_THREAT)
        lines.append(f"虽败犹战，全服威胁 +{LOSS_THREAT}。")
    ctx.repo.invalidate_ready(ctx.user_id)
    lines.append(f"精力 -{energy}；气血仅在本场战斗内结算。")
    title = "首领战胜利" if battle.winner == 0 else ("首领战平局" if battle.winner == -1 else "首领战败退")
    reply = Reply(title, tuple(lines), ("灵宠首领", "灵宠战报", "灵宠任务"))
    record_battle(
        ctx, kind="pve", battle_key=battle_key(ctx.now), battle_name=f"{boss.name}首领战",
        battle=battle, capture=capture, reply=reply,
    )
    return reply


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    arg = arg.strip()
    week = week_ordinal(ctx.now)
    if arg == "击退":
        if not defeated(ctx):
            raise GameError(f"本周首领尚未被击退（全服威胁 {threat(ctx)}/{THREAT_GOAL}）。")
        if not wins_this_week(ctx, player.user_id):
            raise GameError("本周需战胜首领一次才能分享击退奖励。")
        if claimed(ctx, player.user_id, REWARD_PREFIX, week):
            raise GameError("本周击退奖励已领取。")
        _mark(ctx, player.user_id, REWARD_PREFIX, week, wins_this_week(ctx, player.user_id))
        lines = ("击退奖励已领取。", "，".join(grant(ctx, BOSS_REWARD, player.user_id)))
        return Reply("首领击退奖励", lines, ("灵宠首领", "我的灵宠"))
    if not arg.isdecimal():
        raise GameError("格式：灵宠首领领奖 1，或 灵宠首领领奖 击退。")
    tier = next((entry for entry in TIERS if str(entry[0]) == arg), None)
    if tier is None:
        raise GameError("没有该档位：可选 1、3、7 或 击退。")
    wins, stones, items = tier
    if tier_claimed(ctx, player.user_id, week, wins):
        raise GameError(f"第 {wins} 档奖励已领取，下周再战。")
    actual = wins_this_week(ctx, player.user_id)
    if actual < wins:
        raise GameError(f"本周已胜 {actual} 场，还需 {wins - actual} 场才能领取第 {wins} 档。")
    _mark_id(ctx, player.user_id, tier_credential(week, wins), actual)
    reward = Reward.model_validate({
        "exp": {"minimum": 0, "maximum": 0}, "stones": {"minimum": stones, "maximum": stones},
        "items": {key: {"minimum": amount, "maximum": amount} for key, amount in items.items()},
    })
    lines = (f"第 {wins} 档奖励已领取。", "，".join(grant(ctx, reward, player.user_id)))
    return Reply("首领档位奖励", lines, ("灵宠首领", "我的灵宠"))
