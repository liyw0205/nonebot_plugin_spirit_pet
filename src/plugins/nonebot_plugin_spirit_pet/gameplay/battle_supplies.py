"""Daily combat preparation backed by existing consumable pills."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.time import beijing_day

ACTIVE_PREFIX = "battle_supply_active_"
USED_PREFIX = "battle_supply_used_"


def _active_key(day: str, supply_id: str) -> str:
    return f"{ACTIVE_PREFIX}{day}_{supply_id}"


def _used_key(day: str) -> str:
    return f"{USED_PREFIX}{day}"


def _row(ctx: Context, key: str):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, key),
    ).fetchone()


def active(ctx: Context, user_id: str | None = None):
    owner = user_id or ctx.user_id
    day = beijing_day(ctx.now)
    prefix = f"{ACTIVE_PREFIX}{day}_"
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND claimed=1",
        (owner, f"{prefix}*"),
    ).fetchone()
    if row is None:
        return None
    return ctx.content.battle_supplies.get(row["quest_id"][len(prefix):])


def _used(ctx: Context) -> bool:
    return _row(ctx, _used_key(beijing_day(ctx.now))) is not None


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _rates_text(supply) -> str:
    def percent(rate: float) -> str:
        return f"{'+' if rate >= 1 else ''}{int(round((rate - 1) * 100))}%"

    return f"输出 {percent(supply.dealt)} · 承伤 {percent(supply.taken)}"


def _item_name(ctx: Context, supply) -> str:
    return ctx.content.items[supply.item_id].name


def page(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠战备 [选择 <战备名> | 清除]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠战备",
            (
                "战备丹只在当天的战斗中生效，不会改变伙伴四维。",
                "尚未结契，先完成领养，再准备战斗补给。",
            ),
            ("灵宠帮助",),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    current = active(ctx)
    used = _used(ctx)
    lines = ["每日只能消耗一枚战备丹；北京时间 00:00 后重新选择。"]
    if current is not None:
        lines.append(f"今日战备：{current.name} · {_rates_text(current)} · 已消耗{_item_name(ctx, current)} 1")
    elif used:
        lines.append("今日战备：已清除（本日不能再次消耗，明日恢复）。")
    else:
        lines.append("今日战备：尚未准备。")
    links = []
    for supply in sorted(ctx.content.battle_supplies.values(), key=lambda entry: entry.id):
        held = _owned(ctx, supply.item_id)
        state = "当前" if current is not None and current.id == supply.id else (
            "今日不可再选" if used else ("可选择" if held else "缺货")
        )
        lines.append(
            f"{supply.name} · {_item_name(ctx, supply)} ×{held} · {_rates_text(supply)} · {state}。"
            f"{supply.description}"
        )
        if current is not None and current.id == supply.id:
            links.append(InlineCommand(len(lines) - 1, "清除战备", "灵宠战备 清除"))
        elif not used and held:
            links.append(InlineCommand(len(lines) - 1, "选择战备", f"灵宠战备 选择 {supply.name}"))
    return Reply(
        "灵宠战备",
        tuple(lines),
        ("灵宠背包", "灵宠炼丹", "灵宠集市"),
        tuple(links),
    )


def choose(ctx: Context, arg: str) -> Reply:
    from ..utils.time import beijing_day

    supply = named(ctx.content.battle_supplies, arg.strip())
    ctx.player()
    if active(ctx) is not None:
        raise GameError("今日已经准备战备丹；如需停用，请先发送 灵宠战备 清除。")
    if _used(ctx):
        raise GameError("今日战备丹已经消耗过，清除后也不能再次选择，明日 00:00（北京时间）恢复。")
    held = _owned(ctx, supply.item_id)
    item = ctx.content.items[supply.item_id]
    if held < 1:
        raise GameError(f"{item.name}不足：当前持有 0，需要 1；可去灵宠炼丹或灵宠集市获取。")
    day = beijing_day(ctx.now)
    ctx.repo.consume_item(ctx.user_id, supply.item_id, 1)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, _used_key(day)),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, _active_key(day, supply.id)),
    )
    return Reply(
        "战备已定",
        (
            f"今日消耗 {item.name} 1，已启用{supply.name}。",
            f"本日战斗生效：{_rates_text(supply)}；不会改变四维，明日自动失效。",
        ),
        ("灵宠战备", "灵宠首领", "灵宠秘境"),
    )


def clear(ctx: Context, arg: str = "") -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠战备 清除。")
    ctx.player()
    current = active(ctx)
    if current is None:
        raise GameError("今日没有正在生效的战备丹。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _active_key(beijing_day(ctx.now), current.id)),
    )
    return Reply(
        "战备已清除",
        (f"今日{current.name}已停用，不返还已经消耗的{_item_name(ctx, current)}。", "本日不能再次选择战备丹，明日恢复。"),
        ("灵宠战备", "灵宠背包"),
    )


def rates(ctx: Context, user_id: str | None = None) -> tuple[float, float, str | None]:
    supply = active(ctx, user_id)
    return (supply.dealt, supply.taken, supply.name) if supply else (1.0, 1.0, None)


def objective_line(ctx: Context, user_id: str) -> str:
    supply = active(ctx, user_id)
    return f"战备：{supply.name}（{_rates_text(supply)}）" if supply else "战备：今日未准备"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts[0] == "选择":
        if len(parts) < 2:
            raise GameError("格式：灵宠战备 选择 <战备名>。")
        return choose(ctx, " ".join(parts[1:]))
    if parts[0] == "清除":
        return clear(ctx, " ".join(parts[1:]))
    raise GameError("格式：灵宠战备 [选择 <战备名> | 清除]。")
