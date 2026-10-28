"""Cave residence: three upgradeable facilities with one action each per Beijing day.

State lives in the existing ``quest_progress`` table:

* ``cave_<facility>_level`` — current level (an absent row means level 1)
* ``cave_<facility>_day_<Beijing date>`` — present once today's action was taken

Upgrades spend stones and one themed material; each facility then pays its current
level's yield once per day (energy, affinity or a crafted item).
"""

from ..application.context import Context
from ..domain.cave_content import CaveFacility
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.energy import add_energy
from ..utils.time import beijing_day

LEVEL_PREFIX = "cave_"
DAY_SUFFIX = "_day_"


def facilities(ctx: Context) -> list[CaveFacility]:
    return sorted(ctx.content.cave.values(), key=lambda facility: facility.id)


def _level_key(facility_id: str) -> str:
    return f"{LEVEL_PREFIX}{facility_id}_level"


def _day_key(facility_id: str, day: str) -> str:
    return f"{LEVEL_PREFIX}{facility_id}{DAY_SUFFIX}{day}"


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def level_of(ctx: Context, facility: CaveFacility, user_id: str | None = None) -> int:
    stored = _progress(ctx, _level_key(facility.id), user_id)
    return max(1, min(facility.max_level, stored or 1))


def used_today(ctx: Context, facility: CaveFacility, user_id: str | None = None) -> bool:
    return bool(_progress(ctx, _day_key(facility.id, beijing_day(ctx.now)), user_id))


def total_levels(ctx: Context, user_id: str | None = None) -> int:
    return sum(level_of(ctx, facility, user_id) for facility in facilities(ctx))


def max_levels(ctx: Context) -> int:
    return sum(facility.max_level for facility in facilities(ctx))


def remaining(ctx: Context, user_id: str | None = None) -> int:
    return sum(1 for facility in facilities(ctx) if not used_today(ctx, facility, user_id))


def effect_text(ctx: Context, facility: CaveFacility, level: int) -> str:
    amount = facility.yield_at(level)
    if facility.effect == "energy":
        return f"为一只伙伴恢复 {amount} 精力"
    if facility.effect == "affinity":
        return f"为一只伙伴增加 {amount} 亲密"
    assert facility.item is not None
    return f"获得 {ctx.content.items[facility.item].name} ×{amount}"


def _owned(ctx: Context, user_id: str, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _cost_text(ctx: Context, step) -> str:
    items = "、".join(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in step.items.items()
    )
    return "、".join(part for part in (f"灵石 {step.stones}" if step.stones else "", items) if part)


def _affordable(ctx: Context, player, step) -> bool:
    if player.stones < step.stones:
        return False
    return all(_owned(ctx, player.user_id, item_id) >= amount for item_id, amount in step.items.items())


def _upsert(ctx: Context, key: str, progress: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, progress),
    )


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠洞府 [升级|使用] <设施> [灵宠名]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠洞府",
            (
                "尚未结契，先完成领养，才能开辟自己的洞府。",
                "洞府有三处设施：灵泉补精力、兽栏增亲密、丹房炼蕴灵丹。",
                "每处设施每日可用一次，升级需要灵石与材料。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    player = ctx.player()
    lines = [
        f"洞府总览：{total_levels(ctx)}/{max_levels(ctx)} 级"
        f" · 今日剩余 {remaining(ctx)} 次设施行动（北京时间 00:00 重置）。"
    ]
    links = []
    for facility in facilities(ctx):
        current = level_of(ctx, facility)
        state = "今日已用" if used_today(ctx, facility) else "今日可用"
        lines.append(
            f"{facility.name} · Lv{current} · {effect_text(ctx, facility, current)} · {state}"
        )
        if not used_today(ctx, facility):
            links.append(InlineCommand(len(lines) - 1, "使用", f"灵宠洞府 使用 {facility.name}"))
        step = facility.upgrade_at(current)
        if step is None:
            lines.append("  已达最高等级，效果固定。")
            continue
        flag = "" if _affordable(ctx, player, step) else "（资源不足）"
        lines.append(f"  升级 Lv{current + 1}：{_cost_text(ctx, step)}{flag}")
        if _affordable(ctx, player, step):
            links.append(InlineCommand(len(lines) - 1, "升级", f"灵宠洞府 升级 {facility.name}"))
    lines.append("每日按北京时间换日；升级与使用均为整笔结算，资源不足不会扣任何材料。")
    return Reply(
        "灵宠洞府", tuple(lines), ("灵宠洞府", "我的灵宠", "灵宠背包", "灵宠目标"), tuple(links),
    )


def upgrade(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    text = arg.strip()
    if not text:
        raise GameError("格式：灵宠洞府 升级 <设施>。")
    facility = named(ctx.content.cave, text)
    current = level_of(ctx, facility)
    step = facility.upgrade_at(current)
    if step is None:
        raise GameError(f"{facility.name}已满级。")
    if player.stones < step.stones:
        raise GameError(f"灵石不足：升级{facility.name}需要 {step.stones}，当前 {player.stones}。")
    short = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, player.user_id, item_id)}"
        for item_id, amount in step.items.items()
        if _owned(ctx, player.user_id, item_id) < amount
    ]
    if short:
        raise GameError(f"材料不足：升级{facility.name}还需{'、'.join(short)}。")

    player.stones -= step.stones
    for item_id, amount in step.items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    _upsert(ctx, _level_key(facility.id), current + 1)

    lines = [
        f"{facility.name} 提升至 Lv{current + 1}：{_cost_text(ctx, step)}已扣除。",
        f"当前效果：{effect_text(ctx, facility, current + 1)}（每日一次）。",
    ]
    following = facility.upgrade_at(current + 1)
    lines.append(
        f"下一级需：{_cost_text(ctx, following)}。" if following is not None else "这处设施已达最高等级。"
    )
    lines.append(
        f"洞府总览：{total_levels(ctx)}/{max_levels(ctx)} 级 · 今日剩余 {remaining(ctx)} 次设施行动。"
    )
    return Reply("灵宠洞府", tuple(lines), ("灵宠洞府", "灵宠背包", "我的灵宠"))


def _target(ctx: Context, name: str):
    if not name:
        return ctx.pet()
    row = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND name=? ORDER BY pet_id LIMIT 1",
        (ctx.user_id, name),
    ).fetchone()
    if row is None:
        raise GameError(f"没有找到名为{name}的伙伴。")
    return ctx.repo.pet(int(row["pet_id"]))


def use(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    parts = arg.split()
    if not parts:
        raise GameError("格式：灵宠洞府 使用 <设施> [灵宠名]。")
    facility = named(ctx.content.cave, parts[0])
    leftover = " ".join(parts[1:])
    if facility.effect == "item" and leftover:
        raise GameError(f"{facility.name}不需要指定伙伴。")
    if used_today(ctx, facility):
        raise GameError(f"{facility.name}今日已经用过，北京时间 00:00 后恢复。")

    current = level_of(ctx, facility)
    amount = facility.yield_at(current)
    if facility.effect == "item":
        assert facility.item is not None
        ctx.repo.add_item(ctx.user_id, facility.item, amount)
        head = f"{facility.name}开炉：{ctx.content.items[facility.item].name} ×{amount} 已入乾坤袋。"
    else:
        pet = _target(ctx, leftover)
        if pet.archived:
            raise GameError(f"{pet.name}已封存，无法行动。")
        ctx.require_idle_pet(pet)
        if facility.effect == "energy":
            if pet.energy >= 100:
                raise GameError(f"{pet.name}精力已满，无需凝神。")
            gained = add_energy(pet, amount, ctx.now)
            head = f"{facility.name}凝神：{pet.name}精力 +{gained}（{pet.energy}/100）。"
        else:
            if pet.affinity >= 100:
                raise GameError(f"{pet.name}亲密已满，无需抚慰。")
            before = pet.affinity
            pet.affinity = min(100, before + amount)
            head = f"{facility.name}抚慰：{pet.name}亲密 +{pet.affinity - before}（{pet.affinity}/100）。"
        ctx.repo.invalidate_ready(ctx.user_id)

    _upsert(ctx, _day_key(facility.id, beijing_day(ctx.now)), 1)
    lines = [
        head,
        f"{facility.name} Lv{current} · 今日已用，明日 00:00 后可再用。",
        f"今日剩余 {remaining(ctx)} 次设施行动。",
    ]
    return Reply("灵宠洞府", tuple(lines), ("灵宠洞府", "灵宠背包", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "升级":
        return upgrade(ctx, " ".join(parts[1:]))
    if parts[0] == "使用":
        return use(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠洞府 [升级|使用] <设施> [灵宠名]。")


def objective_line(ctx: Context, user_id: str) -> str:
    return (
        f"洞府：总 {total_levels(ctx, user_id)}/{max_levels(ctx)} 级"
        f" · 今日剩余 {remaining(ctx, user_id)} 次设施行动"
    )
