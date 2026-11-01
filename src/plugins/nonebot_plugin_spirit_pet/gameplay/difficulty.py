"""Dungeon difficulty tiers: raise the enemies' stats for a larger payout.

Contracts constrain *how* you fight a fixed dungeon; difficulty tiers change the fight itself. Each
tier scales every enemy's four stats by a fixed factor and scales the dungeon's own reward by a fixed
percentage, so the risk and the payout move together and neither is hand-tuned per dungeon.

The scaling happens in ``adventure.run_dungeon`` through optional parameters, so the default path —
and every existing caller — is unchanged.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import adventure
from . import counters

STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def tiers(ctx: Context):
    return sorted(ctx.content.difficulties.values(), key=lambda entry: entry.enemy_scale)


def tier(ctx: Context, arg: str):
    return named(ctx.content.difficulties, arg)


def scale_text(ctx: Context, entry) -> str:
    if entry.enemy_scale == 1.0:
        return "敌手数值不变"
    return f"敌手四维 ×{entry.enemy_scale:g}"


def reward_of(ctx: Context, dungeon, entry) -> Reward:
    factor = 1 + entry.reward_percent / 100
    base = dungeon.reward
    items = {
        item_id: Range(
            minimum=max(bounds.minimum, int(bounds.minimum * factor)),
            maximum=max(bounds.maximum, int(bounds.maximum * factor)),
        )
        for item_id, bounds in base.items.items()
    }
    return Reward(
        exp=Range(minimum=int(base.exp.minimum * factor), maximum=int(base.exp.maximum * factor)),
        stones=Range(minimum=int(base.stones.minimum * factor), maximum=int(base.stones.maximum * factor)),
        items=items,
    )


def reward_text(ctx: Context, dungeon, entry) -> str:
    reward = reward_of(ctx, dungeon, entry)
    parts = [f"修为 {reward.exp.minimum}-{reward.exp.maximum}", f"灵石 {reward.stones.minimum}-{reward.stones.maximum}"]
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}-{bounds.maximum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠试炼 [<秘境>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠试炼",
            (
                "尚未结契，先完成领养，才能选择试炼难度。",
                "提高难度会让敌手更强，同时提高该秘境的奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    dungeons = [entry for entry in ctx.content.dungeons.values() if not entry.team]
    lines = ["难度只改变该秘境的敌手数值与奖励，不改变精力、调息与掉落规则。"]
    links = []
    for dungeon in dungeons:
        lines.append(f"{dungeon.name}（{dungeon.energy} 精力）")
        for entry in tiers(ctx):
            lines.append(
                f"   {entry.name}：{scale_text(ctx, entry)}"
                f" · 奖励 +{entry.reward_percent}% · {reward_text(ctx, dungeon, entry)}"
            )
            if entry.reward_percent:
                links.append(InlineCommand(
                    len(lines) - 1, "挑战", f"灵宠试炼 {dungeon.name} {entry.name}",
                ))
    return Reply("灵宠试炼", tuple(lines), ("灵宠试炼", "灵宠秘境", "灵宠目标"), tuple(links))


def run(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠试炼 <秘境> <难度>。")
    dungeon = named(ctx.content.dungeons, parts[0])
    if dungeon.team:
        raise GameError("组队秘境请由队长发送 灵宠组队挑战。")
    entry = tier(ctx, parts[1])
    if entry.reward_percent == 0:
        raise GameError(f"{entry.name}就是秘境原本的难度，直接发送 灵宠挑战 {dungeon.name} 即可。")

    reward = reward_of(ctx, dungeon, entry)
    outcome = adventure.run_dungeon(
        ctx, dungeon, [ctx.user_id], enemy_scale=entry.enemy_scale, reward=reward, return_state=True,
    )
    reply, battle = outcome[0], outcome[1]
    if battle.winner == 0:
        counters.bump(ctx, "hard_clears")
    lines = list(reply.lines)
    lines.append(f"{entry.name}档：{scale_text(ctx, entry)}，奖励按 +{entry.reward_percent}% 结算。")
    return Reply(f"{reply.title} · {entry.name}", tuple(lines), reply.commands)


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else run(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "试炼：尚未结契"
    return f"试炼：可选 {len(tiers(ctx)) - 1} 档强化难度"


