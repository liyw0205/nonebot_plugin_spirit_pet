from sqlite3 import Row

from ...application.context import Context
from ...domain.models import GameError
from ...domain.state import Player


def membership(ctx: Context, user_id: str | None = None) -> Row | None:
    return ctx.repo.conn.execute(
        "SELECT m.*, t.leader_id FROM team_members m JOIN teams t USING(team_id) WHERE m.user_id=?",
        (ctx.user_id if user_id is None else user_id,),
    ).fetchone()


def require_member(ctx: Context) -> Row:
    ctx.player()
    member = membership(ctx)
    if member is None:
        raise GameError("尚未加入队伍，可发送 灵宠组队 或 灵宠入队 队长道号。")
    return member


def require_leader(ctx: Context) -> Row:
    member = require_member(ctx)
    if member["leader_id"] != ctx.user_id:
        raise GameError("仅队长可以进行此操作。")
    return member


def named_player(ctx: Context, arg: str) -> Player:
    player = ctx.repo.player_by_name(arg.strip())
    if player is None:
        raise GameError("该道号不存在，请填写对方的道号。")
    return player


def require_room(ctx: Context, team_id: int) -> Row:
    team = ctx.repo.conn.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
    if team is None:
        raise GameError("该队伍已经解散。")
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM team_members WHERE team_id=?", (team_id,),
    ).fetchone()[0]
    if count >= ctx.content.rules.max_team_size:
        raise GameError("队伍已满。")
    return team


def invalidate_team(ctx: Context, team_id: int) -> None:
    ctx.repo.invalidate_team_ready(team_id)


def clear_candidate_requests(ctx: Context, user_id: str) -> None:
    ctx.repo.conn.execute("DELETE FROM team_requests WHERE candidate_id=?", (user_id,))


def add_member(ctx: Context, team_id: int, user_id: str) -> None:
    ctx.player(user_id)
    if membership(ctx, user_id) is not None:
        raise GameError("该道友已有队伍，请先退出。")
    require_room(ctx, team_id)
    ctx.repo.conn.execute("INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (user_id, team_id))
    clear_candidate_requests(ctx, user_id)
    invalidate_team(ctx, team_id)
