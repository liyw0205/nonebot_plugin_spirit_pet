import json
from dataclasses import asdict
from datetime import datetime

from ..application.context import Context
from ..domain.achievement_content import Achievement
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import BEIJING
from . import codex
from .equipment_set_rewards import SET_REWARDS, claim_id

COLLECTION_PAGE_SIZE = 9
ACHIEVEMENT_PAGE_SIZE = 5


def collection(ctx: Context, arg: str) -> Reply:
    page = quantity(arg or "1", 999)
    species = tuple(ctx.content.species.values())
    pages = max(1, (len(species) + COLLECTION_PAGE_SIZE - 1) // COLLECTION_PAGE_SIZE)
    if page > pages:
        raise GameError(f"灵宠收集共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    owned_counts = {
        row["species_id"]: row["amount"] for row in ctx.repo.conn.execute(
            "SELECT species_id, COUNT(*) AS amount FROM pets WHERE user_id=? GROUP BY species_id",
            (ctx.user_id,),
        )
    }
    owned = set(owned_counts)
    entries = species[(page - 1) * COLLECTION_PAGE_SIZE:page * COLLECTION_PAGE_SIZE]
    commands = []
    if page > 1:
        commands.append(f"灵宠收集 {page - 1}")
    if page < pages:
        commands.append(f"灵宠收集 {page + 1}")
    commands.extend(("灵宠图鉴", "灵宠成就", "灵宠图鉴奖励"))
    collected = len(owned & set(ctx.content.species))
    duplicate_species = sum(amount >= 2 for amount in owned_counts.values())
    lines = [f"已收集 {collected}/{len(species)} 种 · 同族复数 {duplicate_species} 种"]
    links = []
    claimable = 0
    for entry in entries:
        amount = owned_counts.get(entry.id, 0)
        # Reward state mirrors 灵宠图鉴奖励: claimed beats owned beats uncollected.
        if player is not None and codex.claimed(ctx, ctx.user_id, entry.id):
            status = "已领取"
        elif amount:
            status = f"已拥有（{amount}只）· 奖励可领取"
            claimable += 1
        else:
            status = "未收集"
        lines.append(f"{entry.name} · {status}")
        if amount and player is not None and status != "已领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取收集奖励", f"灵宠图鉴领奖 {entry.name}",
            ))
    if claimable:
        lines.append(f"本页有 {claimable} 族收集奖励可领取，也可在 灵宠图鉴奖励 逐页查看。")
    return Reply(f"灵宠收集 {page}/{pages}", (
        *lines,
    ), tuple(commands), tuple(links))


def _metric(ctx: Context, user_id: str, metric: str) -> int:
    conn = ctx.repo.conn
    if metric == "species_collected":
        query, params = "SELECT COUNT(DISTINCT species_id) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "duplicate_species":
        query = "SELECT COUNT(*) FROM (SELECT species_id FROM pets WHERE user_id=? GROUP BY species_id HAVING COUNT(*)>=2)"
        params = (user_id,)
    elif metric == "pets_owned":
        query, params = "SELECT COUNT(*) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_realm":
        query, params = "SELECT COALESCE(MAX(realm+1),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_layer":
        query, params = "SELECT COALESCE(MAX(realm*10+layer),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "max_bloodline":
        query, params = "SELECT COALESCE(MAX(bloodline),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "stage_clears":
        # Tower floors share the progress table, so chapter progress counts only chapters.
        query, params = (
            "SELECT COUNT(*) FROM pve_stage_progress WHERE user_id=? AND stage_id NOT LIKE 'tower_%'",
            (user_id,),
        )
    elif metric == "tower_depth":
        cleared = {
            row["stage_id"] for row in ctx.repo.conn.execute(
                "SELECT stage_id FROM pve_stage_progress WHERE user_id=? AND stage_id LIKE 'tower_%'",
                (user_id,),
            )
        }
        return max(
            (floor.order for floor in ctx.content.tower.values() if floor.id in cleared), default=0,
        )
    elif metric == "pvp_wins":
        query, params = "SELECT COUNT(*) FROM pvp_results WHERE winner_id=?", (user_id,)
    elif metric == "pve_wins":
        query = (
            "SELECT COUNT(*) FROM battle_records b JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind IN ('pve','pve_stage') AND b.winner_side=p.side"
        )
        params = (user_id,)
    elif metric == "team_pve_wins":
        query = (
            "SELECT COUNT(*) FROM battle_records b JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND p.permission='participant' "
            "AND b.kind IN ('pve','pve_stage') AND b.winner_side=p.side "
            "AND (SELECT COUNT(*) FROM battle_participants teammates "
            "WHERE teammates.battle_id=b.battle_id AND teammates.side=p.side "
            "AND teammates.permission='participant')>=2"
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
    elif metric == "expedition_claims":
        query, params = "SELECT COUNT(*) FROM expeditions WHERE user_id=? AND state='claimed'", (user_id,)
    elif metric == "max_affinity":
        query, params = "SELECT COALESCE(MAX(affinity),0) FROM pets WHERE user_id=?", (user_id,)
    elif metric == "best_bond_streak":
        query, params = "SELECT COALESCE(MAX(best_bond_streak),0) FROM players WHERE user_id=?", (user_id,)
    elif metric == "adventures_discovered":
        encounter_ids = tuple(ctx.content.encounters)
        placeholders = ",".join("?" for _ in encounter_ids)
        query = (
            f"SELECT COUNT(*) FROM adventure_discoveries WHERE user_id=? "
            f"AND encounter_id IN ({placeholders})"
        )
        params = (user_id, *encounter_ids)
    elif metric == "max_enhancement":
        # Equipped and stored items both carry a level; the best one counts.
        query = (
            "SELECT COALESCE(MAX(enhancement),0) FROM ("
            "SELECT e.enhancement AS enhancement FROM equipment e "
            "JOIN pets p USING(pet_id) WHERE p.user_id=? "
            "UNION ALL SELECT u.enhancement FROM unequipped_equipment u WHERE u.user_id=?)"
        )
        params = (user_id, user_id)
    elif metric == "spar_wins":
        query = (
            "SELECT COUNT(*) FROM battle_records b JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind='spar' AND b.winner_side=p.side"
        )
        params = (user_id,)
    elif metric == "battles_fought":
        query, params = "SELECT COUNT(*) FROM battle_participants WHERE user_id=?", (user_id,)
    elif metric == "equipment_owned":
        query = (
            "SELECT (SELECT COUNT(*) FROM equipment e JOIN pets p USING(pet_id) WHERE p.user_id=?) "
            "+ (SELECT COUNT(*) FROM unequipped_equipment WHERE user_id=?)"
        )
        params = (user_id, user_id)
    elif metric == "achievements_claimed":
        query, params = "SELECT COUNT(*) FROM achievement_claims WHERE user_id=?", (user_id,)
    elif metric == "resonances_enabled":
        query, params = "SELECT COUNT(*) FROM player_resonance WHERE user_id=?", (user_id,)
    elif metric in ("journey_claims", "echo_claims", "first_clear_claims"):
        # The three claim systems share the progress table, so each counts its own prefix.
        prefix = {"journey_claims": "journey_", "echo_claims": "echo_", "first_clear_claims": "first_clear_"}
        query, params = (
            "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 AND quest_id LIKE ?",
            (user_id, prefix[metric] + "%"),
        )
    elif metric == "equipment_set_claims":
        credentials = tuple(
            claim_id(set_id) for set_id in SET_REWARDS if set_id in ctx.content.equipment_sets
        )
        if not credentials:
            return 0
        placeholders = ",".join("?" for _ in credentials)
        query, params = (
            f"SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 "
            f"AND quest_id IN ({placeholders})",
            (user_id, *credentials),
        )
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
    if metric == "max_enhancement":
        return f"+{value}"
    return str(value)


def _progress_values(ctx: Context, metric: str, target_value: int, value: int) -> str:
    shown = min(value, target_value)
    current = _milestone(ctx, metric, value)
    target = _milestone(ctx, metric, target_value)
    if metric in {"max_realm", "max_layer", "max_bloodline", "max_enhancement"}:
        return f"进度：{current} / {target}"
    return f"进度：{shown}/{target_value}"


def _progress(ctx: Context, achievement: Achievement, value: int) -> str:
    return _progress_values(ctx, achievement.metric, achievement.target, value)


def _reward_summary(stones: int, items: list[dict[str, object]]) -> str:
    parts = [f"灵石 +{stones}"] if stones else []
    parts.extend(f"{item['name']} +{item['amount']}" for item in items)
    return "、".join(parts) or "无奖励"


def _preview_items(ctx: Context, achievement: Achievement) -> list[dict[str, object]]:
    return [
        {"item_id": item_id, "name": ctx.content.items[item_id].name, "amount": amount}
        for item_id, amount in achievement.reward.items.items()
    ]


def _saved_snapshot(row, achievement_id: str) -> dict:
    try:
        snapshot = json.loads(row["reward_snapshot"])
        valid = (
            isinstance(snapshot, dict)
            and snapshot.get("achievement_id") == achievement_id
            and isinstance(snapshot.get("achievement_name"), str)
            and isinstance(snapshot.get("metric"), str)
            and type(snapshot.get("target")) is int and snapshot["target"] > 0
            and type(snapshot.get("progress_at_claim")) is int and snapshot["progress_at_claim"] >= 0
            and type(snapshot.get("stones")) is int and snapshot["stones"] >= 0
            and isinstance(snapshot.get("items"), list)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and type(item.get("amount")) is int and item["amount"] > 0
                for item in snapshot["items"]
            )
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        valid = False
    if not valid:
        raise GameError("该成就领取记录暂不可回顾，请联系管理员检查存档。")
    return snapshot


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
    lines, commands, links = [], [], []
    for entry in selected:
        value = _metric(ctx, ctx.user_id, entry.metric) if player else 0
        claimed = entry.id in claims
        state = (
            "已领取" if claimed else "未结契" if not player
            else "可领奖" if value >= entry.target else "进行中"
        )
        status_line = len(lines)
        lines.extend((
            f"{entry.name} · {state} · {_progress(ctx, entry, value)}",
            f"条件：{entry.description}",
            f"奖励预览：{_reward_summary(entry.reward.stones, _preview_items(ctx, entry))}",
        ))
        detail_command = f"灵宠成就详情 {entry.name}"
        commands.append(detail_command)
        links.append(InlineCommand(status_line, "查看详情", detail_command))
        if value >= entry.target and not claimed and player:
            command = f"灵宠成就领奖 {entry.name}"
            commands.append(command)
            links.append(InlineCommand(status_line, "领取奖励", command))
    if page > 1:
        commands.append(f"灵宠成就 {page - 1}")
    if page < pages:
        commands.append(f"灵宠成就 {page + 1}")
    commands.append("灵宠收集")
    return Reply(f"灵宠成就 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    achievement = named(ctx.content.achievements, arg)
    player = ctx.repo.player(ctx.user_id)
    row = ctx.repo.achievement_claim(ctx.user_id, achievement.id)
    if row is not None:
        snapshot = _saved_snapshot(row, achievement.id)
        name = snapshot["achievement_name"]
        value = snapshot["progress_at_claim"]
        metric = snapshot["metric"]
        target = snapshot["target"]
        actual_items = snapshot["items"]
        reward_line = f"实际发放：{_reward_summary(snapshot['stones'], actual_items)}"
        claimed_at = datetime.fromtimestamp(row["claimed_at"], BEIJING).strftime("%Y-%m-%d %H:%M:%S")
        lines = (
            f"条件：{achievement.description}",
            f"领取状态：已领取 · 领取时{_progress_values(ctx, metric, target, value)}",
            f"领取时间：{claimed_at}（北京时间）",
            reward_line,
            "领取凭证：已永久保存",
        )
        return Reply(f"成就回顾 · {name}", lines, ("灵宠成就", "灵宠收集"))

    value = _metric(ctx, ctx.user_id, achievement.metric) if player else 0
    state = "可领奖" if player and value >= achievement.target else "进行中" if player else "未结契"
    command = f"灵宠成就领奖 {achievement.name}"
    commands = ["灵宠成就", "灵宠收集"]
    links = ()
    if player and value >= achievement.target:
        commands.insert(0, command)
        links = (InlineCommand(3, "领取奖励", command),)
    return Reply(f"成就详情 · {achievement.name}", (
        f"条件：{achievement.description}",
        f"领取状态：{state}",
        f"当前{_progress(ctx, achievement, value)}",
        f"奖励预览：{_reward_summary(achievement.reward.stones, _preview_items(ctx, achievement))}",
    ), tuple(commands), links)


def _reply_from_row(row) -> Reply:
    value = json.loads(row["reply"])
    return Reply.from_data(value)


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
        f"{player.uid_label}完成成就：{achievement.name}。",
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
