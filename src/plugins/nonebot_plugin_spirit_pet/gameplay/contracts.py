"""Dungeon contracts: a voluntary constraint on an existing dungeon, paid only when it held.

Base dungeons are a fixed bet — content decides both the difficulty and the payout — so a strong
player has nothing to risk. A contract adds a constraint the player chooses (go solo, win within N
rounds, keep everyone alive) and pays an extra bonus only if that constraint actually held. Nothing
about the dungeon itself changes: the run goes through the shared path, pays its normal reward, and the
contract bonus is granted on top.
"""

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from . import adventure
from .rewards import grant

STAT_NAMES = {"stones": "灵石", "exp": "修为"}


def rule(ctx: Context):
    return ctx.content.contracts


def contracts(ctx: Context):
    return sorted(rule(ctx).values(), key=lambda entry: entry.id)


def dungeons_for(ctx: Context, contract) -> list:
    """Solo-capable, non-team dungeons a player's current lineup can enter."""
    return [dungeon for dungeon in ctx.content.dungeons.values() if not dungeon.team]


def condition_text(ctx: Context, contract) -> str:
    if contract.kind == "solo":
        return "只带一位伙伴通关"
    if contract.kind == "speed":
        return f"在 {contract.rounds} 回合内结束战斗"
    return "出战伙伴全部存活"


def bonus_text(ctx: Context, contract) -> str:
    parts = []
    if contract.bonus.stones_percent:
        parts.append(f"额外灵石 +{contract.bonus.stones_percent}%")
    if contract.bonus.exp_percent:
        parts.append(f"额外修为 +{contract.bonus.exp_percent}%")
    parts.extend(
        f"{ctx.content.items[item_id].name} ×{amount}"
        for item_id, amount in contract.bonus.items.items()
    )
    return " · ".join(parts)


def satisfied(ctx: Context, contract, battle, allies) -> bool:
    if battle.winner != 0:
        return False
    if contract.kind == "solo":
        return len(allies) == 1
    if contract.kind == "speed":
        return battle.rounds <= (contract.rounds or 0)
    return all(fighter.hp > 0 for fighter in allies)


def bonus_of(ctx: Context, contract, dungeon) -> Reward:
    base = dungeon.reward
    stones = base.stones.minimum * contract.bonus.stones_percent // 100
    exp = base.exp.minimum * contract.bonus.exp_percent // 100
    items = {
        item_id: Range(minimum=amount, maximum=amount)
        for item_id, amount in contract.bonus.items.items()
    }
    return Reward(exp=Range(minimum=exp, maximum=exp), stones=Range(minimum=stones, maximum=stones), items=items)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠契约 [<契约> <秘境>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠契约",
            (
                "尚未结契，先完成领养，才能签下契约。",
                "契约给秘境加一条自选约束，达成才有额外奖励。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    roster = ctx.repo.active_pets(ctx.user_id)
    lines = [f"契约只在秘境获胜且约束达成时额外发奖；基础奖励不变。当前出战 {len(roster)} 只。"]
    links = []
    for contract in contracts(ctx):
        lines.append(f"{contract.name} · {condition_text(ctx, contract)} · {bonus_text(ctx, contract)}")
        for dungeon in dungeons_for(ctx, contract):
            lines.append(f"   {dungeon.name}（{dungeon.energy} 精力）")
            links.append(InlineCommand(
                len(lines) - 1, "签契挑战", f"灵宠契约 {contract.name} {dungeon.name}",
            ))
    return Reply("灵宠契约", tuple(lines), ("灵宠契约", "灵宠秘境", "灵宠目标"), tuple(links))


def run(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠契约 <契约> <秘境>。")
    contract = named(rule(ctx), parts[0])
    dungeon = named(ctx.content.dungeons, parts[1])
    if dungeon.team:
        raise GameError("组队秘境不能签契约。")
    if contract.kind == "solo":
        roster = ctx.repo.active_pets(ctx.user_id)
        if len(roster) != 1:
            raise GameError(f"{contract.name}要求只带一位伙伴，当前出战 {len(roster)} 只。")

    outcome = adventure.run_dungeon(ctx, dungeon, [ctx.user_id], return_state=True)
    reply, battle, allies = outcome
    won = battle.winner == 0
    held = satisfied(ctx, contract, battle, allies)
    lines = list(reply.lines)
    if won and held:
        granted = grant(ctx, bonus_of(ctx, contract, dungeon))
        lines.append(f"{contract.name}达成：{'，'.join(granted)}")
        title = f"{reply.title} · {contract.name}"
    elif won:
        lines.append(f"{contract.name}未达成（{condition_text(ctx, contract)}），只结算基础奖励。")
        title = reply.title
    else:
        title = reply.title
    return Reply(title, tuple(lines), reply.commands)


def dispatch(ctx: Context, arg: str) -> Reply:
    return page(ctx, arg) if not arg.strip() else run(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "契约：尚未结契"
    return f"契约：可签 {len(contracts(ctx))} 种（独行/速战/无伤）"
