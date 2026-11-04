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
    checkin_rewards,
    codex_trials,
    daily_assignment,
    drill,
    expeditions,
    free_summon,
    mailbox,
    merchant,
    realm_milestone_rewards,
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
