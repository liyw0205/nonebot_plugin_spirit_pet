import re

from ..application.context import Context
from ..domain.models import GameError, Reply


def random_name(ctx: Context) -> str:
    definitions = ctx.content.dao_names
    names = [prefix + suffix for prefix in definitions.prefixes for suffix in definitions.suffixes]
    start = ctx.rng.randint(0, len(names) - 1)
    for offset in range(len(names)):
        candidate = names[(start + offset) % len(names)]
        if ctx.repo.player_by_name(candidate) is None:
            return candidate
    base = names[start]
    number = ctx.rng.randint(1000, 9999)
    for offset in range(9000):
        candidate = f"{base}{1000 + (number - 1000 + offset) % 9000}"
        if ctx.repo.player_by_name(candidate) is None:
            return candidate
    raise GameError("暂未找到可用道号，请稍后再试。")


def profile(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("修士名帖", ("尚未结契，领养灵宠时会获得专属道号。",), ("灵宠领养 青鸾",))
    return Reply("修士名帖", (f"道号：{player.dao_name}", f"论剑积分：{player.rating}"), ("我的灵宠", "灵宠论剑榜"))


def rename(ctx: Context, arg: str) -> Reply:
    if not arg:
        return profile(ctx, arg)
    player = ctx.player()
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", arg):
        raise GameError("道号限 2-12 个汉字、英文字母或数字。")
    occupied = ctx.repo.player_by_name(arg)
    if occupied and occupied.user_id != player.user_id:
        raise GameError("该道号已被使用，请换一个。")
    player.dao_name = arg
    return Reply("道号已定", (f"道号：{arg}。",))
