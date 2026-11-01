"""Pet pair bond: two specific pets that only help each other while deployed together.

Every other bonus in the game is a function of one pet or of the account. A pair bond is the first
that lives *between* two pets: each pet may hold exactly one partner, and the rates apply only while
both stand in the same lineup. With three roster slots that means a lineup can realise at most one
pair, so choosing the pair is a decision rather than another free stat.

State is one symmetric ``quest_progress`` row, ``bonded_<lower_id>_<higher_id>``, which makes "one
partner per pet" a property of the key instead of a second table. Rates scale **base** stats only, in
the same place as mood and formation, so flat bonuses keep their documented integers.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .loadout import combatant

KEY = "bonded_"
STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def rule(ctx: Context):
    return ctx.content.rules.pair_bond


def _pair_key(low: int, high: int) -> str:
    return f"{KEY}{min(low, high)}_{max(low, high)}"


def partner_of(ctx: Context, pet_id: int, user_id: str | None = None) -> int | None:
    """The pet this one is bonded to, if any."""
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{KEY}%"),
    ).fetchall()
    for row in rows:
        ids = row["quest_id"][len(KEY):].split("_")
        if len(ids) != 2 or not all(part.isdecimal() for part in ids):
            continue
        low, high = int(ids[0]), int(ids[1])
        if pet_id in (low, high):
            return high if pet_id == low else low
    return None


def roster_ids(ctx: Context, user_id: str | None = None) -> set[int]:
    return {pet.pet_id for pet in ctx.repo.active_pets(user_id or ctx.user_id)}


def deployed_together(ctx: Context, pet_id: int, user_id: str | None = None) -> bool:
    partner = partner_of(ctx, pet_id, user_id)
    if partner is None:
        return False
    roster = roster_ids(ctx, user_id)
    return pet_id in roster and partner in roster


def rate_of(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, float]:
    """Rates this pet gains from its bond, and only while the pair is deployed together."""
    if not deployed_together(ctx, pet_id, user_id):
        return {}
    return dict(rule(ctx).rates)


def rate_text(ctx: Context, rates: dict[str, float]) -> str:
    if not rates:
        return "无加成"
    return " · ".join(
        f"{STAT_NAMES[stat]} +{rate * 100:.0f}%" for stat, rate in rates.items()
    )


def cost_text(ctx: Context) -> str:
    items = "、".join(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in rule(ctx).items.items()
    )
    return f"灵石 {rule(ctx).stones}" + (f" · {items}" if items else "")


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _roster_pets(ctx: Context):
    return ctx.repo.active_pets(ctx.user_id)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠同心 [结契 <伙伴A> <伙伴B> | 解契 <伙伴>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠同心",
            (
                "尚未结契，先完成领养，才能与伙伴立下同心。",
                "同心只对同一出战阵容里的两位伙伴生效，且每位伙伴只能有一位同心。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    roster = _roster_pets(ctx)
    if not roster:
        return Reply("灵宠同心", ("出战阵容还没有伙伴。",), ("灵宠出战", "灵宠帮助"))
    lines = [
        f"同心加成只在两位伙伴同时出战时生效：{rate_text(ctx, rule(ctx).rates)}；"
        f"每位伙伴只能有一位同心，结契 {cost_text(ctx)}。"
    ]
    links = []
    for pet in roster:
        partner = partner_of(ctx, pet.pet_id)
        if partner is None:
            lines.append(f"{pet.name}（#{pet.pet_id}）· 未结契 · 亲密 {pet.affinity}")
            continue
        partner_pet = ctx.repo.pet(partner)
        together = "同时出战" if deployed_together(ctx, pet.pet_id) else "未同时出战"
        lines.append(
            f"{pet.name}（#{pet.pet_id}）· 同心 {partner_pet.name} · {together}"
            f" · {rate_text(ctx, rate_of(ctx, pet.pet_id))}"
        )
        links.append(InlineCommand(len(lines) - 1, "解契", f"灵宠同心 解契 {pet.name}"))
    free = [pet for pet in roster if partner_of(ctx, pet.pet_id) is None]
    for index, left in enumerate(free):
        for right in free[index + 1:]:
            lines.append(
                f"可结契：{left.name} × {right.name}"
                f"（亲密 {left.affinity}/{right.affinity}，需各 {rule(ctx).min_affinity}）"
            )
            links.append(InlineCommand(
                len(lines) - 1, "结契", f"灵宠同心 结契 {left.name} {right.name}",
            ))
    return Reply("灵宠同心", tuple(lines), ("灵宠同心", "我的灵宠", "灵宠属性"), tuple(links))


def _pet_named(ctx: Context, name: str):
    row = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND name=? AND archived=0 ORDER BY pet_id LIMIT 1",
        (ctx.user_id, name),
    ).fetchone()
    return row["pet_id"] if row else None


def bond(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠同心 结契 <伙伴A> <伙伴B>。")
    player = ctx.player()
    left_id, right_id = (_pet_named(ctx, parts[0]), _pet_named(ctx, parts[1]))
    if left_id is None or right_id is None:
        raise GameError("没有找到这只伙伴，请检查名字。")
    if left_id == right_id:
        raise GameError("同心需要两位不同的伙伴。")
    roster = roster_ids(ctx)
    if left_id not in roster or right_id not in roster:
        raise GameError("只有出战阵容里的伙伴才能结契，请先用 灵宠出战 安排。")
    for pet_id in (left_id, right_id):
        if partner_of(ctx, pet_id) is not None:
            raise GameError(f"{ctx.repo.pet(pet_id).name}已有同心，请先解契。")
    left, right = ctx.repo.pet(left_id), ctx.repo.pet(right_id)
    short = [
        f"{pet.name} 亲密 {pet.affinity}/{rule(ctx).min_affinity}"
        for pet in (left, right) if pet.affinity < rule(ctx).min_affinity
    ]
    if short:
        raise GameError(f"亲密不足：{'、'.join(short)}。")
    if player.stones < rule(ctx).stones:
        raise GameError(f"灵石不足：结契需要 {rule(ctx).stones}，当前 {player.stones}。")
    missing = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, item_id)}"
        for item_id, amount in rule(ctx).items.items()
        if _owned(ctx, item_id) < amount
    ]
    if missing:
        raise GameError(f"材料不足：结契还需{'、'.join(missing)}。")

    player.stones -= rule(ctx).stones
    for item_id, amount in rule(ctx).items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
        (ctx.user_id, _pair_key(left_id, right_id)),
    )
    ctx.repo.invalidate_ready(player.user_id)
    lines = [
        f"{left.name} 与 {right.name} 立下同心：{cost_text(ctx)}已扣除。",
        f"同时出战时双方 {rate_text(ctx, rule(ctx).rates)}。",
        "每位伙伴只能有一位同心；解契免费，但不退回材料。",
    ]
    return Reply("同心结契", tuple(lines), ("灵宠同心", "灵宠属性", "我的灵宠"))


def dissolve(ctx: Context, arg: str) -> Reply:
    name = arg.strip()
    if not name:
        raise GameError("格式：灵宠同心 解契 <伙伴>。")
    player = ctx.player()
    pet_id = _pet_named(ctx, name)
    if pet_id is None:
        raise GameError("没有找到这只伙伴，请检查名字。")
    partner = partner_of(ctx, pet_id)
    if partner is None:
        raise GameError(f"{name}尚未结契。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _pair_key(pet_id, partner)),
    )
    ctx.repo.invalidate_ready(player.user_id)
    return Reply(
        "同心已解",
        (
            f"{ctx.repo.pet(pet_id).name} 与 {ctx.repo.pet(partner).name} 的同心已解除。",
            "解契不消耗资源，也不退回当初的材料。",
        ),
        ("灵宠同心", "我的灵宠"),
    )


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "结契":
        return bond(ctx, " ".join(parts[1:]))
    if parts[0] == "解契":
        return dissolve(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠同心 [结契 <伙伴A> <伙伴B> | 解契 <伙伴>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "同心：尚未结契"
    roster = ctx.repo.active_pets(user_id)
    bonded = sum(1 for pet in roster if partner_of(ctx, pet.pet_id, user_id) is not None)
    active = sum(1 for pet in roster if deployed_together(ctx, pet.pet_id, user_id))
    if not bonded:
        return "同心：尚未结契"
    return f"同心：{bonded}/{len(roster)} 只已结契（{active} 只在阵中生效）"
