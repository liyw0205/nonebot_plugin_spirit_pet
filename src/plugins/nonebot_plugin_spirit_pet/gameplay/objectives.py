from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import season_bounds
from . import daily_assignment, daily_dungeon, echoes, first_clear, free_summon, journey, main_quest, quests, season_missions, titles, weekly_quests
from . import codex
from . import stage_stars
from .arena import tier_rewards as arena_tier_rewards
from . import checkin_rewards, companionship_rewards, companionship
from . import affinity_milestone_rewards
from . import bloodline_milestone_rewards
from . import equipment_set_rewards
from . import realm_milestone_rewards
from . import skill_mastery_rewards
from .achievements import _metric as achievement_metric

HUB_PAGES = (
    "灵宠签到奖励", "灵宠陪伴奖励", "灵宠任务", "灵宠今日秘境", "灵宠周常", "灵宠主线", "灵宠成就", "灵宠称号", "灵宠秘境首通",
    "灵宠每周召唤", "灵宠行纪", "灵宠回响", "灵宠赛季任务", "灵宠课题", "灵宠图鉴奖励", "灵宠关卡星级",
    "灵宠段位奖励",
    "灵宠血脉赏",
    "灵宠套装",
    "灵宠灵术赏",
    "灵宠亲密赏",
    "灵宠境界赏",
)


def _claim_line(name: str, claimable: list[str], total: int) -> str:
    if claimable:
        return f"{name}：可领 {len(claimable)} 项（{'、'.join(claimable)}）· 共 {total} 项"
    return f"{name}：暂无可领 · 共 {total} 项"


def _daily_line(ctx: Context, user_id: str) -> str:
    """Mirror `quests.quests`' claimable test over the shared progress table."""
    rows = {
        row["quest_id"]: row for row in ctx.repo.conn.execute(
            "SELECT * FROM quest_progress WHERE user_id=?", (user_id,),
        )
    }
    claimable = []
    for quest in ctx.content.quests.values():
        row = rows.get(quest.id)
        if row and row["claimed"]:
            continue
        if (row["progress"] if row else 0) >= quest.target:
            claimable.append(quest.name)
    return _claim_line("今日任务", claimable, len(ctx.content.quests))


def _checkin_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None:
        return "连续签到：尚未结契"
    streak = checkin_rewards.current_streak(ctx, player)
    best = checkin_rewards.best_streak(ctx, player)
    claimable = [
        f"{days} 天" for days, _, _, _ in checkin_rewards.MILESTONES
        if best >= days and not checkin_rewards._claimed(ctx, user_id, days)
    ]
    if claimable:
        return f"连续签到：可领 {len(claimable)} 档（{'、'.join(claimable)}）· 当前 {streak} 天/最佳 {best} 天"
    return f"连续签到：当前 {streak} 天 · 历史最佳 {best} 天"


def _bond_reward_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None:
        return "连续陪伴：尚未结契"
    current = companionship.active_bond_streak(player, ctx.now)
    best = player.best_bond_streak
    claimable = [
        f"{days} 天" for days, _, _, _ in companionship_rewards.MILESTONES
        if best >= days and not companionship_rewards._claimed(ctx, user_id, days)
    ]
    if claimable:
        return f"连续陪伴：可领 {len(claimable)} 档（{'、'.join(claimable)}）· 当前 {current} 天/最佳 {best} 天"
    return f"连续陪伴：当前 {current} 天 · 历史最佳 {best} 天"


def _weekly_line(ctx: Context, user_id: str) -> str:
    claimable = [
        quest.name for quest in ctx.content.weekly_quests.values()
        if not weekly_quests.claimed_this_week(ctx, user_id, quest.id)
        and weekly_quests._metric(ctx, user_id, quest.metric) >= quest.target
    ]
    return _claim_line("本周周常", claimable, len(ctx.content.weekly_quests))


def _main_quest_line(ctx: Context, user_id: str) -> str:
    claimed = main_quest._claimed(ctx, user_id)
    current = main_quest._current(ctx, user_id)
    if current is None:
        return f"主线：{len(ctx.content.main_quests)} 步全部完成"
    state, value = main_quest._state(ctx, user_id, current, claimed, current)
    return f"主线：下一步 {current.name} · {state}（{value}/{current.target}）"


def _achievement_line(ctx: Context, user_id: str) -> str:
    claims = {
        row["achievement_id"] for row in ctx.repo.conn.execute(
            "SELECT achievement_id FROM achievement_claims WHERE user_id=?", (user_id,),
        )
    }
    claimable = [
        entry.name for entry in ctx.content.achievements.values()
        if entry.id not in claims and achievement_metric(ctx, user_id, entry.metric) >= entry.target
    ]
    return _claim_line("成就", claimable, len(ctx.content.achievements))


def _dungeon_line(ctx: Context, user_id: str) -> str:
    dungeon = daily_dungeon.featured_dungeon(ctx.content, ctx.now)
    wins = daily_dungeon.wins_today(ctx, user_id, dungeon.id)
    states = " · ".join(
        f"{kind} {daily_dungeon._state(ctx, user_id, claim_id, wins)}"
        for kind, claim_id in daily_dungeon.CLAIM_KINDS.items()
    )
    return f"今日秘境：{dungeon.name} · {states}"


def _first_clear_line(ctx: Context, user_id: str) -> str:
    claimable = [
        dungeon.name for dungeon in ctx.content.dungeons.values()
        if first_clear._cleared(ctx, dungeon.id)
        and not first_clear.claimed(ctx, user_id, dungeon.id)
    ]
    total = len(ctx.content.dungeons)
    if claimable:
        return f"秘境首通：可领 {len(claimable)} 处（{'、'.join(claimable)}）· 共 {total} 处"
    return f"秘境首通：暂无可领 · 共 {total} 处"


def _arena_tier_line(ctx: Context, user_id: str) -> str:
    season_id, _, _ = season_bounds(ctx.now)
    score = arena_tier_rewards.season_rating(ctx, user_id, season_id)
    tiers = ctx.content.arena.tiers
    claimable = [
        tier.name for tier in tiers
        if score >= tier.minimum_rating
        and not arena_tier_rewards.claimed(ctx, user_id, season_id, tier.id)
    ]
    if claimable:
        return f"段位奖励：可领 {len(claimable)} 档（{'、'.join(claimable)}）· 当前积分 {score}"
    return f"段位奖励：暂无可领 · 当前积分 {score}"


def _stage_star_line(ctx: Context, user_id: str) -> str:
    reached = stage_stars.total(ctx, user_id)
    milestones = sorted(ctx.content.stage_star_rewards)
    claimable = [
        milestone for milestone in milestones
        if reached >= milestone and not stage_stars.claimed(ctx, user_id, milestone)
    ]
    maximum = stage_stars.FULL_STARS * len(ctx.content.stages)
    if claimable:
        joined = "、".join(f"{milestone} 星" for milestone in claimable)
        return f"关卡星级：可领 {len(claimable)} 档（{joined}）· 当前 {reached}/{maximum} 星"
    return f"关卡星级：暂无可领 · 当前 {reached}/{maximum} 星"


def _equipment_set_line(ctx: Context, user_id: str) -> str:
    entries = equipment_set_rewards.claimable(ctx, user_id)
    if entries:
        names = "、".join(entry.name for entry in entries)
        return f"套装完成奖励：可领 {len(entries)} 套（{names}）· 共 {len(ctx.content.equipment_sets)} 套"
    return f"套装完成奖励：暂无可领 · 共 {len(ctx.content.equipment_sets)} 套"


def _skill_mastery_line(ctx: Context, user_id: str) -> str:
    maximum = max(ctx.content.skill_levels)
    rows = ctx.repo.conn.execute(
        "SELECT p.pet_id, p.name AS pet_name, s.skill_id FROM pets p "
        "JOIN learned_skills s ON s.pet_id=p.pet_id WHERE p.user_id=? AND s.level=? "
        "ORDER BY p.pet_id, s.skill_id",
        (user_id, maximum),
    ).fetchall()
    claimable = []
    for row in rows:
        if not skill_mastery_rewards.claimed(ctx, user_id, row["pet_id"], row["skill_id"]):
            skill = ctx.content.skills.get(row["skill_id"])
            name = skill.name if skill else f"技能 {row['skill_id']}"
            claimable.append(f"{row['pet_name']}·{name}")
    if claimable:
        return f"灵术精进奖励：可领 {len(claimable)} 项（{'、'.join(claimable)}）· 五阶精通 {len(rows)} 项"
    return f"灵术精进奖励：暂无可领 · 五阶精通 {len(rows)} 项"


def _realm_milestone_line(ctx: Context, user_id: str) -> str:
    return realm_milestone_rewards.summary(ctx, user_id)


def _affinity_milestone_line(ctx: Context, user_id: str) -> str:
    return affinity_milestone_rewards.summary(ctx, user_id)


def _bloodline_milestone_line(ctx: Context, user_id: str) -> str:
    return bloodline_milestone_rewards.summary(ctx, user_id)


def _codex_line(ctx: Context, user_id: str) -> str:
    entries = tuple(ctx.content.species.values())
    owned = codex.collected(ctx, user_id)
    claimable = [
        species.name for species in entries
        if species.id in owned and not codex.claimed(ctx, user_id, species.id)
    ]
    claimed = sum(1 for species in entries if codex.claimed(ctx, user_id, species.id))
    if claimable:
        return f"图鉴奖励：可领 {len(claimable)} 族（{'、'.join(claimable)}）· 已领取 {claimed}/{len(entries)} 族"
    return f"图鉴奖励：暂无可领 · 已领取 {claimed}/{len(entries)} 族"


def _free_summon_line(ctx: Context, user_id: str) -> str:
    state = "可领取" if free_summon.available(ctx, user_id) else "本周已领取"
    return f"每周召唤：{state}"


def _journey_line(ctx: Context, user_id: str) -> str:
    entries = tuple(ctx.content.journey.values())
    claimable = [
        chapter.name for chapter in entries
        if journey._state(ctx, user_id, chapter) == "可领取"
    ]
    done = sum(1 for chapter in entries if journey._claimed(ctx, user_id, chapter.id))
    if claimable:
        return f"行纪：可领 {len(claimable)} 章（{'、'.join(claimable)}）· 已完成 {done}/{len(entries)} 章"
    return f"行纪：暂无可领 · 已完成 {done}/{len(entries)} 章"


def _echo_line(ctx: Context, user_id: str) -> str:
    rows = echoes._rows(ctx, user_id)
    pending = sum(1 for _, _, state in rows if state == "可回响")
    discovered = len({encounter.id for encounter, _, _ in rows})
    if pending:
        return f"回响：可回响 {pending} 项 · 已发现 {discovered}/{len(ctx.content.encounters)} 条奇闻"
    return f"回响：暂无可回响 · 已发现 {discovered}/{len(ctx.content.encounters)} 条奇闻"


def _season_line(ctx: Context, user_id: str) -> str:
    entries = tuple(ctx.content.season_missions.values())
    _, start, _ = season_missions.window(ctx)
    claimable = [
        mission.name for mission in entries
        if season_missions._state(ctx, user_id, mission, start) == "可领取"
    ]
    done = sum(1 for mission in entries if season_missions._claimed(ctx, user_id, mission.id, start))
    if claimable:
        return f"赛季任务：可领 {len(claimable)} 项（{'、'.join(claimable)}）· 已领取 {done}/{len(entries)} 项"
    return f"赛季任务：暂无可领 · 已领取 {done}/{len(entries)} 项"


def _assignment_line(ctx: Context, user_id: str) -> str:
    chosen = daily_assignment._chosen(ctx, user_id)
    if chosen is not None:
        return f"今日课题：今日已选「{chosen.name}」"
    offered = daily_assignment.todays(ctx)
    claimable = [
        entry.name for entry in offered
        if daily_assignment._value(ctx, user_id, entry) >= entry.target
    ]
    if claimable:
        return f"今日课题：可领 1 项（{'、'.join(claimable)}）· 今日三项任选其一"
    return "今日课题：暂无可领 · 今日三项任选其一"


def _title_line(ctx: Context, user_id: str) -> str:
    held = titles.earned(ctx, user_id)
    holder = held[-1][0] if held else None
    return f"称号：{holder.name if holder else '尚无'} · 已获得 {len(held)}/{len(ctx.content.titles)} 项"


def objectives(ctx: Context, arg: str) -> Reply:
    """One read-only page summarising every objective system's claimable state."""
    if arg.strip():
        raise GameError("灵宠目标 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠目标", (
            "尚未结契，先完成领养，就能在这里看到所有可领奖励。",
            "这里汇总每日、每周、成长、收集与套装奖励的领取状态。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    quests.refresh(ctx)
    lines = [
        _checkin_line(ctx, player.user_id),
        _bond_reward_line(ctx, player.user_id),
        _daily_line(ctx, player.user_id),
        _dungeon_line(ctx, player.user_id),
        _weekly_line(ctx, player.user_id),
        _main_quest_line(ctx, player.user_id),
        _achievement_line(ctx, player.user_id),
        _title_line(ctx, player.user_id),
        _first_clear_line(ctx, player.user_id),
        _free_summon_line(ctx, player.user_id),
        _journey_line(ctx, player.user_id),
        _echo_line(ctx, player.user_id),
        _season_line(ctx, player.user_id),
        _assignment_line(ctx, player.user_id),
        _codex_line(ctx, player.user_id),
        _stage_star_line(ctx, player.user_id),
        _arena_tier_line(ctx, player.user_id),
        _bloodline_milestone_line(ctx, player.user_id),
        _equipment_set_line(ctx, player.user_id),
        _skill_mastery_line(ctx, player.user_id),
        _affinity_milestone_line(ctx, player.user_id),
        _realm_milestone_line(ctx, player.user_id),
    ]
    links = tuple(
        InlineCommand(index, "前往", command) for index, command in enumerate(HUB_PAGES)
    )
    return Reply("灵宠目标", tuple(lines), ("灵宠帮助", "我的灵宠"), links)
