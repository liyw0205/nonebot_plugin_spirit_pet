"""Gear sockets: one gem per pet slot, scaling one base stat.

A socket belongs to the pet's slot rather than to the equipped item, so swapping gear keeps the gem
and the layer never has to hook into equip/unequip. State is one row per socket,
``socket_<pet_id>_<slot>_<gem id>``, which also makes "a slot holds at most one gem" a structural
property instead of a validation rule.
"""

from ..application.context import Context
from ..domain.gem_content import SocketGem
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import counters
from .pet_targets import note_prep_change

PREFIX = "socket_"
CUT_PREFIX = "gemcut_"
SLOTS = ("weapon", "armor", "charm")
SLOT_NAMES = {"weapon": "兵刃", "armor": "护甲", "charm": "灵饰"}
STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def _prefix(pet_id: int) -> str:
    return f"{PREFIX}{pet_id}_"


def _rows(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, str]:
    # The row belongs to the player (the column is a foreign key to players), the pet id lives in the
    # quest key so a socket can never leak across accounts.
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{_prefix(pet_id)}%"),
    ).fetchall()
    found = {}
    for row in rows:
        if row["quest_id"].startswith(f"{_prefix(pet_id)}"):
            for slot in SLOTS:
                key = f"{_prefix(pet_id)}{slot}_"
                if row["quest_id"].startswith(key):
                    found[slot] = row["quest_id"][len(key):]
    return found


def socketed(ctx: Context, pet_id: int, slot: str, user_id: str | None = None) -> SocketGem | None:
    gem_id = _rows(ctx, pet_id, user_id).get(slot)
    return ctx.content.gems.get(gem_id) if gem_id else None


def rates(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, float]:
    """Sum of gem rates per stat, including the slot's cut level."""
    out: dict[str, float] = {}
    step = ctx.content.rules.socket_cut.rate_step
    for slot in SLOTS:
        gem = socketed(ctx, pet_id, slot, user_id)
        if gem is not None:
            out[gem.stat] = out.get(gem.stat, 0.0) + gem.rate + step * cut_level(ctx, pet_id, slot, user_id)
    return out


def cut_level(ctx: Context, pet_id: int, slot: str, user_id: str | None = None) -> int:
    """How many times this slot's gem has been refined."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{CUT_PREFIX}{pet_id}_{slot}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _equipped(ctx: Context, pet_id: int) -> dict[str, str]:
    rows = ctx.repo.conn.execute(
        "SELECT slot, item_id FROM equipment WHERE pet_id=?", (pet_id,)
    ).fetchall()
    return {row["slot"]: row["item_id"] for row in rows}


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id)
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _drop(ctx: Context, pet_id: int, slot: str) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{_prefix(pet_id)}{slot}_%"),
    )


def _link(ctx: Context, pet, arg: str) -> Reply:
    equipped = _equipped(ctx, pet.pet_id)
    sockets = _rows(ctx, pet.pet_id)
    rule = ctx.content.rules.socket_cut
    lines = [f"{pet.name}的镶嵌：每个槽位可嵌入一颗宝石，宝石属该槽位，替换装备不会脱落。"]
    links = []
    for slot in SLOTS:
        item = equipped.get(slot)
        gear = ctx.content.items[item].name if item else "未装备"
        gem_id = sockets.get(slot)
        gem = ctx.content.gems.get(gem_id) if gem_id else None
        detail = f"，{gem.name}（{STAT_NAMES[gem.stat]} +{int(gem.rate * 100)}%）" if gem else "，未镶嵌"
        lines.append(f"{SLOT_NAMES[slot]}：{gear}{detail}")
        if gem is not None:
            level = cut_level(ctx, pet.pet_id, slot)
            links.append(InlineCommand(len(lines) - 1, "卸下", f"灵宠镶嵌 卸下 {SLOT_NAMES[slot]}"))
            if level < rule.max_level:
                cost = rule.stones[level]
                total = int((gem.rate + rule.rate_step * (level + 1)) * 100)
                lines.append(
                    f"  雕琢 {level}/{rule.max_level} · 下一级 {cost} 灵石与 {gem.name} "
                    f"{rule.gem_cost} 颗 · {STAT_NAMES[gem.stat]} 至 +{total}%"
                )
                links.append(InlineCommand(
                    len(lines) - 1, "雕琢", f"灵宠镶嵌 雕琢 {SLOT_NAMES[slot]}",
                ))
            else:
                lines.append(f"  雕琢 {level}/{rule.max_level} · 已到顶。")
        elif item is not None:
            for candidate in sorted(ctx.content.gems.values(), key=lambda gem: gem.stat):
                if _owned(ctx, candidate.item_id):
                    links.append(InlineCommand(
                        len(lines) - 1, f"镶{candidate.name}", f"灵宠镶嵌 {SLOT_NAMES[slot]} {candidate.name}"
                    ))
    return Reply("灵宠镶嵌", tuple(lines), ("灵宠镶嵌", "灵宠装备", "灵宠背包"), tuple(links))


def cut(ctx: Context, arg: str) -> Reply:
    """Refine a socketed gem one level, or straight to an optional target level.

    A target level is settled atomically: every level from the current one up to
    the target is priced from the cut ladder, both stones and gems are checked
    before anything is written, and the whole batch lands in one transaction, so
    a shortfall leaves the slot, stones and gem inventory untouched.
    """
    parts = arg.split()
    if not parts or len(parts) > 2:
        raise GameError("格式：灵宠镶嵌 雕琢 <槽位> [目标等级]。")
    player = ctx.player()
    pet = ctx.pet()
    slot = _slot(ctx, parts[0])
    gem = socketed(ctx, pet.pet_id, slot)
    if gem is None:
        raise GameError(f"{SLOT_NAMES[slot]}槽位没有宝石，无法雕琢。")
    rule = ctx.content.rules.socket_cut
    level = cut_level(ctx, pet.pet_id, slot)
    if level >= rule.max_level:
        raise GameError(f"{SLOT_NAMES[slot]}已雕琢到 +{level}，无法再提升。")
    target = level + 1
    if len(parts) == 2:
        if not parts[1].isdecimal() or not 1 <= int(parts[1]) <= rule.max_level:
            raise GameError(f"目标等级须为 1-{rule.max_level} 的整数。")
        target = int(parts[1])
        if target <= level:
            raise GameError(f"{SLOT_NAMES[slot]}当前 +{level}，目标等级须更高。")

    steps = target - level
    stones = sum(rule.stones[step] for step in range(level, target))
    gem_cost = rule.gem_cost * steps
    owned_gems = _owned(ctx, gem.item_id)
    if player.stones < stones or owned_gems < gem_cost:
        span = f"（+{level}→+{target}，共 {steps} 级）" if steps > 1 else ""
        raise GameError(
            f"雕琢需要 {stones} 灵石与{gem.name} {gem_cost} 颗{span}；"
            f"当前灵石 {player.stones}、{gem.name} {owned_gems} 颗。"
        )
    with ctx.repo.conn:
        player.stones -= stones
        ctx.repo.consume_item(player.user_id, gem.item_id, gem_cost)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (player.user_id, f"{CUT_PREFIX}{pet.pet_id}_{slot}", target),
        )
    counters.bump(ctx, "gem_cuts", steps)
    note_prep_change(ctx, pet)
    total = int((gem.rate + rule.rate_step * target) * 100)
    return Reply("宝石雕琢", (
        f"{pet.name}的{SLOT_NAMES[slot]}雕琢至 +{target}，{STAT_NAMES[gem.stat]} +{total}%。",
        f"消耗 {stones} 灵石与{gem.name} {gem_cost} 颗；雕琢属于槽位，换宝石不会清零。",
    ), ("灵宠镶嵌", "灵宠装备", "灵宠背包"))


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠镶嵌 [<槽位> <宝石> | 卸下 <槽位> | 雕琢 <槽位> [目标等级]]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠镶嵌",
            ("尚未结契，先完成领养，才能镶嵌宝石。",),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    return _link(ctx, ctx.pet(), "")


def _slot(ctx: Context, name: str) -> str:
    for slot, label in SLOT_NAMES.items():
        if label == name:
            return slot
    raise GameError(f"未知槽位：{name}（可填 兵刃、护甲、灵饰）。")


def socket(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠镶嵌 <槽位> <宝石>。")
    ctx.player()
    pet = ctx.pet()
    slot = _slot(ctx, parts[0])
    gem = named({entry.name: entry for entry in ctx.content.gems.values()}, parts[1])
    if slot not in _equipped(ctx, pet.pet_id):
        raise GameError(f"{SLOT_NAMES[slot]}槽位尚未装备，无法镶嵌。")
    if socketed(ctx, pet.pet_id, slot) is not None:
        raise GameError(f"{SLOT_NAMES[slot]}槽位已有宝石，请先卸下。")
    if _owned(ctx, gem.item_id) < 1:
        raise GameError(f"背包里没有{gem.name}。")
    with ctx.repo.conn:
        ctx.repo.consume_item(ctx.user_id, gem.item_id, 1)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1",
            (ctx.user_id, f"{_prefix(pet.pet_id)}{slot}_{gem.id}"),
        )
    return Reply(
        "镶嵌完成",
        (
            f"{pet.name}的{SLOT_NAMES[slot]}嵌入{gem.name}，{STAT_NAMES[gem.stat]} +{int(gem.rate * 100)}%。",
            "宝石绑定该槽位，替换装备不会影响它；卸下会把宝石放回背包。",
        ),
        ("灵宠镶嵌", "灵宠装备", "灵宠背包"),
    )


def remove(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠镶嵌 卸下 <槽位>。")
    ctx.player()
    pet = ctx.pet()
    slot = _slot(ctx, arg.strip())
    gem = socketed(ctx, pet.pet_id, slot)
    if gem is None:
        raise GameError(f"{SLOT_NAMES[slot]}槽位没有宝石。")
    with ctx.repo.conn:
        _drop(ctx, pet.pet_id, slot)
        ctx.repo.add_item(ctx.user_id, gem.item_id, 1)
    return Reply(
        "已卸下宝石",
        (f"取回{gem.name}，{pet.name}的{SLOT_NAMES[slot]}回到未镶嵌状态。",),
        ("灵宠镶嵌", "灵宠背包"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "卸下":
        return remove(ctx, " ".join(parts[1:]))
    if parts[0] == "雕琢":
        return cut(ctx, " ".join(parts[1:]))
    return socket(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None or player.active_pet_id is None:
        return "镶嵌：尚未结契"
    rows = _rows(ctx, player.active_pet_id, user_id)
    return f"镶嵌：{len(rows)}/3 个槽位已镶宝石"
