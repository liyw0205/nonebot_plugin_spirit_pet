from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import BEIJING

PAGE_SIZE = 5
RECENT_WINDOW = 5


def _rows(ctx: Context, user_id: str):
    dungeon_ids = tuple(ctx.content.dungeons)
    if not dungeon_ids:
        return ()
    placeholders = ",".join("?" for _ in dungeon_ids)
    return ctx.repo.conn.execute(
        "SELECT b.battle_key AS dungeon_id, COUNT(*) AS fights, "
        "SUM(b.winner_side=p.side) AS wins, "
        "SUM(b.winner_side=-1) AS draws, "
        "SUM(b.winner_side=1-p.side) AS losses, "
        "MAX(CASE WHEN b.winner_side=p.side THEN b.played_at END) AS last_win, "
        "MAX(b.played_at) AS last_fight "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve' "
        f"AND b.battle_key IN ({placeholders}) "
        "GROUP BY b.battle_key",
        (user_id, *dungeon_ids),
    ).fetchall()


def _time(value: int | None) -> str:
    if value is None:
        return "尚无获胜"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _dungeon(ctx: Context, dungeon_id: str):
    return ctx.content.dungeons[dungeon_id]


def _recent(ctx: Context, user_id: str, dungeon_id: str) -> tuple[str, ...]:
    rows = ctx.repo.conn.execute(
        "SELECT b.winner_side=p.side AS won, b.winner_side=-1 AS drawn, b.played_at "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? "
        "ORDER BY b.played_at DESC, b.battle_id DESC LIMIT ?",
        (user_id, dungeon_id, RECENT_WINDOW),
    ).fetchall()
    return tuple(
        f"{datetime.fromtimestamp(row['played_at'], BEIJING).strftime('%m-%d')}"
        f" · {'胜' if row['won'] else '平' if row['drawn'] else '负'}"
        for row in rows
    )


def catalog(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value and not value.isdecimal():
        return detail(ctx, value)
    page = quantity(value or "1", 999999)
    player = ctx.repo.player(ctx.user_id)
    title = "秘境战绩"
    if player is None:
        return Reply(title, (
            "秘境战绩按秘境汇总你参与过的每一场真实战斗（扫荡不写战报，不计入）。",
            "尚未结契，先完成领养，出战获胜后这里会记录战绩。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    rows = _rows(ctx, player.user_id)
    rows = sorted(rows, key=lambda row: (-row["last_fight"], row["dungeon_id"]))
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"秘境战绩共 {pages} 页。")
    if not rows:
        return Reply(f"{title} 1/1", (
            "还没有秘境出战记录；发送 灵宠挑战 <秘境名> 打一场真实战斗。",
        ), ("灵宠秘境", "灵宠帮助"))
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for row in selected:
        dungeon = _dungeon(ctx, row["dungeon_id"])
        wins, losses, draws = row["wins"], row["losses"], row["draws"]
        lines.append(
            f"{dungeon.name} · 出战 {row['fights']} 场 · {wins} 胜 {losses} 负 {draws} 平"
            f" · 最近获胜：{_time(row['last_win'])}"
        )
        links.append(InlineCommand(
            len(lines) - 1, "查看战绩", f"灵宠秘境战绩 {dungeon.name}",
        ))
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠秘境战绩 {page - 1}")
    if page < pages:
        commands.append(f"灵宠秘境战绩 {page + 1}")
    commands.extend(("灵宠秘境", "灵宠秘境首通"))
    return Reply(f"{title} {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    dungeon = named(ctx.content.dungeons, arg)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        raise GameError("尚未结契，先完成领养再查看秘境战绩。")
    rows = [row for row in _rows(ctx, player.user_id) if row["dungeon_id"] == dungeon.id]
    if not rows:
        raise GameError(f"还没有{dungeon.name}的出战记录，发送 灵宠挑战 {dungeon.name} 打一场。")
    row = rows[0]
    wins, losses, draws = row["wins"], row["losses"], row["draws"]
    command = "灵宠组队挑战" if dungeon.team else "灵宠挑战"
    recent = _recent(ctx, player.user_id, dungeon.id)
    lines = [
        f"{dungeon.name} · 出战 {row['fights']} 场 · {wins} 胜 {losses} 负 {draws} 平。",
        f"最近出战：{_time(row['last_fight'])} · 最近获胜：{_time(row['last_win'])}。",
        "最近五场（新在前）：" + ("、".join(recent) if recent else "无"),
    ]
    links = [
        InlineCommand(2, "查看首通奖励", "灵宠秘境首通"),
        InlineCommand(0, f"前往{'组队' if dungeon.team else '挑战'}", f"{command} {dungeon.name}"),
    ]
    return Reply(
        f"秘境战绩 · {dungeon.name}", tuple(lines),
        (f"{command} {dungeon.name}", "灵宠秘境", "灵宠秘境首通"), tuple(links),
    )
