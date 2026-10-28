"""Defense lineup and weekly defense rewards for ranked PVP.

The defense lineup is a 1-3 pet mirror the owner prepares in advance. It is
stored as one `quest_progress` row per slot, so the schema stays unchanged:

* `defense_pet_<slot>` with `progress` = pet id
* `defense_reward_<week_start>_<tier>` marks a claimed weekly tier

Ranked challenges use the lineup when it is valid; otherwise they fall back to
the owner's active roster, preserving the old mirror behavior for players who
never configure one. Defense wins are read from `pvp_results`; no battle hook,
counter column, or new table is needed.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_week
from . import loadout

SLOTS = (1, 2, 3)
PREFIX = "defense_pet_"
CLAIM_PREFIX = "defense_reward_"
_COMMANDS = ("灵宠防守", "灵宠论剑榜", "灵宠战报", "我的灵宠")


def _keys(ctx: Context, user_id: str) -> list[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ?",
        (user_id, f"{PREFIX}*"),
    )
    return [row["quest_id"] for row in rows]


def _slots(ctx: Context, user_id: str) -> dict[int, int]:
    slots = {}
    for key in _keys(ctx, user_id):
        suffix = key[len(PREFIX):]
        if not suffix.isdecimal():
            continue
        slot = int(suffix)
        row = ctx.repo.conn.execute(
            "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
            (user_id, key),
        ).fetchone()
        if slot in SLOTS and row is not None and row["progress"] > 0:
            slots[slot] = int(row["progress"])
    return dict(sorted(slots.items()))


def _usable(pets: list) -> bool:
    """A defense mirror is 1-3 distinct species of a single great realm."""
    return (
        bool(pets)
        and len(pets) <= 3
        and len({pet.species_id for pet in pets}) == len(pets)
        and len({pet.realm for pet in pets}) == 1
    )


def _stored(ctx: Context, user_id: str) -> tuple[list, bool, bool]:
    """Load the stored preset as (pets, has_rows, broken)."""
    slots = _slots(ctx, user_id)
    pets = []
    broken = False
    for pet_id in slots.values():
        try:
            pet = ctx.repo.pet(pet_id)
        except GameError:
            broken = True
            continue
        if pet.user_id != user_id or pet.archived:
            broken = True
            continue
        pets.append(pet)
    return pets, bool(slots), broken


def configured(ctx: Context, user_id: str) -> tuple[list, str | None]:
    """Return (pets, problem); problem is None only for a usable lineup."""
    pets, has_rows, broken = _stored(ctx, user_id)
    if not has_rows:
        return [], None
    if broken or not _usable(pets):
        return pets, "失效"
    return pets, None


def resolve(ctx: Context, user_id: str) -> tuple[list, bool]:
    """The lineup that actually defends, and whether it came from the preset.

    A stored preset that stopped being usable (封存/易主/失联/种类重复/跨大境界)
    falls back to the active roster so an attacker is never blocked by it.
    """
    pets, problem = configured(ctx, user_id)
    if pets and problem is None:
        return pets, True
    return ctx.repo.active_pets(user_id), False


def has_valid(ctx: Context, user_id: str) -> bool:
    pets, problem = configured(ctx, user_id)
    return bool(pets) and problem is None


def fighters(ctx: Context, user_id: str) -> list:
    """Build the ranked-defense mirror, falling back to the active roster."""
    pets, _ = resolve(ctx, user_id)
    if not pets:
        raise GameError("对方尚未选择出战灵宠。")
    if len(pets) > 3 or len({pet.species_id for pet in pets}) != len(pets):
        raise GameError("出战阵容最多三只灵宠，且不能重复宠物种类。")
    return [
        loadout.combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id)
        for pet in pets
    ]


def clear(ctx: Context, user_id: str) -> int:
    keys = _keys(ctx, user_id)
    for key in keys:
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?", (user_id, key),
        )
    return len(keys)


def set_lineup(ctx: Context, pet_ids: list[int]) -> tuple:
    ctx.player()
    if not pet_ids:
        raise GameError("请至少选择一只灵宠作为防守阵容。")
    if len(pet_ids) > 3:
        raise GameError("防守阵容最多三只灵宠。")
    if len(set(pet_ids)) != len(pet_ids):
        raise GameError("防守阵容不能重复同一只灵宠。")
    pets = []
    for pet_id in pet_ids:
        pet = ctx.repo.pet(pet_id)
        if pet.user_id != ctx.user_id:
            raise GameError("只能使用自己的灵宠。")
        if pet.archived:
            raise GameError(f"{pet.name}已封存，不能加入防守阵容。")
        pets.append(pet)
    if len({pet.species_id for pet in pets}) != len(pets):
        raise GameError("防守阵容不能重复宠物种类。")
    if len({pet.realm for pet in pets}) != 1:
        raise GameError("防守阵容需为同一大境界的灵宠。")
    clear(ctx, ctx.user_id)
    for slot, pet in enumerate(pets, 1):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (ctx.user_id, f"{PREFIX}{slot}", pet.pet_id),
        )
    return tuple(pets)


def weekly_record(ctx: Context, user_id: str | None = None) -> tuple[int, int]:
    """(challenges received, successful defenses) in the current Beijing week."""
    owner = user_id or ctx.user_id
    start, end = beijing_week(ctx.now)
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(winner_id=?), 0) AS wins"
        " FROM pvp_results WHERE target_id=? AND played_at>=? AND played_at<?",
        (owner, owner, start, end),
    ).fetchone()
    return int(row["total"]), int(row["wins"])


def _claim_key(start: int, tier_id: str) -> str:
    return f"{CLAIM_PREFIX}{start}_{tier_id}"


def _claimed(ctx: Context, start: int, user_id: str | None = None) -> set[str]:
    owner = user_id or ctx.user_id
    prefix = f"{CLAIM_PREFIX}{start}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{prefix}%"),
    )
    return {
        row["quest_id"][len(prefix):]
        for row in rows
        if row["quest_id"].startswith(prefix)
    }


def claimable(ctx: Context, user_id: str | None = None) -> list:
    """Tiers reached this week and not yet claimed, in content order."""
    start, _ = beijing_week(ctx.now)
    claimed = _claimed(ctx, start, user_id)
    _, wins = weekly_record(ctx, user_id)
    return [
        tier for tier in ctx.content.arena.defense_tiers
        if tier.id not in claimed and wins >= tier.wins
    ]


def claim(ctx: Context, wins: int) -> Reply:
    ctx.player()
    tier = next((item for item in ctx.content.arena.defense_tiers if item.wins == wins), None)
    if tier is None:
        raise GameError("没有这个守擂档位。")
    start, _ = beijing_week(ctx.now)
    if tier.id in _claimed(ctx, start):
        return _reply((f"「{tier.name}」本周已经领取，无需重复领取。",))
    _, actual = weekly_record(ctx)
    if actual < tier.wins:
        raise GameError(f"本周守擂成功 {actual} 场，尚未达到 {tier.wins} 场。")
    player = ctx.player()
    player.stones += tier.stones
    lines = [f"「{tier.name}」已领取：灵石 +{tier.stones}"]
    for item_id, amount in tier.items.items():
        ctx.repo.add_item(player.user_id, item_id, amount)
        lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (ctx.user_id, _claim_key(start, tier.id), actual),
    )
    return _reply(tuple(lines))


def _reply(lines: tuple[str, ...]) -> Reply:
    return Reply("灵宠防守", lines, _COMMANDS)


def _reward_text(ctx: Context, tier) -> str:
    parts = [f"灵石 {tier.stones}"]
    parts.extend(f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in tier.items.items())
    return "、".join(parts)


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠防守", (
            "设置 1-3 只同大境界、不同种类的灵宠作为论剑防守镜像，并按本周守擂胜场领取奖励。",
            "尚未结契，先完成领养，再布置自己的防守阵容。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))
    pets, problem = configured(ctx, ctx.user_id)
    active = ctx.repo.active_pets(ctx.user_id)
    if problem is not None:
        lineup = "防守阵容已失效，暂沿用出战阵容：" + ("、".join(pet.name for pet in active) or "未选择") + "。"
    elif not pets:
        lineup = "防守阵容：未设置，沿用出战阵容（" + ("、".join(pet.name for pet in active) or "未选择") + "）。"
    else:
        lineup = "防守阵容（镜像）：" + "、".join(f"#{pet.pet_id} {pet.name}" for pet in pets) + "。"
    total, wins = weekly_record(ctx)
    lines = [
        lineup,
        f"本周被挑战 {total} 场，守擂成功 {wins} 场；周一 00:00 重置。",
        "设置：灵宠防守 设置 编号1 [编号2 编号3]（1-3 只、同大境界、不同种类）；清除：灵宠防守 清除。",
    ]
    start, _ = beijing_week(ctx.now)
    claimed = _claimed(ctx, start)
    links = []
    for tier in ctx.content.arena.defense_tiers:
        if tier.id in claimed:
            state = "已领取"
        elif wins >= tier.wins:
            state = "可领取"
        else:
            state = f"未达成（{wins}/{tier.wins}）"
        lines.append(f"守擂 {tier.wins} 胜 · {tier.name} · {_reward_text(ctx, tier)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取", f"灵宠防守 领取 {tier.wins}"))
    if _slots(ctx, ctx.user_id):
        links.append(InlineCommand(0, "清除阵容", "灵宠防守 清除"))
    return Reply("灵宠防守", tuple(lines), _COMMANDS, tuple(links))


def entry(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    action = parts[0]
    if action == "设置":
        if len(parts) < 2:
            raise GameError("格式：灵宠防守 设置 编号1 [编号2 编号3]。")
        if any(not value.isdecimal() for value in parts[1:]):
            raise GameError("灵宠编号必须是数字。")
        pets = set_lineup(ctx, [int(value) for value in parts[1:]])
        return _reply((
            "防守阵容已保存：" + "、".join(f"#{pet.pet_id} {pet.name}" for pet in pets) + "。",
            "防守镜像不消耗精力、不增加熟练度；论剑挑战会优先使用这套阵容。",
        ))
    if action == "清除":
        if len(parts) != 1:
            raise GameError("格式：灵宠防守 清除。")
        removed = clear(ctx, ctx.user_id)
        if not removed:
            return _reply(("当前没有设置防守阵容，未做改动。",))
        return _reply(("防守阵容已清除，论剑将沿用出战阵容。",))
    if action == "领取":
        if len(parts) != 2 or not parts[1].isdecimal():
            raise GameError("格式：灵宠防守 领取 <守擂胜场>。")
        return claim(ctx, int(parts[1]))
    raise GameError("格式：灵宠防守 [设置 编号...|清除|领取 胜场]。")
