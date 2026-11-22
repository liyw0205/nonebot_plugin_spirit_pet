"""Asynchronous weekly shared boss encounters for the four sects."""

import json
from dataclasses import asdict
from datetime import date, datetime, time

from ..application.context import Context
from ..domain.battle_content import Skill
from ..domain.content import Enemy, Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.sect_boss_content import SectBoss
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from ..utils.time import BEIJING, beijing_day, beijing_week
from . import sects
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .rewards import grant

WEEK = 7 * 86_400
RANK_PAGE_SIZE = 8
HISTORY_PAGE_SIZE = 6
BATTLE_KEY_PREFIX = "sect_boss_"


def definitions(ctx: Context) -> list[SectBoss]:
    return sorted(ctx.content.sect_bosses.values(), key=lambda boss: boss.sect)


def boss_for(ctx: Context, sect_id: str) -> SectBoss | None:
    return next((boss for boss in definitions(ctx) if boss.sect == sect_id), None)


def _require_sect(ctx: Context):
    if ctx.repo.player(ctx.user_id) is None:
        raise GameError("尚未结契，先完成领养，才能参加师门共讨。")
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，先发送 灵宠师门 拜入 <门派>。")
    boss = boss_for(ctx, sect.id)
    if boss is None:
        raise GameError("本门暂无共讨首领内容。")
    return sect, boss


def _week_row(ctx: Context, sect_id: str, week_start: int):
    return ctx.repo.conn.execute(
        "SELECT * FROM sect_boss_weeks WHERE week_start=? AND sect_id=?",
        (week_start, sect_id),
    ).fetchone()


def _week_key(start: int, sect_id: str) -> str:
    return f"{BATTLE_KEY_PREFIX}{start}_{sect_id}"


def _combat_snapshot(ctx: Context, boss: SectBoss) -> str:
    enemy = ctx.content.enemies[boss.enemy]
    skill = ctx.content.skills.get(enemy.signature_skill) if enemy.signature_skill else None
    return json.dumps({
        "definition": boss.model_dump(mode="json"),
        "enemy": enemy.model_dump(mode="json"),
        "signature_skill": skill.model_dump(mode="json") if skill else None,
    }, ensure_ascii=False, separators=(",", ":"))


def _week_boss(ctx: Context, row, fallback: SectBoss | None = None) -> SectBoss:
    definition = json.loads(row["combat_snapshot"]).get("definition")
    if definition is not None:
        return SectBoss.model_validate(definition)
    return fallback or boss_for(ctx, row["sect_id"])


def _create_week(ctx: Context, sect, boss: SectBoss, week_start: int):
    # The first action in a new week closes any prior live instance at its exact boundary.
    ctx.repo.conn.execute(
        "UPDATE sect_boss_weeks SET state='expired', closed_at=week_start+? "
        "WHERE sect_id=? AND week_start<? AND state='active' AND current_hp>0",
        (WEEK, sect.id, week_start),
    )
    ctx.repo.conn.execute(
        "INSERT OR IGNORE INTO sect_boss_weeks(week_start,sect_id,enemy_id,boss_name,description,"
        "combat_snapshot,max_hp,current_hp,state,started_at,closed_at) "
        "VALUES (?,?,?,?,?,?,?,?, 'active', ?, NULL)",
        (
            week_start, sect.id, boss.enemy, boss.name, boss.description,
            _combat_snapshot(ctx, boss), boss.max_hp, boss.max_hp, ctx.now,
        ),
    )
    return _week_row(ctx, sect.id, week_start)


def _enemy_for(ctx: Context, row, current_hp: int):
    snapshot = json.loads(row["combat_snapshot"])
    enemy = Enemy.model_validate(snapshot["enemy"])
    stats = enemy.stats.model_copy(update={"hp": current_hp})
    enemy = enemy.model_copy(update={"stats": stats})
    skills = dict(ctx.content.skills)
    skill_snapshot = snapshot.get("signature_skill")
    if skill_snapshot is not None:
        skill = Skill.model_validate(skill_snapshot)
        skills[skill.id] = skill
    return enemy, skills


def _personal_damage(ctx: Context, start: int, sect_id: str, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COALESCE(SUM(damage),0) AS total FROM sect_boss_attacks "
        "WHERE week_start=? AND sect_id=? AND user_id=?",
        (start, sect_id, user_id),
    ).fetchone()
    return int(row["total"])


def _total_damage(ctx: Context, start: int, sect_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COALESCE(SUM(damage),0) AS total FROM sect_boss_attacks "
        "WHERE week_start=? AND sect_id=?",
        (start, sect_id),
    ).fetchone()
    return int(row["total"])


def _daily_attempts(ctx: Context, start: int, sect_id: str, user_id: str, day: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM sect_boss_attacks "
        "WHERE week_start=? AND sect_id=? AND user_id=? AND battle_day=?",
        (start, sect_id, user_id, day),
    ).fetchone()
    return int(row["total"])


def _ranking(ctx: Context, start: int, sect_id: str):
    return ctx.repo.conn.execute(
        "SELECT a.user_id, i.id AS identity_id, SUM(a.damage) AS damage, COUNT(*) AS attempts "
        "FROM sect_boss_attacks a JOIN player_identity i ON i.user_id=a.user_id "
        "WHERE a.week_start=? AND a.sect_id=? GROUP BY a.user_id,i.id "
        "ORDER BY SUM(a.damage) DESC,i.id ASC",
        (start, sect_id),
    ).fetchall()


def _rank_for(ctx: Context, start: int, sect_id: str, user_id: str) -> int | None:
    for rank, row in enumerate(_ranking(ctx, start, sect_id), 1):
        if row["user_id"] == user_id:
            return rank
    return None


def _claimed(ctx: Context, start: int, sect_id: str, user_id: str, scope: str, tier: int) -> bool:
    return ctx.repo.conn.execute(
        "SELECT 1 FROM sect_boss_claims WHERE week_start=? AND sect_id=? AND user_id=? AND scope=? AND tier=?",
        (start, sect_id, user_id, scope, tier),
    ).fetchone() is not None


def _claimable(ctx: Context, row, sect_id: str, user_id: str):
    start = int(row["week_start"])
    if not start + WEEK <= ctx.now < start + 2 * WEEK:
        return []
    personal = _personal_damage(ctx, start, sect_id, user_id)
    if personal <= 0:
        return []
    total = _total_damage(ctx, start, sect_id)
    result = []
    boss = _week_boss(ctx, row)
    if row["state"] == "defeated":
        for tier in boss.milestones:
            if total >= tier.total_damage and personal >= tier.member_damage and not _claimed(
                ctx, start, sect_id, user_id, "sect", tier.tier,
            ):
                result.append(("sect", tier.tier, tier.reward))
    for tier in boss.personal_tiers:
        if personal >= tier.damage and not _claimed(ctx, start, sect_id, user_id, "personal", tier.tier):
            result.append(("personal", tier.tier, tier.reward))
    return result


def _reward_label(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}"] if reward.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items() if bounds.minimum
    )
    return " · ".join(parts)


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 共讨 [挑战|榜 [页码]|个人战历 [页码]|战历 [页码]|领奖]。")
    sect, boss = _require_sect(ctx)
    start, end = beijing_week(ctx.now)
    row = _week_row(ctx, sect.id, start)
    if row is not None:
        boss = _week_boss(ctx, row, boss)
    total = _total_damage(ctx, start, sect.id)
    personal = _personal_damage(ctx, start, sect.id, ctx.user_id)
    rank = _rank_for(ctx, start, sect.id, ctx.user_id)
    used = _daily_attempts(ctx, start, sect.id, ctx.user_id, beijing_day(ctx.now))
    hp = boss.max_hp if row is None else int(row["current_hp"])
    state = "尚未开战" if row is None else (
        "已击败" if row["state"] == "defeated" else
        "自然周结束" if row["state"] == "expired" else "进行中"
    )
    lines = [
        f"{sect.name} · {boss.name}（北京时间自然周，每周一 00:00 开启新战）。",
        boss.description,
        f"本门首领：气血 {hp}/{boss.max_hp} · {state} · 门派本周伤害 {total}/{boss.max_hp}。",
        f"我的伤害 {personal} · 本周名次 {rank if rank is not None else '未上榜'} · 今日挑战 {used}/{boss.daily_attempts}。",
    ]
    links = []
    can_challenge = (row is None or row["state"] == "active") and used < boss.daily_attempts
    if can_challenge:
        lines.append("可派出当前出战阵容继续共讨；挑战消耗每只出战灵宠的精力并进入 PVE 调息。")
        links.append(InlineCommand(
            len(lines) - 1, "出战共讨", f"灵宠师门 共讨 挑战 {start} {sect.id}",
        ))
    elif row is not None and row["state"] == "defeated":
        lines.append("本门已击败首领，本周共讨结束。")
    elif used >= boss.daily_attempts:
        lines.append(f"今日共讨次数已用完，明日 00:00（北京时间）恢复。")
    else:
        lines.append("本周首领尚未开战。")

    if row is not None:
        claimed = {
            (claim["scope"], claim["tier"])
            for claim in ctx.repo.conn.execute(
                "SELECT scope,tier FROM sect_boss_claims WHERE week_start=? AND sect_id=? AND user_id=?",
                (start, sect.id, ctx.user_id),
            )
        }
        for tier in boss.milestones:
            eligible = row["state"] == "defeated" and total >= tier.total_damage and personal >= tier.member_damage
            marker = "已领取" if ("sect", tier.tier) in claimed else (
                "已达成，活动后续自然周开放领取" if eligible else f"全门 {total}/{tier.total_damage} · 个人 {personal}/{tier.member_damage}"
            )
            lines.append(f"全门里程碑 {tier.tier}：{_reward_label(ctx, tier.reward)} · {marker}")
        for tier in boss.personal_tiers:
            marker = "已领取" if ("personal", tier.tier) in claimed else (
                "个人伤害达标，活动后续自然周开放领取" if personal >= tier.damage
                else f"个人伤害 {personal}/{tier.damage}"
            )
            lines.append(f"个人伤害档 {tier.tier}：{_reward_label(ctx, tier.reward)} · {marker}")

    lines.append("查看本周 UID 排名。")
    links.append(InlineCommand(len(lines) - 1, "本周榜单", "灵宠师门 共讨 榜 1"))
    lines.append("查看本人每次共讨攻击与对应战报。")
    links.append(InlineCommand(len(lines) - 1, "个人战历", "灵宠师门 共讨 个人战历 1"))
    lines.append("查看已结束周的门派进度与公开 UID 排名。")
    links.append(InlineCommand(len(lines) - 1, "往期战历", "灵宠师门 共讨 战历 1"))
    lines.append("查看三周共讨联赛、锁定门派报名与跨周排名。")
    links.append(InlineCommand(len(lines) - 1, "三周联赛", "灵宠师门 共讨 联赛"))

    previous = _week_row(ctx, sect.id, start - WEEK)
    if previous is not None and _claimable(ctx, previous, sect.id, ctx.user_id):
        lines.append("上周共讨奖励已有档位可领，可一次领取全部已达档位。")
        links.append(InlineCommand(
            len(lines) - 1, "领取上周奖励",
            f"灵宠师门 共讨 领奖 活动 {start - WEEK} {sect.id}",
        ))
    return Reply("灵宠师门 · 共讨", tuple(lines), ("灵宠师门", "灵宠目标"), tuple(links))


def challenge(ctx: Context, arg: str = "") -> Reply:
    binding = arg.split()
    if binding and (
        len(binding) != 2 or not binding[0].isdecimal() or binding[1] not in ctx.content.sects
    ):
        raise GameError("格式：灵宠师门 共讨 挑战。")
    prior = ctx.repo.conn.execute(
        "SELECT initiator_id,kind,battle_key,reply FROM battle_records WHERE operation_id=?",
        (ctx.operation_id,),
    ).fetchone()
    if prior is not None:
        if prior["initiator_id"] != ctx.user_id:
            raise GameError("该战斗消息已被其他身份处理，不能复用。")
        if prior["kind"] != "pve_stage" or not prior["battle_key"].startswith(BATTLE_KEY_PREFIX):
            raise GameError("该战斗消息已被用于其他结算，不能复用。")
        return Reply.from_data(json.loads(prior["reply"]))
    if ctx.repo.conn.execute(
        "SELECT 1 FROM sect_boss_claims WHERE operation_id=? LIMIT 1", (ctx.operation_id,),
    ).fetchone() is not None:
        raise GameError("该操作号已用于共讨领奖，不能再挑战。")

    player = ctx.player()
    sect, boss = _require_sect(ctx)
    start, _ = beijing_week(ctx.now)
    if binding and (int(binding[0]) != start or binding[1] != sect.id):
        raise GameError("共讨入口已过期或门派已变化，请重新打开本周共讨页面。")
    from . import sect_boss_league

    sect_boss_league.before_challenge(ctx, start, sect.id)
    row = _week_row(ctx, sect.id, start)
    if row is not None:
        boss = _week_boss(ctx, row, boss)
    day = beijing_day(ctx.now)
    used = _daily_attempts(ctx, start, sect.id, ctx.user_id, day)
    if used >= boss.daily_attempts:
        raise GameError(f"今日师门共讨已达 {boss.daily_attempts} 次，明日 00:00（北京时间）再战。")

    selected = [(ctx.user_id, pet) for pet in ctx.active_pets(ctx.user_id)]
    checked = False
    for _, pet in selected:
        if not checked:
            ctx.check_action(player, pet, "pve", boss.energy, ctx.config.spirit_pet_pve_cooldown)
            checked = True
        else:
            ctx.require_idle_pet(pet)
            if pet.energy < boss.energy:
                raise GameError(f"{pet.name}精力不足，共讨需要 {boss.energy} 点。")

    if row is None:
        row = _create_week(ctx, sect, boss, start)
    if row["state"] == "defeated":
        raise GameError("本门本周已击败共讨首领，下周一 00:00 后开启新的共讨。")
    if row["state"] != "active":
        raise GameError("本门共讨自然周已结束，不能再追加伤害。")

    current_hp = int(row["current_hp"])
    enemy, skills = _enemy_for(ctx, row, current_hp)
    allies = [
        combatant(ctx, user_id, recover_energy=False, pet_id=pet.pet_id)
        for user_id, pet in selected
    ]
    enemies = [enemy_fighter(enemy, skills)]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id] * len(allies), []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements)
    if len(battle.remaining_hp) != 2 or len(battle.remaining_hp[1]) != 1:
        raise RuntimeError("battle result is missing the structured sect boss HP")
    battle_hp_after = battle.remaining_hp[1][0]
    if type(battle_hp_after) is not int or battle_hp_after < 0:
        raise RuntimeError("battle result has invalid sect boss HP")
    damage = min(current_hp, max(0, current_hp - battle_hp_after))
    current_after = current_hp - damage

    for _, pet in selected:
        pet.energy -= boss.energy
    player.last_pve = ctx.now
    ctx.repo.invalidate_ready(ctx.user_id)
    for _, pet in selected:
        award_mastery(ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id)

    new_state = "defeated" if current_after == 0 else "active"
    closed_at = ctx.now if new_state == "defeated" else None
    cursor = ctx.repo.conn.execute(
        "UPDATE sect_boss_weeks SET current_hp=?,state=?,closed_at=? "
        "WHERE week_start=? AND sect_id=? AND state='active' AND current_hp=?",
        (current_after, new_state, closed_at, start, sect.id, current_hp),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("sect boss HP changed during a serialized challenge")

    personal_total = _personal_damage(ctx, start, sect.id, ctx.user_id) + damage
    total = _total_damage(ctx, start, sect.id) + damage
    lines = [f"{sect.name}共讨 · {boss.name}：伤害 {damage}，当前气血 {current_after}/{boss.max_hp}。", *battle.lines]
    lines.append(f"我本周累计伤害 {personal_total} · 门派累计伤害 {total}。")
    if new_state == "defeated":
        lines.append("最后一击奏效，本门共讨首领已被击败；奖励将在活动结束后的下一个自然周开放领取。")
    else:
        lines.append("每只出战灵宠精力 -{0}；气血仅在本场战斗内结算。".format(boss.energy))
    title = "师门共讨 · 首领击败" if new_state == "defeated" else "师门共讨 · 战斗结算"
    reply = Reply(title, tuple(lines), ("灵宠师门 共讨", "灵宠战报", "灵宠目标"))
    battle_id = record_battle(
        ctx, kind="pve_stage", battle=battle, capture=capture, reply=reply,
        battle_key=_week_key(start, sect.id), battle_name=f"{sect.name}·{boss.name}",
    )
    ctx.repo.conn.execute(
        "INSERT INTO sect_boss_attacks(week_start,sect_id,user_id,battle_day,attempt,operation_id,battle_id,"
        "hp_before,hp_after,damage,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            start, sect.id, ctx.user_id, day, used + 1, ctx.operation_id, battle_id,
            current_hp, current_after, damage, ctx.now,
        ),
    )
    return reply


def ranking(ctx: Context, arg: str = "1") -> Reply:
    if len(arg.split()) > 1:
        raise GameError("格式：灵宠师门 共讨 榜 [页码]。")
    sect, boss = _require_sect(ctx)
    start, end = beijing_week(ctx.now)
    week = _week_row(ctx, sect.id, start)
    if week is not None:
        boss = _week_boss(ctx, week, boss)
    rows = _ranking(ctx, start, sect.id)
    page_data = paginate(rows, arg, "师门共讨榜", "灵宠师门 共讨 榜", RANK_PAGE_SIZE)
    lines = [
        f"{sect.name}共讨榜 {page_data.number}/{page_data.total} · "
        f"门派伤害 {_total_damage(ctx, start, sect.id)}/{boss.max_hp} · "
        f"{'暂定' if ctx.now < end else '结算'}。",
    ]
    offset = (page_data.number - 1) * RANK_PAGE_SIZE
    for index, row in enumerate(page_data.entries, offset + 1):
        lines.append(
            f"{index}. UID {int(row['identity_id']) + 9999} · 伤害 {row['damage']} · 挑战 {row['attempts']} 次"
        )
    if not page_data.entries:
        lines.append("本周尚无有效挑战。")
    personal_rank = _rank_for(ctx, start, sect.id, ctx.user_id)
    if personal_rank is not None:
        lines.append(f"我的名次：第 {personal_rank}。")
    commands = ("灵宠师门 共讨", *page_data.navigation)
    return Reply("灵宠师门 · 共讨榜", tuple(lines), commands)


def history(ctx: Context, arg: str = "1") -> Reply:
    if len(arg.split()) > 1:
        raise GameError("格式：灵宠师门 共讨 战历 [页码]。")
    sect, _ = _require_sect(ctx)
    current, _ = beijing_week(ctx.now)
    rows = ctx.repo.conn.execute(
        "SELECT * FROM sect_boss_weeks WHERE sect_id=? AND week_start<? ORDER BY week_start DESC",
        (sect.id, current),
    ).fetchall()
    page_data = paginate(rows, arg, "师门共讨战历", "灵宠师门 共讨 战历", HISTORY_PAGE_SIZE)
    lines = [f"{sect.name}共讨战历 {page_data.number}/{page_data.total} · 仅公开门派进度与 UID 排名。"]
    links = []
    offset = (page_data.number - 1) * HISTORY_PAGE_SIZE
    for index, row in enumerate(page_data.entries, offset + 1):
        damage = _total_damage(ctx, row["week_start"], sect.id)
        state = _state_label(row, ctx.now)
        week = datetime.fromtimestamp(row["week_start"], BEIJING).date().isoformat()
        lines.append(f"{index}. {week} · {row['boss_name']} · {state} · 伤害 {damage}/{row['max_hp']}。")
        links.append(InlineCommand(len(lines) - 1, "公开榜单", f"灵宠师门 共讨 往期 {week}"))
    if not page_data.entries:
        lines.append("尚无已结束的共讨活动。")
    return Reply(
        "灵宠师门 · 共讨战历", tuple(lines),
        ("灵宠师门 共讨", *page_data.navigation), tuple(links),
    )


def personal_history(ctx: Context, arg: str = "1") -> Reply:
    if len(arg.split()) > 1:
        raise GameError("格式：灵宠师门 共讨 个人战历 [页码]。")
    sect, _ = _require_sect(ctx)
    page_number = quantity(arg or "1", 999)
    total = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) AS total FROM sect_boss_attacks WHERE sect_id=? AND user_id=?",
        (sect.id, ctx.user_id),
    ).fetchone()["total"])
    pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    if page_number > pages:
        raise GameError(f"师门共讨个人战历共 {pages} 页。")
    rows = ctx.repo.conn.execute(
        "SELECT a.*, w.boss_name FROM sect_boss_attacks a "
        "JOIN sect_boss_weeks w ON w.week_start=a.week_start AND w.sect_id=a.sect_id "
        "WHERE a.sect_id=? AND a.user_id=? "
        "ORDER BY a.created_at DESC,a.attack_id DESC LIMIT ? OFFSET ?",
        (sect.id, ctx.user_id, HISTORY_PAGE_SIZE, (page_number - 1) * HISTORY_PAGE_SIZE),
    ).fetchall()
    lines = [f"{sect.name}个人共讨战历 {page_number}/{pages} · 仅显示本人攻击。"]
    links = []
    for row in rows:
        week = datetime.fromtimestamp(row["week_start"], BEIJING).date().isoformat()
        played = datetime.fromtimestamp(row["created_at"], BEIJING).strftime("%m-%d %H:%M")
        lines.append(
            f"{week} {played} · {row['boss_name']} · 第{row['attempt']}次 · "
            f"伤害 {row['damage']} · 气血 {row['hp_before']}→{row['hp_after']}。"
        )
        links.append(InlineCommand(
            len(lines) - 1, "查看战报", f"灵宠战报 查看 {row['battle_id']}",
        ))
    if not rows:
        lines.append("尚无个人共讨攻击记录。")
    navigation = []
    if page_number > 1:
        navigation.append(f"灵宠师门 共讨 个人战历 {page_number - 1}")
    if page_number < pages:
        navigation.append(f"灵宠师门 共讨 个人战历 {page_number + 1}")
    return Reply(
        "灵宠师门 · 个人共讨战历", tuple(lines),
        ("灵宠师门 共讨", *navigation), tuple(links),
    )


def _state_label(row, now: int) -> str:
    if row["state"] == "defeated":
        return "首领已败"
    if row["state"] == "expired" or now >= int(row["week_start"]) + WEEK:
        return "自然周结束"
    return "进行中"


def _parse_week(value: str) -> int:
    try:
        chosen = date.fromisoformat(value)
    except ValueError as exc:
        raise GameError("往期日期请使用周一日期 YYYY-MM-DD。") from exc
    if chosen.weekday() != 0:
        raise GameError("往期日期必须是北京时间周一 YYYY-MM-DD。")
    return int(datetime.combine(chosen, time.min, BEIJING).timestamp())


def past(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    try:
        date.fromisoformat(parts[0])
        date_first = True
    except (IndexError, ValueError):
        date_first = False
    if date_first and len(parts) in {1, 2}:
        current, _ = _require_sect(ctx)
        sect = current
        date_arg = parts[0]
        page_arg = parts[1] if len(parts) == 2 else "1"
    elif len(parts) in {2, 3}:
        name, date_arg = parts[:2]
        sect = next((item for item in sects.sects(ctx) if item.name == name or item.id == name), None)
        if sect is None:
            raise GameError("没有该门派。")
        page_arg = parts[2] if len(parts) == 3 else "1"
    else:
        raise GameError("格式：灵宠师门 共讨 往期 [门派名] YYYY-MM-DD [页码]。")
    start = _parse_week(date_arg)
    current_start, _ = beijing_week(ctx.now)
    if start >= current_start:
        raise GameError("只能查看已结束自然周的共讨归档。")
    row = _week_row(ctx, sect.id, start)
    if row is None:
        raise GameError(f"{sect.name}在 {date_arg} 没有共讨记录。")
    rows = _ranking(ctx, start, sect.id)
    page_command = f"灵宠师门 共讨 往期 {sect.id} {date_arg}"
    page_data = paginate(rows, page_arg, "师门共讨归档榜", page_command, RANK_PAGE_SIZE)
    lines = [
        f"公开归档 · {sect.name} · {row['boss_name']} · {_state_label(row, ctx.now)} · "
        f"榜单 {page_data.number}/{page_data.total}",
        f"门派总伤害 {_total_damage(ctx, start, sect.id)}/{row['max_hp']} · UID 排名。",
    ]
    offset = (page_data.number - 1) * RANK_PAGE_SIZE
    for rank, entry in enumerate(page_data.entries, offset + 1):
        lines.append(f"{rank}. UID {int(entry['identity_id']) + 9999} · 伤害 {entry['damage']} · 挑战 {entry['attempts']} 次")
    if not page_data.entries:
        lines.append("本周没有有效挑战。")
    return Reply(
        "师门共讨 · 公开归档", tuple(lines),
        ("灵宠师门 共讨", *page_data.navigation),
    )


def claimable(ctx: Context, user_id: str, sect_id: str | None = None):
    sect_id = sect_id or (sects.current(ctx, user_id).id if sects.current(ctx, user_id) else None)
    if sect_id is None:
        return []
    current, _ = beijing_week(ctx.now)
    row = _week_row(ctx, sect_id, current - WEEK)
    return [] if row is None else _claimable(ctx, row, sect_id, user_id)


def claim(ctx: Context, arg: str = "") -> Reply:
    prior = ctx.repo.conn.execute(
        "SELECT user_id,reply FROM sect_boss_claims WHERE operation_id=? ORDER BY scope,tier LIMIT 1",
        (ctx.operation_id,),
    ).fetchone()
    if prior is not None:
        if prior["user_id"] != ctx.user_id:
            raise GameError("该领奖操作已由其他身份处理，不能复用。")
        return Reply.from_data(json.loads(prior["reply"]))
    if ctx.repo.conn.execute(
        "SELECT 1 FROM battle_records WHERE operation_id=?", (ctx.operation_id,),
    ).fetchone() is not None:
        raise GameError("该操作号已用于战斗，不能再领取共讨奖励。")

    parts = arg.split()
    activity_binding = None
    if parts and parts[0] == "活动":
        if len(parts) < 3 or not parts[1].isdecimal() or parts[2] not in ctx.content.sects:
            raise GameError("共讨领奖入口已过期或格式错误，请重新打开本周页面。")
        activity_binding = (int(parts[1]), parts[2])
        parts = parts[3:]
    sect, _ = _require_sect(ctx)
    if len(parts) > 2 or (parts and parts[0] not in {"门派", "个人"}):
        raise GameError("格式：灵宠师门 共讨 领奖 [门派|个人 [档位]]；不写档位则领取该范围全部已达奖励。")
    scope = {"门派": "sect", "个人": "personal"}.get(parts[0]) if parts else None
    try:
        tier_filter = int(parts[1]) if len(parts) == 2 and parts[1].isdecimal() else None
    except ValueError:
        tier_filter = None
    if len(parts) == 2 and tier_filter is None:
        raise GameError("奖励档位必须是正整数。")

    current, _ = beijing_week(ctx.now)
    start = current - WEEK
    if activity_binding and activity_binding != (start, sect.id):
        raise GameError("共讨领奖入口已过期或门派已变化，请重新打开本周页面。")
    row = _week_row(ctx, sect.id, start)
    if row is None or not start + WEEK <= ctx.now < start + 2 * WEEK:
        raise GameError("当前没有处于领取周的师门共讨活动。")
    if row["state"] == "active" and int(row["current_hp"]) > 0:
        ctx.repo.conn.execute(
            "UPDATE sect_boss_weeks SET state='expired',closed_at=? "
            "WHERE week_start=? AND sect_id=? AND state='active' AND current_hp>0",
            (start + WEEK, start, sect.id),
        )
        row = _week_row(ctx, sect.id, start)

    rewards = _claimable(ctx, row, sect.id, ctx.user_id)
    if scope is not None:
        rewards = [entry for entry in rewards if entry[0] == scope]
    if tier_filter is not None:
        rewards = [entry for entry in rewards if entry[1] == tier_filter]
    if not rewards:
        raise GameError("没有符合条件的共讨奖励；需本周有效参战、达到对应伤害档，门派奖励还要求首领被击败。")

    lines = []
    snapshots = []
    for reward_scope, tier, reward in rewards:
        result = grant(ctx, reward, ctx.user_id)
        label = "全门里程碑" if reward_scope == "sect" else "个人伤害档"
        lines.append(f"{label} {tier} 已领取：{'，'.join(result)}。")
        snapshots.append((reward_scope, tier, reward.model_dump(mode="json")))
    reply = Reply("师门共讨奖励", tuple(lines), ("灵宠师门 共讨", "我的灵宠"))
    reply_data = json.dumps(asdict(reply), ensure_ascii=False, separators=(",", ":"))
    for reward_scope, tier, snapshot in snapshots:
        ctx.repo.conn.execute(
            "INSERT INTO sect_boss_claims(week_start,sect_id,user_id,scope,tier,operation_id,claimed_at,"
            "reward_snapshot,reply) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                start, sect.id, ctx.user_id, reward_scope, tier, ctx.operation_id, ctx.now,
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), reply_data,
            ),
        )
    return reply


def objective_line(ctx: Context, user_id: str) -> str | None:
    sect = sects.current(ctx, user_id)
    if sect is None:
        return None
    available = claimable(ctx, user_id, sect.id)
    if available:
        return f"师门共讨：上周有 {len(available)} 档奖励可领"
    boss = boss_for(ctx, sect.id)
    start, _ = beijing_week(ctx.now)
    row = _week_row(ctx, sect.id, start)
    if row is not None:
        boss = _week_boss(ctx, row, boss)
    if row is not None and row["state"] == "defeated":
        return f"师门共讨：{boss.name}已击败，等待下周奖励开放"
    hp = boss.max_hp if row is None else int(row["current_hp"])
    return f"师门共讨：{boss.name}气血 {hp}/{boss.max_hp}"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    head = parts[0]
    rest = " ".join(parts[1:])
    if head == "挑战":
        return challenge(ctx, rest)
    if head in {"榜", "排行"}:
        return ranking(ctx, rest or "1")
    if head in {"战历", "历史"}:
        return history(ctx, rest or "1")
    if head in {"个人战历", "个人历史"}:
        return personal_history(ctx, rest or "1")
    if head == "往期":
        return past(ctx, rest)
    if head == "领奖":
        return claim(ctx, rest)
    if head == "联赛":
        from . import sect_boss_league
        return sect_boss_league.dispatch(ctx, rest)
    raise GameError("格式：灵宠师门 共讨 [挑战 [周起点 门派]|榜 [页码]|个人战历 [页码]|战历 [页码]|往期 [门派名] YYYY-MM-DD [页码]|领奖]。")
