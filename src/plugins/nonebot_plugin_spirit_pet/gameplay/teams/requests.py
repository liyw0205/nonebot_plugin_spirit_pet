import re
from sqlite3 import Row

from ...application.context import Context
from ...domain.models import GameError, Reply
from ...utils.arguments import quantity
from .common import add_member, membership, named_player, require_leader, require_room

PAGE_SIZE = 4
_JOIN = "FROM team_requests r JOIN teams t USING(team_id) "
_VISIBLE = "r.expires_at>? AND (r.candidate_id=? OR t.leader_id=?)"


def _prune(ctx: Context) -> None:
    ctx.repo.conn.execute("DELETE FROM team_requests WHERE expires_at<=?", (ctx.now,))


def _create(ctx: Context, team_id: int, candidate_id: str, kind: str) -> None:
    existing = ctx.repo.conn.execute(
        "SELECT kind FROM team_requests WHERE team_id=? AND candidate_id=? AND expires_at>?",
        (team_id, candidate_id, ctx.now),
    ).fetchone()
    if existing:
        direction = "请由队长处理原申请" if existing["kind"] == "apply" else "请由受邀道友处理原邀请"
        raise GameError(f"双方已有待处理队务，{direction}，或由原发起人撤回。")
    limit = ctx.config.spirit_pet_team_request_limit
    for field, value, label in (("team_id", team_id, "该队伍"), ("candidate_id", candidate_id, "该道友")):
        count = ctx.repo.conn.execute(
            f"SELECT COUNT(*) FROM team_requests WHERE {field}=? AND expires_at>?", (value, ctx.now),
        ).fetchone()[0]
        if count >= limit:
            raise GameError(f"{label}待处理队务已达 {limit} 条上限，请先处理或等待过期。")
    _prune(ctx)
    ctx.repo.conn.execute(
        "INSERT INTO team_requests(team_id, candidate_id, kind, initiator_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (team_id, candidate_id, kind, ctx.user_id, ctx.now, ctx.now + ctx.config.spirit_pet_team_request_ttl),
    )


def join(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if membership(ctx):
        raise GameError("你已有队伍，请先退出。")
    leader = named_player(ctx, arg)
    team = ctx.repo.conn.execute("SELECT team_id FROM teams WHERE leader_id=?", (leader.user_id,)).fetchone()
    if team is None:
        raise GameError("该道号当前没有带队。")
    require_room(ctx, team["team_id"])
    _create(ctx, team["team_id"], ctx.user_id, "apply")
    return Reply("入队申请已提交", (
        f"{player.dao_name}申请加入{leader.dao_name}的队伍，须由队长同意。",
        f"申请 {ctx.config.spirit_pet_team_request_ttl} 秒后失效，不预留名额，不消耗资源。",
    ), (f"灵宠队务 {leader.dao_name}", f"灵宠队伍撤回 {leader.dao_name}"))


def invite(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    candidate = named_player(ctx, arg)
    if candidate.user_id == ctx.user_id:
        raise GameError("不能邀请自己加入队伍。")
    if membership(ctx, candidate.user_id):
        raise GameError("该道友已有队伍，请先退出。")
    require_room(ctx, member["team_id"])
    _create(ctx, member["team_id"], candidate.user_id, "invite")
    return Reply("队伍邀请已发起", (
        f"{ctx.player().dao_name}邀请{candidate.dao_name}加入队伍，须由受邀道友同意。",
        f"邀请 {ctx.config.spirit_pet_team_request_ttl} 秒后失效，不预留名额，不消耗资源。",
        "邀请保存在对方的队务中，不会向其他群或私聊主动推送。",
    ), (f"灵宠队务 {candidate.dao_name}", f"灵宠队伍撤回 {candidate.dao_name}"))


def _request(ctx: Context, arg: str) -> Row:
    ctx.player()
    other = named_player(ctx, arg)
    row = ctx.repo.conn.execute(
        "SELECT r.*, t.leader_id " + _JOIN + "WHERE r.expires_at>? AND "
        "((r.candidate_id=? AND t.leader_id=?) OR (t.leader_id=? AND r.candidate_id=?))",
        (ctx.now, ctx.user_id, other.user_id, ctx.user_id, other.user_id),
    ).fetchone()
    if row is None:
        raise GameError("没有与你和该道友有关的待处理队务，或记录已过期。")
    return row


def _opponent(ctx: Context, request: Row) -> str:
    user_id = request["leader_id"] if request["candidate_id"] == ctx.user_id else request["candidate_id"]
    return ctx.player(user_id).dao_name


def _decider(request: Row) -> str:
    return request["leader_id"] if request["kind"] == "apply" else request["candidate_id"]


def _require_decider(ctx: Context, request: Row) -> None:
    expected_initiator = request["candidate_id"] if request["kind"] == "apply" else request["leader_id"]
    if request["initiator_id"] != expected_initiator:
        raise GameError("该队务的发起人已失去授权，请撤回或等待过期后重新发起。")
    if _decider(request) != ctx.user_id:
        raise GameError("只能由队长审批入队申请，或由受邀道友处理队伍邀请；发起人可以撤回。")


def accept(ctx: Context, arg: str) -> Reply:
    request = _request(ctx, arg)
    _require_decider(ctx, request)
    candidate_name = ctx.player(request["candidate_id"]).dao_name
    leader_name = ctx.player(request["leader_id"]).dao_name
    add_member(ctx, request["team_id"], request["candidate_id"])
    _prune(ctx)
    return Reply("加入队伍", (
        f"{candidate_name}已加入{leader_name}的队伍。",
        "该道友的其他入队申请和邀请已取消，全队需重新准备；未消耗资源。",
    ), ("灵宠队伍", "灵宠准备"))


def _delete(ctx: Context, request: Row) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM team_requests WHERE team_id=? AND candidate_id=?",
        (request["team_id"], request["candidate_id"]),
    )
    _prune(ctx)


def reject(ctx: Context, arg: str) -> Reply:
    request = _request(ctx, arg)
    _require_decider(ctx, request)
    other = _opponent(ctx, request)
    _delete(ctx, request)
    return Reply("队务已拒绝", (f"已拒绝与{other}的队务，未消耗资源。",), ("灵宠队务",))


def withdraw(ctx: Context, arg: str) -> Reply:
    request = _request(ctx, arg)
    if request["initiator_id"] != ctx.user_id:
        raise GameError("只有原发起人可以撤回；处理方可以拒绝。")
    other = _opponent(ctx, request)
    _delete(ctx, request)
    return Reply("队务已撤回", (f"已撤回与{other}的队务，未消耗资源。",), ("灵宠队务",))


def _summary(ctx: Context, request: Row) -> str:
    name = _opponent(ctx, request)
    kind = "入队申请" if request["kind"] == "apply" else "队伍邀请"
    state = "待你处理" if _decider(request) == ctx.user_id else "等待对方处理"
    return f"{name} · {kind} · {state} · 剩余 {request['expires_at'] - ctx.now} 秒"


def _detail(ctx: Context, arg: str) -> Reply:
    request = _request(ctx, arg)
    other = _opponent(ctx, request)
    commands = []
    if request["initiator_id"] == ctx.user_id:
        commands.append(f"灵宠队伍撤回 {other}")
    elif _decider(request) == ctx.user_id:
        commands.extend((f"灵宠队伍同意 {other}", f"灵宠队伍拒绝 {other}"))
    commands.append("灵宠队务")
    return Reply("队务详情", (
        _summary(ctx, request),
        f"队长：{ctx.player(request['leader_id']).dao_name}；候选道友：{ctx.player(request['candidate_id']).dao_name}。",
        "待处理记录不预留名额；同意时仍须队伍未满且候选道友未加入其他队伍。",
    ), tuple(commands))


def inbox(ctx: Context, arg: str) -> Reply:
    ctx.player()
    explicit_page = re.fullmatch(r"分页\s+([0-9]+)", arg)
    if explicit_page:
        page = quantity(explicit_page[1], 999)
    elif arg and (not arg.isascii() or not arg.isdigit() or ctx.repo.player_by_name(arg) is not None):
        return _detail(ctx, arg)
    else:
        page = quantity(arg or "1", 999)
    params = (ctx.now, ctx.user_id, ctx.user_id)
    total = ctx.repo.conn.execute("SELECT COUNT(*) " + _JOIN + "WHERE " + _VISIBLE, params).fetchone()[0]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"队务共 {pages} 页。")
    rows = ctx.repo.conn.execute(
        "SELECT r.*, t.leader_id " + _JOIN + "WHERE " + _VISIBLE
        + " ORDER BY r.expires_at, r.created_at, r.team_id, r.candidate_id LIMIT ? OFFSET ?",
        (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    commands = [f"灵宠队务 {_opponent(ctx, row)}" for row in rows]
    if page > 1:
        commands.append(f"灵宠队务 分页 {page - 1}")
    if page < pages:
        commands.append(f"灵宠队务 分页 {page + 1}")
    if not commands:
        commands.append("灵宠队伍" if membership(ctx) else "灵宠组队")
    return Reply(f"待处理队务 {page}/{pages}", tuple(_summary(ctx, row) for row in rows) or (
        "当前没有待处理的入队申请或队伍邀请。",
    ), tuple(commands))
