from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from ..utils.randomness import weighted_choice
from .combat import enemy_fighter, fight
from .battle_records import capture_snapshot, record_battle
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant

ADVENTURE_CODEX_PAGE_SIZE = 4


def explore(ctx: Context, arg: str) -> Reply:
    routes = tuple(ctx.content.exploration_routes.values())
    if not arg:
        lines = []
        for route in routes:
            encounters = [ctx.content.encounters[key] for key in route.encounters]
            realm = next(realm.name for realm in ctx.content.realms if realm.id == route.min_realm)
            exp_min = min(entry.reward.exp.minimum for entry in encounters)
            exp_max = max(entry.reward.exp.maximum for entry in encounters)
            stones_min = min(entry.reward.stones.minimum for entry in encounters)
            stones_max = max(entry.reward.stones.maximum for entry in encounters)
            item_ids = dict.fromkeys(
                item_id for entry in encounters for item_id in entry.reward.items
            )
            item_ranges = []
            for item_id in item_ids:
                bounds = [entry.reward.items.get(item_id) for entry in encounters]
                maximum = max(bound.maximum if bound else 0 for bound in bounds)
                if maximum:
                    minimum = min(bound.minimum if bound else 0 for bound in bounds)
                    item_ranges.append(f"{ctx.content.items[item_id].name} {minimum}-{maximum}")
            reward = f"修为 {exp_min}-{exp_max} · 灵石 {stones_min}-{stones_max}"
            if item_ranges:
                reward += " · 道具 " + "、".join(item_ranges)
            total_weight = sum(entry.weight for entry in encounters)
            odds = "奇遇概率：" + " · ".join(
                f"{entry.name} {entry.weight / total_weight:.0%}" for entry in encounters
            )
            lines.extend((f"{route.name}：{route.description} · {realm}起", reward, odds))
        return Reply(
            "山海历练路线", tuple(lines),
            tuple(f"灵宠历练 {route.name}" for route in routes)
            + ("灵宠奇闻", "我的灵宠", "灵宠任务"),
        )

    route = named(ctx.content.exploration_routes, arg)
    player, pet = ctx.player(), ctx.pet()
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == route.min_realm)
    if pet.realm < minimum:
        realm = ctx.content.realms[minimum].name
        raise GameError(f"{route.name}需要{realm}境界。")
    energy = ctx.content.rules.explore_energy
    ctx.check_action(player, pet, "explore", energy, ctx.config.spirit_pet_explore_cooldown)
    entries = [ctx.content.encounters[key] for key in route.encounters]
    encounter = weighted_choice(ctx.rng, entries, [entry.weight for entry in entries])
    discovered = ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES (?, ?, ?)", (ctx.user_id, encounter.id, ctx.now),
    ).rowcount == 1
    pet.energy -= energy
    player.last_explore = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "explore")
    lines = [f"奇遇：{encounter.name}", encounter.text]
    if discovered:
        lines.append("新奇闻已收入灵宠奇闻。")
    lines.extend(grant(ctx, encounter.reward))
    lines.append(f"精力 -{energy}。")
    return Reply(
        f"山海历练 · {route.name}",
        tuple(lines),
        ("灵宠奇闻", "灵宠历练", "灵宠秘境", "灵宠任务"),
    )


def adventure_codex(ctx: Context, arg: str) -> Reply:
    routes = tuple(ctx.content.exploration_routes.values())
    pages = max(1, (len(routes) + ADVENTURE_CODEX_PAGE_SIZE - 1) // ADVENTURE_CODEX_PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠奇闻共 {pages} 页。")

    known = {
        row["encounter_id"] for row in ctx.repo.conn.execute(
            "SELECT encounter_id FROM adventure_discoveries WHERE user_id=?", (ctx.user_id,),
        )
    }
    all_ids = {encounter_id for route in routes for encounter_id in route.encounters}
    selected = routes[(page - 1) * ADVENTURE_CODEX_PAGE_SIZE:page * ADVENTURE_CODEX_PAGE_SIZE]
    lines = [f"奇闻发现：{len(known & all_ids)}/{len(all_ids)}。"]
    commands = []
    for route in selected:
        found = sum(encounter_id in known for encounter_id in route.encounters)
        lines.append(f"{route.name} · {found}/{len(route.encounters)}")
        for encounter_id in route.encounters:
            encounter = ctx.content.encounters[encounter_id]
            if encounter_id in known:
                lines.append(f"已遇 · {encounter.name}：{encounter.text}")
            else:
                lines.append(f"未遇 · {encounter.name}：尚未触发。")
        commands.append(f"灵宠历练 {route.name}")
    if page > 1:
        commands.append(f"灵宠奇闻 {page - 1}")
    if page < pages:
        commands.append(f"灵宠奇闻 {page + 1}")
    commands.extend(("灵宠历练", "灵宠成就", "灵宠奇闻榜"))
    return Reply(f"灵宠奇闻 {page}/{pages}", tuple(lines), tuple(commands))


def _enemy_detail(ctx: Context, enemy_id: str) -> str:
    enemy = ctx.content.enemies[enemy_id]
    line = (
        f"{enemy.name} · 主属性：{ctx.content.elements[enemy.primary_element].name}"
        f" · 气血 {enemy.stats.hp} 攻击 {enemy.stats.attack}"
        f" 防御 {enemy.stats.defense} 速度 {enemy.stats.speed}"
    )
    if enemy.signature_skill:
        skill = ctx.content.skills[enemy.signature_skill]
        line += f" · 招式：{skill.name}（每 {enemy.skill_every} 次行动施展）"
    return line


def dungeons(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        dungeon = named(ctx.content.dungeons, arg)
        reward = dungeon.reward
        realm = next(realm.name for realm in ctx.content.realms if realm.id == dungeon.min_realm)
        command = "灵宠组队挑战" if dungeon.team else "灵宠挑战"
        return Reply(dungeon.name, (
            f"{'组队' if dungeon.team else '单人'} · {realm}起 · 每只灵宠精力 {dungeon.energy}",
            *(_enemy_detail(ctx, key) for key in dungeon.enemies),
            f"胜利：修为 {reward.exp.minimum}-{reward.exp.maximum}"
            f" · 灵石 {reward.stones.minimum}-{reward.stones.maximum}",
            *(f"{ctx.content.items[key].name}：{bounds.minimum}-{bounds.maximum}"
              for key, bounds in reward.items.items()),
        ), (f"{command} {dungeon.name}", "我的灵宠", "灵宠秘境"))
    entries = sorted(ctx.content.dungeons.values(), key=lambda dungeon: (
        next(index for index, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm),
        dungeon.team, dungeon.id,
    ))
    page = quantity(arg or "1", 999)
    pages = (len(entries) + 4) // 5
    if page > pages:
        raise GameError(f"山海秘境共 {pages} 页。")
    selected = entries[(page - 1) * 5:page * 5]
    commands = [f"灵宠秘境 {dungeon.name}" for dungeon in selected]
    if page > 1:
        commands.append(f"灵宠秘境 {page - 1}")
    if page < pages:
        commands.append(f"灵宠秘境 {page + 1}")
    return Reply(f"山海秘境 {page}/{pages}", tuple(
        f"{dungeon.name}：{'组队' if dungeon.team else '单人'}"
        f" · {next(r.name for r in ctx.content.realms if r.id == dungeon.min_realm)}起"
        f" · 精力 {dungeon.energy}"
        for dungeon in selected
    ), tuple(commands))


def challenge(ctx: Context, arg: str) -> Reply:
    dungeon = named(ctx.content.dungeons, arg or "forest")
    if dungeon.team:
        raise GameError("组队秘境请由队长发送 灵宠组队挑战 秘境名称。")
    return run_dungeon(ctx, dungeon, [ctx.user_id])


def run_dungeon(ctx: Context, dungeon, user_ids: list[str]) -> Reply:
    players = [ctx.player(user_id) for user_id in user_ids]
    pets = [ctx.pet(user_id) for user_id in user_ids]
    minimum = next(i for i, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm)
    for player, pet in zip(players, pets):
        if pet.realm < minimum:
            raise GameError(f"{pet.name}境界不足，{dungeon.name}需要{ctx.content.realms[minimum].name}。")
        ctx.check_action(player, pet, "pve", dungeon.energy, ctx.config.spirit_pet_pve_cooldown)
    allies = [combatant(ctx, user_id) for user_id in user_ids]
    enemies = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in dungeon.enemies]
    capture = capture_snapshot(ctx, (allies, enemies), (list(user_ids), []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)
    lines = [f"{dungeon.name} · {battle.rounds} 回合", *battle.lines]
    for player, pet in zip(players, pets):
        pet.energy -= dungeon.energy
        player.last_pve = ctx.now
        ctx.repo.invalidate_ready(player.user_id)
        lines.extend(award_mastery(ctx, player.user_id, battle.skill_uses[0].get(pet.pet_id, {})))
        if battle.winner == 0:
            advance(ctx, "pve", player.user_id)
            lines.append(f"{player.dao_name}的{pet.name}：" + "，".join(grant(ctx, dungeon.reward, player.user_id)))
    lines.append(f"每只灵宠精力 -{dungeon.energy}；气血仅在本场战斗内结算。")
    title = "秘境获胜" if battle.winner == 0 else ("秘境平局" if battle.winner == -1 else "秘境败退")
    reply = Reply(title, tuple(lines), ("灵宠战报", "我的灵宠", "灵宠任务", "灵宠喂养"))
    record_battle(ctx, kind="pve", battle_key=dungeon.id, battle_name=dungeon.name, battle=battle,
                  capture=capture, reply=reply)
    return reply
