"""Pet attunement: trade materials to change a pet's native element.

Element is the only build axis that was immutable: it decides which skills and gear a pet may use
(``compatibility.check_requirements``) and how damage scales (``combat.effectiveness``). Attuning a
pet to another base element replaces its element set with that single element, so the player trades
away every element-gated skill and piece of gear it can no longer meet — which is why an attunement
is refused outright while incompatible gear is still worn, and why incompatible skills are unequipped
automatically and reported.

State lives in ``quest_progress``: ``attune_<pet_id>_<element>`` is the current override (the element
id sits in the key because ``progress`` is an integer column) and ``attune_week_<week>_<pet_id>``
enforces the weekly limit.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.elements import expand_elements
from ..utils.time import beijing_week
from .skills import learned

KEY = "attune_"


def table(ctx: Context):
    return ctx.content.attunements


def weekly_limit(ctx: Context) -> int:
    return ctx.content.rules.attunement.weekly_limit


def current(ctx: Context, pet_id: int, user_id: str | None = None) -> str | None:
    """The element a pet was attuned to, if any."""
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ? ORDER BY quest_id LIMIT 1",
        (owner, f"{KEY}{pet_id}_%"),
    ).fetchone()
    return row["quest_id"][len(f"{KEY}{pet_id}_"):] if row else None


def elements_of(ctx: Context, pet) -> tuple[str, ...]:
    """The pet's effective element set: its attunement, or the species default."""
    override = current(ctx, pet.pet_id, pet.user_id)
    return (override,) if override else tuple(ctx.content.species[pet.species_id].elements)


def primary_of(ctx: Context, pet) -> str:
    return current(ctx, pet.pet_id, pet.user_id) or ctx.content.species[pet.species_id].primary_element


def _element_names(ctx: Context, elements) -> str:
    return "、".join(ctx.content.elements[key].name for key in elements)


def _weekly_used(ctx: Context, pet_id: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{KEY}week_{beijing_week(ctx.now)[0]}_{pet_id}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _roster(ctx: Context):
    return ctx.repo.conn.execute(
        "SELECT pet_id, species_id, name, realm FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id",
        (ctx.user_id,),
    ).fetchall()


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def cost_text(ctx: Context, option) -> str:
    items = "、".join(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in option.items.items()
    )
    return f"灵石 {option.stones}" + (f" · {items}" if items else "")


def _compatible(ctx: Context, pet, requirement, elements) -> bool:
    species = ctx.content.species[pet.species_id]
    if requirement.categories and species.category not in requirement.categories:
        return False
    return set(requirement.elements).issubset(expand_elements(elements, ctx.content.elements))


def _blocking_gear(ctx: Context, pet, elements) -> list[str]:
    from .equipment import loadout

    blocked = []
    for item_id, _ in loadout(ctx, pet.pet_id).values():
        item = ctx.content.items[item_id]
        gear = ctx.content.equipment[item.equipment_id]
        if not _compatible(ctx, pet, gear.requirements, elements):
            blocked.append(gear.name)
    return blocked


def _orphaned_skills(ctx: Context, pet, elements) -> list[str]:
    return [
        skill_id
        for skill_id, active in learned(ctx, pet.pet_id).items()
        if active and not _compatible(ctx, pet, ctx.content.skills[skill_id].requirements, elements)
    ]


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠易脉 [<宠物编号> <元素>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠易脉",
            (
                "尚未结契，先完成领养，才能查看易脉。",
                "易脉会改写伙伴的本命元素，进而改变它可用的灵术、装备与克制关系。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    roster = [ctx.repo.pet(row["pet_id"]) for row in _roster(ctx)]
    if not roster:
        return Reply("灵宠易脉", ("名册里还没有伙伴。",), ("灵宠领养", "灵宠帮助"))
    lines = [
        f"易脉消耗材料改写本命元素；每只伙伴每周 {weekly_limit(ctx)} 次，"
        "改属后不兼容的灵术会自动卸下，仍穿着的装备不兼容时整次拒绝。"
    ]
    links = []
    for pet in roster:
        elements = elements_of(ctx, pet)
        override = current(ctx, pet.pet_id, pet.user_id)
        state = f"已易脉为{ctx.content.elements[override].name}" if override else "本命未改"
        lines.append(
            f"{pet.name}（#{pet.pet_id}）· 当前 {'、'.join(_element_names(ctx, elements))} · {state}"
            f" · 本周已用 {_weekly_used(ctx, pet.pet_id)}/{weekly_limit(ctx)}"
        )
        for option in table(ctx).options:
            if option.element in elements:
                continue
            blocked = _blocking_gear(ctx, pet, (option.element,))
            note = f" · 需先卸下 {'、'.join(blocked)}" if blocked else ""
            lines.append(f"   {ctx.content.elements[option.element].name}：{cost_text(ctx, option)}{note}")
            if not blocked:
                links.append(InlineCommand(
                    len(lines) - 1, "易脉", f"灵宠易脉 {pet.pet_id} {ctx.content.elements[option.element].name}",
                ))
    return Reply("灵宠易脉", tuple(lines), ("灵宠易脉", "我的灵宠", "灵宠技能", "灵宠目标"), tuple(links))


def attune(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠易脉 <宠物编号> <元素>。")
    player = ctx.player()
    pet_id, element_name = parts
    if not pet_id.isdecimal():
        raise GameError("格式：灵宠易脉 <宠物编号> <元素>。")
    row = ctx.repo.conn.execute(
        "SELECT pet_id, species_id, name, realm, archived FROM pets WHERE user_id=? AND pet_id=?",
        (ctx.user_id, int(pet_id)),
    ).fetchone()
    if row is None:
        raise GameError("没有找到这只伙伴。")
    if row["archived"]:
        raise GameError("封存的伙伴不能易脉。")
    pet = ctx.repo.pet(row["pet_id"])
    ctx.require_idle_pet(pet)
    option = next(
        (row for row in table(ctx).options if element_name in {row.element, ctx.content.elements[row.element].name}),
        None,
    )
    if option is None:
        raise GameError("未找到该元素，请检查名称。")
    if _weekly_used(ctx, pet.pet_id) >= weekly_limit(ctx):
        raise GameError(f"{pet.name}本周已易脉 {weekly_limit(ctx)} 次，下周再试。")
    if option.element in elements_of(ctx, pet):
        raise GameError(f"{pet.name}已经是{ctx.content.elements[option.element].name}属性。")
    blocked = _blocking_gear(ctx, pet, (option.element,))
    if blocked:
        raise GameError(f"需先卸下不兼容的装备：{'、'.join(blocked)}。")
    if player.stones < option.stones:
        raise GameError(f"灵石不足：易脉需要 {option.stones}，当前 {player.stones}。")
    short = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, item_id)}"
        for item_id, amount in option.items.items()
        if _owned(ctx, item_id) < amount
    ]
    if short:
        raise GameError(f"材料不足：易脉还需{'、'.join(short)}。")

    player.stones -= option.stones
    for item_id, amount in option.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{KEY}{pet.pet_id}_%"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
        (ctx.user_id, f"{KEY}{pet.pet_id}_{option.element}"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
        (ctx.user_id, f"{KEY}week_{beijing_week(ctx.now)[0]}_{pet.pet_id}"),
    )
    dropped = _orphaned_skills(ctx, pet, (option.element,))
    for skill_id in dropped:
        ctx.repo.conn.execute(
            "UPDATE learned_skills SET equipped=0 WHERE pet_id=? AND skill_id=?", (pet.pet_id, skill_id),
        )
    ctx.repo.invalidate_ready(ctx.user_id)

    lines = [
        f"{pet.name}本命改为{ctx.content.elements[option.element].name}：{cost_text(ctx, option)}已扣除。",
        f"当前元素：{_element_names(ctx, (option.element,))}；克制与灵术/装备兼容随之改变。",
    ]
    if dropped:
        names = "、".join(ctx.content.skills[skill_id].name for skill_id in dropped)
        lines.append(f"以下灵术已不兼容，自动卸下：{names}。")
    lines.append(f"本周该伙伴已易脉 {_weekly_used(ctx, pet.pet_id)}/{weekly_limit(ctx)} 次。")
    return Reply("易脉完成", tuple(lines), ("灵宠易脉", "灵宠技能", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else attune(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "易脉：尚未结契"
    overrides = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND quest_id LIKE ? AND quest_id NOT LIKE ?",
        (user_id, f"{KEY}%", f"{KEY}week_%"),
    ).fetchone()[0]
    return f"易脉：{overrides} 只伙伴已改属" if overrides else "易脉：本命元素均未改"
