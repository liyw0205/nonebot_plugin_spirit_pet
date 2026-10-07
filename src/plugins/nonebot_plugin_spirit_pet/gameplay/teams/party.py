from ...application.context import Context
from ...domain.models import GameError, Reply
from ...domain.state import Pet
from ...utils.arguments import named
from ..adventure import run_dungeon
from .common import add_member, membership, require_leader, require_member


def _active_pet(ctx: Context, user_id: str) -> Pet:
    player = ctx.player(user_id)
    if player.active_pet_id is None:
        raise GameError("尚未选择出战灵宠。")
    return ctx.repo.pet(player.active_pet_id)


def create(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if membership(ctx):
        raise GameError("你已有队伍，请先退出。")
    cursor = ctx.repo.conn.execute("INSERT INTO teams(leader_id) VALUES (?)", (ctx.user_id,))
    team_id = cursor.lastrowid
    add_member(ctx, team_id, ctx.user_id)
    return Reply("灵契小队", (
        f"{player.dao_name}组建了小队，担任队长。",
        f"队伍容量：1/{ctx.content.rules.max_team_size}。",
    ), ("灵宠队伍", "灵宠队务", "灵宠准备"))


def status(ctx: Context, arg: str) -> Reply:
    member = require_member(ctx)
    if arg:
        return _member_detail(ctx, member, arg)
    rows = ctx.repo.conn.execute(
        "SELECT m.*, p.dao_name FROM team_members m JOIN players p USING(user_id) "
        "WHERE m.team_id=? ORDER BY (m.user_id=?) DESC, p.dao_name",
        (member["team_id"], member["leader_id"]),
    ).fetchall()
    leader_name = ctx.player(member["leader_id"]).dao_name
    lines = [f"队伍容量：{len(rows)}/{ctx.content.rules.max_team_size}。"]
    own_ready = False
    others = []
    for row in rows:
        pet = _active_pet(ctx, row["user_id"])
        role = "队长" if row["user_id"] == member["leader_id"] else "队员"
        ready = row["ready_pet_id"] == pet.pet_id
        lines.append(f"{role} {row['dao_name']} · {pet.name} · {'已准备' if ready else '未准备'}")
        if row["user_id"] == ctx.user_id:
            own_ready = ready
        else:
            others.append(row["dao_name"])
    commands = ["灵宠队务", "灵宠取消准备" if own_ready else "灵宠准备"]
    if member["leader_id"] == ctx.user_id:
        if len(rows) >= 2:
            commands.append("灵宠组队挑战 上古灵殿")
        commands.append("灵宠解散")
    else:
        commands.extend(("灵宠退队", "灵宠秘境"))
    commands.extend(f"灵宠队伍 {name}" for name in others)
    return Reply(f"{leader_name}的小队", tuple(lines), tuple(commands))


def _member_detail(ctx: Context, member, dao_name: str) -> Reply:
    row = ctx.repo.conn.execute(
        "SELECT m.*, p.dao_name FROM team_members m JOIN players p USING(user_id) "
        "WHERE m.team_id=? AND p.dao_name=? COLLATE NOCASE", (member["team_id"], dao_name),
    ).fetchone()
    if row is None:
        raise GameError("该道友不在你的队伍中。")
    pet = _active_pet(ctx, row["user_id"])
    role = "队长" if row["user_id"] == member["leader_id"] else "队员"
    ready = row["ready_pet_id"] == pet.pet_id
    commands = ["灵宠队伍", "灵宠队务"]
    if row["user_id"] == ctx.user_id:
        commands.append("灵宠取消准备" if ready else "灵宠准备")
    elif member["leader_id"] == ctx.user_id:
        commands.extend((f"灵宠踢人 {row['dao_name']}", f"灵宠转让 {row['dao_name']}"))
    return Reply(f"队员名帖 · {row['dao_name']}", (
        f"队伍：{ctx.player(member['leader_id']).dao_name}的小队。",
        f"身份：{role}。", f"出战灵宠：{pet.name} · {'已准备' if ready else '未准备'}。",
    ), tuple(commands))


def ready(ctx: Context, arg: str) -> Reply:
    require_member(ctx)
    pet = _active_pet(ctx, ctx.user_id)
    ctx.require_idle_pet(pet)
    ctx.repo.conn.execute("UPDATE team_members SET ready_pet_id=? WHERE user_id=?", (pet.pet_id, ctx.user_id))
    return Reply("出征准备", (
        f"{pet.name}已准备。队长下一次组队挑战将消耗本宠的精力并共享 PVE 冷却。",
        "战斗后、切宠或改变参战能力后准备失效；成员或队长变化后全队需重新准备。",
    ), ("灵宠取消准备", "灵宠队伍"))


def unready(ctx: Context, arg: str) -> Reply:
    require_member(ctx)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("取消准备", ("已取消出征准备。",), ("灵宠准备", "灵宠队伍"))


def challenge(ctx: Context, arg: str) -> Reply:
    member = require_leader(ctx)
    dungeon = named(ctx.content.dungeons, arg or "temple")
    if not dungeon.team:
        raise GameError("该秘境为单人秘境。")
    rows = ctx.repo.conn.execute(
        "SELECT * FROM team_members WHERE team_id=? ORDER BY user_id", (member["team_id"],),
    ).fetchall()
    if len(rows) < 2:
        raise GameError("组队挑战至少需要两名玩家。")
    for row in rows:
        active_pet_id = ctx.player(row["user_id"]).active_pet_id
        if active_pet_id is None or active_pet_id != row["ready_pet_id"]:
            raise GameError("全体成员准备后才能挑战。")
    return run_dungeon(ctx, dungeon, [row["user_id"] for row in rows])
