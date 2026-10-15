from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from .rewards import grant

PAGE_SIZE = 5
CLAIM_PREFIX = "echo_"


def claim_id(encounter_id: str) -> str:
    return CLAIM_PREFIX + encounter_id


def _discovered(ctx: Context, user_id: str, encounter_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT 1 FROM adventure_discoveries WHERE user_id=? AND encounter_id=?",
        (user_id, encounter_id),
    ).fetchone()
    return row is not None


def _chosen(ctx: Context, user_id: str, encounter_id: str):
    """The exclusive choice already made for this encounter, if any."""
    row = ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(encounter_id)),
    ).fetchone()
    if not row or not row["claimed"]:
        return None
    encounter = ctx.content.encounters[encounter_id]
    index = int(row["progress"])
    if not 1 <= index <= len(encounter.options):
        return None
    return encounter.options[index - 1]


def _rows(ctx: Context, user_id: str):
    """(encounter, option, state) for every discovered encounter's options."""
    entries = []
    for encounter in ctx.content.encounters.values():
        if not _discovered(ctx, user_id, encounter.id):
            continue
        chosen = _chosen(ctx, user_id, encounter.id)
        for option in encounter.options:
            if chosen is None:
                state = "可回响"
            elif chosen.id == option.id:
                state = f"已回响（{chosen.label}）"
            else:
                state = "已错过"
            entries.append((encounter, option, state))
    return entries


def catalog(ctx: Context, arg: str) -> Reply:
    page = quantity(arg or "1", 999)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("奇闻回响", (
            "历练中发现的奇闻可以回响一次：在它的选项里做出选择，得到对应的结果与奖励。",
            "同一条奇闻的选项互斥，选定后其余选项失效；未发现的奇闻不会出现在这里。",
            "尚未结契，先完成领养，再去历练。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    rows = _rows(ctx, player.user_id)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"灵宠回响共 {pages} 页。")
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = []
    links = []
    for encounter, option, state in selected:
        lines.append(f"{encounter.name} · {option.label} · {state}")
        if state == "可回响":
            links.append(InlineCommand(
                len(lines) - 1, "做出选择", f"灵宠回响选择 {encounter.name} {option.label}",
            ))
    pending = sum(1 for _, _, state in rows if state == "可回响")
    discovered = len({encounter.id for encounter, _, _ in rows})
    lines.append(f"已发现 {discovered}/{len(ctx.content.encounters)} 条奇闻，尚有 {pending} 个选项可回响。")
    commands = []
    if page > 1:
        commands.append(f"灵宠回响 {page - 1}")
    if page < pages:
        commands.append(f"灵宠回响 {page + 1}")
    commands.extend(("灵宠历练", "灵宠目标"))
    return Reply(f"奇闻回响 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def choose(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠回响选择 奇闻名 选项名，例如 灵宠回响选择 灵泉寻踪 取水。")
    encounter = named(ctx.content.encounters, parts[0])
    if not _discovered(ctx, player.user_id, encounter.id):
        raise GameError(f"尚未发现{encounter.name}，请先在历练中遇见它。")
    chosen = _chosen(ctx, player.user_id, encounter.id)
    if chosen is not None:
        raise GameError(f"{encounter.name}已回响（{chosen.label}），其余选项已失效。")
    option = next((entry for entry in encounter.options if parts[1] in {entry.id, entry.label}), None)
    if option is None:
        labels = "、".join(entry.label for entry in encounter.options)
        raise GameError(f"{encounter.name}没有这个选项；可选：{labels}。")
    result = grant(ctx, option.reward, player.user_id)
    index = encounter.options.index(option) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(encounter.id), index),
    )
    return Reply("奇闻回响", (
        f"{encounter.name} · {option.label}", option.text, *result,
    ), ("灵宠回响", "灵宠历练", "灵宠目标"))
