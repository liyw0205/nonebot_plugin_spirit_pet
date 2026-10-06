from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from .adventure import run_dungeon


def membership(ctx: Context):
    return ctx.repo.conn.execute(
        "SELECT m.*, t.leader_id FROM team_members m JOIN teams t USING(team_id) WHERE m.user_id=?",
        (ctx.user_id,),
    ).fetchone()


def create(ctx: Context, arg: str) -> Reply:
    ctx.player()
    if membership(ctx):
        raise GameError("你已有队伍，请先退出。")
    cursor = ctx.repo.conn.execute("INSERT INTO teams(leader_id) VALUES (?)", (ctx.user_id,))
    team_id = cursor.lastrowid
    ctx.repo.conn.execute("INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (ctx.user_id, team_id))
    return Reply("灵契小队", (f"队伍编号：{team_id}，你是队长。",), ("灵宠队伍", "灵宠准备"))


def join(ctx: Context, arg: str) -> Reply:
    ctx.player()
    if membership(ctx):
        raise GameError("你已有队伍，请先退出。")
    leader = ctx.repo.player_by_name(arg)
    if leader:
        row = ctx.repo.conn.execute("SELECT team_id FROM teams WHERE leader_id=?", (leader.user_id,)).fetchone()
        if row is None:
            raise GameError("该道号当前没有带队。")
        team_id = row["team_id"]
    elif arg.isascii() and arg.isdigit():
        team_id = quantity(arg, 999999999)
    else:
        raise GameError("队伍不存在，请填写队长道号或队伍编号。")
    team = ctx.repo.conn.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
    if not team:
        raise GameError("队伍不存在。")
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM team_members WHERE team_id=?", (team_id,),
    ).fetchone()[0]
    if count >= ctx.content.rules.max_team_size:
        raise GameError("队伍已满。")
    ctx.repo.conn.execute("INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (ctx.user_id, team_id))
    return Reply("加入队伍", (f"已加入队伍 {team_id}。",), ("灵宠队伍", "灵宠准备", "灵宠退队"))


def status(ctx: Context, arg: str) -> Reply:
    member = membership(ctx)
    if not member:
        raise GameError("尚未组队，可发送 灵宠组队 或 灵宠入队 队长道号。")
    rows = ctx.repo.conn.execute(
        "SELECT * FROM team_members WHERE team_id=? ORDER BY user_id", (member["team_id"],),
    ).fetchall()
    lines = []
    for row in rows:
        pet = ctx.pet(row["user_id"])
        role = "队长" if row["user_id"] == member["leader_id"] else "队员"
        ready = "已准备" if row["ready_pet_id"] == pet.pet_id else "未准备"
        lines.append(f"{role} {ctx.player(row['user_id']).dao_name} · {pet.name} · {ready}")
    return Reply(f"灵契小队 {member['team_id']}", tuple(lines), ("灵宠准备", "灵宠取消准备", "灵宠组队挑战 上古灵殿"))


def ready(ctx: Context, arg: str) -> Reply:
    if not membership(ctx):
        raise GameError("尚未加入队伍。")
    pet = ctx.pet()
    ctx.repo.conn.execute("UPDATE team_members SET ready_pet_id=? WHERE user_id=?", (pet.pet_id, ctx.user_id))
    return Reply("出征准备", (
        f"{pet.name}已准备。队长下一次组队挑战将消耗本宠的精力并共享 PVE 冷却。",
        "本次战斗后、切宠或进行其他消耗精力的行动后，准备自动取消。",
    ), ("灵宠取消准备", "灵宠队伍"))


def unready(ctx: Context, arg: str) -> Reply:
    if not membership(ctx):
        raise GameError("尚未加入队伍。")
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("取消准备", ("已取消出征准备。",))


def leave(ctx: Context, arg: str) -> Reply:
    member = membership(ctx)
    if not member:
        raise GameError("尚未加入队伍。")
    if member["leader_id"] == ctx.user_id:
        ctx.repo.conn.execute("DELETE FROM teams WHERE team_id=?", (member["team_id"],))
        return Reply("小队解散", ("队长已离开，队伍解散。",))
    ctx.repo.conn.execute("DELETE FROM team_members WHERE user_id=?", (ctx.user_id,))
    return Reply("退出队伍", ("已离开队伍。",))


def challenge(ctx: Context, arg: str) -> Reply:
    member = membership(ctx)
    if not member or member["leader_id"] != ctx.user_id:
        raise GameError("仅队长可以发起组队挑战。")
    dungeon = named(ctx.content.dungeons, arg or "temple")
    if not dungeon.team:
        raise GameError("该秘境为单人秘境。")
    rows = ctx.repo.conn.execute(
        "SELECT * FROM team_members WHERE team_id=? ORDER BY user_id", (member["team_id"],),
    ).fetchall()
    if len(rows) < 2:
        raise GameError("组队挑战至少需要两名玩家。")
    for row in rows:
        if ctx.player(row["user_id"]).active_pet_id != row["ready_pet_id"]:
            raise GameError("全体成员准备后才能挑战。")
    return run_dungeon(ctx, dungeon, [row["user_id"] for row in rows])
