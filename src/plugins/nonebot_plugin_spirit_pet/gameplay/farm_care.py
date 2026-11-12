"""Optional three-step crop care, scoped to a single planting cycle."""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity

TITLE = "灵宠养苗"
STAGES = ("扎根", "展叶", "结实")
PREFIX = "farm_care_"
CYCLE = "farm_cycle_"


def value(ctx: Context, key: str, owner: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (owner or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def write(ctx: Context, key: str, number: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, key, number),
    )


def reset(ctx: Context, plot: int) -> None:
    for field in ("step", "cut", "yield", "updated"):
        ctx.repo.conn.execute(
            "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
            (ctx.user_id, f"{PREFIX}{field}_{plot}"),
        )


def cut(ctx: Context, plot: int, owner: str | None = None) -> int:
    return value(ctx, f"{PREFIX}cut_{plot}", owner)


def bonus(ctx: Context, plot: int) -> int:
    return value(ctx, f"{PREFIX}yield_{plot}")


def receipt(ctx: Context, plot: int, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": "farm_care", "plot": plot, "cycle": value(ctx, f"{CYCLE}{plot}"),
         "status": "harvested"}, reply)
    return reply


def _crop(ctx: Context, plot: int):
    from . import farming
    opened, row, _ = farming._plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦。")
    if row is None:
        raise GameError(f"田位 {plot} 还没有播种。")
    crop = farming._crop(ctx, row)
    if ctx.now < row["progress"]:
        raise GameError("当前时间早于种植时间，请等待时钟恢复。")
    if ctx.now < value(ctx, f"{PREFIX}updated_{plot}"):
        raise GameError("当前时间早于上次养护，请等待时钟恢复。")
    remaining = farming._growth_seconds(ctx, plot, crop) - (ctx.now - row["progress"])
    return crop, row, remaining


def page(ctx: Context, plot: int | None = None) -> Reply:
    from . import farming
    lines = ["每季可选三次养护：扎根、展叶、结实；不养护仍按原规则生长。",
             "每步二选一：松土花10灵石，缩短该田基础生长期5%；培肥花1灵粮，收获基础产出加20%。",
             "最多缩时15%或增产60%，可混合；增产与轮作相加后逐项取整，枯萎只返种子。",
            "扎根可立即照料，展叶/结实分别在基础生长期的三分之一、三分之二开放；按顺序每段一次。"]
    lines.append("每项材料、修为、灵石均向下取整；小额产出培肥一次可能不增加数量。灵粮与种子可在灵宠商店购买。")
    links = []
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴，再开垦播种。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        for number in ([plot] if plot is not None else range(1, farming.PLOT_COUNT + 1)):
            opened, row, _ = farming._plot_state(ctx, number)
            if not opened or row is None:
                if plot is not None:
                    _crop(ctx, number)
                continue
            crop, row, remaining = _crop(ctx, number)
            step = value(ctx, f"{PREFIX}step_{number}")
            cycle = value(ctx, f"{CYCLE}{number}") or row["progress"]
            lines.append(f"田位 {number} · {crop.name} · 养护 {step}/3 · 缩时{cut(ctx, number)}秒 · 增产{bonus(ctx, number)}%。")
            if remaining <= 0:
                lines.append("已成熟或枯萎，不能继续养护。")
                links.append(InlineCommand(len(lines) - 1, "查看灵田", "灵宠灵田"))
            elif step < 3:
                wait = row["progress"] + farming._effective_duration(ctx, number, crop.duration) * step // 3 - ctx.now
                if wait > 0:
                    lines.append(f"{STAGES[step]}尚需{wait}秒开放；作物继续生长。")
                    continue
                reduction = min(max(1, farming._effective_duration(ctx, number, crop.duration) * 5 // 100), max(0, remaining - 1))
                lines.append(f"{STAGES[step]}：松土可缩短{reduction}秒；培肥增加20%基础产出。")
                for choice in ("松土", "培肥"):
                    links.append(InlineCommand(len(lines) - 1, choice,
                        f"{TITLE} {number} {choice} 季 {cycle} 步 {step + 1}"))
    return Reply(TITLE, tuple(lines), ("灵宠背包", "灵宠商店", "灵宠目标"), tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    from . import farming
    parts = arg.split()
    if not parts:
        return page(ctx)
    plot = quantity(parts[0], farming.PLOT_COUNT)
    if not 1 <= plot <= farming.PLOT_COUNT:
        raise GameError(f"田位编号是1-{farming.PLOT_COUNT}。")
    if len(parts) == 1:
        return page(ctx, plot)
    if len(parts) != 6 or parts[1] not in ("松土", "培肥") or parts[2] != "季" or parts[4] != "步":
        raise GameError("请先查看 灵宠养苗 <田位>，使用当前季的养护入口。")
    ctx.player()
    crop, row, remaining = _crop(ctx, plot)
    cycle = value(ctx, f"{CYCLE}{plot}") or row["progress"]
    step = value(ctx, f"{PREFIX}step_{plot}")
    if quantity(parts[3], 2**63 - 1) != cycle or quantity(parts[5], 4) != step + 1:
        raise GameError("这是旧季或已执行步骤的养护入口，请重新查看灵宠养苗。")
    if remaining <= 0:
        raise GameError("作物已经成熟或枯萎，不能继续养护。")
    if step >= 3:
        raise GameError("本季三次养护已经完成。")
    wait = row["progress"] + farming._effective_duration(ctx, plot, crop.duration) * step // 3 - ctx.now
    if wait > 0:
        raise GameError(f"{STAGES[step]}尚需{wait}秒开放。")
    key = f"{PREFIX}{'cut' if parts[1] == '松土' else 'yield'}_{plot}"
    if parts[1] == "松土":
        amount = min(max(1, farming._effective_duration(ctx, plot, crop.duration) * 5 // 100), max(0, remaining - 1))
        if amount == 0:
            raise GameError("距离成熟不足2秒，无需松土；可培肥或等待收获。")
        player = ctx.player()
        if player.stones < 10:
            raise GameError("松土需要10灵石，当前灵石不足。")
        player.stones -= 10
        detail = f"灵石 -10，生长时间缩短{amount}秒。"
    else:
        ctx.repo.consume_item(ctx.user_id, "spirit_food", 1)
        amount = 20
        detail = "灵粮 -1，收获基础产出增加20%（逐项取整）。"
    write(ctx, key, value(ctx, key) + amount)
    write(ctx, f"{PREFIX}step_{plot}", step + 1)
    write(ctx, f"{PREFIX}updated_{plot}", ctx.now)
    reply = page(ctx, plot)
    reply = Reply(reply.title, (f"田位{plot} · {STAGES[step]}{parts[1]}：{detail}", *reply.lines),
                  reply.commands, tuple(InlineCommand(link.line + 1, link.label, link.command) for link in reply.inline_commands))
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": "farm_care", "plot": plot, "cycle": cycle, "step": step + 1}, reply)
    return reply
