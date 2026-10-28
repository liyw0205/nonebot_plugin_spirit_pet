"""Spirit kitchen: cook meals from materials, raise 厨艺 and serve roster banquets.

State lives in the existing ``quest_progress`` table:

* ``cuisine_dish_<dish_id>`` — portions cooked (drives the 厨艺 level)
* ``cuisine_heat_<Beijing date>`` — heat spent today

Single meals become consumable items in the bag; banquets are served immediately to
every owned, non-archived pet that is not out on an expedition.
"""

from ..application.context import Context
from ..domain.cuisine_content import CuisineDish
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import beijing_day

DISH_PREFIX = "cuisine_dish_"
HEAT_PREFIX = "cuisine_heat_"


def dishes(ctx: Context) -> list[CuisineDish]:
    return sorted(ctx.content.cuisine.values(), key=lambda dish: (dish.level, dish.id))


def _cooked(ctx: Context, user_id: str | None = None) -> dict[str, int]:
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{DISH_PREFIX}%"),
    )
    return {
        row["quest_id"][len(DISH_PREFIX):]: int(row["progress"])
        for row in rows
        if row["quest_id"].startswith(DISH_PREFIX)
    }


def mastered(ctx: Context, user_id: str | None = None) -> int:
    return sum(1 for portions in _cooked(ctx, user_id).values() if portions > 0)


def level(ctx: Context, user_id: str | None = None) -> int:
    """1 + the number of different dishes cooked, capped by the content rule."""
    return min(ctx.content.rules.cuisine.max_level, 1 + mastered(ctx, user_id))


def _heat_used(ctx: Context, user_id: str | None = None) -> int:
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (owner, f"{HEAT_PREFIX}{beijing_day(ctx.now)}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def heat_left(ctx: Context, user_id: str | None = None) -> int:
    return max(0, ctx.content.rules.cuisine.daily_heat - _heat_used(ctx, user_id))


def _owned(ctx: Context, user_id: str, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _effects_text(effects) -> str:
    parts = []
    if effects.energy:
        parts.append(f"精力+{effects.energy}")
    if effects.exp:
        parts.append(f"修为+{effects.exp}")
    if effects.affinity:
        parts.append(f"亲密+{effects.affinity}")
    return " ".join(parts)


def _dish_effects(ctx: Context, dish: CuisineDish):
    if dish.item is not None:
        return ctx.content.items[dish.item].effects
    assert dish.effects is not None  # the model guarantees exactly one output
    return dish.effects


def _cost_text(ctx: Context, dish: CuisineDish) -> str:
    parts = [f"灵石 {dish.stones}"] if dish.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in dish.ingredients.items()
    )
    return "、".join(parts)


def _shortage(ctx: Context, dish: CuisineDish, count: int) -> str | None:
    if ctx.player().stones < dish.stones * count:
        return f"灵石不足：需要 {dish.stones * count}"
    for item_id, amount in dish.ingredients.items():
        need = amount * count
        owned = _owned(ctx, ctx.user_id, item_id)
        if owned < need:
            return f"{ctx.content.items[item_id].name}不足：需要 {need}，当前 {owned}"
    return None


def _state(ctx: Context, dish: CuisineDish, count: int = 1) -> str:
    if level(ctx) < dish.level:
        return f"未解锁（需厨艺 {dish.level} 级）"
    if heat_left(ctx) < dish.heat * count:
        return "灶火不足"
    if _shortage(ctx, dish, count):
        return "材料不足"
    return "可烹饪"


def page(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠膳房", (
            "以材料烹制灵膳：单膳收进乾坤袋，宴席当场宴请全部在册伙伴。",
            "尚未结契，先完成领养，再来掌勺。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))
    rules = ctx.content.rules.cuisine
    lines = [
        f"厨艺 {level(ctx)} 级 · 已掌握 {mastered(ctx)}/{len(ctx.content.cuisine)} 道"
        f" · 今日灶火 {heat_left(ctx)}/{rules.daily_heat}（北京时间 00:00 重置）。",
    ]
    links = []
    for dish in dishes(ctx):
        scope = "宴席（全体）" if dish.effects else "单膳"
        lines.append(
            f"{dish.name} · {dish.level} 级 · 灶火 {dish.heat} · {scope}"
            f" · {_cost_text(ctx, dish)} · {_effects_text(_dish_effects(ctx, dish))}"
            f" · {_state(ctx, dish)}"
        )
        if _state(ctx, dish) == "可烹饪":
            links.append(InlineCommand(len(lines) - 1, "烹饪", f"灵宠烹饪 {dish.name}"))
    lines.append("单膳进入乾坤袋，可用 灵宠使用 或 灵宠喂养 交给伙伴；宴席立即作用于全部在册伙伴。")
    return Reply(
        "灵宠膳房", tuple(lines),
        ("灵宠膳房", "灵宠背包", "灵宠目标", "我的灵宠"), tuple(links),
    )


def entry(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠膳房 不接受参数，直接发送即可。")
    return page(ctx)


def _eligible(ctx: Context) -> list:
    return [
        pet for pet in ctx.repo.owned_pets(ctx.user_id)
        if ctx.repo.active_expedition(pet.pet_id) is None
    ]


def cook(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    parts = arg.split()
    if not parts:
        raise GameError("格式：灵宠烹饪 <菜名> [份数]。")
    count = 1
    if parts[-1].isdecimal():
        count = quantity(parts[-1], 9)
        parts = parts[:-1]
    if not parts:
        raise GameError("格式：灵宠烹饪 <菜名> [份数]。")
    dish = named(ctx.content.cuisine, " ".join(parts))

    current = level(ctx)
    if current < dish.level:
        raise GameError(f"厨艺不足：{dish.name}需要厨艺 {dish.level} 级，当前 {current} 级。")
    heat_cost = dish.heat * count
    left = heat_left(ctx)
    if heat_cost > left:
        raise GameError(f"今日灶火不足：{dish.name} ×{count} 需要 {heat_cost} 点，今日只剩 {left} 点。")
    shortage = _shortage(ctx, dish, count)
    if shortage:
        raise GameError(shortage)

    diners = _eligible(ctx) if dish.effects is not None else []
    if dish.effects is not None and not diners:
        raise GameError("没有可宴请的伙伴：全部在册伙伴都在外出派遣。")

    stone_cost = dish.stones * count
    player.stones -= stone_cost
    for item_id, amount in dish.ingredients.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount * count)
    if dish.item is not None:
        ctx.repo.add_item(ctx.user_id, dish.item, count)
    else:
        from .economy import add_energy

        effects = _dish_effects(ctx, dish)
        for pet in diners:
            add_energy(pet, effects.energy, ctx.now)
            pet.exp += effects.exp
            pet.affinity = min(100, pet.affinity + effects.affinity)
        ctx.repo.invalidate_ready(ctx.user_id)

    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (ctx.user_id, f"{HEAT_PREFIX}{beijing_day(ctx.now)}", heat_cost),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (ctx.user_id, f"{DISH_PREFIX}{dish.id}", count),
    )

    after = level(ctx)
    if dish.item is not None:
        head = (
            f"{dish.name} ×{count} 已入乾坤袋：灵石 -{stone_cost}，"
            f"灶火 -{heat_cost}。"
        )
    else:
        head = (
            f"{dish.name}已开席：{len(diners)} 只伙伴 {_effects_text(_dish_effects(ctx, dish))}，"
            f"灵石 -{stone_cost}，灶火 -{heat_cost}。"
        )
    lines = [head]
    if after > current:
        lines.append(f"厨艺提升：{current} 级 → {after} 级。")
    lines.append(
        f"厨艺 {after} 级 · 已掌握 {mastered(ctx)}/{len(ctx.content.cuisine)} 道"
        f" · 今日灶火 {heat_left(ctx)}/{ctx.content.rules.cuisine.daily_heat}。"
    )
    return Reply("灵宠膳房", tuple(lines), ("灵宠膳房", "灵宠背包", "我的灵宠"))


def objective_line(ctx: Context, user_id: str) -> str:
    left = heat_left(ctx, user_id)
    total = ctx.content.rules.cuisine.daily_heat
    return (
        f"灵膳：灶火 {left}/{total} · 已掌握 {mastered(ctx, user_id)}/{len(ctx.content.cuisine)} 道"
        f" · 厨艺 {level(ctx, user_id)} 级"
    )
