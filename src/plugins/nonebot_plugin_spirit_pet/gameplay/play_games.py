from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.time import beijing_day

GAMES = (
    ("hide_food", "藏食寻宝", 3, None),
    ("aura_resonance", "灵息共振", 2, 2),
    ("reaction", "反应试炼", 1, 1),
)
# (key, name, 精彩亲密加成, 精彩灵粮奖励) — 寻常 = +2 亲密, 失手 = +1 亲密.
CREDENTIAL_PREFIX = "play_game_"
GAMES_PER_DAY = 1


def _today(ctx: Context) -> str:
    return beijing_day(ctx.now)


def _row(ctx: Context, day: str):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{CREDENTIAL_PREFIX}{day}"),
    ).fetchone()


def _played_count(row) -> int:
    return row["progress"] if row else 0


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠嬉戏 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠嬉戏", (
            "每天可以和出战灵宠玩一局小游戏：藏食寻宝、灵息共振或反应试炼。",
            "尚未结契，先完成领养，再和伙伴嬉戏。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    day = _today(ctx)
    row = _row(ctx, day)
    played = _played_count(row)
    lines = [f"今日已玩 {played}/{GAMES_PER_DAY} 局。"]
    links = []
    for key, name, _, _ in GAMES:
        if played >= GAMES_PER_DAY and row["claimed"] == key:
            lines.append(f"{name} · 已游玩")
        elif played >= GAMES_PER_DAY:
            lines.append(f"{name} · 今日已错过")
        else:
            lines.append(f"{name} · 可游玩")
            links.append(InlineCommand(len(lines) - 1, "开始游戏", f"灵宠嬉戏 {name}"))
    return Reply("灵宠嬉戏", tuple(lines), ("我的灵宠", "灵宠陪伴奖励"), tuple(links))


def play_game(ctx: Context, arg: str) -> Reply:
    name = arg.strip()
    if not name:
        return catalog(ctx, "")
    entry = next((g for g in GAMES if g[1] == name), None)
    if entry is None:
        raise GameError("没有这个小游戏，可选：藏食寻宝、灵息共振、反应试炼。")
    ctx.player()  # adoption reply for unregistered players
    day = _today(ctx)
    row = _row(ctx, day)
    if _played_count(row) >= GAMES_PER_DAY:
        raise GameError("今天已经和灵宠嬉戏过了，明日再来。")
    pet = ctx.pet()
    ctx.require_idle_pet(pet)

    # 掷点 + 亲密/境界加成：亲密最多 100、境界 0-6，合计决定档位。
    roll = ctx.rng.randint(1, 100)
    bonus = pet.affinity // 20 + getattr(pet, "realm", 0)
    score = roll + bonus
    if score >= 90:
        grade, grade_name = 3, "精彩"
    elif score >= 50:
        grade, grade_name = 2, "寻常"
    else:
        grade, grade_name = 1, "失手"
    _, game_name, great_affinity, great_food = entry
    if grade == 3:
        gained = great_affinity
        food = great_food or 0
    elif grade == 2:
        gained, food = 2, 0
    else:
        gained, food = 1, 0
    pet.affinity = min(100, pet.affinity + gained)
    if food:
        ctx.repo.add_item(ctx.user_id, "spirit_food", food)
    # progress = 已玩局数; quest_id 追加游戏 key 由 claimed 字段无法承载，
    # 改为把游戏 key 写入独立行：play_game_<日期> 唯一，claimed 不适用。
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=0",
        (ctx.user_id, f"{CREDENTIAL_PREFIX}{day}", GAMES_PER_DAY),
    )
    grade_lines = {
        3: f"{pet.name}玩得格外尽兴，灵契愈发牢固（{game_name}·精彩）。",
        2: f"{pet.name}和你玩得开心（{game_name}·寻常）。",
        1: f"{pet.name}有点兴致缺缺，但也陪你玩完了（{game_name}·失手）。",
    }
    lines = [grade_lines[grade], f"亲密 +{gained}（{pet.affinity}/100）。"]
    if food:
        lines.append("灵粮 +1")
    return Reply("灵宠嬉戏", tuple(lines), ("灵宠嬉戏", "我的灵宠", "灵宠陪伴奖励"))
