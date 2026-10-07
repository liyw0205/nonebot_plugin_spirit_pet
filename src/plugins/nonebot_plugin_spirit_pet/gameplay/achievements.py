import json
from dataclasses import asdict

from ..application.context import Context
from ..domain.achievement_content import Achievement
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity

COLLECTION_PAGE_SIZE = 9
ACHIEVEMENT_PAGE_SIZE = 5


def collection(ctx: Context, arg: str) -> Reply:
    page = quantity(arg or "1", 999)
    species = tuple(ctx.content.species.values())
    pages = max(1, (len(species) + COLLECTION_PAGE_SIZE - 1) // COLLECTION_PAGE_SIZE)
    if page > pages:
        raise GameError(f"灵宠收集共 {pages} 页。")
    owned = {
        row["species_id"] for row in ctx.repo.conn.execute(
            "SELECT DISTINCT species_id FROM pets WHERE user_id=?", (ctx.user_id,),
        )
    }
    entries = species[(page - 1) * COLLECTION_PAGE_SIZE:page * COLLECTION_PAGE_SIZE]
    commands = []
    if page > 1:
        commands.append(f"灵宠收集 {page - 1}")
    if page < pages:
        commands.append(f"灵宠收集 {page + 1}")
    commands.extend(("灵宠图鉴", "灵宠成就"))
    collected = len(owned & set(ctx.content.species))
    return Reply(f"灵宠收集 {page}/{pages}", (
        f"已收集 {collected}/{len(species)} 种",
        *(f"{entry.name} · {'已拥有' if entry.id in owned else '未收集'}" for entry in entries),
    ), tuple(commands))


def _metric(ctx: Context, user_id: str, metric: str) -> int:
    conn = ctx.repo.conn
    if metric == "species_collected":
        query, params = "SELECT COUNT(DISTINCT species_id) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "pets_owned":
        query, params = "SELECT COUNT(*) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_realm":
        query, params = "SELECT COALESCE(MAX(realm+1),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_layer":
        query, params = "SELECT COALESCE(MAX(realm*10+layer),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_bloodline":
        query, params = "SELECT COALESCE(MAX(bloodline),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "stage_clears":
        query, params = "SELECT COUNT(*) FROM pve_stage_progress WHERE user_id=?", (user_id,)
    elif metric == "pvp_wins":
        query, params = "SELECT COUNT(*) FROM pvp_results WHERE winner_id=?", (user_id,)
    elif metric == "pve_wins":
        query = (
            "SELECT COUNT(*) FROM battle_records b JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind IN ('pve','pve_stage') AND b.winner_side=p.side"
        )
        params = (user_id,)
    elif metric == "lineage_branches":
        query, params = "SELECT COUNT(DISTINCT lineage_id) FROM pets WHERE user_id=? AND lineage_id IS NOT NULL", (user_id,)
    elif metric == "skills_learned":
        query = "SELECT COUNT(DISTINCT s.skill_id) FROM learned_skills s JOIN pets p USING(pet_id) WHERE p.user_id=?"
        params = (user_id,)
    elif metric == "max_skill_level":
        query = "SELECT COALESCE(MAX(s.level),0) FROM learned_skills s JOIN pets p USING(pet_id) WHERE p.user_id=?"
        params = (user_id,)
    elif metric == "skill_level_sum":
        query = "SELECT COALESCE(SUM(s.level),0) FROM learned_skills s JOIN pets p USING(pet_id) WHERE p.user_id=?"
        params = (user_id,)
    else:
        raise ValueError(f"unknown achievement metric: {metric}")
    return int(conn.execute(query, params).fetchone()[0])


def _milestone(ctx: Context, metric: str, value: int) -> str:
    if metric == "max_realm":
        if value <= 0:
            return "尚未结契"
        return ctx.content.realms[min(value - 1, len(ctx.content.realms) - 1)].name
    if metric == "max_layer":
        if value <= 0:
            return "尚未结契"
        index, layer = divmod(value - 1, 10)
        return f"{ctx.content.realms[min(index, len(ctx.content.realms) - 1)].name}{layer + 1}层"
    if metric == "max_bloodline":
        return ctx.content.bloodlines[min(value, len(ctx.content.bloodlines) - 1)].name
    return str(value)


def _progress(ctx: Context, achievement: Achievement, value: int) -> str:
    shown = min(value, achievement.target)
    current = _milestone(ctx, achievement.metric, value)
    target = _milestone(ctx, achievement.metric, achievement.target)
    if achievement.metric in {"max_realm", "max_layer", "max_bloodline"}:
        return f"进度：{current} / {target}"
    return f"进度：{shown}/{achievement.target}"


def achievements(ctx: Context, arg: str) -> Reply:
    entries = tuple(ctx.content.achievements.values())
    page = quantity(arg or "1", 999)
    pages = max(1, (len(entries) + ACHIEVEMENT_PAGE_SIZE - 1) // ACHIEVEMENT_PAGE_SIZE)
    if page > pages:
        raise GameError(f"灵宠成就共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    claims = {
        row["achievement_id"] for row in ctx.repo.conn.execute(
            "SELECT achievement_id FROM achievement_claims WHERE user_id=?", (ctx.user_id,),
        )
    }
    selected = entries[(page - 1) * ACHIEVEMENT_PAGE_SIZE:page * ACHIEVEMENT_PAGE_SIZE]
    lines, commands = [], []
    for entry in selected:
        value = _metric(ctx, ctx.user_id, entry.metric) if player else 0
        claimed = entry.id in claims
        state = "已领取" if claimed else "可领奖" if value >= entry.target and player else "进行中"
        lines.extend((
            f"{entry.name} · {state} · {_progress(ctx, entry, value)}",
            entry.description,
        ))
        if value >= entry.target and not claimed and player:
            commands.append(f"灵宠成就领奖 {entry.name}")
    if page > 1:
        commands.append(f"灵宠成就 {page - 1}")
    if page < pages:
        commands.append(f"灵宠成就 {page + 1}")
    commands.append("灵宠收集")
    return Reply(f"灵宠成就 {page}/{pages}", tuple(lines), tuple(commands))


def _reply_from_row(row) -> Reply:
    value = json.loads(row["reply"])
    return Reply(value["title"], tuple(value["lines"]), tuple(value["commands"]))


def claim(ctx: Context, arg: str) -> Reply:
    prior = ctx.repo.achievement_claim_by_operation(ctx.operation_id)
    if prior is not None:
        if prior["user_id"] != ctx.user_id:
            raise GameError("该领奖消息已被其他身份处理，不能复用。")
        return _reply_from_row(prior)

    player = ctx.player()
    achievement = named(ctx.content.achievements, arg)
    if ctx.repo.achievement_claim(ctx.user_id, achievement.id) is not None:
        raise GameError("该成就奖励已领取，不能重复领取。")
    value = _metric(ctx, ctx.user_id, achievement.metric)
    if value < achievement.target:
        raise GameError(f"成就尚未完成：{achievement.description}")
    missing = set(achievement.reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"成就奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")

    item_snapshot = [
        {"item_id": item_id, "name": ctx.content.items[item_id].name, "amount": amount}
        for item_id, amount in achievement.reward.items.items()
    ]
    snapshot = {
        "achievement_id": achievement.id,
        "achievement_name": achievement.name,
        "metric": achievement.metric,
        "target": achievement.target,
        "progress_at_claim": value,
        "stones": achievement.reward.stones,
        "items": item_snapshot,
    }
    reply = Reply("成就奖励已领取", (
        f"{player.dao_name}完成成就：{achievement.name}。",
        achievement.description,
        f"灵石 +{achievement.reward.stones}。",
        *(f"{item['name']} +{item['amount']}" for item in item_snapshot),
    ), ("灵宠成就", "灵宠收集", "灵宠背包"))
    ctx.repo.record_achievement_claim(
        user_id=ctx.user_id,
        achievement_id=achievement.id,
        operation_id=ctx.operation_id,
        claimed_at=ctx.now,
        reward_snapshot=json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        reply=json.dumps(asdict(reply), ensure_ascii=False, separators=(",", ":")),
    )
    player.stones += achievement.reward.stones
    for item_id, amount in achievement.reward.items.items():
        ctx.repo.add_item(ctx.user_id, item_id, amount)
    return reply
