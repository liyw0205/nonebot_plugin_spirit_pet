"""Season battle pass: dual-track 30-level ladder over arena seasons.

Experience is earned from real activity and stored per player per season in
`quest_progress` as `battle_pass_exp_<season>`. Levels are derived (100 EXP per
level, capped at 30) so no schema change is needed. Reward credentials are
`pass_reward_<season>_<level>_<track>`; the premium track also uses
`battle_pass_premium_<season>` for its one-time unlock. Seasons align with the
arena season (Beijing calendar month), so a new season naturally resets every
credential without touching old rows.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.pagination import paginate
from ..utils.time import beijing_day, season_bounds
from .rewards import grant

LEVELS = 30
EXP_PER_LEVEL = 100
MAX_EXP = LEVELS * EXP_PER_LEVEL
PREMIUM_COST = 2000
PAGE_SIZE = 5
EXP_PREFIX = "battle_pass_exp_"
PREMIUM_PREFIX = "battle_pass_premium_"
REWARD_PREFIX = "pass_reward_"
LAST_SEASON_PREFIX = "battle_pass_seen_"
DAILY_CLEAR_PREFIX = "battle_pass_daily_"
TRACKS = ("免费", "进阶")
PREMIUM_TITLE = "赛季行者"

# Activity EXP: every source is a single settlement hook, so one action can
# never award the same row twice.
ACTIVITY_EXP = {
    "pve_win": 20,
    "pvp_challenge": 20,
    "expedition_return": 30,
    "farm_harvest": 20,
    "daily_all_clear": 50,
}


def _free_reward(level: int) -> Reward:
    """Small steady currency along the free track; every level pays out."""
    stones = 40 + level * 4
    items = {"spirit_food": Range(minimum=1, maximum=1)} if level % 5 == 0 else {}
    if level % 10 == 0:
        items["forge_ore"] = Range(minimum=1, maximum=1)
    return Reward(exp=Range(minimum=0, maximum=0), stones=Range(minimum=stones, maximum=stones), items=items)


def _premium_reward(level: int) -> Reward:
    """Premium pays at every fifth level, with materials the free track lacks."""
    stones = 120 + level * 10
    items = {"bloodline_essence": Range(minimum=1, maximum=1)}
    if level % 15 == 0:
        items["breakthrough_pill"] = Range(minimum=1, maximum=1)
    return Reward(exp=Range(minimum=0, maximum=0), stones=Range(minimum=stones, maximum=stones), items=items)


PREMIUM_LEVELS = tuple(range(5, LEVELS + 1, 5))


def season_id(now: int) -> str:
    """The battle pass shares the arena season (Beijing calendar month)."""
    return season_bounds(now)[0]


def exp_id(season: str) -> str:
    return f"{EXP_PREFIX}{season}"


def premium_id(season: str) -> str:
    return f"{PREMIUM_PREFIX}{season}"


def claim_id(season: str, level: int, track: str) -> str:
    return f"{REWARD_PREFIX}{season}_{level}_{'premium' if track == '进阶' else 'free'}"


def experience(ctx: Context, user_id: str | None = None) -> int:
    """Season EXP, capped at the final level so later activity is not lost silently."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, exp_id(season_id(ctx.now))),
    ).fetchone()
    return min(int(row["progress"]), MAX_EXP) if row else 0


def level_of(exp: int) -> int:
    return min(exp // EXP_PER_LEVEL, LEVELS)


def premium(ctx: Context, user_id: str | None = None) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, premium_id(season_id(ctx.now))),
    ).fetchone()
    return bool(row and row["claimed"])


def add_experience(ctx: Context, source: str, user_id: str | None = None) -> int:
    """Award activity EXP once per settlement; returns the amount granted."""
    amount = ACTIVITY_EXP.get(source)
    if amount is None:
        raise ValueError(f"unknown battle pass activity: {source}")
    owner = user_id or ctx.user_id
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (owner, exp_id(season_id(ctx.now)), amount),
    )
    return amount


def claim_daily_clear(ctx: Context, user_id: str | None = None) -> bool:
    """Award the all-clear bonus once per Beijing day; True only on first award.

    The credential is per day so a replayed claim or a second visit to the
    daily board after midnight can never pay the same day twice.
    """
    owner = user_id or ctx.user_id
    credential = f"{DAILY_CLEAR_PREFIX}{beijing_day(ctx.now)}"
    inserted = ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO NOTHING",
        (owner, credential, ctx.now),
    )
    if inserted.rowcount != 1:
        return False
    add_experience(ctx, "daily_all_clear", owner)
    return True


def claimed(ctx: Context, user_id: str, level: int, track: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(season_id(ctx.now), level, track)),
    ).fetchone()
    return bool(row and row["claimed"])


def _reward_for(track: str, level: int) -> Reward | None:
    if track == "免费":
        return _free_reward(level)
    if level % 5:
        return None
    return _premium_reward(level)


def _reward_text(ctx: Context, reward: Reward) -> str:
    parts = [f"灵石 {reward.stones.minimum}"] if reward.stones.minimum else []
    parts.extend(
        f"{ctx.content.items[item].name if item in ctx.content.items else item} {bounds.minimum}"
        for item, bounds in reward.items.items()
    )
    return "，".join(parts) or "无"


def _title_line(level: int) -> str:
    return f"限定称号「{PREMIUM_TITLE}」" if level >= LEVELS else ""


def _state(ctx: Context, user_id: str, level: int, track: str, current: int) -> str:
    if claimed(ctx, user_id, level, track):
        return "已领取"
    if track == "进阶" and not premium(ctx, user_id):
        return "未解锁进阶"
    if current < level:
        return "未达成"
    return "可领取"


def catalog(ctx: Context, arg: str) -> Reply:
    season = season_id(ctx.now)
    current = level_of(experience(ctx))
    unlocked = premium(ctx)
    player = ctx.repo.player(ctx.user_id)
    page_of_levels = paginate(
        tuple(range(1, LEVELS + 1)), arg, "灵宠战令", "灵宠战令", PAGE_SIZE,
    )
    lines = [
        f"赛季 {season} · 战令 {current}/{LEVELS} 级（{experience(ctx)} 点经验）"
        f" · {'进阶已解锁' if unlocked else f'进阶未解锁（{PREMIUM_COST} 灵石）'}",
        "活跃度来源：" + "，".join(
            f"{label} +{ACTIVITY_EXP[key]}" for key, label in (
                ("pve_win", "秘境/关卡胜利"), ("pvp_challenge", "论剑挑战"),
                ("expedition_return", "委托归来"), ("farm_harvest", "灵田收获"),
                ("daily_all_clear", "每日任务全清"),
            )
        ) + "。",
    ]
    links = []
    for level in page_of_levels.entries:
        free_reward = _free_reward(level)
        free_state = _state(ctx, player.user_id if player else "", level, "免费", current)
        lines.append(f"{level} 级 · 免费：{_reward_text(ctx, free_reward)} · {free_state}")
        if player is not None and free_state == "可领取":
            links.append(InlineCommand(len(lines) - 1, "领取免费", f"灵宠战令领奖 {level} 免费"))
        premium_reward = _reward_for("进阶", level)
        if premium_reward is not None:
            premium_state = _state(ctx, player.user_id if player else "", level, "进阶", current)
            title = " · 限定称号「赛季行者」" if level >= LEVELS else ""
            lines.append(
                f"{level} 级 · 进阶：{_reward_text(ctx, premium_reward)}{title} · {premium_state}"
            )
            if player is not None and premium_state == "可领取":
                links.append(InlineCommand(len(lines) - 1, "领取进阶", f"灵宠战令领奖 {level} 进阶"))
    commands = list(page_of_levels.navigation)
    commands.append("灵宠战令回顾")
    if player is None:
        lines.append("尚未结契，先完成领养，活跃度才会累积为战令经验。")
        return Reply(
            f"战令 {current} 级 · {page_of_levels.number}/{page_of_levels.total}", tuple(lines), ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    if not unlocked:
        commands.insert(0, "灵宠战令进阶")
        lines.append(f"解锁进阶轨需 {PREMIUM_COST} 灵石，本季有效，费用不退还。")
    commands.append("灵宠目标")
    title = f"战令 {current} 级 · {page_of_levels.number}/{page_of_levels.total}"
    return Reply(title, tuple(lines), tuple(commands), tuple(links))


def unlock(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠战令进阶 不接受参数，直接发送即可。")
    player = ctx.player()
    season = season_id(ctx.now)
    if premium(ctx, player.user_id):
        raise GameError(f"赛季 {season} 的进阶轨已经解锁。")
    if player.stones < PREMIUM_COST:
        raise GameError(f"解锁进阶轨需要 {PREMIUM_COST} 灵石，当前灵石不足。")
    player.stones -= PREMIUM_COST
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, premium_id(season), ctx.now),
    )
    return Reply("战令进阶解锁", (
        f"赛季 {season} 的进阶轨已解锁，花费 {PREMIUM_COST} 灵石。",
        f"已达成 {len([level for level in PREMIUM_LEVELS if level_of(experience(ctx)) >= level])} 个进阶节点可领取。",
    ), ("灵宠战令", "灵宠目标"))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠战令领奖 <级别> <免费|进阶>。")
    level = quantity(parts[0], LEVELS)
    track = parts[1]
    if track not in TRACKS:
        raise GameError("领奖轨只能是 免费 或 进阶。")
    player = ctx.player()
    reward = _reward_for(track, level)
    if reward is None:
        raise GameError(f"进阶轨每 5 级发奖，{level} 级没有进阶奖励。")
    season = season_id(ctx.now)
    if claimed(ctx, player.user_id, level, track):
        raise GameError(f"赛季 {season} 的 {level} 级{track}奖励已领取。")
    if track == "进阶" and not premium(ctx, player.user_id):
        raise GameError("进阶轨尚未解锁，请先发送 灵宠战令进阶。")
    current = level_of(experience(ctx))
    if current < level:
        raise GameError(f"战令等级不足：当前 {current} 级，需 {level} 级。")
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(season, level, track), level),
    )
    lines = [f"赛季 {season} · {level} 级{track}奖励", *result]
    if track == "进阶" and level >= LEVELS:
        lines.append(f"获得限定称号「{PREMIUM_TITLE}」，可在 灵宠称号 佩戴。")
    return Reply("战令奖励", tuple(lines), ("灵宠战令", "灵宠称号", "灵宠目标"))


def _season_levels(ctx: Context, user_id: str) -> list[tuple[str, int]]:
    """Every season this player earned EXP in, newest first."""
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id, f"{EXP_PREFIX}%"),
    )
    out = []
    for row in rows:
        season = row["quest_id"][len(EXP_PREFIX):]
        if season:
            out.append((season, level_of(int(row["progress"]))))
    return sorted(out, reverse=True)


def history(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠战令回顾 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("战令回顾", (
            "尚未结契，先完成领养，才能回顾各赛季战令等级。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    current = season_id(ctx.now)
    seasons = _season_levels(ctx, player.user_id)
    lines = [f"当前赛季：{current} · 战令 {level_of(experience(ctx))}/{LEVELS} 级。"]
    history_rows = [(season, level) for season, level in seasons if season != current]
    if not history_rows:
        lines.append("还没有已结束赛季的战令记录。")
    for season, level in history_rows:
        lines.append(f"赛季 {season} · 战令 {level}/{LEVELS} 级")
    return Reply("战令回顾", tuple(lines), ("灵宠战令", "灵宠目标"))


def claimed_count(ctx: Context, user_id: str) -> int:
    """Claims across all seasons, used by the achievements/title metric."""
    return ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 AND quest_id LIKE ?",
        (user_id, f"{REWARD_PREFIX}%"),
    ).fetchone()[0]


def premium_claim_count(ctx: Context, user_id: str) -> int:
    """Premium-track claims in the current season only: the title is per-season."""
    season = season_id(ctx.now)
    return ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM quest_progress WHERE user_id=? AND claimed=1 AND quest_id LIKE ?",
        (user_id, f"{REWARD_PREFIX}{season}_%_premium"),
    ).fetchone()[0]
