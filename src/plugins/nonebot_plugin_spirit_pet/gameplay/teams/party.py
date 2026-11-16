import json

from ...application.context import Context
from ...domain.models import GameError, InlineCommand, Reply
from ...domain.state import Pet
from ...utils.arguments import named
from ...utils.pagination import paginate
from ...utils.time import cooldown_left
from ..adventure import run_dungeon
from ..cultivation import _available_energy
from .common import TEAM_HELP, add_member, membership, require_leader, require_member


def _can_ready(ctx: Context, active: list[Pet]) -> bool:
    """Ready is rejected while any roster pet is still out on an expedition."""
    return bool(active) and all(not pet.archived and ctx.repo.active_expedition(pet.pet_id) is None for pet in active)


def _roster(ctx: Context, user_id: str, leader_id: str) -> list[Pet]:
    active = ctx.repo.active_pets(user_id)
    return active if user_id == leader_id else active[:1]


def _roster_issue(ctx: Context, active: list[Pet]) -> tuple[str, str]:
    if not active:
        return "尚未出战", "灵宠列表"
    for pet in active:
        if pet.archived:
            return f"{pet.name}已封存，需复原", f"灵宠复原 {pet.pet_id}"
        expedition = ctx.repo.active_expedition(pet.pet_id)
        if expedition is not None:
            state = "正在派遣" if ctx.now < expedition["finishes_at"] else "派遣奖励待领取"
            return f"{pet.name}{state}", "灵宠行程"
    return "", ""


def _ready_ids(row) -> list[int]:
    value = row["ready_pet_ids"] if "ready_pet_ids" in row.keys() else ""
    if value:
        return [int(item) for item in json.loads(value)]
    return [int(row["ready_pet_id"])] if row["ready_pet_id"] is not None else []


def create(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    if membership(ctx):
        raise GameError("你已有队伍，请先退出。")
    cursor = ctx.repo.conn.execute("INSERT INTO teams(leader_id) VALUES (?)", (ctx.user_id,))
    team_id = cursor.lastrowid
    add_member(ctx, team_id, ctx.user_id)
    return Reply("灵契小队", (
        f"{player.uid_label}组建了小队，担任队长。",
        f"队伍容量：1/{ctx.content.rules.max_team_size}。",
    ), ("灵宠队伍", "灵宠队务", "灵宠准备", TEAM_HELP))


def status(ctx: Context, arg: str) -> Reply:
    member = require_member(ctx)
    if arg.split()[:1] == ["秘境"]:
        parts = arg.split()
        if len(parts) > 2:
            raise GameError("格式：灵宠队伍 秘境 [页码]。")
        return _dungeon_catalog(ctx, member, parts[1] if len(parts) == 2 else "")
    if arg:
        return _member_detail(ctx, member, arg)
    rows = ctx.repo.conn.execute(
        "SELECT m.*, identity.id AS player_internal_id FROM team_members m "
        "JOIN player_identity identity USING(user_id) "
        "WHERE m.team_id=? ORDER BY (m.user_id=?) DESC, identity.id",
        (member["team_id"], member["leader_id"]),
    ).fetchall()
    leader_name = ctx.player(member["leader_id"]).uid_label
    lines = [f"队伍容量：{len(rows)}/{ctx.content.rules.max_team_size}。"]
    own_ready = False
    own_active: list[Pet] = []
    all_ready = True
    # The capacity line carries the guide link, so help stays reachable without
    # spending one of the four button slots the page actions need.
    links = [InlineCommand(0, "组队指南", TEAM_HELP)]
    for row in rows:
        active = _roster(ctx, row["user_id"], member["leader_id"])
        role = "队长" if row["user_id"] == member["leader_id"] else "队员"
        ready_ids = _ready_ids(row)
        issue, recovery = _roster_issue(ctx, active)
        ready = not issue and ready_ids == [item.pet_id for item in active]
        roster = "、".join(item.name for item in active) or "无"
        uid_label = f"UID {row['player_internal_id'] + 9999}"
        lines.append(f"{role} {uid_label} · 出战 {roster} · {'已准备' if ready else '未准备'}"
                     + (f" · {issue}" if issue else ""))
        all_ready = all_ready and ready
        if row["user_id"] == ctx.user_id:
            own_ready = ready
            own_active = active
            if recovery:
                links.append(InlineCommand(len(lines) - 1, "整备伙伴", recovery))
        else:
            # Each other member links their own roster card; the row command leaves the
            # button set, so every member stays reachable under the four-button cap.
            links.append(InlineCommand(len(lines) - 1, "查看名帖", f"灵宠队伍 {uid_label}"))
    commands = ["灵宠队务"]
    if own_ready:
        commands.append("灵宠取消准备")
    elif _can_ready(ctx, own_active):
        commands.append("灵宠准备")
    if member["leader_id"] == ctx.user_id:
        # The business layer rejects a team run until every member is ready, so the
        # entry appears exactly when it can actually run.
        if len(rows) >= 2 and all_ready:
            commands.append("灵宠队伍 秘境")
        commands.append("灵宠解散")
    else:
        commands.extend(("灵宠退队", "灵宠秘境"))
    return Reply(f"{leader_name}的小队", tuple(lines), tuple(commands), tuple(links))


def _member_detail(ctx: Context, member, uid: str) -> Reply:
    player = ctx.repo.player_by_uid(uid)
    if player is None:
        raise GameError("没有找到这位玩家，请填写有效的 UID。")
    row = ctx.repo.conn.execute(
        "SELECT m.* FROM team_members m WHERE m.team_id=? AND m.user_id=?",
        (member["team_id"], player.user_id),
    ).fetchone()
    if row is None:
        raise GameError("这位玩家不在你的队伍中。")
    active = _roster(ctx, row["user_id"], member["leader_id"])
    role = "队长" if row["user_id"] == member["leader_id"] else "队员"
    ready_ids = _ready_ids(row)
    issue, recovery = _roster_issue(ctx, active)
    ready = not issue and ready_ids == [item.pet_id for item in active]
    commands = ["灵宠队伍", "灵宠队务"]
    if row["user_id"] == ctx.user_id:
        if ready:
            commands.append("灵宠取消准备")
        elif _can_ready(ctx, active):
            commands.append("灵宠准备")
    elif member["leader_id"] == ctx.user_id:
        commands.extend((f"灵宠踢人 {player.uid_label}", f"灵宠转让 {player.uid_label}"))
    links = [InlineCommand(1, "组队指南", TEAM_HELP)]
    if row["user_id"] == ctx.user_id and recovery:
        links.append(InlineCommand(2, "整备伙伴", recovery))
    return Reply(f"队员名帖 · {player.uid_label}", (
        f"队伍：{ctx.player(member['leader_id']).uid_label}的小队。",
        f"身份：{role}。", f"出战灵宠：{'、'.join(item.name for item in active) or '无'}"
        f" · {issue or ('已准备' if ready else '未准备')}。",
    ), tuple(commands), tuple(links))


def _dungeon_blocker(ctx: Context, member, rows, rosters, dungeon) -> str:
    if member["leader_id"] != ctx.user_id:
        return "请由队长发起挑战"
    if len(rows) < 2:
        return "至少需要两名玩家"
    if sum(len(active) for active in rosters.values()) > 5:
        return "组队最多出战五只灵宠"
    for row in rows:
        active = rosters[row["user_id"]]
        uid = ctx.player(row["user_id"]).uid_label
        issue, _ = _roster_issue(ctx, active)
        if issue:
            return f"{uid}：{issue}"
        if len({pet.species_id for pet in active}) != len(active):
            return f"{uid}的出战种族重复，请调整阵容"
        if _ready_ids(row) != [pet.pet_id for pet in active]:
            return f"{uid}尚未准备"
        remaining = cooldown_left(ctx.player(row["user_id"]).last_pve, ctx.now, ctx.config.spirit_pet_pve_cooldown)
        if remaining:
            return f"{uid}还需调息 {remaining} 秒"
        minimum = next(i for i, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm)
        for pet in active:
            if pet.realm < minimum:
                return f"{uid}的{pet.name}境界不足，需{ctx.content.realms[minimum].name}"
            if _available_energy(ctx, pet) < dungeon.energy:
                return f"{uid}的{pet.name}精力不足，需 {dungeon.energy} 点"
    return ""


def _dungeon_catalog(ctx: Context, member, arg: str) -> Reply:
    entries = sorted((dungeon for dungeon in ctx.content.dungeons.values() if dungeon.team), key=lambda dungeon: (
        next(i for i, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm), dungeon.id,
    ))
    page = paginate(entries, arg, "组队秘境", "灵宠队伍 秘境", page_size=5)
    rows = ctx.repo.conn.execute("SELECT * FROM team_members WHERE team_id=? ORDER BY user_id",
                                 (member["team_id"],)).fetchall()
    rosters = {row["user_id"]: _roster(ctx, row["user_id"], member["leader_id"]) for row in rows}
    lines, links = [], []
    for dungeon in page.entries:
        blocker = _dungeon_blocker(ctx, member, rows, rosters, dungeon)
        realm = next(realm.name for realm in ctx.content.realms if realm.id == dungeon.min_realm)
        lines.append(f"{dungeon.name} · {realm}起 · 每宠精力 {dungeon.energy} · {blocker or '可挑战'}")
        links.append(InlineCommand(len(lines) - 1, "查看详情", f"灵宠秘境 {dungeon.name}"))
        if not blocker:
            links.append(InlineCommand(len(lines) - 1, "发起挑战", f"灵宠组队挑战 {dungeon.name}"))
    return Reply(f"组队秘境 {page.number}/{page.total}", tuple(lines), (*page.navigation, "灵宠队伍", "灵宠任务"), tuple(links))


def ready(ctx: Context, arg: str) -> Reply:
    member = require_member(ctx)
    active = ctx.repo.active_pets(ctx.user_id)
    if ctx.user_id != member["leader_id"]:
        active = active[:1]
    for pet in active:
        if pet.archived:
            raise ctx.archived_active_pet(pet, ctx.user_id)
        ctx.require_idle_pet(pet)
    if not active:
        raise ctx.missing_pet()
    ctx.repo.conn.execute(
        "UPDATE team_members SET ready_pet_id=?, ready_pet_ids=? WHERE user_id=?",
        (active[0].pet_id, json.dumps([pet.pet_id for pet in active]), ctx.user_id),
    )
    return Reply("出征准备", (
        f"已准备 {len(active)} 只灵宠：{'、'.join(pet.name for pet in active)}。",
        "组队战斗最多五只灵宠；队长最多三只，每位队友出战一只。",
        "战斗后、切换阵容或改变参战能力后准备失效；成员或队长变化后全队需重新准备。",
    ), ("灵宠取消准备", "灵宠队伍", TEAM_HELP))


def unready(ctx: Context, arg: str) -> Reply:
    require_member(ctx)
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("取消准备", ("已取消出征准备。",), ("灵宠准备", "灵宠队伍", TEAM_HELP))


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
    from ..loadout import team_pets
    selected = team_pets(ctx, [row["user_id"] for row in rows], member["leader_id"])
    selected_by_user: dict[str, list[int]] = {}
    for user_id, pet in selected:
        selected_by_user.setdefault(user_id, []).append(pet.pet_id)
    for row in rows:
        expected = selected_by_user.get(row["user_id"], [])
        if _ready_ids(row) != expected:
            raise GameError("全体成员准备后才能挑战。")
    return run_dungeon(ctx, dungeon, [row["user_id"] for row in rows], member["leader_id"])
