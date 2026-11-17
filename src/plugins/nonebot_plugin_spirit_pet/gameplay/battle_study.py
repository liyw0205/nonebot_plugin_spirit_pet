"""Per-pet opening-combat studies earned from successful roster relay stages."""

import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .pet_targets import pet_id as parse_pet_id

TITLE = "灵宠战研"
KIND = "partner_battle_study"
QUALIFIED_PREFIX = "relay_study_qualified_"
STUDY_PREFIX = "relay_study_"
BRANCHES = {
    "守御": ("guard", "守御", "开场护盾",
             "每级获得气血上限 5% 的开场护盾，持续该伙伴最初两次行动"),
    "强袭": ("assault", "强袭", "开场增攻",
             "每级获得攻击 4% 的开场增幅，持续该伙伴最初两次行动"),
}
COSTS = ((1, 30), (2, 60), (2, 100))
MAX_LEVEL = len(COSTS)


def _qualified_key(pet_id: int) -> str:
    return f"{QUALIFIED_PREFIX}{pet_id}"


def _study_key(pet_id: int, branch: str) -> str:
    return f"{STUDY_PREFIX}{pet_id}_{branch}"


def qualify(ctx: Context, pet_id: int) -> None:
    """Unlock only the pets that actually cleared a relay stage."""
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1) "
        "ON CONFLICT(user_id,quest_id) DO NOTHING",
        (ctx.user_id, _qualified_key(pet_id)),
    )


def qualified(ctx: Context, pet_id: int, user_id: str | None = None) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (user_id or ctx.user_id, _qualified_key(pet_id)),
    ).fetchone() is not None


def for_pet(ctx: Context, pet_id: int, user_id: str | None = None) -> tuple[str | None, int]:
    owner = user_id or ctx.user_id
    prefix = f"{STUDY_PREFIX}{pet_id}_"
    rows = ctx.repo.conn.execute(
        "SELECT quest_id,progress,claimed FROM quest_progress WHERE user_id=? "
        "AND substr(quest_id,1,?)=?",
        (owner, len(prefix), prefix),
    ).fetchall()
    if not rows:
        return None, 0
    if len(rows) != 1:
        raise GameError("伙伴战研记录重复，请联系管理员检查存档。")
    row = rows[0]
    suffix = str(row["quest_id"])[len(f"{STUDY_PREFIX}{pet_id}_"):]
    if (suffix not in {"guard", "assault"} or int(row["claimed"]) != 1
            or not 1 <= int(row["progress"]) <= MAX_LEVEL):
        raise GameError("伙伴战研记录无效，请联系管理员检查存档。")
    return suffix, int(row["progress"])


def _active_relay(ctx: Context) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT snapshot FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')='roster_relay' ORDER BY action_id DESC LIMIT 1",
        (ctx.user_id,),
    ).fetchone()
    if row is None:
        return False
    try:
        state = json.loads(row["snapshot"])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GameError("轮战记录损坏，暂不能调整战研。") from exc
    return state.get("status") == "active"


def _pet(ctx: Context, value: str):
    pet_id = parse_pet_id(value)
    row = ctx.repo.conn.execute(
        "SELECT user_id FROM pets WHERE pet_id=?", (pet_id,),
    ).fetchone()
    if row is None or row["user_id"] != ctx.user_id:
        raise GameError("没有找到属于你的这只伙伴。")
    pet = ctx.repo.pet(pet_id)
    if pet.archived:
        raise GameError(f"{pet.name}已封存，不能进行战研。")
    ctx.require_idle_pet(pet)
    return pet


def _cost_text(ctx: Context, level: int) -> str:
    ore, stones = COSTS[level]
    return f"锻灵矿 {ore}、灵石 {stones}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError(f"格式：{TITLE} [升级 <伙伴编号> <守御|强袭>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先完成领养。", "轮战胜场可为实际参战伙伴解锁开场战研。"),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    active = _active_relay(ctx)
    pets = sorted(ctx.repo.owned_pets(ctx.user_id), key=lambda pet: pet.pet_id)
    lines = ["轮战胜场解锁伙伴战研；仅本人且仍在册的伙伴可投入资源，每宠固定一个分支。"]
    links = []
    for pet in pets:
        branch = None
        level = 0
        has_qualification = qualified(ctx, pet.pet_id)
        if not has_qualification:
            state = "未解锁（需在轮战获胜）"
        else:
            branch, level = for_pet(ctx, pet.pet_id)
            if branch is None:
                state = "已解锁 · 未研习 · 首级消耗 " + _cost_text(ctx, 0)
            else:
                _, name, effect, description = next(
                    entry for entry in BRANCHES.values() if entry[0] == branch
                )
                state = f"{name} {level}/{MAX_LEVEL}级 · {effect} · {description}"
                if level < MAX_LEVEL:
                    state += f" · 下级消耗 {_cost_text(ctx, level)}"
                else:
                    state += " · 已满级"
        lines.append(f"{pet.name}（编号 {pet.pet_id}）· {state}")
        available = not active and not pet.archived and ctx.repo.active_expedition(pet.pet_id) is None
        if has_qualification and branch is None:
            for token, (_, name, _, description) in BRANCHES.items():
                lines.append(f"   编号 {pet.pet_id} · {name}：{description}。")
                if available:
                    links.append(InlineCommand(
                        len(lines) - 1, f"研习{name}", f"{TITLE} 升级 {pet.pet_id} {token}",
                    ))
        elif branch is not None and level < MAX_LEVEL and available:
            token = next(key for key, entry in BRANCHES.items() if entry[0] == branch)
            links.append(InlineCommand(
                len(lines) - 1, "继续研习", f"{TITLE} 升级 {pet.pet_id} {token}",
            ))
    if not pets:
        lines.append("名册中还没有伙伴。")
    if active:
        lines.append("轮战进行中：先完成或放弃本轮，再调整战研。")
        links.clear()
    return Reply(TITLE, tuple(lines), ("灵宠轮战", "灵宠目标", "我的灵宠"), tuple(links))


def upgrade(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 3 or parts[0] != "升级":
        raise GameError(f"格式：{TITLE} 升级 <伙伴编号> <守御|强袭>。")
    player = ctx.player()
    pet = _pet(ctx, parts[1])
    branch = BRANCHES.get(parts[2])
    if branch is None:
        raise GameError("战研分支只能选择 守御 或 强袭。")
    branch_id, name, effect, description = branch
    if _active_relay(ctx):
        raise GameError("轮战进行中不能调整战研，请先完成或放弃本轮。")
    if not qualified(ctx, pet.pet_id):
        raise GameError(f"{pet.name}尚未解锁战研，需先由{pet.name}实际参与并赢得轮战。")
    current_branch, level = for_pet(ctx, pet.pet_id)
    if current_branch is not None and current_branch != branch_id:
        current_name = next(entry[1] for entry in BRANCHES.values() if entry[0] == current_branch)
        raise GameError(f"{pet.name}已选择{current_name}分支；战研分支固定，不返还已投入资源。")
    if level >= MAX_LEVEL:
        raise GameError(f"{pet.name}{name}战研已达 {MAX_LEVEL} 级上限。")
    ore, stones = COSTS[level]
    inventory = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='forge_ore'",
        (ctx.user_id,),
    ).fetchone()
    available_ore = int(inventory["quantity"]) if inventory else 0
    if available_ore < ore:
        raise GameError(f"锻灵矿不足：需要 {ore}，当前 {available_ore}。")
    if player.stones < stones:
        raise GameError(f"灵石不足：需要 {stones}，当前 {player.stones}。")

    ctx.repo.consume_item(ctx.user_id, "forge_ore", ore)
    player.stones -= stones
    next_level = level + 1
    key = _study_key(pet.pet_id, branch_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress,claimed=1",
        (ctx.user_id, key, next_level),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    remaining = int(ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='forge_ore'",
        (ctx.user_id,),
    ).fetchone()["quantity"])
    reply = Reply(TITLE, (
        f"{pet.name}（编号 {pet.pet_id}）完成{name}战研 {next_level}/{MAX_LEVEL}级：{effect}。",
        description + "。",
        f"消耗锻灵矿 {ore}、灵石 {stones}；剩余锻灵矿 {remaining}、灵石 {player.stones}。",
        "效果只随该伙伴进入战斗，持续其最初两次行动；不会随领队切换转移。",
    ), (TITLE, "灵宠出战预设", "灵宠属性"))
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": KIND, "pet_id": pet.pet_id, "branch": branch_id, "level": next_level,
         "paid_ore": ore, "paid_stones": stones}, reply,
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "升级":
        return upgrade(ctx, arg)
    if parts[0] == "记录":
        if len(parts) != 1:
            raise GameError(f"格式：{TITLE} 记录。")
        records = ctx.repo.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')=? ORDER BY action_id DESC LIMIT 10",
            (ctx.user_id, KIND),
        ).fetchall()
        if not records:
            return Reply(TITLE, ("还没有战研记录。",), (TITLE, "灵宠轮战"))
        lines = ["最近战研消耗（新的在前）："]
        for row in records:
            state = json.loads(row["snapshot"])
            pet = ctx.repo.pet(int(state["pet_id"]))
            _, name, _, _ = next(entry for entry in BRANCHES.values() if entry[0] == state["branch"])
            lines.append(
                f"{pet.name}（编号 {pet.pet_id}）· {name} {state['level']}级"
                f" · 锻灵矿 {state['paid_ore']}、灵石 {state['paid_stones']}"
            )
        return Reply(TITLE + "记录", tuple(lines), (TITLE, "灵宠轮战"))
    raise GameError(f"格式：{TITLE} [升级 <伙伴编号> <守御|强袭>|记录]。")


def objective_line(ctx: Context, user_id: str) -> str:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id,progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id, f"{STUDY_PREFIX}%"),
    ).fetchall()
    qualified_pets = set()
    studied_pets = set()
    for row in rows:
        key = str(row["quest_id"])
        if key.startswith(QUALIFIED_PREFIX):
            qualified_pets.add(key[len(QUALIFIED_PREFIX):])
        elif key.startswith(STUDY_PREFIX):
            parts = key[len(STUDY_PREFIX):].rsplit("_", 1)
            if len(parts) == 2 and parts[0].isdecimal() and parts[1] in {"guard", "assault"}:
                studied_pets.add(parts[0])
    return f"战研：已解锁 {len(qualified_pets)} 只 · 已研习 {len(studied_pets)} 只"
