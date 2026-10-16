from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from .rewards import grant

CLAIM_PREFIX = "rank_milestone_"
MILESTONES = (
    (3, "三甲争锋", 1600, {"forge_ore": 4, "bloodline_essence": 2}),
    (10, "十强入榜", 700, {"forge_ore": 2, "bloodline_essence": 1}),
    (20, "榜中有名", 220, {"forge_ore": 1}),
)


def claim_id(rank: int) -> str:
    return f"{CLAIM_PREFIX}{rank}"


def leaderboard_rows(ctx: Context) -> tuple[dict, ...]:
    """Return the stable public board, choosing one valid active pet per player."""
    rows = ctx.repo.conn.execute(
        "SELECT p.*, identity.id + 9999 AS uid FROM pets p "
        "JOIN players owner USING(user_id) JOIN player_identity identity USING(user_id) "
        "WHERE p.archived=0"
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        realm, layer, exp, pet_id = row["realm"], row["layer"], row["exp"], row["pet_id"]
        if (
            type(realm) is not int or not 0 <= realm < len(ctx.content.realms)
            or type(layer) is not int or layer not in ctx.content.layers
            or type(exp) is not int or exp < 0 or type(pet_id) is not int
        ):
            continue
        grouped.setdefault(row["user_id"], []).append(row)

    best = [max(entries, key=lambda row: (
        row["realm"], row["layer"], row["exp"], -row["pet_id"],
    )) for entries in grouped.values()]
    best.sort(key=lambda row: (-row["realm"], -row["layer"], -row["exp"], row["pet_id"]))
    return tuple({**dict(row), "rank": index} for index, row in enumerate(best, 1))


def current_rank(ctx: Context, user_id: str) -> int | None:
    return next((row["rank"] for row in leaderboard_rows(ctx) if row["user_id"] == user_id), None)


def _record(ctx: Context, user_id: str, rank: int):
    return ctx.repo.conn.execute(
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(rank)),
    ).fetchone()


def _reward(ctx: Context, milestone) -> Reward | None:
    _, _, stones, item_amounts = milestone
    for item_id in item_amounts:
        item = ctx.content.items.get(item_id)
        if item is None or item.kind not in {"consumable", "material"}:
            return None
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=stones, maximum=stones),
        items={
            item_id: Range(minimum=amount, maximum=amount)
            for item_id, amount in item_amounts.items()
        },
    )


def _reward_text(ctx: Context, milestone) -> str:
    reward = _reward(ctx, milestone)
    if reward is None:
        return "奖励内容待修复"
    _, _, stones, item_amounts = milestone
    parts = [f"灵石 {stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in item_amounts.items()
    )
    return "，".join(parts)


def _state(ctx: Context, user_id: str, milestone, rank: int | None) -> str:
    threshold = milestone[0]
    record = _record(ctx, user_id, threshold)
    if record is not None:
        progress, claimed = record["progress"], record["claimed"]
        if claimed:
            if type(progress) is int and 1 <= progress <= threshold:
                return f"已领取（第 {progress} 名）"
            return "领取记录异常"
        return "领取记录异常"
    if rank is None:
        return "尚未入榜"
    if rank <= threshold:
        return "可领取" if _reward(ctx, milestone) is not None else "奖励待修复"
    return f"还差至前 {threshold} 名 {rank - threshold} 名"


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠排行奖励 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines = [
            "万灵榜按每位玩家最高的一只在册灵宠排名，封存伙伴不计入。",
            *(f"前 {milestone[0]} 名 · {milestone[1]} · {_reward_text(ctx, milestone)}"
              for milestone in MILESTONES),
            "尚未结契，先完成领养；结契后可查看自己的名次并领奖。",
        ]
        return Reply("万灵榜奖励", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    rank = current_rank(ctx, player.user_id)
    heading = f"当前万灵榜名次：第 {rank} 名。" if rank is not None else "当前万灵榜名次：尚未入榜。"
    lines = [heading]
    links = []
    for milestone in MILESTONES:
        threshold, name = milestone[:2]
        state = _state(ctx, player.user_id, milestone, rank)
        lines.append(f"前 {threshold} 名 · {name} · {_reward_text(ctx, milestone)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取名次奖励", f"灵宠排行领奖 {threshold}",
            ))
    return Reply("万灵榜奖励", tuple(lines), ("灵宠排行", "灵宠目标"), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    milestone = next((entry for entry in MILESTONES if str(entry[0]) == value), None)
    if milestone is None:
        raise GameError("格式：灵宠排行领奖 <名次>，可选 3、10、20。")

    player = ctx.player()
    threshold, name = milestone[:2]
    record = _record(ctx, player.user_id, threshold)
    if record is not None:
        if record["claimed"]:
            raise GameError(f"前 {threshold} 名的万灵榜奖励已领取。")
        raise GameError(f"前 {threshold} 名的万灵榜领取记录异常，请联系管理员检查存档。")

    rank = current_rank(ctx, player.user_id)
    if rank is None:
        raise GameError("你尚未进入万灵榜，需有一只在册灵宠后才能领取。")
    if rank > threshold:
        raise GameError(f"当前第 {rank} 名，尚未进入前 {threshold} 名。")
    reward = _reward(ctx, milestone)
    if reward is None:
        raise GameError("万灵榜奖励物品定义缺失或类型错误；尚未领取。")

    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, claim_id(threshold), rank),
    )
    return Reply("万灵榜奖励", (
        f"前 {threshold} 名里程碑「{name}」已领取（第 {rank} 名）。", *result,
    ), ("灵宠排行奖励", "灵宠排行", "灵宠目标"))
