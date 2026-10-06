from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from ..utils.randomness import weighted_choice
from .combat import Fighter, fight
from .loadout import combatant
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
    return Reply("山海秘境", tuple(
        f"{dungeon.name}：{'组队' if dungeon.team else '单人'}"
        f" · {next(r.name for r in ctx.content.realms if r.id == dungeon.min_realm)}起"
        f" · 精力 {dungeon.energy}"
        for dungeon in ctx.content.dungeons.values()
    ), ("灵宠挑战 青岚林", "灵宠队伍", "灵宠组队"))


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
        Fighter.create(ctx.content.enemies[key].name, ctx.content.enemies[key].stats, tuple(ctx.content.enemies[key].elements))
        for key in dungeon.enemies
    ]
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)
    lines = [f"{dungeon.name} · {battle.rounds} 回合", *battle.lines]
    for player, pet in zip(players, pets):
        pet.energy -= dungeon.energy
        player.last_pve = ctx.now
        ctx.repo.invalidate_ready(player.user_id)
        if battle.winner == 0:
            advance(ctx, "pve", player.user_id)
            lines.append(f"{player.dao_name}的{pet.name}：" + "，".join(grant(ctx, dungeon.reward, player.user_id)))
    lines.append(f"每只灵宠精力 -{dungeon.energy}；气血仅在本场战斗内结算。")
    title = "秘境获胜" if battle.winner == 0 else ("秘境平局" if battle.winner == -1 else "秘境败退")
    return Reply(title, tuple(lines), ("我的灵宠", "灵宠任务", "灵宠喂养"))
