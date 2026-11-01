"""Pet dedication: retire a surplus pet for materials and a freed roster slot.

Pets only accumulate: duplicate summons have no outlet but 封存, and a sealed pet stays forever.
Dedicating one ends that: it leaves the roster permanently, pays materials scaled by its realm, and
frees a slot.

A real ``DELETE FROM pets`` is unsafe here — eight tables plus ``pvp_results`` and
``players.active_pet_id`` reference ``pets``, and battle history must stay readable — so dedication is
a soft retirement: ``archived=1`` plus a permanent ``released_<pet_id>`` marker. The pet keeps its
rows, cannot be restored, and no longer occupies the roster. Because the action is irreversible, a
bare ``灵宠归灵 <伙伴>`` only previews; ``确认 <伙伴>`` executes.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from .rewards import grant

KEY = "released_"


def rule(ctx: Context):
    return ctx.content.rules.pet_release


def released(ctx: Context, pet_id: int, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{KEY}{pet_id}"),
    ).fetchone()
    return row is not None


def reward_of(ctx: Context, pet) -> Reward:
    table = rule(ctx)
    stones = table.stones_base + table.stones_per_realm * pet.realm
    items = {item_id: Range(minimum=amount, maximum=amount) for item_id, amount in table.items.items()}
    egg = f"egg_{pet.species_id}"
    if egg in ctx.content.items:
        items[egg] = Range(minimum=1, maximum=1)
    return Reward(exp=Range(minimum=0, maximum=0), stones=Range(minimum=stones, maximum=stones), items=items)


def reward_text(ctx: Context, reward: Reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}"]
    parts.extend(f"{ctx.content.items[item_id].name} {amount.minimum}" for item_id, amount in reward.items.items())
    return " · ".join(parts)


def _roster_ids(ctx: Context) -> set[int]:
    return {pet.pet_id for pet in ctx.repo.active_pets(ctx.user_id)}


def blockers(ctx: Context, pet) -> list[str]:
    from .pair_bond import partner_of

    if released(ctx, pet.pet_id):
        return ["已归灵"]
    if pet.pet_id in _roster_ids(ctx):
        return ["仍在出战阵容"]
    if ctx.repo.active_expedition(pet.pet_id) is not None:
        return ["正在外出派遣"]
    if partner_of(ctx, pet.pet_id) is not None:
        return ["仍有同心，请先解契"]
    if pet.ascended:
        return ["已飞升，不可归灵"]
    return []


def candidates(ctx: Context):
    rows = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? ORDER BY archived, pet_id", (ctx.user_id,),
    ).fetchall()
    return [ctx.repo.pet(row["pet_id"]) for row in rows if not released(ctx, row["pet_id"])]


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠归灵 [<伙伴> | 确认 <伙伴>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠归灵",
            (
                "尚未结契，先完成领养，才能查看归灵。",
                "归灵会让伙伴永久离开名册，换取灵石、材料与该族灵卵。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pool = candidates(ctx)
    if not pool:
        return Reply("灵宠归灵", ("名册里没有可归灵的伙伴。",), ("灵宠列表", "灵宠帮助"))
    lines = ["归灵不可撤销：伙伴会永久离开名册并释放一个名额，战报与图鉴记录保留。"]
    links = []
    for pet in pool:
        reasons = blockers(ctx, pet)
        state = f"可归灵 · {reward_text(ctx, reward_of(ctx, pet))}" if not reasons else f"不可归灵（{reasons[0]}）"
        lines.append(f"{pet.name}（#{pet.pet_id}）· {state}")
        if not reasons:
            links.append(InlineCommand(len(lines) - 1, "归灵", f"灵宠归灵 {pet.pet_id}"))
    return Reply("灵宠归灵", tuple(lines), ("灵宠归灵", "灵宠列表", "灵宠封存库"), tuple(links))


def _find(ctx: Context, arg: str):
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠归灵 <伙伴>。")
    if text.isdecimal():
        row = ctx.repo.conn.execute(
            "SELECT pet_id FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, int(text)),
        ).fetchone()
        if row is not None:
            return ctx.repo.pet(row["pet_id"])
    row = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND name=? ORDER BY pet_id LIMIT 1", (ctx.user_id, text),
    ).fetchone()
    if row is None:
        raise GameError("没有找到这只伙伴。")
    return ctx.repo.pet(row["pet_id"])


def preview(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet = _find(ctx, arg)
    reasons = blockers(ctx, pet)
    if reasons:
        raise GameError(f"{pet.name}暂时不能归灵：{reasons[0]}。")
    reward = reward_of(ctx, pet)
    return Reply(
        "归灵预览",
        (
            f"确认后 {pet.name}（#{pet.pet_id}）将永久归灵，换取 {reward_text(ctx, reward)}。",
            "归灵不可撤销：伙伴离开名册并释放一个名额，战报与图鉴记录保留。",
            f"确认请发送：灵宠归灵 确认 {pet.pet_id}",
        ),
        ("灵宠归灵", "灵宠列表"),
        (InlineCommand(2, "确认归灵", f"灵宠归灵 确认 {pet.pet_id}"),),
    )


def confirm(ctx: Context, arg: str) -> Reply:
    ctx.player()
    pet = _find(ctx, arg)
    reasons = blockers(ctx, pet)
    if reasons:
        raise GameError(f"{pet.name}暂时不能归灵：{reasons[0]}。")
    if not [row for row in candidates(ctx) if row.pet_id != pet.pet_id]:
        raise GameError("至少需要保留一只伙伴，不能把最后一只归灵。")

    reward = reward_of(ctx, pet)
    name = pet.name
    pet.archived = True
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, f"{KEY}{pet.pet_id}"),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [f"{name}已归灵：{reward_text(ctx, reward)}。"]
    lines.extend(grant(ctx, reward))
    lines.append("伙伴已永久离开名册，名额已释放；战报与图鉴记录保留。")
    return Reply("归灵完成", tuple(lines), ("灵宠归灵", "灵宠列表", "灵宠召唤"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "确认":
        return confirm(ctx, " ".join(parts[1:]))
    return preview(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "归灵：尚未结契"
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id, f"{KEY}%"),
    ).fetchone()[0]
    return f"归灵：已归灵 {count} 只" if count else "归灵：名册仍可整理"
