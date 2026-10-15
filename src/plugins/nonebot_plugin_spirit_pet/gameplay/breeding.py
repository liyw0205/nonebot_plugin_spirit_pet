from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from .pet_targets import pet_id

PAIR_PAGE_SIZE = 4


def _available_energy(ctx: Context, pet) -> int:
    restored = max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval
    return min(100, pet.energy + restored)


def _pair_blocker(ctx: Context, player, first, second) -> str:
    for pet in (first, second):
        expedition = ctx.repo.active_expedition(pet.pet_id)
        if expedition is not None:
            state = "外出中，先完成行程" if ctx.now < expedition["finishes_at"] else "行程已完成，先领取奖励"
            return f"{pet.name}{state}"
    rule = ctx.content.rules.breeding
    if first.affinity < rule.affinity or second.affinity < rule.affinity:
        return f"亲密不足（{first.affinity}/{second.affinity}），需双方满 {rule.affinity}"
    if _available_energy(ctx, first) < rule.energy or _available_energy(ctx, second) < rule.energy:
        return f"精力不足，需双方各 {rule.energy} 点"
    if player.stones < rule.cost.stones:
        return f"灵石不足，需 {rule.cost.stones} 灵石"
    return ""


def _best_pair(ctx: Context, player, members: list) -> tuple:
    for index, first in enumerate(members):
        for second in members[index + 1:]:
            if not _pair_blocker(ctx, player, first, second):
                return first, second
    return members[0], members[1]


def _candidate_pairs(ctx: Context, player) -> list[tuple]:
    groups: dict[str, list] = {}
    for pet in ctx.repo.owned_pets(ctx.user_id):
        groups.setdefault(pet.species_id, []).append(pet)
    return [
        (*_best_pair(ctx, player, members), len(members))
        for members in groups.values()
        if len(members) >= 2
    ]


def breeding(ctx: Context, arg: str) -> Reply:
    """Read-only pair list without arguments; breed the named pair with two ids."""
    return catalog(ctx, arg) if not arg.strip() else breed(ctx, arg)


def catalog(ctx: Context, arg: str) -> Reply:
    rule = ctx.content.rules.breeding
    lines = [
        f"同族双灵，共育新契：双方须同族、亲密满 {rule.affinity}、各有 {rule.energy} 精力，另耗 {rule.cost.stones} 灵石。",
        "所得为该族灵卵，用 灵宠使用 <灵卵> 孵化，名册有空位时即可迎接新伙伴。",
    ]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再与伙伴同修此道。")
        return Reply("灵宠培育", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    pairs = _candidate_pairs(ctx, player)
    if not pairs:
        lines.append("名册里还没有同族伙伴，先寻访第二只同族灵宠。")
        return Reply("灵宠培育", tuple(lines), ("灵宠召唤 ", "灵宠图鉴", "灵宠列表"), (
            InlineCommand(len(lines) - 1, "了解获取途径", "灵宠图鉴"),
        ))

    page = paginate(pairs, arg, "灵宠培育", "灵宠培育", page_size=PAIR_PAGE_SIZE)
    links = []
    for first, second, count in page.entries:
        species = ctx.content.species[first.species_id]
        blocker = _pair_blocker(ctx, player, first, second)
        extra = f" · 本族共 {count} 只" if count > 2 else ""
        lines.append(
            f"{species.name}：编号 {first.pet_id} + {second.pet_id} · 亲密 {first.affinity}/{second.affinity}"
            f" · 可用精力 {_available_energy(ctx, first)}/{_available_energy(ctx, second)}{extra} · {blocker or '可培育'}"
        )
        if not blocker:
            links.append(InlineCommand(
                len(lines) - 1, "培育这一对", f"灵宠培育 {first.pet_id} {second.pet_id}",
            ))
    return Reply(
        f"灵宠培育 {page.number}/{page.total}", tuple(lines),
        (*page.navigation, "灵宠列表"), tuple(links),
    )


def _pair_arguments(arg: str) -> tuple[int, int]:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠培育 编号A 编号B，例如 灵宠培育 3 7。")
    return pet_id(parts[0]), pet_id(parts[1])


def breed(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    first_id, second_id = _pair_arguments(arg)
    if first_id == second_id:
        raise GameError("培育需要两只不同的同族灵宠。")
    owned = {pet.pet_id: pet for pet in ctx.repo.owned_pets(ctx.user_id)}
    for value in (first_id, second_id):
        if value in owned:
            continue
        archived = ctx.repo.conn.execute(
            "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1",
            (ctx.user_id, value),
        ).fetchone()
        if archived is not None:
            raise GameError(f"{archived['name']}已封存，请先复原后再培育。")
        raise GameError("没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
    first, second = owned[first_id], owned[second_id]
    if first.species_id != second.species_id:
        raise GameError("培育双方必须是同一种族。")

    rule = ctx.content.rules.breeding
    for pet in (first, second):
        ctx.require_idle_pet(pet)
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    if first.affinity < rule.affinity or second.affinity < rule.affinity:
        raise GameError(
            f"培育需要双方亲密达到 {rule.affinity}，当前 {first.name} {first.affinity}、"
            f"{second.name} {second.affinity}。"
        )
    if first.energy < rule.energy or second.energy < rule.energy:
        raise GameError(
            f"培育需要双方各有 {rule.energy} 精力，当前 {first.name} {first.energy}、"
            f"{second.name} {second.energy}。"
        )
    if player.stones < rule.cost.stones:
        raise GameError(f"培育需要 {rule.cost.stones} 灵石。")

    egg = ctx.content.items[f"egg_{first.species_id}"]
    player.stones -= rule.cost.stones
    first.energy -= rule.energy
    second.energy -= rule.energy
    ctx.repo.add_item(ctx.user_id, egg.id, 1)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("灵宠培育成功", (
        f"{first.name}（编号 {first.pet_id}）与 {second.name}（编号 {second.pet_id}）同族相契。",
        f"灵石 -{rule.cost.stones}，双方各消耗 {rule.energy} 精力。",
        f"获得{egg.name} ×1。",
    ), ("灵宠培育", "灵宠背包", "灵宠列表"), (
        InlineCommand(2, "孵化灵卵", f"灵宠使用 {egg.name}"),
    ))
