"""Team-ranked arena: 2-3 player teams battle other ready teams.

Reuses the existing team roster (all members prepared via 灵宠准备), the combat
engine and the season machinery. Team ratings live in `quest_progress` under
the captain's user_id (`team_rating_<season>_<team_id>`, one row per team per
season); tier credentials use `team_tier_<season>_<team_id>_<tier>` rows with
the claimed flag. The 1v1 ladder and its scoring are untouched. Schema 20
stays.
"""

import json

from ...application.context import Context
from ...domain.content import Range, Reward
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import quantity
from ...utils.time import beijing_day
from ..battle_records import capture_snapshot, record_battle
from ..combat import fight
from ..loadout import combatant, team_pets
from ..mastery import award_mastery
from ..quests import advance
from .. import battle_pass
from ..rewards import grant
from .common import current_season

RATING_PREFIX = "team_rating_"
TIER_PREFIX = "team_tier_"
DELTA = 20
PAGE_SIZE = 5
# Per-team daily battle cap: mirrors season.rules.daily_matches (5) for team play.
MAX_DAILY_TEAM_BATTLES = 5


def _team_id(ctx: Context, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT team_id FROM team_members WHERE user_id=?", (user_id,),
    ).fetchone()
    if row is None:
        raise GameError("你还没有队伍，先发送 灵宠组队 建队或入队。")
    return row["team_id"]


def _members(ctx: Context, team_id: int) -> list[str]:
    return [
        row["user_id"] for row in ctx.repo.conn.execute(
            "SELECT user_id FROM team_members WHERE team_id=? ORDER BY user_id", (team_id,),
        )
    ]


def _ready_ids(ctx: Context, user_id: str) -> list[int]:
    """Pet ids the member prepared; the same row the ready check reads."""
    row = ctx.repo.conn.execute(
        "SELECT ready_pet_ids FROM team_members WHERE user_id=?", (user_id,),
    ).fetchone()
    if row is None or not row["ready_pet_ids"]:
        return []
    return [int(item) for item in json.loads(row["ready_pet_ids"])]


def _ready(ctx: Context, user_id: str) -> bool:
    return bool(_ready_ids(ctx, user_id))


def _side_pets(ctx: Context, team_id: int) -> list[tuple[str, int]]:
    """One side of a ranked team battle, as (owner, pet_id) pairs.

    Team battles share one loadout rule (`loadout.team_pets`): the captain
    fields up to three pets, each teammate fields one, at most five per side.
    `灵宠准备` previews exactly these pets, so the battle must use them too.
    """
    members = _members(ctx, team_id)
    return [(user_id, pet.pet_id) for user_id, pet in team_pets(ctx, members, _captain(ctx, team_id))]


def _check_ready(ctx: Context, team_id: int, side: list[tuple[str, int]]) -> None:
    """Reject when a member's ready row no longer matches the side that fights."""
    expected: dict[str, list[int]] = {}
    for user_id, pet_id in side:
        expected.setdefault(user_id, []).append(pet_id)
    for user_id in _members(ctx, team_id):
        if _ready_ids(ctx, user_id) != expected.get(user_id, []):
            raise GameError(f"{ctx.player(user_id).uid_label}尚未准备当前出战灵宠，请全队重新 灵宠准备。")


def rating(ctx: Context, season_id: str, team_id: int) -> int:
    captain = _members(ctx, team_id)[0]
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (captain, f"{RATING_PREFIX}{season_id}_{team_id}"),
    ).fetchone()
    return row["progress"] if row else 1000


def set_rating(ctx: Context, season_id: str, team_id: int, value: int) -> None:
    captain = _members(ctx, team_id)[0]
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (captain, f"{RATING_PREFIX}{season_id}_{team_id}", max(0, value)),
    )


def tier_claimed(ctx: Context, season_id: str, team_id: int, tier_id: str) -> bool:
    captain = _members(ctx, team_id)[0]
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (captain, f"{TIER_PREFIX}{season_id}_{team_id}_{tier_id}"),
    ).fetchone()
    return row is not None


def _team_battles(ctx: Context, season_id: str) -> list:
    """Every recorded team battle this season, oldest first, with both sides.

    Team battles write battle_records only (key `team_<season>`), so the
    1v1 pvp_results quotas cannot apply; these rows are the team equivalent.
    """
    rows = ctx.repo.conn.execute(
        "SELECT b.battle_id, b.played_at FROM battle_records b "
        "WHERE b.kind='pvp' AND b.battle_key=? ORDER BY b.battle_id",
        (f"team_{season_id}",),
    ).fetchall()
    return [dict(battle_id=row["battle_id"], played_at=row["played_at"]) for row in rows]


def _side_captain(ctx: Context, battle_id: int, side: int) -> str | None:
    """The captain of one side of a recorded team battle."""
    row = ctx.repo.conn.execute(
        "SELECT tm.team_id FROM battle_participants p "
        "JOIN team_members tm ON tm.user_id=p.user_id "
        "WHERE p.battle_id=? AND p.side=? LIMIT 1",
        (battle_id, side),
    ).fetchone()
    return _captain(ctx, row["team_id"]) if row else None


def _daily_battles(ctx: Context, season_id: str, team_id: int) -> int:
    """How many ranked battles this team started today (Beijing)."""
    captain = _captain(ctx, team_id)
    today = beijing_day(ctx.now)
    return sum(
        1 for battle in _team_battles(ctx, season_id)
        if _side_captain(ctx, battle["battle_id"], 0) == captain
        and beijing_day(battle["played_at"]) == today
    )


def _pair_battles(ctx: Context, season_id: str, first: int, second: int) -> tuple[int, int]:
    """How often these two teams met today and this season."""
    captains = {_captain(ctx, first), _captain(ctx, second)}
    today, total = 0, 0
    day = beijing_day(ctx.now)
    for battle in _team_battles(ctx, season_id):
        first_captain = _side_captain(ctx, battle["battle_id"], 0)
        second_captain = _side_captain(ctx, battle["battle_id"], 1)
        if {first_captain, second_captain} != captains:
            continue
        total += 1
        if beijing_day(battle["played_at"]) == day:
            today += 1
    return today, total


def team_pvp(ctx: Context, arg: str) -> Reply:
    """Captain-initiated ranked team battle against another ready team."""
    if not arg.strip():
        raise GameError("格式：灵宠组队论剑 <对方队长UID>。")
    ctx.player()
    season = current_season(ctx)
    target_captain = ctx.repo.player_by_uid(quantity(arg.strip(), 9_223_372_036_854_775_807))
    if target_captain is None or target_captain.user_id == ctx.user_id:
        raise GameError("请填写其他队伍的队长 UID。")
    my_team = _team_id(ctx, ctx.user_id)
    their_team = _team_id(ctx, target_captain.user_id)
    if my_team == their_team:
        raise GameError("不能挑战自己的队伍。")
    members, opponents = _members(ctx, my_team), _members(ctx, their_team)
    if len(members) < 2 or len(opponents) < 2:
        raise GameError("组队论剑需要双方至少两名在队成员。")
    if not all(_ready(ctx, user) for user in members):
        raise GameError("本队须全员准备后才能发起组队论剑。")
    if not all(_ready(ctx, user) for user in opponents):
        raise GameError("对方队伍尚未全员准备，无法应战。")
    daily_cap = min(season.rules.daily_matches, MAX_DAILY_TEAM_BATTLES)
    if _daily_battles(ctx, season.season_id, my_team) >= daily_cap:
        raise GameError(f"本队今日组队论剑次数已用尽（{daily_cap} 场）。")
    today, total = _pair_battles(ctx, season.season_id, my_team, their_team)
    if today >= season.rules.pair_daily_matches:
        raise GameError("双方今日已结算至同对组队论剑上限，明日再战。")
    if total >= season.rules.pair_season_matches:
        raise GameError("双方本赛季同对组队论剑次数已用尽。")
    my_side = _side_pets(ctx, my_team)
    their_side = _side_pets(ctx, their_team)
    _check_ready(ctx, my_team, my_side)
    _check_ready(ctx, their_team, their_side)
    for user in (*members, *opponents):
        for pet in ctx.repo.active_pets(user):
            ctx.require_idle_pet(pet)
    attackers = [combatant(ctx, user, recover_energy=False, pet_id=pet_id) for user, pet_id in my_side]
    defenders = [combatant(ctx, user, recover_energy=False, pet_id=pet_id) for user, pet_id in their_side]
    capture = capture_snapshot(
        ctx, (attackers, defenders),
        ([user for user, _ in my_side], [user for user, _ in their_side]),
    )
    battle = fight(attackers, defenders, ctx.rng, ctx.content.elements)
    my_rating = rating(ctx, season.season_id, my_team)
    their_rating = rating(ctx, season.season_id, their_team)
    if battle.winner == 0:
        my_rating, their_rating = my_rating + DELTA, max(0, their_rating - DELTA)
        advance(ctx, "pvp")
    elif battle.winner == 1:
        my_rating, their_rating = max(0, my_rating - DELTA), their_rating + DELTA
    set_rating(ctx, season.season_id, my_team, my_rating)
    set_rating(ctx, season.season_id, their_team, their_rating)
    # Every challenger completed a ranked challenge, so each earns season activity once.
    for user in members:
        battle_pass.add_experience(ctx, "pvp_challenge", user)
    mastery_lines = []
    for user in members:
        # Only pets that actually fought pay energy and earn mastery.
        for pet_id in [pid for owner, pid in my_side if owner == user]:
            ctx.repo.pet(pet_id).energy -= season.rules.energy
            mastery_lines.extend(award_mastery(
                ctx, user, battle.skill_uses[0].get(pet_id, {}), pet_id=pet_id,
            ))
        ctx.repo.invalidate_ready(user)
    result = "双方战平。" if battle.winner == -1 else (
        "本队获胜。" if battle.winner == 0 else "本队败退。"
    )
    reply = Reply("组队论剑结算", (
        f"本队 {len(attackers)} 宠 对 对方 {len(defenders)} 宠 · {battle.rounds} 回合",
        *battle.lines, result,
        f"本队积分 {my_rating} · 对方积分 {their_rating}（±{DELTA}）",
        *mastery_lines,
    ), ("灵宠组队论剑", "灵宠战报", "灵宠赛季"))
    record_battle(
        ctx, kind="pvp", battle_key=f"team_{season.season_id}", battle_name="组队论剑",
        battle=battle, capture=capture, reply=reply,
    )
    return reply


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠组队论剑 不接受参数，直接发送即可。")
    season = current_season(ctx)
    player = ctx.player()
    team_id = _team_id(ctx, player.user_id)
    value = rating(ctx, season.season_id, team_id)
    lines = [f"组队论剑 · 赛季 {season.season_id} · 队伍 {team_id} · 积分 {value}"]
    links = []
    for tier in sorted(ctx.content.arena.tiers, key=lambda entry: entry.minimum_rating):
        claimed = tier_claimed(ctx, season.season_id, team_id, tier.id)
        if claimed:
            state = "已领取"
        elif value >= tier.minimum_rating:
            state = "可领取"
        else:
            state = f"还差 {tier.minimum_rating - value} 分"
        lines.append(f"{tier.name}（{tier.minimum_rating} 分）：{state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, f"领取{tier.name}", f"灵宠组队段位领奖 {tier.name}"))
    return Reply("组队论剑", tuple(lines), ("灵宠赛季", "灵宠帮助"), tuple(links))


def _uid(ctx: Context, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT id FROM player_identity WHERE user_id=?", (user_id,),
    ).fetchone()
    return int(row["id"]) + 9999 if row else 0


def _captain(ctx: Context, team_id: int) -> str:
    row = ctx.repo.conn.execute(
        "SELECT leader_id FROM teams WHERE team_id=?", (team_id,),
    ).fetchone()
    return row["leader_id"]


def matchmaking(ctx: Context, arg: str) -> Reply:
    """List opposing teams within the season rating gap for the captain.

    Read-only: it writes no report, rating or credential. Candidates mirror the
    rules team_pvp enforces -- a team of the same size, at least two members,
    every member ready -- and same-size plus rating-gap filtering happens before
    paging so unavailable teams never consume a slot.
    """
    page = quantity(arg or "1", 999)
    season = current_season(ctx)
    player = ctx.player()
    my_team = _team_id(ctx, player.user_id)
    if _captain(ctx, my_team) != player.user_id:
        raise GameError("只有队长可以发起组队论剑匹配。")
    members = _members(ctx, my_team)
    if len(members) < 2:
        raise GameError("组队论剑需要至少两名在队成员。")
    if not all(_ready(ctx, user) for user in members):
        raise GameError("本队须全员准备后才能匹配对手。")
    mine = rating(ctx, season.season_id, my_team)
    rows = ctx.repo.conn.execute(
        "SELECT leader.leader_id AS captain, leader.team_id AS team_id "
        "FROM teams leader "
        "WHERE leader.team_id!=? ORDER BY leader.team_id",
        (my_team,),
    ).fetchall()
    candidates = []
    for row in rows:
        their_team = int(row["team_id"])
        opponents = _members(ctx, their_team)
        if len(opponents) != len(members) or len(opponents) < 2:
            continue
        if not all(_ready(ctx, user) for user in opponents):
            continue
        theirs = rating(ctx, season.season_id, their_team)
        if abs(mine - theirs) > season.rules.max_rating_gap:
            continue
        candidates.append({
            "uid": _uid(ctx, row["captain"]),
            "size": len(opponents),
            "rating": theirs,
        })
    candidates.sort(key=lambda entry: (abs(mine - entry["rating"]), entry["uid"]))
    window = candidates[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    if page > 1 and not window:
        raise GameError("该页暂无候选队伍。")
    links = tuple(
        InlineCommand(index, "挑战该队伍", f"灵宠组队论剑 {entry['uid']}")
        for index, entry in enumerate(window)
    )
    lines = tuple(
        f"UID {entry['uid']} · {entry['size']} 人队 · 积分 {entry['rating']}"
        f" · 相差 {abs(mine - entry['rating'])} 分"
        for entry in window
    ) or ("暂无符合条件的候选队伍。",)
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠组队匹配 {page - 1}")
    if len(candidates) > page * PAGE_SIZE:
        commands.append(f"灵宠组队匹配 {page + 1}")
    commands.extend(("灵宠组队论剑", "灵宠目标"))
    return Reply(
        f"组队论剑候选 · {season.season_id} · 第{page}页",
        lines + ("向对方队长发起挑战，无需对方在线。",),
        tuple(commands), links,
    )


def claim_tier(ctx: Context, arg: str) -> Reply:
    name = arg.strip()
    season = current_season(ctx)
    player = ctx.player()
    team_id = _team_id(ctx, player.user_id)
    tier = next((entry for entry in ctx.content.arena.tiers if entry.name == name), None)
    if tier is None:
        raise GameError("没有该段位，发送 灵宠组队论剑 查看全部档位。")
    if tier_claimed(ctx, season.season_id, team_id, tier.id):
        raise GameError(f"{tier.name}的组队段位奖励已领取，下季再战。")
    value = rating(ctx, season.season_id, team_id)
    if value < tier.minimum_rating:
        raise GameError(f"队伍积分 {value}，还差 {tier.minimum_rating - value} 分才能领取 {tier.name}。")
    captain = _members(ctx, team_id)[0]
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (captain, f"{TIER_PREFIX}{season.season_id}_{team_id}_{tier.id}", value),
    )
    reward = Reward.model_validate({
        "exp": {"minimum": 0, "maximum": 0},
        "stones": {"minimum": tier.stones, "maximum": tier.stones},
        "items": {key: {"minimum": amount, "maximum": amount} for key, amount in tier.items.items()},
    })
    lines = (f"{tier.name}组队段位奖励已领取。", "，".join(grant(ctx, reward, player.user_id)))
    return Reply("组队段位奖励", lines, ("灵宠组队论剑", "我的灵宠"))
