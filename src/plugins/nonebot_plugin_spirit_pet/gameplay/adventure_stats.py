"""Read-only records for adventure ambush battles persisted in battle_records."""

from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import BEIJING

PAGE_SIZE = 5
RECENT_WINDOW = 5
KEY_PREFIX = "ambush_"


def _rows(ctx: Context, user_id: str) -> list[dict]:
    order = {route_id: index for index, route_id in enumerate(ctx.content.exploration_routes)}
    rows = []
    for row in ctx.repo.conn.execute(
        "SELECT b.battle_key AS battle_key, COUNT(*) AS fights, "
        "SUM(b.winner_side=p.side) AS wins, "
        "SUM(b.winner_side=-1) AS draws, "
        "SUM(b.winner_side=1-p.side) AS losses, "
        "MAX(CASE WHEN b.winner_side=p.side THEN b.played_at END) AS last_win, "
        "MAX(b.played_at) AS last_fight "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key LIKE ? "
        "GROUP BY b.battle_key",
        (user_id, f"{KEY_PREFIX}%"),
    ).fetchall():
        route_id = row["battle_key"][len(KEY_PREFIX):]
        route = ctx.content.exploration_routes.get(route_id)
        if route is None:
            continue
        rows.append({
            "route": route,
            "order": order[route_id],
            "fights": row["fights"],
            "wins": row["wins"],
            "losses": row["losses"],
            "draws": row["draws"],
            "last_win": row["last_win"],
            "last_fight": row["last_fight"],
        })
    return rows


def _time(value: int | None) -> str:
    if value is None:
        return "尚无获胜"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _stamp(value: int | None) -> str:
    if value is None:
        return "无记录"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _recent(ctx: Context, user_id: str, route_id: str) -> tuple[str, ...]:
    rows = ctx.repo.conn.execute(
        "SELECT b.winner_side=p.side AS won, b.winner_side=-1 AS drawn, b.played_at "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? "
        "ORDER BY b.played_at DESC, b.battle_id DESC LIMIT ?",
        (user_id, f"{KEY_PREFIX}{route_id}", RECENT_WINDOW),
    ).fetchall()
    return tuple(
        f"{datetime.fromtimestamp(row['played_at'], BEIJING).strftime('%m-%d')}"
        f" · {'胜' if row['won'] else '平' if row['drawn'] else '负'}"
        for row in rows
    )


def _row_text(row) -> str:
    route = row["route"]
    return (
        f"{route.name} · 伏击 {row['fights']} 场 · "
        f"{row['wins']} 胜 {row['losses']} 负 {row['draws']} 平 · "
        f"最近伏击：{_stamp(row['last_fight'])}"
    )


def catalog(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value and not value.isdecimal():
        return detail(ctx, value)
    page = quantity(value or "1", 999999)
    player = ctx.repo.player(ctx.user_id)
    title = "历练战绩"
    if player is None:
        return Reply(
            title,
            (
                "历练伏击会写入战报；结契后可按路线查看次数、胜负平与最近五场。",
                "尚未结契，先完成领养；历练需要先选择一条路线。",
            ),
            ("灵宠历练", "灵宠帮助"),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    rows = _rows(ctx, player.user_id)
    rows.sort(key=lambda row: (-row["last_fight"], row["order"]))
    if not rows:
        return Reply(f"{title} 1/1", (
            "还没有历练伏击记录。每条历练路线有伏击概率，遭遇后才会写入战报。",
            "发送 灵宠历练 <路线> 可查看路线与伏击说明。",
        ), ("灵宠历练", "灵宠战报", "灵宠帮助"))
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"历练战绩共 {pages} 页。")
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for row in selected:
        lines.append(_row_text(row))
        links.append(InlineCommand(
            len(lines) - 1, "查看战绩", f"灵宠历练战绩 {row['route'].name}",
        ))
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠历练战绩 {page - 1}")
    if page < pages:
        commands.append(f"灵宠历练战绩 {page + 1}")
    commands.extend(("灵宠历练", "灵宠战报", "灵宠帮助"))
    return Reply(f"{title} {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    route = named(ctx.content.exploration_routes, arg)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        raise GameError("尚未结契，先完成领养再查看历练战绩。")
    rows = [row for row in _rows(ctx, player.user_id) if row["route"].id == route.id]
    if not rows:
        raise GameError(
            f"还没有{route.name}的伏击记录，发送 灵宠历练 {route.name} 可能遭遇伏击。"
        )
    row = rows[0]
    recent = _recent(ctx, player.user_id, route.id)
    chance = ctx.content.rules.explore_ambush_chance
    lines = [
        f"{route.name} · 伏击 {row['fights']} 场 · "
        f"{row['wins']} 胜 {row['losses']} 负 {row['draws']} 平。",
        f"伏击概率：{chance:.0%} · 最近伏击：{_stamp(row['last_fight'])} · "
        f"最近获胜：{_time(row['last_win'])}。",
        "最近五场（新在前）：" + ("、".join(recent) if recent else "无"),
    ]
    return Reply(
        f"历练战绩 · {route.name}",
        tuple(lines),
        ("灵宠历练战绩", "灵宠历练", "灵宠战报"),
        (InlineCommand(0, "再探此路", f"灵宠历练 {route.name}"),),
    )


__all__ = ["KEY_PREFIX", "PAGE_SIZE", "RECENT_WINDOW", "catalog", "detail"]
