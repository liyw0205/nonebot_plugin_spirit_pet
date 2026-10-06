from ...application.context import Context
from ...domain.models import GameError, Reply
from .common import invalidate_team, named_player, require_leader, require_member


def leave(ctx: Context, arg: str) -> Reply:
    member = require_member(ctx)
    if member["leader_id"] == ctx.user_id:
        raise GameError("队长不能直接退队，请先转让队长或显式解散队伍。")
    ctx.repo.conn.execute(
        "DELETE FROM team_members WHERE user_id=? AND team_id=?", (ctx.user_id, member["team_id"]),
    )
    invalidate_team(ctx, member["team_id"])
    return Reply("退出队伍", (
        f"{ctx.player().dao_name}已离开{ctx.player(member['leader_id']).dao_name}的小队。",
    ), ("灵宠组队", "灵宠队务"))


def kick(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    target = named_player(ctx, arg)
    if target.user_id == ctx.user_id:
        raise GameError("不能踢出自己，请转让队长或解散队伍。")
    deleted = ctx.repo.conn.execute(
        "DELETE FROM team_members WHERE user_id=? AND team_id=?", (target.user_id, member["team_id"]),
    )
    if deleted.rowcount != 1:
        raise GameError("该道友不在你的队伍中。")
    invalidate_team(ctx, member["team_id"])
    return Reply("移出队伍", (
        f"{target.dao_name}已被移出{ctx.player().dao_name}的小队，全队准备已取消。",
    ), ("灵宠队伍", "灵宠队务"))


def transfer(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    target = named_player(ctx, arg)
    if target.user_id == ctx.user_id:
        raise GameError("你已是队长，不能向自己转让。")
    target_member = ctx.repo.conn.execute(
        "SELECT 1 FROM team_members WHERE user_id=? AND team_id=?", (target.user_id, member["team_id"]),
    ).fetchone()
    if not target_member:
        raise GameError("只能向本队的其他成员转让队长。")
    ctx.repo.conn.execute("UPDATE teams SET leader_id=? WHERE team_id=?", (target.user_id, member["team_id"]))
    ctx.repo.conn.execute("DELETE FROM team_requests WHERE team_id=?", (member["team_id"],))
    invalidate_team(ctx, member["team_id"])
    return Reply("队长交接", (
        f"{ctx.player().dao_name}已将队长转让给{target.dao_name}。",
        "本队全部邀请与申请已取消，全队需要重新准备。",
    ), ("灵宠队伍", "灵宠队务", "灵宠退队"))


def disband(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    invalidate_team(ctx, member["team_id"])
    ctx.repo.conn.execute("DELETE FROM teams WHERE team_id=?", (member["team_id"],))
    return Reply("小队解散", (
        f"{ctx.player().dao_name}已解散小队，成员离队，本队全部邀请与申请已取消。",
    ), ("灵宠组队", "灵宠队务"))
