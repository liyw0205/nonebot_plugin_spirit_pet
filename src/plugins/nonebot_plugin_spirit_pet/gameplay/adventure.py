from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from ..utils.randomness import weighted_choice
from .combat import Fighter, fight
from .battle_records import capture_snapshot, record_battle
from .loadout import combatant
from .mastery import award_mastery
from .quests import advance
from .rewards import grant


def explore(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    energy = ctx.content.rules.explore_energy
    ctx.check_action(player, pet, "explore", energy, ctx.config.spirit_pet_explore_cooldown)
    entries = list(ctx.content.encounters.values())
    encounter = weighted_choice(ctx.rng, entries, [entry.weight for entry in entries])
    pet.energy -= energy
    player.last_explore = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    advance(ctx, "explore")
    return Reply("山海历练", (encounter.text, *grant(ctx, encounter.reward), f"精力 -{energy}。"))


def dungeons(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        dungeon = named(ctx.content.dungeons, arg)
        reward = dungeon.reward
        realm = next(realm.name for realm in ctx.content.realms if realm.id == dungeon.min_realm)
        command = "灵宠组队挑战" if dungeon.team else "灵宠挑战"
        return Reply(dungeon.name, (
            f"{'组队' if dungeon.team else '单人'} · {realm}起 · 每只灵宠精力 {dungeon.energy}",
            *(f"{ctx.content.enemies[key].name} · 主属性："
              f"{ctx.content.elements[ctx.content.enemies[key].primary_element].name}"
              f" · 气血 {ctx.content.enemies[key].stats.hp} 攻击 {ctx.content.enemies[key].stats.attack}"
              f" 防御 {ctx.content.enemies[key].stats.defense} 速度 {ctx.content.enemies[key].stats.speed}"
              for key in dungeon.enemies),
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
    enemies = [
        Fighter.create(
            ctx.content.enemies[key].name, ctx.content.enemies[key].stats,
            tuple(ctx.content.enemies[key].elements),
            primary_element=ctx.content.enemies[key].primary_element,
        )
        for key in dungeon.enemies
    ]
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
