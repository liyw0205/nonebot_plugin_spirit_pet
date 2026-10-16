from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from .rewards import grant

PAGE_SIZE = 5
CLAIM_PREFIX = "codex_"


def claim_id(species_id: str) -> str:
    return CLAIM_PREFIX + species_id


def claimed(ctx: Context, user_id: str, species_id: str) -> bool:
    """A collection reward is claimed once and never expires."""
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(species_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def collected(ctx: Context, user_id: str) -> set[str]:
    """Species the player has ever owned; sealed pets still count, as in 灵宠收集."""
    rows = ctx.repo.conn.execute(
        "SELECT DISTINCT species_id FROM pets WHERE user_id=?", (user_id,),
    ).fetchall()
    return {row["species_id"] for row in rows}


def _reward_text(ctx: Context, reward) -> str:
    parts = [f"灵石 {reward.stones}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in reward.items.items()
    )
    return "，".join(parts)


def _grant_reward(reward) -> Reward:
    """The content reward is fixed, so the granted range is a single value."""
    return Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=reward.stones, maximum=reward.stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in reward.items.items()},
    )


def _state(ctx: Context, user_id: str, species_id: str, owned: set[str]) -> str:
    if claimed(ctx, user_id, species_id):
        return "已领取"
    return "可领取" if species_id in owned else "未收集"


def catalog(ctx: Context, arg: str) -> Reply:
    entries = tuple(ctx.content.species.values())
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠图鉴奖励共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠图鉴奖励", (
            "收得每一种灵宠后，都可以在这里领取该族的一份收集奖励。",
            f"共 {len(entries)} 族，奖励按稀有度递增；每族只能领取一次。",
            "尚未结契，先完成领养，再收集更多伙伴。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    owned = collected(ctx, player.user_id)
    selected = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for species in selected:
        reward = ctx.content.codex_rewards[species.id]
        state = _state(ctx, player.user_id, species.id, owned)
        lines.append(f"{species.name} · {_reward_text(ctx, reward)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取收集奖励", f"灵宠图鉴领奖 {species.name}",
            ))
    remaining = sum(
        1 for species in entries
        if species.id in owned and not claimed(ctx, player.user_id, species.id)
    )
    lines.append(f"共 {len(entries)} 族，已收集 {len(owned & set(ctx.content.species))} 族，"
                 f"尚有 {remaining} 族可领取。")
    commands = []
    if page > 1:
        commands.append(f"灵宠图鉴奖励 {page - 1}")
    if page < pages:
        commands.append(f"灵宠图鉴奖励 {page + 1}")
    commands.extend(("灵宠收集", "灵宠目标"))
    return Reply(f"灵宠图鉴奖励 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    species = named(ctx.content.species, arg)
    reward = ctx.content.codex_rewards[species.id]
    if claimed(ctx, player.user_id, species.id):
        raise GameError(f"{species.name}的收集奖励已领取，不能重复领取。")
    if species.id not in collected(ctx, player.user_id):
        raise GameError(f"尚未收得{species.name}，请先领养、召唤或孵化该族。")
    missing = set(reward.items) - set(ctx.content.items)
    if missing:
        raise GameError(f"收集奖励物品定义缺失：{', '.join(sorted(missing))}；尚未领取。")
    result = grant(ctx, _grant_reward(reward), player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, claim_id(species.id)),
    )
    return Reply("图鉴收集奖励", (
        f"{species.name}收集奖励已领取。", *result,
    ), ("灵宠图鉴奖励", "灵宠收集", "灵宠目标"))
