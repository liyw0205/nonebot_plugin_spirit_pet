"""Weighted fishing, optional bait and atomic collection/ledger settlement."""

from copy import copy

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.fishing_content import FishingBait, FishingSpot
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .rewards import grant as _grant

CAST_PREFIX = "fishing_day_"
CATCH_PREFIX = "fish_"
SET_PREFIX = "fishing_set_"
CASTS_PER_DAY = 3
PAGE_SIZE = 5
SPOT_BONUS = (150, {"spirit_food": 1})
ALL_BONUS = (500, {"exp_pill": 1})


def spots(ctx: Context) -> list[FishingSpot]:
    return list(ctx.content.fishing_spots.values())


def _spot(ctx: Context, name: str) -> FishingSpot:
    return named(ctx.content.fishing_spots, name)


def used_today(ctx: Context, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{CAST_PREFIX}{beijing_day(ctx.now)}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def left_today(ctx: Context, user_id: str | None = None) -> int:
    return max(0, CASTS_PER_DAY - used_today(ctx, user_id))


def caught(ctx: Context, spot: FishingSpot, user_id: str | None = None) -> set[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{CATCH_PREFIX}{spot.id}_%"),
    ).fetchall()
    prefix = f"{CATCH_PREFIX}{spot.id}_"
    return {row["quest_id"][len(prefix):] for row in rows}


def total_caught(ctx: Context, user_id: str | None = None) -> int:
    return sum(len(caught(ctx, spot, user_id)) for spot in spots(ctx))


def _voucher(ctx: Context, key: str, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return bool(row and row["claimed"])


def _pay(ctx: Context, key: str, stones: int, items: dict[str, int], label: str) -> list[str]:
    if _voucher(ctx, key):
        return []
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in items.items()
        },
    )
    lines = [label]
    lines.extend(_grant(ctx, reward, ctx.user_id))
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (ctx.user_id, key),
    )
    return lines


def _spot_complete(ctx: Context, spot: FishingSpot) -> bool:
    return len(caught(ctx, spot)) >= len(spot.catches)


def _settle_sets(ctx: Context) -> list[str]:
    """Pay any spot/all bonus the current 鱼获 record has just completed."""
    lines: list[str] = []
    for spot in spots(ctx):
        if _spot_complete(ctx, spot):
            lines.extend(_pay(
                ctx, f"{SET_PREFIX}{spot.id}", SPOT_BONUS[0], SPOT_BONUS[1],
                f"鱼获「{spot.name}」集齐：",
            ))
    if all(_spot_complete(ctx, spot) for spot in spots(ctx)):
        lines.extend(_pay(
            ctx, f"{SET_PREFIX}all", ALL_BONUS[0], ALL_BONUS[1], "三处水系鱼获全齐：",
        ))
    return lines


def bait_for(ctx: Context, spot: FishingSpot, name: str = "") -> FishingBait | None:
    if not name or name in ("素饵", "plain"):
        return None
    bait = named(ctx.content.fishing_baits, name)
    if not any(entry.item in bait.favored_items for entry in spot.catches):
        raise GameError(f"{bait.name}在{spot.name}没有偏向鱼获，请选择其他饵料。")
    return bait


def weights(spot: FishingSpot, bait: FishingBait | None) -> list[int]:
    return [
        entry.weight * (bait.multiplier if bait and entry.item in bait.favored_items else 1)
        for entry in spot.catches
    ]


def preview_pet(ctx: Context):
    player = ctx.repo.player(ctx.user_id)
    if player is None or player.active_pet_id is None:
        return None
    pet = ctx.repo.pet(player.active_pet_id)
    if pet.archived:
        return None
    pet = copy(pet)
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    return pet


def block_reason(ctx: Context, spot: FishingSpot, pet, bait: FishingBait | None = None) -> str:
    if ctx.repo.player(ctx.user_id) is None:
        return "尚未结契，先完成领养"
    if pet is None:
        return "尚未选择可用出战伙伴"
    if pet.realm < spot.realm:
        return f"需要{ctx.content.realms[spot.realm].name}"
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        return "正在外出派遣" if ctx.now < expedition["finishes_at"] else "派遣奖励待领取"
    if left_today(ctx) <= 0:
        return "今日竿数已用完"
    if pet.energy < spot.energy:
        return f"精力不足（需 {spot.energy}）"
    if bait and ctx.repo.inventory(ctx.user_id).get(bait.cost_item, 0) < bait.cost_quantity:
        return f"{ctx.content.items[bait.cost_item].name}不足（需 {bait.cost_quantity}）"
    return ""


def catalog(ctx: Context, arg: str = "") -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠垂钓",
            (
                "三处水系各自有鱼获表：溪口、深潭、灵渊。",
                "尚未结契，先完成领养，再带伙伴去水边。",
            ),
            ("灵宠帮助",),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    pet = preview_pet(ctx)
    page_data = paginate(spots(ctx), arg, "灵宠垂钓", "灵宠垂钓", PAGE_SIZE)
    lines = [
        (f"{pet.name} 精力 {pet.energy}" if pet else "尚未选择可用出战伙伴")
        + f" · 今日剩 {left_today(ctx)}/{CASTS_PER_DAY} 竿"
        f" · 鱼获 {total_caught(ctx)}/{sum(len(spot.catches) for spot in spots(ctx))}",
    ]
    links = []
    for spot in page_data.entries:
        have = len(caught(ctx, spot))
        unlocked = pet is not None and pet.realm >= spot.realm
        state = "未解锁" if not unlocked else ("已集齐" if have >= len(spot.catches) else "可垂钓")
        gate = ctx.content.realms[spot.realm].name if spot.realm else "不限"
        lines.append(
            f"{spot.name} · 需 {gate} · 精力 {spot.energy} · 鱼获 {have}/{len(spot.catches)} · {state}"
        )
        links.append(InlineCommand(len(lines) - 1, "鱼获与择饵", f"灵宠垂钓 详情 {spot.name}"))
        reason = block_reason(ctx, spot, pet)
        if not reason:
            links.append(InlineCommand(len(lines) - 1, "抛竿", f"灵宠垂钓 {spot.name}"))
        elif unlocked:
            lines.append(f"暂不可抛竿：{reason}。")
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    return Reply(
        f"灵宠垂钓 {page_data.number}/{page_data.total}",
        tuple(lines),
        (*page_data.navigation, "灵宠垂钓 鱼篓", "灵宠目标", "我的灵宠")[:4],
        tuple(links),
    )


def cast(ctx: Context, arg: str) -> Reply:
    text = arg.strip()
    if not text:
        return catalog(ctx)
    parts = text.split()
    if len(parts) not in (1, 2):
        raise GameError("格式：灵宠垂钓 地点 [饵料]，或 灵宠垂钓 详情 地点 [饵料]。")
    spot = _spot(ctx, parts[0])
    bait = bait_for(ctx, spot, parts[1] if len(parts) == 2 else "")
    player = ctx.player()
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    if pet.realm < spot.realm:
        raise GameError(
            f"{spot.name}需要{ctx.content.realms[spot.realm].name}，{pet.name}尚未达到。"
        )
    if left_today(ctx, player.user_id) <= 0:
        raise GameError(f"今日垂钓次数已用完（每日 {CASTS_PER_DAY} 竿），明日再来。")
    if pet.energy < spot.energy:
        raise GameError(f"精力不足：{spot.name}每竿需 {spot.energy}，当前 {pet.energy}。")
    if bait and ctx.repo.inventory(player.user_id).get(bait.cost_item, 0) < bait.cost_quantity:
        raise GameError(f"{ctx.content.items[bait.cost_item].name}不足：{bait.name}每竿需 {bait.cost_quantity}。")

    effective_weights = weights(spot, bait)
    total = sum(effective_weights)
    roll = ctx.rng.randint(1, total)
    picked = spot.catches[-1]
    cursor = 0
    for entry, weight in zip(spot.catches, effective_weights):
        cursor += weight
        if roll <= cursor:
            picked = entry
            break
    amount = ctx.rng.randint(picked.minimum, picked.maximum)

    pet.energy -= spot.energy
    if bait:
        ctx.repo.consume_item(player.user_id, bait.cost_item, bait.cost_quantity)
    ctx.repo.invalidate_ready(player.user_id)
    ctx.repo.add_item(player.user_id, picked.item, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, f"{CATCH_PREFIX}{spot.id}_{picked.item}"),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
        (player.user_id, f"{CAST_PREFIX}{beijing_day(ctx.now)}"),
    )

    item = ctx.content.items[picked.item]
    lines = [
        f"{pet.name}在{spot.name}起了竿：{item.name} ×{amount}。",
        f"精力 -{spot.energy}（余 {pet.energy}）· 今日还剩 {left_today(ctx, player.user_id)} 竿。",
        f"{spot.name}鱼获 {len(caught(ctx, spot))}/{len(spot.catches)}"
        f" · 合计 {total_caught(ctx)}/{sum(len(entry.catches) for entry in spots(ctx))}。",
    ]
    bait_name = bait.name if bait else "素饵"
    cost_name = ctx.content.items[bait.cost_item].name if bait else ""
    lines.append(
        f"使用{bait_name} · {cost_name} -{bait.cost_quantity}"
        if bait else "使用素饵 · 不消耗额外物品。"
    )
    lines.extend(_settle_sets(ctx))
    reply = Reply("灵宠垂钓", tuple(lines), (
        f"灵宠垂钓 详情 {spot.name}" + (f" {bait.name}" if bait else ""),
        "灵宠垂钓 鱼篓", "灵宠背包", "灵宠目标",
    ))
    ctx.repo.record_fishing_cast(ctx.operation_id, player.user_id, ctx.now, {
        "pet_name": pet.name, "spot_id": spot.id, "spot_name": spot.name,
        "bait_id": bait.id if bait else "plain", "bait_name": bait_name,
        "cost_item": bait.cost_item if bait else None, "cost_name": cost_name,
        "cost_quantity": bait.cost_quantity if bait else 0,
        "item_id": item.id, "item_name": item.name, "amount": amount, "energy": spot.energy,
        "weights": effective_weights,
    }, reply)
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    from . import fishing_views

    parts = arg.split()
    if not parts:
        return catalog(ctx)
    if parts[0] == "详情":
        return fishing_views.detail(ctx, parts[1:])
    if parts[0] == "鱼篓":
        return fishing_views.basket(ctx, parts[1:])
    if parts[0] == "分页":
        if len(parts) != 2:
            raise GameError("格式：灵宠垂钓 分页 页码。")
        return catalog(ctx, parts[1])
    if len(parts) == 1 and parts[0].isdigit():
        return catalog(ctx, parts[0])
    return cast(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "垂钓：尚未结契"
    total = sum(len(spot.catches) for spot in spots(ctx))
    return (f"垂钓：今日剩 {left_today(ctx, user_id)} 竿 · 鱼获 {total_caught(ctx, user_id)}/{total}"
            " · 水域详情可择饵，鱼篓可回顾")


__all__ = [
    "ALL_BONUS", "CASTS_PER_DAY", "CAST_PREFIX", "CATCH_PREFIX", "SET_PREFIX", "SPOT_BONUS",
    "cast", "catalog", "caught", "dispatch", "left_today", "objective_line", "spots",
    "total_caught", "used_today",
]
