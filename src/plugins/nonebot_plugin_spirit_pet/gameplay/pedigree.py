"""Private, evidence-backed pet family trees and one-time family milestones."""

from collections import deque
import json
from dataclasses import asdict

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .pet_targets import pet_id


def read_only(argument: str) -> bool:
    return not argument.split() or argument.split()[0] != "领奖"


def _families(ctx: Context, user_id: str) -> dict:
    rows = ctx.repo.lineage_eggs(user_id)
    parents: dict[int, tuple[int, int]] = {}
    children: dict[int, list[dict]] = {}
    details: dict[int, tuple[str, str]] = {}
    neighbors: dict[int, set[int]] = {}
    for row in rows:
        child = int(row["child_pet_id"])
        parent_ids = (int(row["parent_a_id"]), int(row["parent_b_id"]))
        parents[child] = parent_ids
        details.setdefault(child, (str(row["child_name"]), str(row["species_id"])))
        details.setdefault(parent_ids[0], (str(row["parent_a_name"]), str(row["parent_a_species_id"])))
        details.setdefault(parent_ids[1], (str(row["parent_b_name"]), str(row["parent_b_species_id"])))
        for parent in parent_ids:
            children.setdefault(parent, []).append(dict(row))
            neighbors.setdefault(parent, set()).update((parent_ids[1] if parent == parent_ids[0] else parent_ids[0], child))
            neighbors.setdefault(child, set()).add(parent)

    nodes = set(neighbors)
    generation_cache: dict[int, int] = {}
    for node in sorted(nodes):
        parent_ids = parents.get(node)
        if parent_ids is None:
            generation_cache[node] = 0
            continue
        if any(parent >= node for parent in parent_ids):
            raise RuntimeError("pet pedigree contains a cycle or invalid pet ordering")
        generation_cache[node] = 1 + max(generation_cache[parent] for parent in parent_ids)

    families = []
    family_by_pet: dict[int, dict] = {}
    unseen = set(nodes)
    while unseen:
        start = min(unseen)
        component = set()
        pending = deque([start])
        while pending:
            current = pending.popleft()
            if current in component:
                continue
            component.add(current)
            unseen.discard(current)
            pending.extend(neighbors[current] - component)
        family = {
            "key": min(component),
            "members": component,
            "generations": max(generation_cache[node] for node in component),
        }
        families.append(family)
        for node in component:
            family_by_pet[node] = family
    return {
        "rows": [dict(row) for row in rows],
        "parents": parents,
        "children": children,
        "details": details,
        "families": families,
        "family_by_pet": family_by_pet,
    }


def family_members(ctx: Context, user_id: str) -> list[dict]:
    """Private, read-only family components derived only from hatched lineage evidence."""
    graph = _families(ctx, user_id)
    result = []
    for family in graph["families"]:
        result.append({
            "key": family["key"],
            "members": tuple(sorted(family["members"])),
            "generations": family["generations"],
            "edges": [row for row in graph["rows"] if row["child_pet_id"] in family["members"]],
            "details": {
                pet_id: graph["details"].get(pet_id, ("未知", ""))
                for pet_id in family["members"]
            },
        })
    return sorted(result, key=lambda family: family["key"])


def _milestone_state(ctx: Context, user_id: str, graph: dict) -> tuple[set[str], list[str]]:
    rows = ctx.repo.conn.execute(
        "SELECT milestone_id FROM pet_pedigree_claims WHERE user_id=?", (user_id,),
    ).fetchall()
    claimed = {str(row["milestone_id"]) for row in rows}
    claimable = []
    for milestone in ctx.content.pedigree_milestones.values():
        if milestone.id in claimed:
            continue
        if any(
            family["generations"] >= milestone.minimum_generation
            and len(family["members"]) >= milestone.minimum_members
            for family in graph["families"]
        ):
            claimable.append(milestone.name)
    return claimed, claimable


def claimable(ctx: Context, user_id: str) -> list[str]:
    _, values = _milestone_state(ctx, user_id, _families(ctx, user_id))
    return values


def objective_line(ctx: Context, user_id: str) -> str:
    graph = _families(ctx, user_id)
    claimed, available = _milestone_state(ctx, user_id, graph)
    if available:
        return f"灵宠谱系：可领取 {len(available)} 项家族里程碑"
    return (
        f"灵宠谱系：{len(graph['families'])} 个有凭证家族 · "
        f"已领 {len(claimed)}/{len(ctx.content.pedigree_milestones)} 项里程碑"
    )


def _overview(ctx: Context, arg: str = "1") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠谱系", (
            "尚未结契；召唤、收服、领养和旧灵卵不会推定亲缘。",
        ), ("灵宠帮助",))
    graph = _families(ctx, ctx.user_id)
    families = sorted(graph["families"], key=lambda family: family["key"])
    page = paginate(families, arg, "灵宠谱系", "灵宠谱系 家族", page_size=5)
    lines = [
        f"可验证家族 {len(families)} 个 · 双亲孵化记录 {len(graph['rows'])} 条。",
        "未登记的旧灵卵与召唤、收服伙伴仍为来源未知；不按库存数量推定亲缘。",
    ]
    links = []
    for family in page.entries:
        members = sorted(family["members"])
        lines.append(
            f"家族起点 #{family['key']} · {len(members)} 位有凭证伙伴 · "
            f"{family['generations']} 代已知关系。"
        )
        links.append(InlineCommand(
            len(lines) - 1, "查看成员谱系", f"灵宠谱系 {members[0]}",
        ))
    claimed, claimable = _milestone_state(ctx, ctx.user_id, graph)
    for milestone in ctx.content.pedigree_milestones.values():
        done = milestone.id in claimed
        ready = milestone.name in claimable
        state = "已领取" if done else ("可领取" if ready else "未达成")
        lines.append(
            f"{milestone.name} · 同族至少 {milestone.minimum_generation} 代、"
            f"{milestone.minimum_members} 位 · {state}。"
        )
        if ready:
            links.append(InlineCommand(
                len(lines) - 1, "领取", f"灵宠谱系 领奖 {milestone.id}",
            ))
    unknown = known = 0
    for item in ctx.content.items.values():
        if item.kind != "pet_egg":
            continue
        item_unknown, item_known = ctx.repo.egg_source_counts(ctx.user_id, item.id)
        unknown += item_unknown
        known += item_known
    lines.append(f"背包灵卵来源：未知 {unknown} 枚 · 可追溯 {known} 枚。")
    links.append(InlineCommand(len(lines) - 1, "亲子传习", "灵宠家族传习"))
    links.append(InlineCommand(len(lines) - 1, "亲子伴游", "灵宠亲子伴游"))
    links.append(InlineCommand(len(lines) - 1, "亲子合战", "灵宠亲子合战"))
    links.append(InlineCommand(len(lines) - 1, "三周联赛", "灵宠亲子合战 联赛"))
    commands = (*page.navigation, "灵宠家族试炼", "灵宠列表", "灵宠培育", "灵宠背包")
    return Reply(f"灵宠谱系 {page.number}/{page.total}", tuple(lines), commands, tuple(links))


def _related(graph: dict, pet: int, mode: str) -> list[int]:
    if mode == "祖辈":
        found = set()
        pending = list(graph["parents"].get(pet, ()))
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(graph["parents"].get(current, ()))
        return sorted(found)
    if mode == "后代":
        found = set()
        pending = [row["child_pet_id"] for row in graph["children"].get(pet, ())]
        while pending:
            current = int(pending.pop())
            if current in found:
                continue
            found.add(current)
            pending.extend(row["child_pet_id"] for row in graph["children"].get(current, ()))
        return sorted(found)
    raise ValueError("unsupported pedigree relation")


def _relationship_page(ctx: Context, graph: dict, target: int, mode: str, page_arg: str) -> Reply:
    family = graph["family_by_pet"][target]
    if mode == "记录":
        records = [row for row in graph["rows"] if int(row["child_pet_id"]) in family["members"]]
        page = paginate(records, page_arg, f"伙伴 {target} 谱系记录",
                        f"灵宠谱系 {target} 记录", page_size=6)
        lines = []
        for row in page.entries:
            lines.append(
                f"#{row['egg_record_id']} · {row['parent_a_name']}（#{row['parent_a_id']}）+ "
                f"{row['parent_b_name']}（#{row['parent_b_id']}）→ "
                f"{row['child_name']}（#{row['child_pet_id']}） · "
                f"培育 {row['created_at']} / 孵化 {row['finished_at']}。"
            )
        return Reply(
            f"灵宠谱系 · {target} · 记录 {page.number}/{page.total}",
            tuple(lines) or ("暂无可回顾的谱系记录。",),
            (*page.navigation, f"灵宠谱系 {target}", "灵宠列表"),
        )
    members = _related(graph, target, mode)
    page = paginate(members, page_arg, f"伙伴 {target} {mode}",
                    f"灵宠谱系 {target} {mode}", page_size=8)
    lines = []
    for member in page.entries:
        name, species = graph["details"].get(member, ("未知", ""))
        species_name = ctx.content.species[species].name if species in ctx.content.species else species
        lines.append(f"编号 {member}：{name} · {species_name}。")
    return Reply(
        f"灵宠谱系 · {target} · {mode} {page.number}/{page.total}",
        tuple(lines) or (f"没有已知{mode}记录。",),
        (*page.navigation, f"灵宠谱系 {target}", "灵宠列表"),
    )


def _pet_view(ctx: Context, parts: list[str]) -> Reply:
    target = pet_id(parts[0])
    owner = ctx.repo.conn.execute(
        "SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, target),
    ).fetchone()
    if owner is None:
        raise GameError("没有属于你的这只灵宠。")
    graph = _families(ctx, ctx.user_id)
    if target not in graph["family_by_pet"]:
        return Reply(f"灵宠谱系 · {target}", (
            "没有可验证的双亲或后代记录；来源未知，不会根据物品或伙伴数量补造关系。",
        ), ("灵宠谱系", "灵宠列表", f"灵宠整备 {target}"))
    mode = parts[1] if len(parts) > 1 else ""
    if mode in {"祖辈", "后代", "记录"}:
        if len(parts) > 3:
            raise GameError("格式：灵宠谱系 编号 祖辈|后代|记录 [页码]。")
        return _relationship_page(ctx, graph, target, mode, parts[2] if len(parts) == 3 else "1")
    if mode:
        raise GameError("格式：灵宠谱系 编号 [祖辈|后代|记录 [页码]]。")

    family = graph["family_by_pet"][target]
    name, species = graph["details"][target]
    species_name = ctx.content.species[species].name if species in ctx.content.species else species
    lines = [
        f"{name}（编号 {target}）· {species_name} · 家族 {len(family['members'])} 位 · "
        f"{family['generations']} 代已知关系。",
    ]
    parents = graph["parents"].get(target)
    if parents:
        row = next(row for row in graph["rows"] if int(row["child_pet_id"]) == target)
        lines.append(
            f"双亲：{row['parent_a_name']}（编号 {parents[0]}）与 "
            f"{row['parent_b_name']}（编号 {parents[1]}）。"
        )
    else:
        lines.append("这是当前凭证图中的最早可验证一代；其更早来源未知。")
    direct_children = sorted({
        int(row["child_pet_id"]) for row in graph["children"].get(target, ())
    })
    lines.append(f"已登记后代 {len(_related(graph, target, '后代'))} 位 · 直接后代 {len(direct_children)} 位。")
    return Reply(
        f"灵宠谱系 · {target}", tuple(lines),
        ("灵宠列表", "灵宠整备 " + str(target), "灵宠谱系"),
        (
            InlineCommand(1, "查看祖辈", f"灵宠谱系 {target} 祖辈"),
            InlineCommand(2, "查看后代", f"灵宠谱系 {target} 后代"),
            InlineCommand(2, "回顾记录", f"灵宠谱系 {target} 记录"),
        ),
    )


def _reward_text(ctx: Context, reward) -> str:
    pieces = [f"灵石 +{reward.stones}"] if reward.stones else []
    pieces.extend(f"{ctx.content.items[item_id].name} ×{amount}"
                  for item_id, amount in reward.items.items())
    return "、".join(pieces)


def claim(ctx: Context, arg: str) -> Reply:
    ctx.player()
    if not arg.strip():
        raise GameError("格式：灵宠谱系 领奖 档位。")
    key = arg.strip()
    milestone = next((
        entry for entry in ctx.content.pedigree_milestones.values()
        if key in {entry.id, entry.name}
    ), None)
    if milestone is None:
        raise GameError("没有这个家族里程碑，请先查看 灵宠谱系。")
    if ctx.repo.conn.execute(
        "SELECT 1 FROM pet_pedigree_claims WHERE user_id=? AND milestone_id=?",
        (ctx.user_id, milestone.id),
    ).fetchone():
        raise GameError(f"{milestone.name}已经领取。")
    graph = _families(ctx, ctx.user_id)
    if not any(
        family["generations"] >= milestone.minimum_generation
        and len(family["members"]) >= milestone.minimum_members
        for family in graph["families"]
    ):
        raise GameError(
            f"{milestone.name}尚未达成：同一已知家族需至少 "
            f"{milestone.minimum_generation} 代、{milestone.minimum_members} 位伙伴。"
        )
    player = ctx.player()
    reward = milestone.reward
    player.stones += reward.stones
    for item_id, amount in reward.items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    reward_snapshot = reward.model_dump()
    reply = Reply("灵宠谱系 · 里程碑", (
        f"达成「{milestone.name}」：同一已知家族达到 {milestone.minimum_generation} 代、"
        f"{milestone.minimum_members} 位。",
        f"获得{_reward_text(ctx, reward)}。",
    ), ("灵宠谱系", "灵宠背包", "我的信息"))
    ctx.repo.record_pedigree_operation(
        ctx.operation_id, ctx.user_id, "milestone_claim", ctx.now,
        {"milestone_id": milestone.id, "reward": reward_snapshot}, reply,
    )
    ctx.repo.conn.execute(
        "INSERT INTO pet_pedigree_claims(user_id,milestone_id,operation_id,claimed_at,reward_snapshot,reply) "
        "VALUES (?,?,?,?,?,?)",
        (ctx.user_id, milestone.id, ctx.operation_id, ctx.now,
         json.dumps(reward_snapshot, ensure_ascii=False),
         json.dumps(asdict(reply), ensure_ascii=False)),
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return _overview(ctx)
    if parts[0] == "领奖":
        if len(parts) != 2:
            raise GameError("格式：灵宠谱系 领奖 档位。")
        return claim(ctx, parts[1])
    if parts[0] == "家族":
        if len(parts) != 2:
            raise GameError("格式：灵宠谱系 家族 页码。")
        return _overview(ctx, parts[1])
    if not parts[0].isdecimal():
        raise GameError("格式：灵宠谱系 [家族 页码|宠物编号 [祖辈|后代|记录 [页码]]|领奖 档位]。")
    return _pet_view(ctx, parts)
