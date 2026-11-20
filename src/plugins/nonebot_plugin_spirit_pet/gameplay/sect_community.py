"""Shared weekly sect progress, derived from successful sect contribution awards."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.sect_content import Sect
from ..utils.time import beijing_week
from . import sects
from .rewards import grant

CLAIM_PREFIX = "sect_community_claim_"


def tiers(ctx: Context):
    return sorted(ctx.content.rules.sect.community_tiers, key=lambda tier: tier.tier)


def member_contribution(ctx: Context, sect: Sect, user_id: str | None = None) -> int:
    return ctx.repo.sect_week_contribution(
        week_start=beijing_week(ctx.now)[0], sect_id=sect.id, user_id=user_id or ctx.user_id,
    )


def total_contribution(ctx: Context, sect: Sect) -> int:
    return ctx.repo.sect_week_total(week_start=beijing_week(ctx.now)[0], sect_id=sect.id)


def record_contribution(ctx: Context, sect: Sect, amount: int) -> None:
    ctx.repo.add_sect_week_contribution(
        week_start=beijing_week(ctx.now)[0], sect_id=sect.id,
        user_id=ctx.user_id, amount=amount,
    )


def _claim_key(ctx: Context, sect: Sect, tier: int) -> str:
    return f"{CLAIM_PREFIX}{beijing_week(ctx.now)[0]}_{sect.id}_{tier}"


def claimed(ctx: Context, sect: Sect, tier: int, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, _claim_key(ctx, sect, tier)),
    ).fetchone()
    return bool(row and row["claimed"])


def claimable(ctx: Context, sect: Sect, user_id: str | None = None) -> list:
    total = total_contribution(ctx, sect)
    personal = member_contribution(ctx, sect, user_id)
    return [
        tier for tier in tiers(ctx)
        if total >= tier.total_contribution
        and personal >= tier.member_contribution
        and not claimed(ctx, sect, tier.tier, user_id)
    ]


def _reward_text(ctx: Context, reward) -> str:
    parts = []
    if reward.stones.minimum == reward.stones.maximum:
        if reward.stones.minimum:
            parts.append(f"灵石 {reward.stones.minimum}")
    elif reward.stones.maximum:
        parts.append(f"灵石 {reward.stones.minimum}-{reward.stones.maximum}")
    for item_id, bounds in reward.items.items():
        quantity = (
            str(bounds.minimum) if bounds.minimum == bounds.maximum
            else f"{bounds.minimum}-{bounds.maximum}"
        )
        parts.append(f"{ctx.content.items[item_id].name} {quantity}")
    return " · ".join(parts) if parts else "无奖励"


def summary_line(ctx: Context, sect: Sect, user_id: str | None = None) -> str:
    total = total_contribution(ctx, sect)
    personal = member_contribution(ctx, sect, user_id)
    next_tier = next((tier for tier in tiers(ctx) if total < tier.total_contribution), None)
    if next_tier is None:
        progress = f"共修 {total}（已达本周最高课题）"
    else:
        progress = f"共修 {total}/{next_tier.total_contribution}"
    return f"{progress} · 我的贡献 {personal}"


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠师门 共修 [领奖 档位|全部]。")
    if ctx.repo.player(ctx.user_id) is None:
        raise GameError("尚未结契，先完成领养，才能参加师门共修。")
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，先发送 灵宠师门 拜入 <门派>。")

    total = total_contribution(ctx, sect)
    personal = member_contribution(ctx, sect)
    config = ctx.content.rules.sect
    lines = [
        f"{sect.name} · {config.community_title}（周一 00:00 北京时间刷新）。",
        config.community_description,
        f"本周同门进度：{total} · 我的贡献：{personal}。",
    ]
    links = []
    for tier in tiers(ctx):
        if claimed(ctx, sect, tier.tier):
            state = "已领取"
        elif total < tier.total_contribution:
            state = f"同门未达（{total}/{tier.total_contribution}）"
        elif personal < tier.member_contribution:
            state = f"个人未达（{personal}/{tier.member_contribution}）"
        else:
            state = "可领取"
        lines.append(
            f"{tier.tier} 阶 · 同门 {tier.total_contribution} · 本人 {tier.member_contribution}"
            f" · {_reward_text(ctx, tier.reward)} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, f"领取{tier.tier}阶", f"灵宠师门 共修 领奖 {tier.tier}",
            ))
    pending = claimable(ctx, sect)
    if len(pending) > 1:
        lines.append(f"可一次领取 {len(pending)} 档课题奖励。")
        links.append(InlineCommand(
            len(lines) - 1, "全部领取", "灵宠师门 共修 领奖 全部",
        ))
    return Reply("师门共修", tuple(lines), ("灵宠师门", "灵宠师门 共修"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if not value:
        raise GameError("格式：灵宠师门 共修 领奖 <档位|全部>。")
    if ctx.repo.player(ctx.user_id) is None:
        raise GameError("尚未结契，先完成领养，才能领取师门共修奖励。")
    sect = sects.current(ctx)
    if sect is None:
        raise GameError("尚未拜入师门，不能领取师门共修奖励。")

    all_tiers = tiers(ctx)
    if value == "全部":
        selected = claimable(ctx, sect)
        if not selected:
            raise GameError("暂无可领的师门共修奖励；需同门达标且本人达到参与门槛。")
    else:
        if not value.isdigit():
            raise GameError("格式：灵宠师门 共修 领奖 <档位|全部>。")
        tier = next((entry for entry in all_tiers if entry.tier == int(value)), None)
        if tier is None:
            raise GameError(f"师门共修只有 {len(all_tiers)} 阶课题。")
        if claimed(ctx, sect, tier.tier):
            raise GameError(f"本周师门共修 {tier.tier} 阶奖励已经领取。")
        total = total_contribution(ctx, sect)
        personal = member_contribution(ctx, sect)
        if total < tier.total_contribution:
            raise GameError(
                f"同门共修进度不足：{tier.total_contribution}，当前 {total}。",
            )
        if personal < tier.member_contribution:
            raise GameError(
                f"本人共修贡献不足：需要 {tier.member_contribution}，当前 {personal}。",
            )
        selected = [tier]

    lines = []
    for tier in selected:
        lines.append(f"{tier.tier} 阶：" + "，".join(grant(ctx, tier.reward)) + "。")
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (ctx.user_id, _claim_key(ctx, sect, tier.tier)),
        )
    lines.append(summary_line(ctx, sect))
    return Reply("师门共修 · 领奖", tuple(lines), ("灵宠师门 共修", "灵宠师门"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split(maxsplit=1)
    if not parts:
        return page(ctx)
    if parts[0] == "领奖":
        return claim(ctx, parts[1] if len(parts) == 2 else "")
    raise GameError("格式：灵宠师门 共修 [领奖 档位|全部]。")
