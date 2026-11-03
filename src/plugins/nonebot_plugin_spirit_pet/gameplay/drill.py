"""灵宠演武: a zero-cost trial fight against a wooden dummy.

Every other combat path in this plugin charges something before it tells the player
anything: ``spar`` needs a second player, ``pvp`` needs matching, and adventure,
stages, tower, corridor, survival, forbidden, team trial, codex trial, gauntlet and
escort all pass through ``ctx.check_action`` (energy + cooldown). A player therefore
cannot check whether a freshly retuned lineup is actually better without spending a
resource, so lineup decisions are made blind.

The drill ground closes that gap without becoming a reward farm:

* the lineup is built by ``loadout.combatants(..., recover_energy=False)``, so mood,
  pair bond, formation, gear, sockets, skills and intent are all included and the
  measurement matches what a real fight would produce;
* the dummy is a plain ``Fighter`` built from static content, anchored to the same
  realm's dungeon enemies rather than a new balance band;
* nothing is charged: no energy, no cooldown, no consumable, and crucially
  ``ctx.check_action`` is never called;
* nothing is gained or recorded: no reward, no battle record, no ``pve_stage_progress``,
  no ``counters.bump``, so no achievement, title, weekly, battle-pass or leaderboard
  counter can be farmed for free.

The only persistence is a per-day attempt counter in ``quest_progress``
(``drill_<Beijing day>``), which needs no schema change. The cap exists so the drill
stays a deliberate test rather than an infinite damage oracle.
"""

import re

from ..application.context import Context
from ..domain.drill_content import DrillDummy
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .combat import Fighter, fight
from .loadout import combatants

DRILL_PREFIX = "drill_"
PAGE_SIZE = 4
TITLE = "灵宠演武"


def rule(ctx: Context):
    return ctx.content.rules.drill


def dummies(ctx: Context) -> list[DrillDummy]:
    """Stable ladder order: content order, then id."""
    return sorted(ctx.content.drills.values(), key=lambda dummy: (dummy.order, dummy.id))


def _day_key(ctx: Context) -> str:
    return f"{DRILL_PREFIX}{beijing_day(ctx.now)}"


def attempts_today(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _day_key(ctx)),
    ).fetchone()
    return int(row["progress"]) if row is not None else 0


def remaining(ctx: Context, user_id: str | None = None) -> int:
    return max(0, rule(ctx).daily_attempts - attempts_today(ctx, user_id))


def _resolve(ctx: Context, value: str) -> DrillDummy:
    """Accept either a dummy name or its 1-based order number."""
    text = value.strip()
    entries = dummies(ctx)
    if not text:
        raise GameError(f"格式：{TITLE} <木人桩名|序号>。")
    if re.fullmatch(r"[0-9]+", text):
        number = int(text)
        if not 1 <= number <= len(entries):
            raise GameError(f"演武场只有 {len(entries)} 座木人桩，请填写 1-{len(entries)}。")
        return entries[number - 1]
    for dummy in entries:
        if dummy.name == text or dummy.id == text:
            return dummy
    raise GameError(f"没有这座木人桩，请查看 {TITLE}。")


def _dummy_fighter(ctx: Context, dummy: DrillDummy) -> Fighter:
    return Fighter.create(
        dummy.name, dummy.stats, tuple(dummy.elements), (), primary_element=dummy.primary_element,
    )


def _state_line(ctx: Context, dummy: DrillDummy) -> str:
    realm = next((r for r in ctx.content.realms if r.id == dummy.realm), None)
    realm_name = realm.name if realm is not None else dummy.realm
    return (
        f"{dummy.order}. {dummy.name} · {realm_name}境 · 气血 {dummy.stats.hp}"
        f" · 攻 {dummy.stats.attack} 防 {dummy.stats.defense} 速 {dummy.stats.speed}"
    )


def catalog(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能进演武场。",
                "演武场用木人桩检验当前阵容：零精力、零冷却，也不发奖励。",
                "打一场只为看清回合数与每个伙伴剩下多少气血。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    left = remaining(ctx)
    entries = dummies(ctx)
    page_data = paginate(entries, arg, TITLE, TITLE, PAGE_SIZE)
    lines = [
        f"今日演武 {attempts_today(ctx)}/{rule(ctx).daily_attempts} 次"
        f" · 剩余 {left} 次 · 第 {page_data.number}/{page_data.total} 页。",
    ]
    links = []
    for dummy in page_data.entries:
        lines.append(_state_line(ctx, dummy))
        lines.append(f"   {dummy.description}")
        if left:
            links.append(InlineCommand(len(lines) - 2, "演武", f"{TITLE} {dummy.name}"))
    if not left:
        lines.append("今日演武次数已用完，明日 00:00（北京时间）恢复。")
    lines.append(f"开始演武：{TITLE} <木人桩名|序号>。演武不耗精力、不发奖励、也不写战报。")
    return Reply(
        TITLE,
        tuple(lines),
        (*page_data.navigation, "灵宠目标", "我的灵宠")[:4],
        tuple(links),
    )


def run(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    dummy = _resolve(ctx, arg)
    lineup = ctx.repo.active_pets(player.user_id)
    if not lineup:
        raise GameError("尚未选择出战灵宠。")
    for pet in lineup:
        ctx.require_idle_pet(pet)
    if remaining(ctx, player.user_id) <= 0:
        raise GameError(
            f"今日演武已达 {rule(ctx).daily_attempts} 次，明日 00:00（北京时间）再来。"
        )
    attackers = combatants(ctx, recover_energy=False)
    defender = _dummy_fighter(ctx, dummy)
    battle = fight(attackers, [defender], ctx.rng, ctx.content.elements)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress + 1",
        (player.user_id, _day_key(ctx), 1),
    )
    outcome = "平局" if battle.winner == -1 else ("破桩" if battle.winner == 0 else "落败")
    lines = [
        f"{battle.rounds} 回合 · {outcome} · 木人桩剩余气血 {max(defender.hp, 0)}/{dummy.stats.hp}。",
    ]
    for fighter, pet in zip(attackers, lineup):
        total = fighter.stats.hp
        left = max(fighter.hp, 0)
        lines.append(
            f"{pet.name}（{pet.pet_id}）· 气血 {left}/{total} · 承伤 {total - left}"
            f" · {'站到最后' if left > 0 else '被打退'}"
        )
    lines.append(
        f"今日演武 {attempts_today(ctx)}/{rule(ctx).daily_attempts} 次"
        " · 演武不耗精力、不发奖励、不写战报。"
    )
    return Reply(
        f"演武 · {dummy.name}",
        tuple(lines),
        (TITLE, "灵宠目标", "我的灵宠"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    """`名单 [页码]` pages the ladder; anything else names the dummy to fight."""
    parts = arg.split()
    if not parts:
        return catalog(ctx, "")
    if parts[0] == "名单":
        return catalog(ctx, " ".join(parts[1:]))
    return run(ctx, " ".join(parts))


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "演武：尚未结契"
    return f"演武：今日 {attempts_today(ctx, user_id)}/{rule(ctx).daily_attempts} 次"


__all__ = [
    "DRILL_PREFIX", "attempts_today", "catalog", "dispatch", "dummies", "objective_line",
    "remaining", "run",
]
