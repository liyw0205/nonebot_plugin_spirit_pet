"""灵宠际遇: one roadside choice per player per Beijing day.

The encounter is drawn deterministically from the player id and the day, so the
page is stable within a day and rotates with the next one. An option always
takes something (stones or items) before it pays out, and the choice is written
once as ``enc_<day>`` with the 1-based option index, which also makes a replay
return the cached reply instead of paying twice.
"""

from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING, beijing_day
from . import counters
from .rewards import grant

PREFIX = "enc_"


def _seed(user_id: str) -> int:
    return sum(ord(char) for char in user_id)


def _day_ordinal(now: int) -> int:
    return datetime.fromtimestamp(now, BEIJING).date().toordinal()


def todays(ctx: Context, user_id: str | None = None):
    """The encounter this player meets today, or None when content is empty."""
    entries = [ctx.content.daily_encounters[key] for key in sorted(ctx.content.daily_encounters)]
    if not entries:
        return None
    owner = user_id or ctx.user_id
    return entries[(_day_ordinal(ctx.now) + _seed(owner)) % len(entries)]


def _key(now: int) -> str:
    return f"{PREFIX}{beijing_day(now)}"


def chosen(ctx: Context, user_id: str | None = None):
    """The option already taken today, if any."""
    owner = user_id or ctx.user_id
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (owner, _key(ctx.now)),
    ).fetchone()
    if not row or not row["claimed"]:
        return None
    encounter = todays(ctx, owner)
    index = int(row["progress"])
    if encounter is None or not 1 <= index <= len(encounter.options):
        return None
    return encounter.options[index - 1]


def _cost_text(ctx: Context, option) -> str:
    parts = [f"灵石 {option.cost.stones}"] if option.cost.stones else []
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in option.cost.items.items()
    )
    return "、".join(parts)


def _reward_text(ctx: Context, option) -> str:
    reward = option.reward
    parts = []
    if reward.exp.maximum:
        parts.append(f"修为 {reward.exp.minimum}-{reward.exp.maximum}")
    if reward.stones.maximum:
        parts.append(f"灵石 {reward.stones.minimum}-{reward.stones.maximum}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}-{bounds.maximum}"
        for item_id, bounds in reward.items.items()
    )
    return "、".join(parts)


def _pay_out(ctx: Context, option, user_id: str) -> tuple[str, ...]:
    """Apply the reward, reusing ``grant`` whenever experience is involved."""
    reward = option.reward
    if reward.exp.maximum > 0:
        return grant(ctx, reward, user_id)
    player = ctx.player(user_id)
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    player.stones += stones
    lines = []
    if stones:
        lines.append(f"灵石 +{stones}")
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if not amount:
            continue
        ctx.repo.add_item(player.user_id, item_id, amount)
        lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return tuple(lines)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠际遇 [选项]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵宠际遇", (
            "尚未结契，先完成领养，才能在路上遇见故事。",
            "际遇每日一次，选定后当日不再刷新。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    encounter = todays(ctx)
    if encounter is None:
        return Reply("灵宠际遇", ("今日没有际遇。",), ("我的灵宠",))
    taken = chosen(ctx)
    if taken is not None:
        return Reply("灵宠际遇", (
            f"{encounter.name} · 今日已了。",
            taken.text,
            _reward_text(ctx, taken) and f"所得：{_reward_text(ctx, taken)}。",
            "明日的路会通向别处。",
        ), ("灵宠际遇", "我的灵宠", "灵宠目标"))
    lines = [f"{encounter.name}", encounter.description, "今日可选："]
    links = []
    for option in encounter.options:
        lines.append(
            f"{option.label}：付出 {_cost_text(ctx, option)} · 可得 {_reward_text(ctx, option)}"
        )
        links.append(InlineCommand(len(lines) - 1, option.label, f"灵宠际遇 {option.label}"))
    lines.append("选定后当日不再刷新；付出不足时整条拒绝，不会部分扣除。")
    return Reply("灵宠际遇", tuple(lines), ("灵宠际遇", "我的灵宠", "灵宠目标"), tuple(links))


def choose(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    encounter = todays(ctx)
    if encounter is None:
        raise GameError("今日没有际遇。")
    taken = chosen(ctx)
    if taken is not None:
        raise GameError(f"{encounter.name}今日已了（{taken.label}），明日再来。")
    option = next(
        (entry for entry in encounter.options if arg.strip() in {entry.id, entry.label}), None,
    )
    if option is None:
        labels = "、".join(entry.label for entry in encounter.options)
        raise GameError(f"{encounter.name}没有这个选项；可选：{labels}。")
    if player.stones < option.cost.stones:
        raise GameError(f"灵石不足：需要 {option.cost.stones}。")
    bag = ctx.repo.inventory(player.user_id)
    short = [
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in option.cost.items.items()
        if bag.get(item_id, 0) < amount
    ]
    if short:
        raise GameError(f"道具不足：{'、'.join(short)}。")

    if option.cost.stones:
        player.stones -= option.cost.stones
    for item_id, amount in option.cost.items.items():
        ctx.repo.consume_item(player.user_id, item_id, amount)
    gained = _pay_out(ctx, option, player.user_id)
    index = encounter.options.index(option) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, _key(ctx.now), index),
    )
    counters.bump(ctx, "encounter_choices")
    lines = [f"{encounter.name} · {option.label}", option.text, *gained]
    return Reply("灵宠际遇", tuple(lines), ("灵宠际遇", "我的灵宠", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else choose(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    encounter = todays(ctx, user_id)
    if encounter is None:
        return "际遇：今日无"
    taken = chosen(ctx, user_id)
    return f"际遇：{'已了' if taken is not None else encounter.name}"
