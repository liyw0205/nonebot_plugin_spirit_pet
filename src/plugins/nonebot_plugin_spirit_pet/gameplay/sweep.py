from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from .rewards import grant


def _cleared(ctx: Context, dungeon_id: str) -> bool:
    """A dungeon may be swept only after this player has won it in a real battle."""
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM battle_records AS r "
        "JOIN battle_participants AS p ON p.battle_id = r.battle_id "
        "WHERE p.user_id=? AND r.kind='pve' AND r.battle_key=? AND r.winner_side = p.side LIMIT 1",
        (ctx.user_id, dungeon_id),
    ).fetchone()
    return row is not None


def sweep(ctx: Context, arg: str) -> Reply:
    if not arg:
        raise GameError("请填写秘境名称，例如 灵宠扫荡 青岚林。")
    dungeon = named(ctx.content.dungeons, arg)
    if dungeon.team:
        raise GameError("组队秘境请由队长发送 灵宠组队挑战 秘境名称。")
    if not _cleared(ctx, dungeon.id):
        raise GameError(f"尚未通关{dungeon.name}，请先发送 灵宠挑战 {dungeon.name}。")

    player = ctx.player()
    minimum = next(
        index for index, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm
    )
    pets = ctx.active_pets(ctx.user_id)
    first = True
    for pet in pets:
        if pet.realm < minimum:
            raise GameError(
                f"{pet.name}境界不足，{dungeon.name}需要{ctx.content.realms[minimum].name}。"
            )
        if first:
            ctx.check_action(player, pet, "pve", dungeon.energy, ctx.config.spirit_pet_pve_cooldown)
            first = False
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < dungeon.energy:
                raise GameError(f"{pet.name}精力不足，需要 {dungeon.energy} 点。")

    for pet in pets:
        pet.energy -= dungeon.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)

    lines = [f"扫荡：{dungeon.name}", *grant(ctx, dungeon.reward)]
    lines.append(f"每只灵宠精力 -{dungeon.energy}；扫荡不写入战报，也不计入获胜场次。")
    return Reply("秘境扫荡", tuple(lines), ("灵宠秘境", "灵宠战报", "我的灵宠", "灵宠任务"))
