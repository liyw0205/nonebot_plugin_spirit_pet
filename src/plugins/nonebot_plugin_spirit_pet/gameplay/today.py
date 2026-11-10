"""灵宠今日: one read-only page that answers "what can I do right now?".

The plugin has grown twenty-odd daily surfaces — check-in, the weekly free summon,
daily shop and assignments, the daily dungeon, unclaimed mail, milestone rewards,
the drill quota, the rotating codex trials, expeditions to collect, commissions to
deliver, market sales. They live on a dozen pages, so a returning player has to
remember all of them.

This module only *aggregates*: every entry is produced by asking the owning module
its own question through its public helper, and every entry links to the command that
actually does the work. Nothing here claims, delivers, collects or sweeps — opening
the page must not change a single row, because a digest that grants rewards would
become a second, silent path to every reward in the game.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from . import (
    affinity_milestone_rewards,
    banquet,
    bounty,
    cave,
    checkin_rewards,
    codex_trials,
    daily_assignment,
    daily_dungeon,
    daily_shop,
    drill,
    expeditions,
    free_summon,
    mailbox,
    market_standing,
    merchant,
    play_games,
    pet_outing,
    fishing,
    spar_goals,
    race,
    realm_milestone_rewards,
    research,
    sects,
    weekly_quests,
)

TITLE = "灵宠今日"
PAGE_SIZE = 8

CLAIM = "claim"
TODO = "todo"


def _entry(kind: str, label: str, detail: str, command: str) -> dict:
    return {"kind": kind, "label": label, "detail": detail, "command": command}


def _milestones(ctx: Context, user_id: str) -> list[dict]:
    """Milestone families whose ``claimable`` already means "state == 可领取"."""
    found = []
    for module, command, name in (
        (affinity_milestone_rewards, "灵宠亲密赏", "亲密"),
        (realm_milestone_rewards, "灵宠境界赏", "境界"),
    ):
        rewards = module.claimable(ctx, user_id)
        if rewards:
            found.append(_entry(
                CLAIM, f"{name}奖励 {len(rewards)} 项可领", "打开对应页面领取", command,
            ))
    return found


def collect(ctx: Context, user_id: str | None = None) -> tuple[list[dict], list[dict]]:
    """``(claimable, pending)`` — both read-only, both linked to a real command."""
    owner = user_id or ctx.user_id
    claimable: list[dict] = []
    pending: list[dict] = []

    if free_summon.available(ctx, owner):
        claimable.append(_entry(
            CLAIM, "每周免费十连可领", "本周还没用掉，召唤不消耗灵石", "灵宠每周召唤领取",
        ))

    letters = mailbox.inbox(ctx, owner)
    if letters:
        claimable.append(_entry(
            CLAIM, f"信箱 {len(letters)} 封待领取", "附件到齐后可在信箱自取", "灵宠信箱",
        ))

    claimable.extend(_milestones(ctx, owner))

    streaks = checkin_rewards.claimable(ctx, owner)
    if streaks:
        claimable.append(_entry(
            CLAIM, f"签到里程碑 {len(streaks)} 项可领", "连续签到已达成的奖励还没领", "灵宠签到奖励",
        ))
    assignments = daily_assignment.claimable(ctx, owner)
    if assignments:
        claimable.append(_entry(
            CLAIM, f"今日课题 {len(assignments)} 项已达标", "每天只能领其中一项", "灵宠课题领奖",
        ))
    if not checkin_rewards.signed_today(ctx, owner):
        pending.append(_entry(
            TODO, "今日还没签到", "签到累计连续天数并给灵石与灵粮", "灵宠签到",
        ))

    rows = expeditions.running_rows(ctx, owner)
    ready = [row for row in rows if row["finishes_at"] <= ctx.now]
    if ready:
        claimable.append(_entry(
            CLAIM, f"派遣 {len(ready)} 项已完成", "领取奖励后可再派出", "灵宠行程",
        ))

    open_orders = [
        entry for entry in merchant.todays(ctx, owner)
        if not merchant.delivered(ctx, entry, owner) and not merchant._missing(ctx, entry)
    ]
    if open_orders:
        claimable.append(_entry(
            CLAIM, f"商会 {len(open_orders)} 单可交付", "材料已备齐，交付即得灵石与声望", "灵宠商会",
        ))

    from . import merchant_contract

    running = merchant_contract.active(ctx, owner)
    if running is not None:
        index = merchant_contract.stage_index(ctx, owner)
        stage = running.stages[index - 1] if 1 <= index <= len(running.stages) else None
        owned = (
            stage is not None
            and all(
                merchant_contract._owned(ctx, item_id, owner) >= amount
                for item_id, amount in stage.items.items()
            )
        )
        if owned:
            claimable.append(_entry(
                CLAIM, f"大单第 {index} 段可交货", f"{running.name}，交齐有额外奖励", "灵宠商会 交货",
            ))
        else:
            pending.append(_entry(
                TODO, f"大单第 {index} 段待交货", f"{running.name}，期限 {running.days} 天", "灵宠商会 大单",
            ))

    shop_left = [
        offer for offer in daily_shop.offers(ctx)
        if daily_shop.bought(ctx, offer) < offer.stock
    ]
    if shop_left:
        pending.append(_entry(
            TODO, f"今日特供剩 {len(shop_left)} 件", "折扣限购，明日 00:00 换一批", "灵宠特供",
        ))

    standing_claimable = market_standing.claimable_list(ctx, owner)
    if standing_claimable:
        names = "、".join(e.name for e in standing_claimable)
        claimable.append(_entry(
            CLAIM, f"商路品阶可领：{names}", "累计成交已达里程碑，领取一次性奖励", "灵宠集市 掌柜",
        ))

    spar_ready = spar_goals.claimable(ctx, owner)
    if spar_ready:
        names = "、".join(goal[1] for goal in spar_ready)
        claimable.append(_entry(
            CLAIM, f"切磋目标可领：{names}", "本周切磋目标已达成", "灵宠切磋目标",
        ))

    casts_left = fishing.left_today(ctx, owner)
    if casts_left:
        pending.append(_entry(
            TODO, f"垂钓还剩 {casts_left} 竿", "详情可择饵偏向未集鱼获，消耗与所得记入鱼篓",
            "灵宠垂钓",
        ))

    outing_left = pet_outing.remaining_today(ctx, owner)
    if outing_left:
        pending.append(_entry(
            TODO, f"出游还剩 {outing_left} 只", "每只灵宠每天可出游一次，累计游历值与见闻",
            "灵宠出游",
        ))

    gaming_claimable = play_games.claimable(ctx, owner)
    if gaming_claimable:
        names = "、".join(f"{game.name} {milestone.at} 局" for game, milestone in gaming_claimable)
        claimable.append(_entry(
            CLAIM, f"嬉戏精通可领：{names}", "小游戏累计局数已达里程碑", "灵宠嬉戏 记录",
        ))

    dungeon = daily_dungeon.featured_dungeon(ctx.content, ctx.now)
    wins = daily_dungeon.wins_today(ctx, owner, dungeon.id)
    for label, claim, need in (
        ("首胜", daily_dungeon.FIRST_CLAIM, 1),
        ("三胜", daily_dungeon.THIRD_CLAIM, 3),
    ):
        if wins >= need and not daily_dungeon.claimed_today(ctx, owner, claim):
            claimable.append(_entry(
                CLAIM, f"今日秘境{label}可领", f"{dungeon.name} · 今日已胜 {wins} 场",
                "灵宠今日秘境领奖",
            ))
            break

    ready_bounties = [
        entry for entry in bounty.todays(ctx)
        if not bounty.claimed(ctx, entry, owner) and bounty.progress(ctx, entry, owner) >= entry.target
    ]
    if ready_bounties:
        claimable.append(_entry(
            CLAIM, f"赏金 {len(ready_bounties)} 份已达", "每日悬赏可分别领取", "灵宠赏金",
        ))

    if cave.remaining(ctx, owner):
        pending.append(_entry(
            TODO, f"洞府还剩 {cave.remaining(ctx, owner)} 次行动", "五处设施每日各一次", "灵宠洞府",
        ))
    if not cave.offered_today(ctx, owner):
        claimable.append(_entry(
            CLAIM, f"洞府供奉可领（{cave.tier(ctx, owner)} 档）", "每日一次，按繁荣档位发放", "灵宠洞府 供奉",
        ))
    if not banquet.held(ctx, owner):
        if banquet.ready(ctx, owner):
            claimable.append(_entry(
                CLAIM, "本周家宴可开席", "宴请全体伙伴并领取周奖励", "灵宠家宴 开席",
            ))
        else:
            pending.append(_entry(
                TODO, "本周家宴未开席", "厨艺、灵粮、灵石与灶火齐备后可开席", "灵宠家宴",
            ))

    sect = sects.current(ctx, owner)
    if sect is not None:
        if not sects.practiced_today(ctx, owner):
            pending.append(_entry(
                TODO, f"{sect.name}今日尚未修行", "修行得贡献与修为，每日一次", "灵宠师门",
            ))
        if sects.claimable(ctx, sect, owner):
            claimable.append(_entry(
                CLAIM, f"{sect.name}有阶位奖励可领", "贡献达标后逐阶领取", "灵宠师门",
            ))
        offers = sects.todays_missions(ctx, sect)
        done = sum(1 for mission in offers if sects.mission_claimed(ctx, mission, owner))
        if done < len(offers):
            pending.append(_entry(
                TODO, f"{sect.name}任务 {done}/{len(offers)}", "完成后交差换贡献与奖励", "灵宠师门 任务",
            ))
        if sects.weekly_claimable(ctx, owner):
            claimable.append(_entry(
                CLAIM, "师门周俸可领", "按本周贡献逐档领取", "灵宠师门 周俸",
            ))
        from . import sect_trial

        trial = sect_trial.trial_for(ctx, sect)
        if trial is not None and not sect_trial.cleared(ctx, trial, owner):
            pending.append(_entry(
                TODO, f"{sect.name}试炼本周未过", f"{trial.name}，每周一次", "灵宠师门 试炼",
            ))

    if race.remaining_today(ctx, owner):
        pending.append(_entry(
            TODO, f"竞速还剩 {race.remaining_today(ctx, owner)} 次", "按用时计成绩，不写战报", "灵宠竞速",
        ))

    if research.left_today(ctx, owner):
        pending.append(_entry(
            TODO, f"研习还剩 {research.left_today(ctx, owner)} 次", "为已携带灵术积累熟练度", "灵宠研习",
        ))

    weekly = [
        quest for quest in ctx.content.weekly_quests.values()
        if not weekly_quests.claimed_this_week(ctx, owner, quest.id)
        and weekly_quests._metric(ctx, owner, quest.metric) >= quest.target
    ]
    if weekly:
        claimable.append(_entry(
            CLAIM, f"周常 {len(weekly)} 项可领", "六项周度目标，按自然周重置", "灵宠周常领奖",
        ))

    left = drill.remaining(ctx, owner)
    if left:
        pending.append(_entry(
            TODO, f"演武还剩 {left} 次", "零精力验证阵容，不发奖励也不写战报", "灵宠演武",
        ))

    slots = codex_trials.weekly_slots(ctx)
    done = len(codex_trials.weekly_cleared(ctx, owner))
    if slots and done < len(slots):
        pending.append(_entry(
            TODO, f"每周图鉴试炼 {done}/{len(slots)}", "本周三场全清另有周奖", "灵宠图鉴试炼 每周",
        ))

    return claimable, pending


def page(ctx: Context, arg: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能查看今日待办。",
                "今日页只汇总各处能领的与还没做的，不代领也不代做。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    claimable, pending = collect(ctx)
    entries = claimable + pending
    if not entries:
        return Reply(TITLE, (
            "今天没有可领的奖励，也没有到点的行程。",
            "体力与次数花完后可以安心下线；明日 00:00（北京时间）会再刷新。",
            "想找能做的事：灵宠目标、灵宠演武、灵宠集市。",
        ), (TITLE, "灵宠目标", "灵宠帮助"))
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    number = quantity(arg or "1", 999)
    if number > pages:
        raise GameError(f"今日待办共 {pages} 页。")
    selected = entries[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]
    lines = [
        f"可领 {len(claimable)} 项 · 未做 {len(pending)} 项 · 第 {number}/{pages} 页。",
    ]
    links = []
    for item in selected:
        badge = "可领" if item["kind"] == CLAIM else "待做"
        lines.append(f"[{badge}] {item['label']} · {item['detail']}")
        links.append(InlineCommand(len(lines) - 1, "前往", item["command"]))
    lines.append("今日页只汇总入口，不代领；具体领取与消耗仍以各页面为准。")
    commands = [TITLE]
    if pages > 1:
        commands.append(f"{TITLE} {number + 1}" if number < pages else f"{TITLE} {number - 1}")
    commands.extend(("灵宠目标", "灵宠帮助"))
    return Reply(TITLE, tuple(lines), tuple(commands)[:4], tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    """Not surfaced: the digest is an index, and 灵宠目标 already lists every track."""
    return ""


__all__ = ["CLAIM", "PAGE_SIZE", "TITLE", "TODO", "collect", "dispatch", "page"]
