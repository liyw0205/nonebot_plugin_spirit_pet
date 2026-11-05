"""Read-only spar records, aggregated by opponent."""

from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import BEIJING

PAGE_SIZE = 5
RECENT_WINDOW = 5


def _rows(ctx: Context, user_id: str) -> list[dict]:
    return [
        dict(row)
        for row in ctx.repo.conn.execute(
            "SELECT b.battle_id AS battle_id, b.winner_side AS winner_side, "
            "b.played_at AS played_at, p.side AS my_side, "
            "(SELECT DISTINCT o.user_id FROM battle_participants o "
            " WHERE o.battle_id=b.battle_id AND o.side=1-p.side LIMIT 1) AS opponent "
            "FROM battle_records b "
            "JOIN (SELECT DISTINCT battle_id, user_id, side FROM battle_participants) p "
            "ON p.battle_id=b.battle_id "
            "WHERE p.user_id=? AND b.kind='spar'",
            (user_id,),
        ).fetchall()
    ]


def _uid(ctx: Context, user_id: str) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT id + 9999 AS uid FROM player_identity WHERE user_id=?", (user_id,),
    ).fetchone()
    return int(row["uid"]) if row is not None else None


def _time(value: int | None) -> str:
    if value is None:
        return "尚无获胜"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _stamp(value: int | None) -> str:
    if value is None:
        return "无记录"
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def _opponents(ctx: Context, user_id: str) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in _rows(ctx, user_id):
        opponent = row["opponent"]
        if not opponent or opponent == user_id:
            continue
        entry = grouped.setdefault(opponent, {
            "opponent": opponent,
            "uid": _uid(ctx, opponent),
            "fights": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "last_fight": None,
            "last_win": None,
        })
        entry["fights"] += 1
        if row["winner_side"] == -1:
            entry["draws"] += 1
        elif row["winner_side"] == row["my_side"]:
            entry["wins"] += 1
            entry["last_win"] = max(entry["last_win"] or 0, row["played_at"])
        else:
            entry["losses"] += 1
        entry["last_fight"] = max(entry["last_fight"] or 0, row["played_at"])
    return list(grouped.values())


def _row_text(entry) -> str:
    return (
        f"UID {entry['uid']} · 切磋 {entry['fights']} 场 · "
        f"{entry['wins']} 胜 {entry['losses']} 负 {entry['draws']} 平 · "
        f"最近切磋：{_stamp(entry['last_fight'])}"
    )


def _recent(ctx: Context, user_id: str, opponent: str) -> tuple[str, ...]:
    rows = [row for row in _rows(ctx, user_id) if row["opponent"] == opponent]
    rows.sort(key=lambda row: (row["played_at"], row["battle_id"]), reverse=True)
    return tuple(
        f"{datetime.fromtimestamp(row['played_at'], BEIJING).strftime('%m-%d')}"
        f" · {'胜' if row['winner_side'] == row['my_side'] else '平' if row['winner_side'] == -1 else '负'}"
        for row in rows[:RECENT_WINDOW]
    )


def _bad_format() -> GameError:
    return GameError("格式：灵宠切磋战绩 [分页 N|UID]，例如 灵宠切磋战绩 10001。")


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    title = "切磋战绩"
    if player is None:
        return Reply(title, (
            "切磋战绩按对手汇总本人参与过的切磋；切磋不消耗资源、不计赛季积分。",
            "尚未结契，先完成领养；切磋需要双方都选择出战灵宠。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    value = arg.strip()
    page = 1
    if value.startswith("分页"):
        parts = value.split()
        if len(parts) != 2 or parts[0] != "分页" or not parts[1].isdecimal():
            raise _bad_format()
        page = int(parts[1])
        if page < 1:
            raise _bad_format()
    elif value:
        if not value.isdecimal():
            raise _bad_format()
        return _detail(ctx, player.user_id, int(value))

    opponents = _opponents(ctx, player.user_id)
    opponents.sort(key=lambda entry: (-entry["last_fight"], entry["uid"] or 0))
    if not opponents:
        return Reply(f"{title} 1/1", (
            "还没有切磋记录；发送 灵宠切磋 <UID> 与道友试一场。",
        ), ("灵宠切磋", "灵宠战报", "灵宠帮助"))
    pages = max(1, (len(opponents) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"切磋战绩共 {pages} 页。")
    selected = opponents[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for entry in selected:
        lines.append(_row_text(entry))
        links.append(InlineCommand(
            len(lines) - 1, "查看战绩", f"灵宠切磋战绩 {entry['uid']}",
        ))
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠切磋战绩 分页 {page - 1}")
    if page < pages:
        commands.append(f"灵宠切磋战绩 分页 {page + 1}")
    commands.extend(("灵宠切磋", "灵宠战报", "灵宠帮助"))
    return Reply(f"{title} {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def _detail(ctx: Context, user_id: str, uid: int) -> Reply:
    if uid < 10000:
        raise GameError("未找到该修士。")
    row = ctx.repo.conn.execute(
        "SELECT user_id FROM player_identity WHERE id=?", (uid - 9999,),
    ).fetchone()
    if row is None or row["user_id"] == user_id:
        raise GameError("未找到该修士。")
    opponent = row["user_id"]
    entry = next((entry for entry in _opponents(ctx, user_id)
                  if entry["opponent"] == opponent), None)
    if entry is None:
        raise GameError(f"还没有与 UID {uid} 的切磋记录，发送 灵宠切磋 {uid} 试一场。")
    recent = _recent(ctx, user_id, opponent)
    return Reply(
        f"切磋战绩 · UID {uid}",
        (
            f"切磋 {entry['fights']} 场 · {entry['wins']} 胜 {entry['losses']} 负 "
            f"{entry['draws']} 平。",
            f"最近切磋：{_stamp(entry['last_fight'])} · 最近获胜：{_time(entry['last_win'])}。",
            "最近五场（新在前）：" + ("、".join(recent) if recent else "无"),
        ),
        ("灵宠切磋战绩", "灵宠切磋", "灵宠战报"),
        (InlineCommand(0, "再切磋", f"灵宠切磋 {uid}"),),
    )


__all__ = ["PAGE_SIZE", "RECENT_WINDOW", "catalog"]
