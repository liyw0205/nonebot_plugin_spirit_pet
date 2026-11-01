"""Battle formation: give each lineup slot a shape instead of another flat bonus.

Every other modifier in the game is a pure gain — sigils, tempering, gear, words, sets, resonance,
sect passives and support only ever add. A formation is the first layer that takes something away:
the vanguard soaks and hits softer, the centre trades health for bite, the rear hits hardest and
folds fastest. Rates multiply **base** stats only, in the same place as mood and before every flat
bonus, so gear, words, sets, sigils and bond keep their documented integers.

State is one ``quest_progress`` row per pet, ``formation_<pet_id>_<position>``; a pet without a row is
unassigned and behaves exactly as before, which keeps every existing baseline intact.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .loadout import combatant

KEY = "formation_"
STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def positions(ctx: Context):
    return ctx.content.formations.positions


def position_of(ctx: Context, pet_id: int) -> str | None:
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ? ORDER BY quest_id LIMIT 1",
        (ctx.user_id, f"{KEY}{pet_id}_%"),
    ).fetchone()
    return row["quest_id"][len(f"{KEY}{pet_id}_"):] if row else None


def rates_of(ctx: Context, pet_id: int) -> dict[str, float]:
    """The multipliers this pet's position applies to its base stats."""
    position = position_of(ctx, pet_id)
    if position is None:
        return {}
    definition = ctx.content.formations.by_id.get(position)
    return dict(definition.rates) if definition else {}


def rate_text(ctx: Context, rates: dict[str, float]) -> str:
    if not rates:
        return "未布阵（暂无增减）"
    return " · ".join(
        f"{STAT_NAMES[stat]} {'+' if rate >= 1 else '−'}{abs(rate - 1) * 100:.0f}%"
        for stat, rate in rates.items()
        if rate != 1
    )


def _roster(ctx: Context):
    return ctx.repo.active_pets(ctx.user_id)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠阵位 [<宠物编号> <位置>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠阵位",
            (
                "尚未结契，先完成领养，才能布置阵位。",
                "前锋扛打但出手钝，后援出手重但更脆；阵位只放大或削弱基础四维。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    roster = _roster(ctx)
    if not roster:
        return Reply("灵宠阵位", ("出战阵容还没有伙伴。",), ("灵宠出战", "灵宠帮助"))
    lines = ["阵位只作用于基础四维，装备、词条、套装与符印的固定加成不受影响。"]
    links = []
    for pet in roster:
        current = position_of(ctx, pet.pet_id)
        label = ctx.content.formations.by_id[current].name if current else "未布阵"
        lines.append(
            f"{pet.name}（#{pet.pet_id}）· {label} · {rate_text(ctx, rates_of(ctx, pet.pet_id))}"
        )
        for position in positions(ctx):
            if position.id == current:
                continue
            lines.append(f"   {position.name}：{rate_text(ctx, position.rates)}")
            links.append(InlineCommand(
                len(lines) - 1, "布阵", f"灵宠阵位 {pet.pet_id} {position.name}",
            ))
    lines.append("同一位置可以有多只伙伴；换位只影响该伙伴自己。")
    return Reply("灵宠阵位", tuple(lines), ("灵宠阵位", "我的灵宠", "灵宠属性"), tuple(links))


def assign(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2 or not parts[0].isdecimal():
        raise GameError("格式：灵宠阵位 <宠物编号> <位置>。")
    player = ctx.player()
    pet_id = int(parts[0])
    row = ctx.repo.conn.execute(
        "SELECT pet_id, name, archived FROM pets WHERE user_id=? AND pet_id=?",
        (ctx.user_id, pet_id),
    ).fetchone()
    if row is None:
        raise GameError("没有找到这只伙伴。")
    if row["archived"]:
        raise GameError("封存的伙伴不能布阵。")
    roster = {pet.pet_id for pet in _roster(ctx)}
    if pet_id not in roster:
        raise GameError("只有出战阵容里的伙伴才能布阵，请先用 灵宠出战 安排。")
    position = next(
        (entry for entry in positions(ctx) if parts[1] in {entry.id, entry.name}), None,
    )
    if position is None:
        raise GameError("没有这个阵位，可选 前锋、中军、后援。")
    if position_of(ctx, pet_id) == position.id:
        raise GameError(f"{row['name']}已经在{position.name}，无需重复布阵。")

    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?", (ctx.user_id, f"{KEY}{pet_id}_%"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
        (ctx.user_id, f"{KEY}{pet_id}_{position.id}"),
    )
    ctx.repo.invalidate_ready(player.user_id)

    lines = [
        f"{row['name']}移至{position.name}：{rate_text(ctx, position.rates)}。",
        f"{position.description}",
        "只影响基础四维，装备、词条、套装、符印与羁绊的固定加成保持原值。",
    ]
    return Reply("布阵完成", tuple(lines), ("灵宠阵位", "灵宠属性", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else assign(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "阵位：尚未结契"
    roster = ctx.repo.active_pets(user_id)
    assigned = 0
    for pet in roster:
        row = ctx.repo.conn.execute(
            "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id LIKE ? LIMIT 1",
            (user_id, f"{KEY}{pet.pet_id}_%"),
        ).fetchone()
        if row:
            assigned += 1
    return f"阵位：已布阵 {assigned}/{len(roster)}" if assigned else "阵位：出战阵容尚未布阵"
