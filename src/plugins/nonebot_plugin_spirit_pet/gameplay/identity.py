import re
from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.time import BEIJING

NAME_RANDOM_ATTEMPTS = 16
NAME_BATCH_SIZE = 128


def random_name(ctx: Context) -> str:
    definitions = ctx.content.dao_names
    capacity = definitions.capacity
    attempted = set()
    for _ in range(NAME_RANDOM_ATTEMPTS):
        index = ctx.rng.randint(0, capacity - 1)
        if index in attempted:
            continue
        attempted.add(index)
        candidate = definitions.name_at(index)
        if ctx.repo.conn.execute(
            "SELECT 1 FROM players WHERE dao_name=? COLLATE NOCASE", (candidate,),
        ).fetchone() is None:
            return candidate

    population = ctx.repo.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    start = population % capacity
    limit = min(population + 1, capacity)
    # At most population names can be occupied; one more distinct probe must be free.
    for offset in range(0, limit, NAME_BATCH_SIZE):
        candidates = [
            definitions.name_at((start + position) % capacity)
            for position in range(offset, min(offset + NAME_BATCH_SIZE, limit))
        ]
        placeholders = ", ".join("?" for _ in candidates)
        occupied = {
            row[0].lower() for row in ctx.repo.conn.execute(
                f"SELECT dao_name FROM players WHERE dao_name COLLATE NOCASE IN ({placeholders})", candidates,
            )
        }
        for candidate in candidates:
            if candidate.lower() not in occupied:
                return candidate
    raise GameError("随机道号已用尽，暂无可用道号，请联系管理员扩充词库。")


def profile(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return ctx.adoption_reply()
    registered = (
        datetime.fromtimestamp(player.registered_at, BEIJING).strftime("%Y-%m-%d %H:%M:%S（UTC+8）")
        if player.registered_at is not None else "未记录"
    )
    return Reply("我的信息", (
        f"道号：{player.dao_name}",
        f"注册时间：{registered}",
        f"平台用户 ID：{player.user_id}",
        f"灵石：{player.stones}",
        f"伙伴：在册 {len(ctx.repo.owned_pets(ctx.user_id))} 只 · 封存 {ctx.repo.archived_pet_count(ctx.user_id)} 只",
        f"出战伙伴：{len(ctx.repo.active_pets(ctx.user_id))} 只",
    ), ("灵宠道号", "灵宠列表", "灵宠背包"))


def rename(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if not arg:
        return Reply("修改道号", ("为自己取一个新道号吧，限 2-12 个汉字、字母或数字。", "例如：灵宠道号 青云。"), ("我的信息",))
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", arg):
        raise GameError("道号限 2-12 个汉字、英文字母或数字。")
    occupied = ctx.repo.player_by_name(arg)
    if occupied and occupied.user_id != player.user_id:
        raise GameError("该道号已被使用，请换一个。")
    player.dao_name = arg
    return Reply("道号已定", (f"道号：{arg}。",), ("我的信息",))
