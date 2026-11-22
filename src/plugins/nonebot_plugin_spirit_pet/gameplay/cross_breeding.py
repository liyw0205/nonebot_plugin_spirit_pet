"""Fixed, evidence-backed recipes for cross-species pedigree eggs."""

import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import beijing_week
from .pet_targets import pet_id

TITLE = "灵宠异族共育"
PAIR_PAGE_SIZE = 4


def read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or len(parts) == 1 or (
        len(parts) == 2 and (parts[0] == "记录" or parts[1].isdecimal())
    )


def _energy(ctx: Context, pet) -> int:
    restored = max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval
    return min(100, pet.energy + restored)


def _realm_index(ctx: Context, realm_id: str) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == realm_id)


def _fostered(ctx: Context, pet_id_value: int) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, f"foster_{pet_id_value}"),
    ).fetchone() is not None


def _pair_blocker(ctx: Context, player, recipe, first, second) -> str:
    expected = {recipe.parent_a_species, recipe.parent_b_species}
    if {first.species_id, second.species_id} != expected:
        return "亲本种族与配方不符"
    for pet in (first, second):
        if pet.archived:
            return f"{pet.name}已封存，先复原再共育"
        if _fostered(ctx, pet.pet_id):
            return f"{pet.name}正在寄养，先归还再共育"
        expedition = ctx.repo.active_expedition(pet.pet_id)
        if expedition is not None:
            state = "外出中，先完成行程" if ctx.now < expedition["finishes_at"] else "行程已完成，先领取奖励"
            return f"{pet.name}{state}"
        if pet.affinity < recipe.minimum_affinity:
            return f"亲密不足，双方需达到 {recipe.minimum_affinity}"
        if pet.realm < _realm_index(ctx, recipe.minimum_realm):
            realm = ctx.content.realms[_realm_index(ctx, recipe.minimum_realm)].name
            return f"境界不足，双方至少达到{realm}"
        if _energy(ctx, pet) < recipe.energy:
            return f"精力不足，双方各需 {recipe.energy} 点"
    if player.stones < recipe.stones:
        return f"灵石不足，需 {recipe.stones}"
    inventory = ctx.repo.inventory(ctx.user_id)
    missing = [ctx.content.items[item_id].name for item_id, amount in recipe.items.items()
               if inventory.get(item_id, 0) < amount]
    if missing:
        return "材料不足：" + "、".join(missing)
    return ""


def _pair_used(ctx: Context, first, second) -> bool:
    pair_key = f"cross_breeding_pair_{min(first.pet_id, second.pet_id)}_{max(first.pet_id, second.pet_id)}"
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, pair_key),
    ).fetchone() is not None


def _owned_pairs(ctx: Context, recipe) -> list[tuple]:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return []
    pets = ctx.repo.owned_pets(ctx.user_id)
    first_species = [pet for pet in pets if pet.species_id == recipe.parent_a_species]
    second_species = [pet for pet in pets if pet.species_id == recipe.parent_b_species]
    pairs = []
    for first in first_species:
        for second in second_species:
            if first.pet_id < second.pet_id:
                pairs.append((first, second))
            else:
                pairs.append((second, first))
    return sorted(pairs, key=lambda pair: (pair[0].pet_id, pair[1].pet_id))


def _cost_text(ctx: Context, recipe) -> str:
    materials = "、".join(
        f"{ctx.content.items[item_id].name} ×{amount}"
        for item_id, amount in recipe.items.items()
    )
    realm = ctx.content.realms[_realm_index(ctx, recipe.minimum_realm)].name
    return (
        f"亲密 ≥{recipe.minimum_affinity} · 境界 ≥{realm} · 双方各耗精力 {recipe.energy} · "
        f"灵石 {recipe.stones} · {materials}"
    )


def _catalog(ctx: Context, argument: str = "1") -> Reply:
    recipes = list(ctx.content.cross_breeding.values())
    page = paginate(recipes, argument, TITLE, TITLE, page_size=4)
    player = ctx.repo.player(ctx.user_id)
    lines = ["固定配方按指定异种亲本产出既有种族灵卵；查看与预览不占每周名额。"]
    links = []
    for recipe in page.entries:
        parents = f"{ctx.content.species[recipe.parent_a_species].name} + {ctx.content.species[recipe.parent_b_species].name}"
        egg = ctx.content.items[f"egg_{recipe.offspring_species}"]
        pairs = _owned_pairs(ctx, recipe) if player else []
        ready = sum(not _pair_blocker(ctx, player, recipe, *pair) for pair in pairs) if player else 0
        lines.append(f"{recipe.id} · {parents} → {egg.name} · 合格组合 {ready}/{len(pairs)}。")
        lines.append(_cost_text(ctx, recipe))
        links.append(InlineCommand(len(lines) - 2, "选择亲本", f"{TITLE} {recipe.id}"))
    if player is None:
        lines.append("尚未结契；完成领养后可查看本人亲本组合。")
        return Reply(TITLE, tuple(lines), ("灵宠领养", "灵宠帮助"), tuple(links))
    lines.append("每人每个北京时间自然周成功一次；同一对亲本一生只能成功一次。")
    return Reply(f"{TITLE} {page.number}/{page.total}", tuple(lines),
                 (*page.navigation, f"{TITLE} 记录"), tuple(links))


def _recipe_page(ctx: Context, recipe, argument: str = "1") -> Reply:
    player = ctx.repo.player(ctx.user_id)
    egg = ctx.content.items[f"egg_{recipe.offspring_species}"]
    title = f"{TITLE} · {recipe.id}"
    lines = [recipe.text, f"产物固定为{egg.name} ×1。", _cost_text(ctx, recipe)]
    if player is None:
        lines.append("尚未结契，完成领养后再选择本人亲本。")
        return Reply(title, tuple(lines), ("灵宠领养", "灵宠帮助"))
    pairs = _owned_pairs(ctx, recipe)
    if not pairs:
        lines.append("名册中尚无这条配方所需的两种族亲本。")
        return Reply(title, tuple(lines), ("灵宠列表", f"{TITLE}"))
    week, _ = beijing_week(ctx.now)
    weekly = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, f"cross_breeding_week_{week}"),
    ).fetchone()
    page = paginate(pairs, argument, title, f"{TITLE} {recipe.id}", page_size=PAIR_PAGE_SIZE)
    links = []
    for first, second in page.entries:
        blocker = _pair_blocker(ctx, player, recipe, first, second)
        if _pair_used(ctx, first, second):
            blocker = "这对亲本已留下永久共育凭证"
        elif weekly:
            blocker = "本周异族共育名额已用"
        lines.append(
            f"#{first.pet_id} {first.name}（{ctx.content.species[first.species_id].name}，"
            f"亲密 {first.affinity}，精力 {_energy(ctx, first)}） + "
            f"#{second.pet_id} {second.name}（{ctx.content.species[second.species_id].name}，"
            f"亲密 {second.affinity}，精力 {_energy(ctx, second)}） · {blocker or '可共育'}。"
        )
        if not blocker:
            links.append(InlineCommand(
                len(lines) - 1, "按此配方共育", f"{TITLE} {recipe.id} {first.pet_id} {second.pet_id}",
            ))
    if weekly:
        lines.append("本周已成功共育；下周名额开放时可再次操作其他亲本。")
    return Reply(f"{title} {page.number}/{page.total}", tuple(lines),
                 (*page.navigation, f"{TITLE}", "灵宠列表"), tuple(links))


def _history(ctx: Context, argument: str = "1") -> Reply:
    rows = ctx.repo.conn.execute(
        "SELECT operation_id,created_at,snapshot FROM pet_pedigree_operations "
        "WHERE user_id=? AND kind='breed' ORDER BY created_at DESC,operation_id DESC",
        (ctx.user_id,),
    ).fetchall()
    records = []
    for row in rows:
        snapshot = json.loads(row["snapshot"])
        if snapshot.get("cross_breeding"):
            records.append((row, snapshot))
    page = paginate(records, argument, f"{TITLE}记录", f"{TITLE} 记录", page_size=6)
    lines = []
    for row, snapshot in page.entries:
        egg = ctx.repo.conn.execute(
            "SELECT status,child_pet_id,child_name FROM pet_lineage_eggs WHERE operation_id=?",
            (row["operation_id"],),
        ).fetchone()
        state = "已孵化" if egg and egg["status"] == "hatched" else (
            "已消耗" if egg and egg["status"] == "consumed" else "灵卵待用"
        )
        child = f" · 后代 {egg['child_name']}（#{egg['child_pet_id']}）" if egg and egg["child_pet_id"] else ""
        lines.append(
            f"{snapshot['recipe_id']} · {snapshot['parent_a_name']}（#{snapshot['parent_a_id']}，"
            f"{ctx.content.species[snapshot['parent_a_species']].name}） + "
            f"{snapshot['parent_b_name']}（#{snapshot['parent_b_id']}，"
            f"{ctx.content.species[snapshot['parent_b_species']].name}） → "
            f"{ctx.content.items[snapshot['egg_id']].name} · {state}{child} · {row['created_at']}。"
        )
    return Reply(f"{TITLE}记录 {page.number}/{page.total}",
                 tuple(lines) or ("还没有异族共育记录。",),
                 (*page.navigation, TITLE, "灵宠谱系"))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return _catalog(ctx)
    if parts[0] == "记录":
        if len(parts) > 2:
            raise GameError(f"格式：{TITLE} 记录 [页码]。")
        return _history(ctx, parts[1] if len(parts) == 2 else "1")
    if len(parts) == 1 and parts[0].isdecimal():
        return _catalog(ctx, parts[0])
    recipe = ctx.content.cross_breeding.get(parts[0])
    if recipe is None:
        raise GameError("没有这条异族共育配方，请先查看配方目录。")
    if len(parts) == 1:
        return _recipe_page(ctx, recipe)
    if len(parts) == 2 and parts[1].isdecimal():
        return _recipe_page(ctx, recipe, parts[1])
    if len(parts) != 3:
        raise GameError(f"格式：{TITLE} 配方编号 亲本编号A 亲本编号B。")
    return _breed(ctx, recipe, pet_id(parts[1]), pet_id(parts[2]))


def _breed(ctx: Context, recipe, first_id: int, second_id: int) -> Reply:
    receipt = ctx.repo.pedigree_operation_reply(
        ctx.operation_id, ctx.user_id, kind="breed", snapshot_flag="cross_breeding",
    )
    if receipt is not None:
        return receipt
    player = ctx.player()
    if first_id == second_id:
        raise GameError("异族共育需要两只不同的真实亲本。")
    owned = {pet.pet_id: pet for pet in ctx.repo.owned_pets(ctx.user_id)}
    for value in (first_id, second_id):
        if value in owned:
            continue
        archived = ctx.repo.conn.execute(
            "SELECT name FROM pets WHERE user_id=? AND pet_id=? AND archived=1",
            (ctx.user_id, value),
        ).fetchone()
        if archived is not None:
            raise GameError(f"{archived['name']}已封存，请先复原后再共育。")
        raise GameError("没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
    first, second = owned[first_id], owned[second_id]
    if {first.species_id, second.species_id} != {recipe.parent_a_species, recipe.parent_b_species}:
        raise GameError("亲本种族与所选配方不符，请重新查看配方亲本。")

    for pet in (first, second):
        ctx.require_idle_pet(pet)
        if _fostered(ctx, pet.pet_id):
            raise GameError(f"{pet.name}正在寄养，先归还再共育。")
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    realm = _realm_index(ctx, recipe.minimum_realm)
    for pet in (first, second):
        if pet.affinity < recipe.minimum_affinity:
            raise GameError(
                f"异族共育需要双方亲密达到 {recipe.minimum_affinity}，"
                f"当前 {first.name} {first.affinity}、{second.name} {second.affinity}。"
            )
        if pet.realm < realm:
            raise GameError(f"异族共育需要双方至少达到{ctx.content.realms[realm].name}。")
        if pet.energy < recipe.energy:
            raise GameError(f"异族共育需要双方各有 {recipe.energy} 精力。")
    if player.stones < recipe.stones:
        raise GameError(f"异族共育需要 {recipe.stones} 灵石。")
    inventory = ctx.repo.inventory(ctx.user_id)
    for item_id, amount in recipe.items.items():
        if inventory.get(item_id, 0) < amount:
            raise GameError(f"异族共育需要 {ctx.content.items[item_id].name} ×{amount}。")

    latest = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='cross_breeding_clock'",
        (ctx.user_id,),
    ).fetchone()
    if latest is not None and ctx.now < latest["progress"]:
        raise GameError("时间早于上次异族共育，请等待时钟恢复后再操作。")
    week, _ = beijing_week(ctx.now)
    week_key = f"cross_breeding_week_{week}"
    pair_key = f"cross_breeding_pair_{min(first_id, second_id)}_{max(first_id, second_id)}"
    if ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, week_key),
    ).fetchone():
        raise GameError("每人每个北京时间自然周只能异族共育一次。")
    if ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, pair_key),
    ).fetchone():
        raise GameError("这对真实亲本已经留下永久异族共育凭证。")

    egg = ctx.content.items[f"egg_{recipe.offspring_species}"]
    player.stones -= recipe.stones
    for item_id, amount in recipe.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    first.energy -= recipe.energy
    second.energy -= recipe.energy
    ctx.repo.add_item(ctx.user_id, egg.id, 1)
    for key in (week_key, pair_key):
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
            (ctx.user_id, key),
        )
    if latest is None:
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES (?, 'cross_breeding_clock', ?, 1)",
            (ctx.user_id, ctx.now),
        )
    else:
        ctx.repo.conn.execute(
            "UPDATE quest_progress SET progress=?,claimed=1 "
            "WHERE user_id=? AND quest_id='cross_breeding_clock'",
            (ctx.now, ctx.user_id),
        )
    ctx.repo.invalidate_ready(ctx.user_id)

    reply = Reply("灵宠异族共育成功", (
        f"{first.name}（{ctx.content.species[first.species_id].name}，#{first.pet_id}）与 "
        f"{second.name}（{ctx.content.species[second.species_id].name}，#{second.pet_id}）依配方相契。",
        f"灵石 -{recipe.stones}，材料与双方各 {recipe.energy} 精力已扣除。",
        f"固定获得{egg.name} ×1；孵化后会把这两位真实亲本连入谱系。",
        "本周名额已用；该亲本组合留下永久凭证。",
    ), (TITLE, "灵宠背包", "灵宠谱系", "灵宠列表"), (
        InlineCommand(2, "孵化灵卵", f"灵宠使用 {egg.name}"),
    ))
    ctx.repo.record_pedigree_operation(
        ctx.operation_id, ctx.user_id, "breed", ctx.now,
        {
            "cross_breeding": True,
            "recipe_id": recipe.id,
            "parent_a_id": first.pet_id,
            "parent_a_name": first.name,
            "parent_a_species": first.species_id,
            "parent_b_id": second.pet_id,
            "parent_b_name": second.name,
            "parent_b_species": second.species_id,
            "offspring_species": recipe.offspring_species,
            "egg_id": egg.id,
            "week_start": week,
            "stones": recipe.stones,
            "items": recipe.items,
        }, reply,
    )
    ctx.repo.record_lineage_egg(
        user_id=ctx.user_id, item_id=egg.id, species_id=recipe.offspring_species,
        parent_a_id=first.pet_id, parent_a_name=first.name,
        parent_b_id=second.pet_id, parent_b_name=second.name,
        operation_id=ctx.operation_id, created_at=ctx.now,
    )
    return reply


def today_state(ctx: Context, user_id: str) -> str | None:
    player = ctx.repo.player(user_id)
    if player is None:
        return None
    week, _ = beijing_week(ctx.now)
    if ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (user_id, f"cross_breeding_week_{week}"),
    ).fetchone():
        return None
    can_check = False
    for recipe in ctx.content.cross_breeding.values():
        for first, second in _owned_pairs(ctx, recipe):
            can_check = True
            if not _pair_used(ctx, first, second) and not _pair_blocker(ctx, player, recipe, first, second):
                return "本周可按固定配方完成一次异族共育"
    return "查看异族共育配方与亲本/资源条件" if can_check else None


def objective_line(ctx: Context, user_id: str) -> str:
    week, _ = beijing_week(ctx.now)
    used = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (user_id, f"cross_breeding_week_{week}"),
    ).fetchone()
    if used:
        return "异族共育：本周已完成"
    state = today_state(ctx, user_id)
    if state is None:
        return "异族共育：先获得配方所需的两种族伙伴"
    if state.startswith("本周可按"):
        return "异族共育：本周可按固定配方共育一次"
    return "异族共育：查看配方与亲本/资源条件"
