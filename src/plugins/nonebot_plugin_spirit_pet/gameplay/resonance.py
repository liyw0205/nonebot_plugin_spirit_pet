from ..application.context import Context
from ..domain.models import GameError, Reply
from ..domain.resonance_content import Resonance
from ..utils.arguments import named, quantity

PAGE_SIZE = 5


def _owned_species(ctx: Context) -> set[str]:
    return {
        row["species_id"] for row in ctx.repo.conn.execute(
            "SELECT DISTINCT species_id FROM pets WHERE user_id=?", (ctx.user_id,),
        )
    }


def _state(resonance: Resonance, owned: set[str], active_id: str | None) -> str:
    if resonance.id == active_id:
        return "已启用"
    if set(resonance.required_species) <= owned:
        return "可启用"
    return "未集齐"


def _bonus_text(resonance: Resonance) -> str:
    labels = (("hp", "气血"), ("attack", "攻击"), ("defense", "防御"), ("speed", "速度"))
    return "、".join(
        f"{label} +{value:.0%}"
        for key, label in labels
        if (value := getattr(resonance.bonuses, key))
    )


def _cost_text(ctx: Context) -> str:
    cost = ctx.content.rules.resonance_cost
    items = [f"{ctx.content.items[key].name} {amount}" for key, amount in cost.items.items()]
    return "、".join((f"{cost.stones} 灵石", *items))


def _detail(ctx: Context, resonance: Resonance, owned: set[str], active_id: str | None) -> Reply:
    required = "、".join(ctx.content.species[key].name for key in resonance.required_species)
    state = _state(resonance, owned, active_id)
    missing = [ctx.content.species[key].name for key in resonance.required_species if key not in owned]
    player = ctx.player()
    active_pet = ctx.repo.pet(player.active_pet_id) if player.active_pet_id is not None else None
    applies = active_pet is not None and active_pet.species_id in resonance.required_species
    lines = [resonance.description, f"共鸣灵宠：{required}", f"战斗效果：{_bonus_text(resonance)}"]
    if state == "已启用":
        lines.append("状态：已启用" + ("，当前出战灵宠可受益。" if applies else "，切换为共鸣灵宠后生效。"))
        commands = ("灵宠共鸣 停用", "灵宠共鸣")
    elif missing:
        lines.append(f"状态：尚未集齐；还需{'、'.join(missing)}。")
        commands = ("灵宠列表", "灵宠图鉴", "灵宠共鸣")
    else:
        lines.append(f"状态：可启用 · 消耗 {_cost_text(ctx)}。")
        commands = (f"灵宠共鸣 激活 {resonance.name}", "灵宠共鸣")
    return Reply(f"灵宠共鸣 · {resonance.name}", tuple(lines), commands)


def _catalog(ctx: Context, page: int) -> Reply:
    entries = tuple(ctx.content.resonances.values())
    pages = (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE
    if page > pages:
        raise GameError(f"灵宠共鸣共 {pages} 页。")
    owned = _owned_species(ctx)
    active = ctx.repo.player_resonance(ctx.user_id)
    active_id = active["resonance_id"] if active else None
    selected = entries[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    lines = tuple(
        f"{resonance.name} · {_state(resonance, owned, active_id)} · "
        f"{'、'.join(ctx.content.species[key].name for key in resonance.required_species)} · "
        f"{_bonus_text(resonance)}"
        for resonance in selected
    )
    commands = [f"灵宠共鸣 查看 {resonance.name}" for resonance in selected]
    if page > 1:
        commands.append(f"灵宠共鸣 {page - 1}")
    if page < pages:
        commands.append(f"灵宠共鸣 {page + 1}")
    if active_id:
        commands.append("灵宠共鸣 停用")
    return Reply(f"灵宠共鸣 {page}/{pages}", lines, tuple(commands))


def _activate(ctx: Context, resonance: Resonance) -> Reply:
    player = ctx.player()
    selected = ctx.repo.player_resonance(ctx.user_id)
    if selected is not None and selected["resonance_id"] == resonance.id:
        return Reply("共鸣已启用", (f"当前共鸣：{resonance.name}；本次没有重复消耗。",))

    owned = _owned_species(ctx)
    missing = [ctx.content.species[key].name for key in resonance.required_species if key not in owned]
    if missing:
        raise GameError(f"尚未集齐共鸣灵宠：{'、'.join(missing)}。")
    cost = ctx.content.rules.resonance_cost
    if player.stones < cost.stones:
        raise GameError(f"启用共鸣需要 {cost.stones} 灵石。")
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    player.stones -= cost.stones
    ctx.repo.set_player_resonance(ctx.user_id, resonance.id, ctx.now)
    ctx.repo.invalidate_ready(ctx.user_id)

    current_pet = ctx.repo.pet(player.active_pet_id) if player.active_pet_id is not None else None
    applies = current_pet is not None and current_pet.species_id in resonance.required_species
    return Reply("灵契共鸣已启用", (
        f"{resonance.name}：{resonance.description}",
        f"当前战斗加成：{_bonus_text(resonance)}" + ("。" if applies else "；切换为共鸣灵宠后生效。"),
        f"消耗 {_cost_text(ctx)}；切换共鸣不会返还已消耗的材料。",
    ), ("灵宠共鸣", "我的灵宠", "灵宠列表"))


def _deactivate(ctx: Context) -> Reply:
    ctx.player()
    if ctx.repo.player_resonance(ctx.user_id) is None:
        raise GameError("当前没有启用灵宠共鸣。")
    ctx.repo.clear_player_resonance(ctx.user_id)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵契共鸣已停用", ("已取消当前共鸣，不返还启用时消耗的材料。",), ("灵宠共鸣", "我的灵宠"))


def resonance(ctx: Context, arg: str) -> Reply:
    ctx.player()
    parts = arg.split(maxsplit=1)
    if not parts:
        return _catalog(ctx, 1)
    if parts[0] == "停用" and len(parts) == 1:
        return _deactivate(ctx)
    if parts[0] in {"查看", "激活"} and len(parts) == 2:
        entry = named(ctx.content.resonances, parts[1])
        if parts[0] == "激活":
            return _activate(ctx, entry)
        selected = ctx.repo.player_resonance(ctx.user_id)
        active_id = selected["resonance_id"] if selected else None
        return _detail(ctx, entry, _owned_species(ctx), active_id)
    if len(parts) == 1 and parts[0].isdecimal():
        return _catalog(ctx, quantity(parts[0], 999))
    if len(parts) == 1:
        entry = named(ctx.content.resonances, parts[0])
        selected = ctx.repo.player_resonance(ctx.user_id)
        active_id = selected["resonance_id"] if selected else None
        return _detail(ctx, entry, _owned_species(ctx), active_id)
    raise GameError("格式：灵宠共鸣 [页码|查看 名称|激活 名称|停用]。")
