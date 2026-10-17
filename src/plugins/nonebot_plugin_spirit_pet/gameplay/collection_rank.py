from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply


def _rows(ctx: Context):
    species_ids = tuple(ctx.content.species)
    placeholders = ",".join("?" for _ in species_ids)
    return ctx.repo.conn.execute(
        "SELECT identity.id + 9999 AS uid, owner.user_id AS user_id, "
        "COUNT(DISTINCT pet.species_id) AS collected, MIN(pet.pet_id) AS first_pet "
        "FROM players owner JOIN player_identity identity USING(user_id) "
        "JOIN pets pet ON pet.user_id=owner.user_id "
        f"AND pet.species_id IN ({placeholders}) "
        "GROUP BY owner.user_id "
        "ORDER BY collected DESC, first_pet ASC, identity.id LIMIT 10",
        species_ids,
    ).fetchall()


def collected_species(ctx: Context, user_id: str) -> int:
    species_ids = tuple(ctx.content.species)
    if not species_ids:
        return 0
    placeholders = ",".join("?" for _ in species_ids)
    return int(ctx.repo.conn.execute(
        f"SELECT COUNT(DISTINCT species_id) FROM pets WHERE user_id=? AND species_id IN ({placeholders})",
        (user_id, *species_ids),
    ).fetchone()[0])


def _personal_rank(ctx: Context, user_id: str) -> int | None:
    species_ids = tuple(ctx.content.species)
    placeholders = ",".join("?" for _ in species_ids)
    row = ctx.repo.conn.execute(
        "SELECT ranked FROM ("
        "SELECT owner.user_id AS user_id, COUNT(DISTINCT pet.species_id) AS collected, "
        "MIN(pet.pet_id) AS first_pet, "
        "ROW_NUMBER() OVER (ORDER BY COUNT(DISTINCT pet.species_id) DESC, MIN(pet.pet_id) ASC, identity.id ASC) AS ranked "
        "FROM players owner JOIN player_identity identity USING(user_id) "
        f"JOIN pets pet ON pet.user_id=owner.user_id AND pet.species_id IN ({placeholders}) "
        "GROUP BY owner.user_id"
        ") WHERE user_id=?",
        (*species_ids, user_id),
    ).fetchone()
    return int(row["ranked"]) if row is not None else None


def collection_rank(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠收集榜 不接受参数，直接发送即可。")
    total = len(ctx.content.species)
    rows = _rows(ctx)
    board = tuple(
        f"{index}. UID {row['uid']} · 收集 {row['collected']}/{total} 族"
        for index, row in enumerate(rows, 1)
    ) or ("尚无修士收得灵宠种族。",)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠收集榜", board,
            ("灵宠图鉴", "灵宠帮助"),
            (InlineCommand(len(board), "开始领养", "灵宠领养 "),),
        )
    mine = collected_species(ctx, player.user_id)
    rank = _personal_rank(ctx, player.user_id)
    suffix = (
        f"你的当前名次：第 {rank} 名 · 已收集 {mine}/{total} 族。"
        if rank is not None else f"你尚未收得灵宠种族 · 已收集 0/{total} 族。"
    )
    return Reply("灵宠收集榜", (*board, suffix), (
        "灵宠收集", "灵宠图鉴奖励", "灵宠目标",
    ), (InlineCommand(len(board), "查看收集奖励", "灵宠图鉴奖励"),))
