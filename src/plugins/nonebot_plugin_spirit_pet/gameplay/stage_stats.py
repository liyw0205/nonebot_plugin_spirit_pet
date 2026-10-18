from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.time import BEIJING

PAGE_SIZE = 5
RECENT_WINDOW = 5


def _catalog(ctx: Context) -> dict[str, object]:
    """Every stat-able battle_key: chapter stages plus tower floors."""
    return {**ctx.content.stages, **ctx.content.tower}


def _entry_name(entry) -> str:
    return entry.name


def _resolve(ctx: Context, value: str):
    text = value.strip()
    if text.isdecimal():
        order = quantity(text, 999999)
        floor = next((floor for floor in ctx.content.tower.values() if floor.order == order), None)
        if floor is not None:
            return floor
        stage = next((stage for stage in ctx.content.stages.values() if stage.order == order), None)
        if stage is not None:
            return stage
        raise GameError("没有这个编号的关卡或塔层，请检查 灵宠关卡 或 灵宠万灵塔。")
    if text in ctx.content.stages:
        return ctx.content.stages[text]
    if text in ctx.content.tower:
        return ctx.content.tower[text]
    return named({**ctx.content.stages, **ctx.content.tower}, text)


def _rows(ctx: Context, user_id: str):
    keys = tuple(_catalog(ctx))
    if not keys:
        return ()
    placeholders = ",".join("?" for _ in keys)
    return ctx.repo.conn.execute(
        "SELECT b.battle_key AS stage_id, COUNT(*) AS fights, "
        "SUM(b.winner_side=p.side) AS wins, "
        "SUM(b.winner_side=-1) AS draws, "
        "SUM(b.winner_side=1-p.side) AS losses, "
        "MAX(CASE WHEN b.winner_side=p.side THEN b.played_at END) AS last_win, "
        "MAX(b.played_at) AS last_fight "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve_stage' "
        f"AND b.battle_key IN ({placeholders}) "
        "GROUP BY b.battle_key",
        (user_id, *keys),
    ).fetchall()


def _time(value: int | None) -> str:
    if value is None:
        return "尚无获胜"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _recent(ctx: Context, user_id: str, stage_id: str) -> tuple[str, ...]:
    rows = ctx.repo.conn.execute(
        "SELECT b.winner_side=p.side AS won, b.winner_side=-1 AS drawn, b.played_at "
        "FROM battle_records b JOIN battle_participants p ON p.battle_id=b.battle_id "
        "WHERE p.user_id=? AND b.kind='pve_stage' AND b.battle_key=? "
        "ORDER BY b.played_at DESC, b.battle_id DESC LIMIT ?",
        (user_id, stage_id, RECENT_WINDOW),
    ).fetchall()
    return tuple(
        f"{datetime.fromtimestamp(row['played_at'], BEIJING).strftime('%m-%d')}"
        f" · {'胜' if row['won'] else '平' if row['drawn'] else '负'}"
        for row in rows
    )


def _challenge_command(ctx: Context, entry) -> str:
    if entry.id in ctx.content.tower:
        return f"灵宠挑战万灵塔 {entry.order}"
    return f"{'灵宠组队关卡' if entry.team else '灵宠挑战关卡'} {entry.order}"


def catalog(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value and not value.isdecimal():
        return detail(ctx, value)
    if value:
        page = quantity(value, 999999)
    else:
        page = 1
    player = ctx.repo.player(ctx.user_id)
    title = "关卡战绩"
    if player is None:
        return Reply(title, (
            "关卡战绩按关卡与塔层汇总你参与过的每一场真实战斗（扫荡不写战报，不计入）。",
            "尚未结契，先完成领养，出战获胜后这里会记录战绩。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    rows = _rows(ctx, player.user_id)
    order = {stage_id: index for index, stage_id in enumerate(_catalog(ctx))}
    rows = sorted(rows, key=lambda row: (-row["last_fight"], order.get(row["stage_id"], 0)))
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"关卡战绩共 {pages} 页。")
    if not rows:
        return Reply(f"{title} 1/1", (
            "还没有关卡出战记录；发送 灵宠挑战关卡 <编号> 打一场真实战斗。",
        ), ("灵宠关卡", "灵宠帮助"))
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for row in selected:
        entry = _catalog(ctx)[row["stage_id"]]
        wins, losses, draws = row["wins"], row["losses"], row["draws"]
        lines.append(
            f"{_entry_name(entry)} · 出战 {row['fights']} 场 · {wins} 胜 {losses} 负 {draws} 平"
            f" · 最近获胜：{_time(row['last_win'])}"
        )
        links.append(InlineCommand(
            len(lines) - 1, "查看战绩", f"灵宠关卡战绩 {_entry_name(entry)}",
        ))
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠关卡战绩 {page - 1}")
    if page < pages:
        commands.append(f"灵宠关卡战绩 {page + 1}")
    commands.extend(("灵宠关卡", "灵宠关卡星级"))
    return Reply(f"{title} {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    entry = _resolve(ctx, arg)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        raise GameError("尚未结契，先完成领养再查看关卡战绩。")
    rows = [row for row in _rows(ctx, player.user_id) if row["stage_id"] == entry.id]
    if not rows:
        raise GameError(f"还没有{entry.name}的出战记录。")
    row = rows[0]
    wins, losses, draws = row["wins"], row["losses"], row["draws"]
    recent = _recent(ctx, player.user_id, entry.id)
    challenge = _challenge_command(ctx, entry)
    lines = [
        f"{entry.name} · 出战 {row['fights']} 场 · {wins} 胜 {losses} 负 {draws} 平。",
        f"最近出战：{_time(row['last_fight'])} · 最近获胜：{_time(row['last_win'])}。",
        "最近五场（新在前）：" + ("、".join(recent) if recent else "无"),
    ]
    links = [
        InlineCommand(2, "查看星级", "灵宠关卡星级"),
        InlineCommand(0, "前往挑战", challenge),
    ]
    return Reply(
        f"关卡战绩 · {entry.name}", tuple(lines),
        (challenge, "灵宠关卡", "灵宠关卡星级"), tuple(links),
    )
