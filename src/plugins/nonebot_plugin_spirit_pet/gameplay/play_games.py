"""灵宠嬉戏: three daily mini-games, each resolved against one pet attribute.

The daily quota is one play per Beijing day, recorded as ``play_game_<day>``
(progress 1). Which game was played is a separate row ``play_pick_<day>_<id>``
so the page can name it — ``claimed`` stays a boolean flag and is never
overloaded with a game id.

Mastery survives the daily reset: ``play_mastery_<id>`` counts plays, and each
milestone (5/15/30) pays exactly once through ``play_milestone_<id>_<at>``.
Everything lives in ``quest_progress``; there is no schema change.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..domain.play_game_content import PlayGame, PlayGameMilestone
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from .combat import pet_stats
from .rewards import grant as _grant_reward

DAY_PREFIX = "play_game_"
PICK_PREFIX = "play_pick_"
MASTERY_PREFIX = "play_mastery_"
CLAIM_PREFIX = "play_milestone_"

GAMES_PER_DAY = 1
BOARD_PAGE_SIZE = 5
GRADE_GREAT = 90
GRADE_PLAIN = 50
MAX_SCORE = 120
AFFINITY_BY_GRADE = {3: 3, 2: 2, 1: 1}


def games(ctx: Context) -> list[PlayGame]:
    return list(ctx.content.play_games.values())


def _game(ctx: Context, name: str) -> PlayGame:
    game = next((entry for entry in games(ctx) if entry.name == name), None)
    if game is None:
        choices = "、".join(entry.name for entry in games(ctx))
        raise GameError(f"没有这个小游戏，可选：{choices}。")
    return game


def _day_row(ctx: Context, user_id: str, day: str):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, f"{DAY_PREFIX}{day}"),
    ).fetchone()


def _picked(ctx: Context, user_id: str, day: str) -> str | None:
    prefix = f"{PICK_PREFIX}{day}_"
    row = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id, f"{prefix}%"),
    ).fetchone()
    return row["quest_id"][len(prefix):] if row else None


def _played(ctx: Context, user_id: str, day: str | None = None) -> tuple[int, str | None]:
    day = day or beijing_day(ctx.now)
    row = _day_row(ctx, user_id, day)
    played = int(row["progress"]) if row else 0
    return played, (_picked(ctx, user_id, day) if played else None)


def mastery(ctx: Context, user_id: str, game_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, f"{MASTERY_PREFIX}{game_id}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _claimed(ctx: Context, user_id: str, game_id: str, at: int) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, f"{CLAIM_PREFIX}{game_id}_{at}"),
    ).fetchone()
    return bool(row and row["claimed"])


def next_milestone(ctx: Context, user_id: str, game: PlayGame) -> PlayGameMilestone | None:
    total = mastery(ctx, user_id, game.id)
    for milestone in game.milestones:
        if total < milestone.at:
            return milestone
    return None


def claimable(ctx: Context, user_id: str) -> list[tuple[PlayGame, PlayGameMilestone]]:
    """Reached-but-unclaimed milestones, lowest tier first per game."""
    found: list[tuple[PlayGame, PlayGameMilestone]] = []
    for game in games(ctx):
        total = mastery(ctx, user_id, game.id)
        for milestone in game.milestones:
            if total >= milestone.at and not _claimed(ctx, user_id, game.id, milestone.at):
                found.append((game, milestone))
                break
    return found


def _reward(milestone: PlayGameMilestone) -> Reward:
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=milestone.stones, maximum=milestone.stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in milestone.items.items()
        },
    )


def _reward_text(ctx: Context, milestone: PlayGameMilestone) -> str:
    parts = [f"灵石 {milestone.stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}"
        for item_id, amount in milestone.items.items()
    )
    return "，".join(parts)


def _score(ctx: Context, pet, game: PlayGame) -> int:
    stats = pet_stats(pet, ctx.content)
    bonus = getattr(stats, game.stat) // 8 + pet.affinity // 25
    return min(MAX_SCORE, ctx.rng.randint(1, 100) + bonus)


def _grade(score: int) -> int:
    if score >= GRADE_GREAT:
        return 3
    if score >= GRADE_PLAIN:
        return 2
    return 1


def require_day(ctx: Context) -> None:
    day = beijing_day(ctx.now)
    if _played(ctx, ctx.user_id, day)[0] >= GAMES_PER_DAY:
        raise GameError("今天已经和灵宠嬉戏过了，明日再来。")
    later = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id GLOB 'play_game_*' "
        "AND quest_id>? LIMIT 1", (ctx.user_id, DAY_PREFIX + day),
    ).fetchone()
    if later:
        raise GameError("日期早于已有嬉戏记录，请等待时钟恢复后再开局。")


def reserve_day(ctx: Context, game: PlayGame) -> None:
    day = beijing_day(ctx.now)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,0)",
        (ctx.user_id, DAY_PREFIX + day),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,0)",
        (ctx.user_id, f"{PICK_PREFIX}{day}_{game.id}"),
    )


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠嬉戏。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = ["每天可以和出战灵宠玩一局小游戏："]
        lines.extend(f"{game.name} · {game.description}" for game in games(ctx))
        lines.append("尚未结契，先完成领养，再和伙伴嬉戏。")
        return Reply(
            "灵宠嬉戏",
            tuple(lines),
            ("灵宠帮助",),
            (InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),),
        )

    played, picked = _played(ctx, player.user_id)
    lines = [f"今日已玩 {played}/{GAMES_PER_DAY} 局。"]
    last = ctx.repo.latest_play_course_action(player.user_id)
    if last and last["snapshot"]["status"] == "active":
        lines.append("还有一局跃障进行中，请继续或退出原赛道；当前不能另外嬉戏。")
        return Reply("灵宠嬉戏", tuple(lines), ("灵宠跃障", "灵宠嬉戏 记录", "我的灵宠"))
    links = []
    for game in games(ctx):
        if played >= GAMES_PER_DAY:
            state = "已游玩" if game.id == picked else "今日已错过"
            lines.append(f"{game.name} · {state}")
            continue
        lines.append(f"{game.name} · 可游玩")
        links.append(InlineCommand(len(lines) - 1, "开始游戏", f"灵宠嬉戏 {game.name}"))
    if played < GAMES_PER_DAY:
        lines.append("每天只能玩一局，精通会一直累积。")
    return Reply(
        "灵宠嬉戏", tuple(lines), ("灵宠嬉戏 记录", "我的灵宠", "灵宠陪伴奖励", "灵宠跃障"), tuple(links),
    )


def play_game(ctx: Context, arg: str) -> Reply:
    head, _, rest = arg.strip().partition(" ")
    if head == "记录":
        return board(ctx, rest)
    if head == "领奖":
        return claim(ctx, rest)
    name = arg.strip()
    if not name:
        return catalog(ctx, "")
    game = _game(ctx, name)
    ctx.player()
    from .play_courses import state
    if state(ctx):
        raise GameError("还有一局跃障未结束，请继续或退出原赛道后再嬉戏。")
    require_day(ctx)
    pet = ctx.pet()
    ctx.require_idle_pet(pet)
    score = _score(ctx, pet, game)
    reserve_day(ctx, game)
    return settle(ctx, pet, game, score)


def settle(ctx: Context, pet, game: PlayGame, score: int) -> Reply:
    """Both instant games and courses consume the same mastery and reward loop."""
    player = ctx.player()
    grade = _grade(score)
    gained = min(100 - pet.affinity, AFFINITY_BY_GRADE[grade] + (game.great_bonus if grade == 3 else 0))
    pet.affinity = min(100, pet.affinity + gained)

    rewards: list[str] = []
    if grade == 3:
        for item_id, amount in game.great_items.items():
            ctx.repo.add_item(player.user_id, item_id, amount)
            rewards.append(f"{ctx.content.items[item_id].name} +{amount}")

    total = mastery(ctx, player.user_id, game.id) + 1
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+1",
        (player.user_id, f"{MASTERY_PREFIX}{game.id}"),
    )

    from .bond_levels import add_exp

    add_exp(ctx, pet.pet_id, 6)
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    grade_line = {
        3: f"{pet.name}玩得格外尽兴，灵契愈发牢固（{game.name}·精彩）。",
        2: f"{pet.name}和你玩得开心（{game.name}·寻常）。",
        1: f"{pet.name}有点兴致缺缺，但也陪你玩完了（{game.name}·失手）。",
    }[grade]
    lines = [grade_line, f"亲密 +{gained}（{pet.affinity}/100）。"]
    lines.extend(rewards)
    lines.append(f"{game.name}精通 {total}。")
    return Reply("灵宠嬉戏", tuple(lines), ("灵宠嬉戏", "灵宠嬉戏 记录", "我的灵宠"))


def board(ctx: Context, arg: str = "") -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(
            "灵宠嬉戏 记录",
            (
                "每条小游戏各自累计精通，达到 5/15/30 局可领一次性奖励。",
                "尚未结契，先完成领养。",
            ),
            ("灵宠帮助",),
            (InlineCommand(1, "开始领养", "灵宠领养 "),),
        )
    page_data = paginate(games(ctx), arg, "灵宠嬉戏 记录", "灵宠嬉戏 记录", BOARD_PAGE_SIZE)
    lines = [f"今日已玩 {_played(ctx, player.user_id)[0]}/{GAMES_PER_DAY} 局。"]
    links = []
    for game in page_data.entries:
        total = mastery(ctx, player.user_id, game.id)
        done = sum(
            1 for milestone in game.milestones
            if _claimed(ctx, player.user_id, game.id, milestone.at)
        )
        pending = next_milestone(ctx, player.user_id, game)
        if pending is None:
            lines.append(
                f"{game.name} · 精通 {total} · 全部精通（已领 {done}/{len(game.milestones)}）"
            )
            continue
        lines.append(
            f"{game.name} · 精通 {total} · 下一档 {pending.at} 局"
            f"（还差 {pending.at - total}）· 已领 {done}/{len(game.milestones)}"
        )
        for milestone in game.milestones:
            if total >= milestone.at and not _claimed(ctx, player.user_id, game.id, milestone.at):
                lines.append(
                    f"  可领取「{game.name} {milestone.at} 局」· {_reward_text(ctx, milestone)}"
                )
                links.append(InlineCommand(
                    len(lines) - 1, "领取奖励", f"灵宠嬉戏 领奖 {game.name} {milestone.at}",
                ))
                break
    lines.append(f"第 {page_data.number}/{page_data.total} 页。")
    return Reply(
        f"灵宠嬉戏 记录 {page_data.number}/{page_data.total}",
        tuple(lines),
        (*page_data.navigation, "灵宠嬉戏", "我的灵宠")[:4],
        tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠嬉戏 领奖 <游戏名> <档位>，例如 灵宠嬉戏 领奖 藏食寻宝 5。")
    player = ctx.player()
    game = _game(ctx, parts[0])
    if not parts[1].isdecimal():
        raise GameError("档位须为局数整数，例如 5、15、30。")
    at = quantity(parts[1], max(99, max(entry.at for entry in game.milestones)))
    milestone = next((entry for entry in game.milestones if entry.at == at), None)
    if milestone is None:
        allowed = "、".join(str(entry.at) for entry in game.milestones)
        raise GameError(f"{game.name}的档位可选：{allowed}。")
    total = mastery(ctx, player.user_id, game.id)
    if total < at:
        raise GameError(f"{game.name}精通 {total}，尚未达成 {at} 局。")
    if _claimed(ctx, player.user_id, game.id, at):
        raise GameError(f"{game.name} {at} 局奖励已领取。")
    result = _grant_reward(ctx, _reward(milestone), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, f"{CLAIM_PREFIX}{game.id}_{at}", total),
    )
    return Reply(
        "嬉戏奖励",
        (f"{game.name} {at} 局精通奖励已领取。", *result),
        ("灵宠嬉戏 记录", "灵宠嬉戏", "我的灵宠"),
    )


def objective_line(ctx: Context, user_id: str) -> str:
    played, _ = _played(ctx, user_id)
    entries = games(ctx)
    mastered = sum(
        1 for game in entries
        if mastery(ctx, user_id, game.id) >= game.milestones[-1].at
    )
    last = ctx.repo.latest_play_course_action(user_id)
    status = "跃障进行中" if last and last["snapshot"]["status"] == "active" else ("今日已玩" if played else "今日未玩")
    return f"嬉戏：{status} · 精通 {mastered}/{len(entries)} 项"


__all__ = [
    "CLAIM_PREFIX", "DAY_PREFIX", "GAMES_PER_DAY", "MASTERY_PREFIX", "PICK_PREFIX",
    "board", "catalog", "claim", "claimable", "games", "mastery", "next_milestone",
    "objective_line", "play_game",
]
