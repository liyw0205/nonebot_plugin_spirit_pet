"""Team-ranked arena: 2-3 player teams battle other ready teams.

Reuses the existing team roster (all members prepared via 灵宠准备), the combat
engine and the season machinery. Team ratings live in `quest_progress` under
the captain's user_id (`team_rating_<season>_<team_id>`, one row per team per
season); tier credentials use `team_tier_<season>_<team_id>_<tier>` rows with
the claimed flag. The 1v1 ladder and its scoring are untouched. Schema 20
stays.
"""

from ...application.context import Context
from ...domain.content import Range, Reward
from ...domain.models import GameError, InlineCommand, Reply
from ...utils.arguments import quantity
from ...utils.time import beijing_day
from ..battle_records import capture_snapshot, record_battle
from ..combat import fight
from ..loadout import combatants
from ..mastery import award_mastery
from ..quests import advance
from .. import battle_pass
from ..rewards import grant
from .common import current_season

RATING_PREFIX = "team_rating_"
TIER_PREFIX = "team_tier_"
DELTA = 20


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


def _ready(ctx: Context, user_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT ready_pet_ids FROM team_members WHERE user_id=?", (user_id,),
    ).fetchone()
    return bool(row and row["ready_pet_ids"])


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
    attackers = [fighter for user in members for fighter in combatants(ctx, user, recover_energy=False)]
    defenders = [fighter for user in opponents for fighter in combatants(ctx, user, recover_energy=False)]
    if len(attackers) > 5 or len(defenders) > 5:
        raise GameError("组队论剑每侧最多出战五只灵宠。")
    capture = capture_snapshot(
        ctx, (attackers, defenders),
        ([user for user in members for _ in combatants(ctx, user, recover_energy=False)],
         [user for user in opponents for _ in combatants(ctx, user, recover_energy=False)]),
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
        for pet in ctx.repo.active_pets(user):
            pet.energy -= season.rules.energy
            mastery_lines.extend(award_mastery(
                ctx, user, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
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
