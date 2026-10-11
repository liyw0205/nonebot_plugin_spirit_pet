from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.lineage_content import StatMultipliers
from ..domain.models import GameError, Reply
from ..utils.arguments import named

if TYPE_CHECKING:
    from ..application.context import Context
    from ..content.catalog import Catalog
    from ..domain.state import Pet


def stat_multipliers(pet: Pet, content: Catalog) -> StatMultipliers:
    if pet.lineage_id is None:
        return StatMultipliers()
    lineage = content.lineages.get(pet.lineage_id)
    if lineage is None or lineage.species_id != pet.species_id or pet.bloodline < lineage.min_bloodline:
        raise GameError("灵宠血脉分支数据无效，请联系管理员检查数据目录。")
    return lineage.stat_multipliers


def describe_multipliers(multipliers: StatMultipliers) -> str:
    return "、".join(
        f"{name} x{getattr(multipliers, field):g}"
        for field, name in (("hp", "气血"), ("attack", "攻击"), ("defense", "防御"), ("speed", "速度"))
    )


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    active = ctx.repo.pet(player.active_pet_id) if player and player.active_pet_id is not None else None
    if arg:
        species = named(ctx.content.species, arg)
    else:
        active = ctx.pet()
        species = ctx.content.species[active.species_id]
    matching = active if active and active.species_id == species.id else None
    current = matching.lineage_id if matching else None
    choices = [branch for branch in ctx.content.lineages.values() if branch.species_id == species.id]
    lines = []
    for branch in choices:
        cost = branch.cost
        materials = "、".join(f"{ctx.content.items[key].name} x{amount}" for key, amount in cost.items.items())
        selected = "（已选）" if branch.id == current else ""
        lines.extend((
            f"{branch.name}{selected}：{branch.description}",
            f"基础成长：{describe_multipliers(branch.stat_multipliers)}。",
            f"需{ctx.content.bloodlines[branch.min_bloodline].name}，"
            f"消耗 {cost.exp} 修为、{cost.stones} 灵石" + (f"、{materials}" if materials else "") + "。",
        ))
    lines.append("分支仅影响基础四维，不改变种族、元素、神通和已有装备技能；选定后不可更换。")
    commands = ()
    if matching and player and current is None:
        inventory = ctx.repo.inventory(ctx.user_id)
        commands = tuple(
            f"灵宠分支 {branch.name}" for branch in choices
            if matching.bloodline >= branch.min_bloodline
            and matching.exp >= branch.cost.exp and player.stones >= branch.cost.stones
            and all(inventory.get(key, 0) >= amount for key, amount in branch.cost.items.items())
        )
    if not commands:
        commands = (f"灵宠图鉴 {species.name}",) + (("我的灵宠",) if active else ())
    return Reply(f"{species.name}血脉分支", tuple(lines), commands)


def choose(ctx: Context, arg: str) -> Reply:
    if not arg:
        raise GameError("请指定血脉分支名称，可先查看“灵宠血脉”。")
    player, pet = ctx.player(), ctx.pet()
    ctx.require_idle_pet(pet)
    if pet.lineage_id is not None:
        raise GameError("这只灵宠已选择血脉分支，不能重复选择或更换。")
    branch = named(ctx.content.lineages, arg)
    if branch.species_id != pet.species_id:
        raise GameError("该分支不属于当前灵宠的种族。")
    if pet.bloodline < branch.min_bloodline:
        stage = ctx.content.bloodlines[branch.min_bloodline].name
        raise GameError(f"需先将当前灵宠进化至{stage}，才能选择此血脉分支。")
    cost = branch.cost
    if pet.exp < cost.exp or player.stones < cost.stones:
        raise GameError(f"选择此分支需要 {cost.exp} 修为和 {cost.stones} 灵石。")
    for item_id, amount in cost.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    pet.exp -= cost.exp
    player.stones -= cost.stones
    pet.lineage_id = branch.id
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("血脉分支觉醒", (
        f"{pet.name}觉醒{branch.name}，原有种族、元素、神通、装备和技能不变。",
        f"基础成长：{describe_multipliers(branch.stat_multipliers)}。",
        f"修为 -{cost.exp}，灵石 -{cost.stones}，分支材料已消耗。",
    ), ("我的灵宠", "灵宠血脉"))
