from datetime import datetime

from ..application.context import Context
from ..domain.models import InlineCommand, Reply
from ..utils.time import BEIJING


def profile(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return ctx.adoption_reply()
    registered = (
        datetime.fromtimestamp(player.registered_at, BEIJING).strftime("%Y-%m-%d %H:%M:%S（UTC+8）")
        if player.registered_at is not None else "未记录"
    )
    lines = (
        f"UID：{player.uid}",
        f"注册时间：{registered}",
        f"灵石：{player.stones}",
        f"灵宠：在册 {ctx.repo.owned_pet_count(ctx.user_id)} 只 · 封存 {ctx.repo.archived_pet_count(ctx.user_id)} 只",
        f"出战伙伴：{len(ctx.repo.active_pets(ctx.user_id))} 只",
    )
    links = [InlineCommand(3, "查看灵宠名册", "灵宠列表")]
    active_count = len(ctx.repo.active_pets(ctx.user_id))
    if active_count:
        links.append(InlineCommand(4, "查看出战阵容", "灵宠出战"))
    else:
        links.append(InlineCommand(4, "选择出战伙伴", "灵宠列表"))
    return Reply("我的信息", lines, ("灵宠列表", "灵宠背包", "灵宠帮助 身份与收集"), tuple(links))
