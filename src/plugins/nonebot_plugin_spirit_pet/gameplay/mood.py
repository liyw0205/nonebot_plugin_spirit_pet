"""Pet mood: a short-term per-pet state that decays with neglect and scales combat stats.

Mood is *derived*, never stored per day. ``quest_progress`` keeps one ``last_care_<pet_id>`` row
holding the Beijing **day ordinal** of the pet's last care, and the value is recomputed from the
elapsed days on every read, so nothing runs on a schedule and a skipped day cannot corrupt state.

Feeding, daily bonding and 安抚 all call :func:`care`, so normal play keeps a pet bright without
any extra button pressing; neglecting it decays the pet through 心境平稳 → 心情低落 → 心灰意冷 and
costs up to 10% of its four stats.
"""

from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day
from .economy import selected_pet

LAST_CARE_KEY = "last_care_"
SOOTHE_ITEM = "spirit_food"


def rule(ctx: Context):
    return ctx.content.rules.mood


def _ordinal(day: str) -> int:
    return date.fromisoformat(day).toordinal()


def last_care(ctx: Context, pet_id: int, user_id: str | None = None) -> int | None:
    """Day ordinal of the last recorded care, or None when the pet was never cared for."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{LAST_CARE_KEY}{pet_id}"),
    ).fetchone()
    return None if row is None else int(row["progress"])


def value(ctx: Context, pet, user_id: str | None = None) -> int:
    """Current mood value: full when never neglected, otherwise one point per decay interval."""
    cap = rule(ctx).max
    marked = last_care(ctx, pet.pet_id, user_id)
    if marked is None:
        return cap
    elapsed = _ordinal(beijing_day(ctx.now)) - marked
    if elapsed <= 0:
        return cap
    return max(0, cap - elapsed // rule(ctx).decay_days)


def level(ctx: Context, pet, user_id: str | None = None):
    from ..domain.mood_content import mood_of

    return mood_of(ctx.content.moods.values(), value(ctx, pet, user_id))


def _rate_text(rate: float) -> str:
    return "±0%" if rate == 0 else f"{rate:+.0%}"


def rate(ctx: Context, pet, user_id: str | None = None) -> float:
    return level(ctx, pet, user_id).rate


def days_to_decay(ctx: Context, pet, user_id: str | None = None) -> int | None:
    """Days until the next point is lost, or None when the pet cannot drop any further."""
    if value(ctx, pet, user_id) <= 0:
        return None
    marked = last_care(ctx, pet.pet_id, user_id)
    if marked is None:
        return rule(ctx).decay_days
    elapsed = _ordinal(beijing_day(ctx.now)) - marked
    return rule(ctx).decay_days - (elapsed % rule(ctx).decay_days)


def care(ctx: Context, pet, user_id: str | None = None) -> None:
    """Record care for today and refill the pet's mood. Called by feeding, bonding and 安抚."""
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user_id or ctx.user_id, f"{LAST_CARE_KEY}{pet.pet_id}", _ordinal(beijing_day(ctx.now))),
    )


def _owned(ctx: Context, item_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (user_id or ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _pets(ctx: Context):
    return sorted(ctx.repo.owned_pets(ctx.user_id), key=lambda pet: pet.pet_id)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠心境 [安抚 <伙伴编号>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠心境",
            (
                "尚未结契，先完成领养，才能查看伙伴的心境。",
                "被长期冷落的伙伴心情会逐日低落，属性随之下降；喂食、互动或安抚都能让它重新振作。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    cap = rule(ctx).max
    rule_cost = rule(ctx).soothe_items
    item = ctx.content.items[SOOTHE_ITEM]
    held = _owned(ctx, SOOTHE_ITEM)
    lines = [
        f"心境上限 {cap}，每 {rule(ctx).decay_days} 天无人照料下降 1 点；"
        f"安抚消耗 {item.name} {rule_cost} 份，直接回满。",
    ]
    links = []
    waiting = 0
    for pet in _pets(ctx):
        current = value(ctx, pet)
        entry = level(ctx, pet)
        remaining = days_to_decay(ctx, pet)
        state = "心境已满" if current >= cap else (
            f"每 {rule(ctx).decay_days} 天再降 1 点" if remaining is not None else "已到最低"
        )
        if current < cap:
            waiting += 1
        lines.append(
            f"{pet.name}（编号 {pet.pet_id}）· {entry.name} {current}/{cap}"
            f" · 四维 {_rate_text(entry.rate)} · {state}"
        )
        if current < cap and held >= rule_cost and ctx.repo.active_expedition(pet.pet_id) is None:
            links.append(InlineCommand(len(lines) - 1, "安抚", f"灵宠心境 安抚 {pet.pet_id}"))
    if waiting:
        lines.append(f"共 {waiting} 只伙伴需要安抚。")
    else:
        lines.append("所有伙伴心境都已回满。")
    if held < rule_cost:
        lines.append(f"{item.name}不足：现有 {held} 份，安抚需要 {rule_cost} 份。")
    lines.append("格式：灵宠心境 安抚 <伙伴编号>；喂食与每日互动也会顺带刷新心境。")
    return Reply("灵宠心境", tuple(lines), ("灵宠心境", "灵宠喂养", "我的灵宠"), tuple(links))


def soothe(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        raise GameError("格式：灵宠心境 安抚 <伙伴编号>。")
    pet = selected_pet(ctx, arg, "安抚")
    cap = rule(ctx).max
    rule_cost = rule(ctx).soothe_items
    if value(ctx, pet) >= cap:
        raise GameError(f"{pet.name}心境已满，无需安抚。")
    ctx.require_idle_pet(pet)
    item = ctx.content.items[SOOTHE_ITEM]
    held = _owned(ctx, SOOTHE_ITEM)
    if held < rule_cost:
        raise GameError(f"{item.name}不足：安抚需要 {rule_cost} 份，当前 {held} 份。")

    before = value(ctx, pet)
    ctx.repo.consume_item(ctx.user_id, SOOTHE_ITEM, rule_cost)
    care(ctx, pet)
    ctx.repo.invalidate_ready(ctx.user_id)
    entry = level(ctx, pet)
    return Reply("安抚灵宠", (
        f"{pet.name}被好好安抚了一番，心境 {before} → {cap}（{entry.name}），四维 {_rate_text(entry.rate)}。",
        f"消耗 {item.name} {rule_cost} 份（剩余 {held - rule_cost} 份）。",
        "喂食与每日互动同样会刷新心境，不必每天都用安抚。",
    ), ("灵宠心境", "灵宠背包", "我的灵宠"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "安抚":
        return soothe(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠心境 [安抚 <伙伴编号>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None:
        return "心境：尚未结契"
    cap = rule(ctx).max
    waiting = sum(
        1 for pet in ctx.repo.owned_pets(user_id) if value(ctx, pet, user_id) < cap
    )
    return f"心境：{waiting} 只待安抚" if waiting else "心境：全员心境已满"
