"""Dungeon contracts: a voluntary constraint on an existing dungeon, paid only when it held.

Base dungeons are a fixed bet — content decides both the difficulty and the payout — so a strong
player has nothing to risk. A contract adds a constraint the player chooses (go solo, win within N
rounds, keep everyone alive) and pays an extra bonus only if that constraint actually held. Nothing
about the dungeon itself changes: the run goes through the shared path, pays its normal reward, and the
contract bonus is granted on top.
"""

import hashlib
import json
from itertools import combinations

from ..application.context import Context
from ..domain.content import Dungeon, Range, Reward
from ..domain.contract_content import Contract
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_week
from . import adventure
from . import counters
from .rewards import grant

STAT_NAMES = {"stones": "灵石", "exp": "修为"}
COMPOSITE_KIND = "composite_dungeon_contract"
WEEKLY_SIGN_LIMIT = 3


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


def _contract_row(ctx: Context):
    row = ctx.repo.conn.execute(
        "SELECT snapshot FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')=? "
        "ORDER BY action_id DESC LIMIT 1",
        (ctx.user_id, COMPOSITE_KIND),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["snapshot"])
    except (TypeError, ValueError) as exc:
        raise GameError("复合契约记录损坏，暂不能继续。") from exc


def _signed_this_week(ctx: Context, week: int) -> int:
    return int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')=? "
        "AND json_extract(snapshot,'$.action')='sign' AND json_extract(snapshot,'$.week')=?",
        (ctx.user_id, COMPOSITE_KIND, week),
    ).fetchone()[0])


def _combined_bonus(ctx: Context, selected, dungeon) -> Reward:
    rewards = [bonus_of(ctx, contract, dungeon) for contract in selected]
    items: dict[str, int] = {}
    for reward in rewards:
        for item_id, amount in reward.items.items():
            items[item_id] = items.get(item_id, 0) + amount.minimum
    return Reward(
        exp=Range(minimum=sum(reward.exp.minimum for reward in rewards),
                  maximum=sum(reward.exp.maximum for reward in rewards)),
        stones=Range(minimum=sum(reward.stones.minimum for reward in rewards),
                     maximum=sum(reward.stones.maximum for reward in rewards)),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in items.items()},
    )


def _deposit(dungeon) -> int:
    """A visible 10% guarantee-stone stake, bounded for future content."""
    return max(10, min(100, dungeon.reward.stones.minimum // 10))


def _record(ctx: Context, state: dict, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, state, reply)
    return reply


def _latest_time(ctx: Context, state: dict | None) -> None:
    if state and ctx.now < int(state.get("last_at", state.get("signed_at", ctx.now))):
        raise GameError("系统时间早于最近契约操作，校准后再继续。")


def _resolve_combo(ctx: Context, parts: list[str]):
    if len(parts) != 3:
        raise GameError("格式：灵宠契约 组合 预览|签约 <条件一> <条件二> <秘境>。")
    first, second = named(rule(ctx), parts[0]), named(rule(ctx), parts[1])
    if first.id == second.id:
        raise GameError("复合契约需要选择两种不同条件。")
    dungeon = named(ctx.content.dungeons, parts[2])
    if dungeon.team:
        raise GameError("复合契约只适用于单人秘境。")
    return tuple(sorted((first, second), key=lambda entry: entry.id)), dungeon


def _validate_roster(ctx: Context, selected, dungeon, expected_ids: list[int] | None = None):
    pets = ctx.repo.active_pets(ctx.user_id)
    if not pets:
        raise ctx.missing_pet()
    if len(pets) > 3 or len({pet.species_id for pet in pets}) != len(pets):
        raise GameError("出战阵容最多三只且不能包含重复种族。")
    for pet in pets:
        if pet.user_id != ctx.user_id:
            raise GameError("签约只能使用属于你的伙伴。")
        if pet.archived:
            raise ctx.archived_active_pet(pet, ctx.user_id)
        ctx.require_idle_pet(pet)
    pet_ids = [pet.pet_id for pet in pets]
    if expected_ids is not None and pet_ids != expected_ids:
        raise GameError("当前出战伙伴与签约名单不同；恢复原阵容后再挑战，契约仍会保留。")
    if any(contract.kind == "solo" for contract in selected) and len(pets) != 1:
        raise GameError(f"独行要求只带一位伙伴，当前出战 {len(pets)} 只。")
    minimum = next(i for i, realm in enumerate(ctx.content.realms) if realm.id == dungeon.min_realm)
    for pet in pets:
        if pet.realm < minimum:
            raise GameError(f"{pet.name}境界不足，{dungeon.name}需要{ctx.content.realms[minimum].name}。")
    return pets


def _reward_text(ctx: Context, reward: dict) -> str:
    items = [f"修为 {reward['exp']}", f"灵石 {reward['stones']}"]
    items.extend(f"{ctx.content.items[key].name if key in ctx.content.items else key} ×{amount}"
                 for key, amount in reward["items"].items() if amount)
    return "、".join(items)


def _resource_snapshot(ctx: Context) -> dict:
    return {
        "stones": ctx.player().stones,
        "exp": sum(pet.exp for pet in ctx.repo.active_pets(ctx.user_id)),
        "items": {row["item_id"]: row["quantity"] for row in ctx.repo.conn.execute(
            "SELECT item_id,quantity FROM inventory WHERE user_id=?", (ctx.user_id,),
        )},
    }


def _resource_delta(before: dict, after: dict) -> dict:
    return {
        "stones": after["stones"] - before["stones"],
        "exp": after["exp"] - before["exp"],
        "items": {key: after["items"].get(key, 0) - before["items"].get(key, 0)
                  for key in sorted(before["items"].keys() | after["items"].keys())
                  if after["items"].get(key, 0) != before["items"].get(key, 0)},
    }


def _project_energy(ctx: Context, pet) -> int:
    restored = max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval
    return min(100, pet.energy + restored)


def _composite_catalog(ctx: Context, argument: str = "") -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return ctx.adoption_reply()
    entries = [dungeon for dungeon in ctx.content.dungeons.values() if not dungeon.team]
    pages = paginate(entries, argument, "复合秘境契约", "灵宠契约 组合", 4)
    state = _contract_row(ctx)
    used = _signed_this_week(ctx, beijing_week(ctx.now)[0])
    lines = [f"复合契约 · 第 {pages.number}/{pages.total} 页 · 本周签约 {used}/{WEEKLY_SIGN_LIMIT} 次。",
             "两项条件同时达成并获胜才返押金并领追加奖；未达成或放弃没收押金。"]
    links = []
    if state and state.get("status") == "active":
        lines.append(f"待履约契约 {state['run_id']} · {state['dungeon']['name']}。")
        links.append(InlineCommand(len(lines) - 1, "继续查看", "灵宠契约"))
    for dungeon in pages.entries:
        minimum = next(realm.name for realm in ctx.content.realms if realm.id == dungeon.min_realm)
        lines.append(f"{dungeon.name} · {minimum}起 · 每只精力 {dungeon.energy} · 押金灵石 {_deposit(dungeon)}。")
        for first, second in combinations(contracts(ctx), 2):
            lines.append(f"   {first.name} + {second.name}")
            try:
                _validate_roster(ctx, (first, second), dungeon)
            except GameError as exc:
                lines[-1] += f" · {exc}"
            else:
                links.append(InlineCommand(
                    len(lines) - 1, "预览", f"灵宠契约 组合 预览 {first.name} {second.name} {dungeon.name}",
                ))
    return Reply("复合秘境契约", tuple(lines),
                 (*pages.navigation, "灵宠契约 组合 记录", "灵宠目标")[:4], tuple(links))


def _preview(ctx: Context, parts: list[str]) -> Reply:
    selected, dungeon = _resolve_combo(ctx, parts)
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("复合秘境契约", ("尚未结契，先完成领养。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    pets = _validate_roster(ctx, selected, dungeon)
    week = beijing_week(ctx.now)[0]
    latest = _contract_row(ctx)
    _latest_time(ctx, latest)
    signed = _signed_this_week(ctx, week)
    deposit = _deposit(dungeon)
    bonus = _combined_bonus(ctx, selected, dungeon)
    lines = [
        f"{selected[0].name} + {selected[1].name} · {dungeon.name}",
        "约束：" + "；".join(condition_text(ctx, contract) for contract in selected),
        f"出战名单：{'、'.join(f'{pet.name}（{pet.pet_id}）' for pet in pets)}。签约后名单固定；装备与技能仍可调整。",
        f"挑战精力：每只需 {dungeon.energy}；当前可用 "
        + "、".join(f"{pet.name} {_project_energy(ctx, pet)}" for pet in pets)
        + "（只读推算，不写回恢复）· 秘境基础奖励照常结算。",
        f"签约押金：灵石 {deposit}；两项均达成并获胜返还押金。",
        "双条件追加奖：" + "、".join(bonus_text(ctx, contract) for contract in selected),
        f"精确追加奖励：修为 {bonus.exp.minimum}、灵石 {bonus.stones.minimum}"
        + ("、" + "、".join(f"{ctx.content.items[key].name} ×{value.minimum}"
                             for key, value in bonus.items.items()) if bonus.items else ""),
        f"本周已签 {signed}/{WEEKLY_SIGN_LIMIT} 次（北京时间周一重置）。",
    ]
    player = ctx.repo.player(ctx.user_id)
    can_sign = signed < WEEKLY_SIGN_LIMIT and not (latest and latest.get("status") == "active")
    can_sign = can_sign and player.stones >= deposit
    if can_sign:
        lines.append(f"确认签约：灵宠契约 组合 签约 {selected[0].id} {selected[1].id} {dungeon.id}。")
        links = (InlineCommand(len(lines) - 1, "支付押金签约",
                               f"灵宠契约 组合 签约 {selected[0].id} {selected[1].id} {dungeon.id}"),)
    else:
        links = ()
        if signed >= WEEKLY_SIGN_LIMIT:
            lines.append("本周签约次数已用完。")
        elif latest and latest.get("status") == "active":
            lines.append("已有待履约契约，请先继续或放弃。")
        else:
            lines.append(f"灵石不足：签约需要 {deposit}。")
    return Reply("复合秘境契约预览", tuple(lines), ("灵宠契约", "灵宠契约 组合", "灵宠目标"), links)


def _sign(ctx: Context, parts: list[str]) -> Reply:
    selected, dungeon = _resolve_combo(ctx, parts)
    player = ctx.player()
    latest = _contract_row(ctx)
    _latest_time(ctx, latest)
    if latest and latest.get("status") == "active":
        raise GameError("已有复合契约待履约，请先继续或放弃。")
    week = beijing_week(ctx.now)[0]
    count = _signed_this_week(ctx, week)
    if count >= WEEKLY_SIGN_LIMIT:
        raise GameError(f"本周复合契约签约次数已达 {WEEKLY_SIGN_LIMIT} 次，下周再来。")
    pets = _validate_roster(ctx, selected, dungeon)
    deposit = _deposit(dungeon)
    if player.stones < deposit:
        raise GameError(f"灵石不足：签约押金需要 {deposit}，当前 {player.stones}。")
    bonus = _combined_bonus(ctx, selected, dungeon)
    player.stones -= deposit
    state = {
        "kind": COMPOSITE_KIND, "action": "sign", "status": "active",
        "run_id": hashlib.sha256(ctx.operation_id.encode()).hexdigest()[:16],
        "signed_at": ctx.now, "last_at": ctx.now, "week": week,
        "conditions": [item.model_dump(mode="json") for item in selected],
        "dungeon": dungeon.model_dump(mode="json"),
        "bonus_reward": bonus.model_dump(mode="json"),
        "deposit": deposit, "pet_ids": [pet.pet_id for pet in pets],
    }
    reply = Reply("复合契约已签", (
        f"契约局号 {state['run_id']} · {selected[0].name}+{selected[1].name} · {dungeon.name}。",
        f"押金灵石 {deposit} 已收；两项均达成且获胜后返还并发追加奖，未达成或败退将没收。",
        f"原出战伙伴固定为：{'、'.join(f'{pet.name}（{pet.pet_id}）' for pet in pets)}；可以继续调整他们的装备与技能。",
        f"本周签约 {count + 1}/{WEEKLY_SIGN_LIMIT} 次。",
    ), ("灵宠契约", "灵宠整备", "灵宠目标"),
       (InlineCommand(1, "按签约阵容出战", f"灵宠契约 组合 出战 {state['run_id']}"),))
    return _record(ctx, state, reply)


def _active_contract(ctx: Context, run_id: str) -> dict:
    state = _contract_row(ctx)
    if state is None or state.get("status") != "active":
        raise GameError("当前没有待履约的复合契约，请查看 灵宠契约。")
    if state.get("run_id") != run_id:
        raise GameError("该契约局号已过期，请重新打开 灵宠契约。")
    _latest_time(ctx, state)
    return state


def _challenge(ctx: Context, run_id: str) -> Reply:
    if not run_id:
        raise GameError("格式：灵宠契约 组合 出战 <契约局号>。")
    state = _active_contract(ctx, run_id)
    conditions = [Contract.model_validate(item) for item in state["conditions"]]
    dungeon = Dungeon.model_validate(state["dungeon"])
    if (dungeon.min_realm not in {realm.id for realm in ctx.content.realms}
            or any(key not in ctx.content.enemies for key in dungeon.enemies)
            or any(key not in ctx.content.items
                   for key in dungeon.reward.items.keys() | state["bonus_reward"]["items"].keys())):
        raise GameError("签约内容暂不可用，可以保留契约或放弃本局。")
    _validate_roster(ctx, conditions, dungeon, expected_ids=state["pet_ids"])
    before = _resource_snapshot(ctx)
    reply, battle, allies = adventure.run_dungeon(ctx, dungeon, [ctx.user_id], return_state=True)
    after_base = _resource_snapshot(ctx)
    base = _resource_delta(before, after_base)
    held = [satisfied(ctx, condition, battle, allies) for condition in conditions]
    success = battle.winner == 0 and all(held)
    player = ctx.player()
    lines = list(reply.lines)
    for condition, passed in zip(conditions, held):
        lines.append(f"条件 {condition.name}：{'达成' if passed else '未达成'}（{condition_text(ctx, condition)}）。")
    energy_cost = {str(pet_id): dungeon.energy for pet_id in state["pet_ids"]}
    cooldown_seconds = ctx.config.spirit_pet_pve_cooldown
    lines.append(
        f"契约账单：伙伴精力各 -{dungeon.energy}；共享 PVE 调息 {cooldown_seconds} 秒。"
    )
    lines.append("基础所得：" + _reward_text(ctx, base))
    bonus = {"stones": 0, "exp": 0, "items": {}}
    if success:
        lines.append("复合契约追加奖：" + "，".join(grant(ctx, Reward.model_validate(state["bonus_reward"]))))
        bonus = _resource_delta(after_base, _resource_snapshot(ctx))
        player.stones += int(state["deposit"])
        lines.append(f"双条件达成：押金灵石 {state['deposit']} 已返还。")
        counters.bump(ctx, "contracts_met")
    else:
        lines.append(f"契约未完全履行，押金灵石 {state['deposit']} 没收；秘境基础结算按战斗结果处理。")
    state.update({"action": "challenge", "status": "settled", "last_at": ctx.now,
                  "outcome": "fulfilled" if success else "forfeited",
                  "condition_results": held,
                  "settlement": {"winner": battle.winner, "rounds": battle.rounds,
                                 "base": base, "bonus": bonus,
                                 "energy_cost": energy_cost,
                                 "pve_cooldown_seconds": cooldown_seconds,
                                 "deposit_returned": state["deposit"] if success else 0}})
    result = Reply("复合契约履约" if success else "复合契约结算", tuple(lines),
                   ("灵宠契约", "灵宠契约 组合 记录", "灵宠战报", "灵宠目标"))
    return _record(ctx, state, result)


def _abandon(ctx: Context, run_id: str) -> Reply:
    if not run_id:
        raise GameError("格式：灵宠契约 组合 放弃 <契约局号>。")
    state = _active_contract(ctx, run_id)
    ctx.player()
    state.update({"action": "abandon", "status": "abandoned", "last_at": ctx.now,
                  "outcome": "forfeited", "condition_results": []})
    reply = Reply("复合契约已放弃", (
        f"契约 {run_id} 已放弃，押金灵石 {state['deposit']} 没收。",
        "已签约次数计入签约周；可以查看记录或重新签约。",
    ), ("灵宠契约", "灵宠契约 组合 记录", "灵宠目标"))
    return _record(ctx, state, reply)


def _history(ctx: Context) -> Reply:
    rows = ctx.repo.conn.execute(
        "SELECT snapshot FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')=? "
        "ORDER BY action_id DESC LIMIT 100",
        (ctx.user_id, COMPOSITE_KIND),
    ).fetchall()
    unique = {}
    for row in rows:
        state = json.loads(row["snapshot"])
        unique.setdefault(state["run_id"], state)
    if not unique:
        return Reply("复合契约记录", ("尚无签约记录。",), ("灵宠契约", "灵宠目标"))
    lines = ["最近复合契约（新的在前）："]
    for state in list(unique.values())[:8]:
        names = "+".join(item["name"] for item in state["conditions"])
        outcome = {"active": "待履约", "settled": "已结算", "abandoned": "已放弃"}.get(
            state["status"], state["status"],
        )
        lines.append(f"{state['run_id']} · {names} · {state['dungeon']['name']} · {outcome} · 押金 {state['deposit']}")
        if state["status"] == "active":
            lines.append("   待履约：回到契约页继续挑战或放弃。")
        else:
            paid = state.get("settlement")
            if paid is not None:
                lines.extend((
                    f"   {'胜利' if paid['winner'] == 0 else '平局' if paid['winner'] == -1 else '败退'}"
                    f" · {paid['rounds']} 回合 · "
                    + "、".join(f"{condition['name']}{'达成' if held else '未达成'}"
                               for condition, held in zip(state["conditions"], state["condition_results"])),
                    "   基础所得：" + _reward_text(ctx, paid["base"]),
                    "   追加所得：" + _reward_text(ctx, paid["bonus"]),
                    "   实战成本：" + "、".join(
                        f"伙伴 {pet_id} 精力 -{amount}"
                        for pet_id, amount in paid.get("energy_cost", {}).items()
                    ) + f"；共享 PVE 调息 {paid.get('pve_cooldown_seconds', 0)} 秒。",
                    f"   押金返还 {paid['deposit_returned']}、没收 {state['deposit'] - paid['deposit_returned']}；"
                    f"本局净灵石 {paid['base']['stones'] + paid['bonus']['stones'] - state['deposit'] + paid['deposit_returned']:+d}。",
                ))
            else:
                lines.append(f"   已放弃：无战斗及奖励，押金 {state['deposit']} 没收。")
    return Reply("复合契约记录", tuple(lines), ("灵宠契约", "灵宠目标"))


def _composite(ctx: Context, parts: list[str]) -> Reply:
    if not parts:
        return _composite_catalog(ctx)
    if len(parts) == 1 and parts[0].isascii() and parts[0].isdecimal():
        return _composite_catalog(ctx, parts[0])
    action, rest = parts[0], parts[1:]
    if action == "预览":
        return _preview(ctx, rest)
    if action == "签约":
        return _sign(ctx, rest)
    if action in {"出战", "放弃"}:
        if len(rest) != 1:
            raise GameError(f"格式：灵宠契约 组合 {action} <契约局号>。")
        return _challenge(ctx, rest[0]) if action == "出战" else _abandon(ctx, rest[0])
    if action == "记录" and not rest:
        return _history(ctx)
    raise GameError("格式：灵宠契约 组合 预览|签约 <条件一> <条件二> <秘境>|出战|放弃 <契约局号>|记录。")


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
    latest = _contract_row(ctx)
    if latest and latest.get("status") == "active":
        lines.extend((
            f"复合契约待履约：局号 {latest['run_id']} · "
            f"{' + '.join(item['name'] for item in latest['conditions'])} · {latest['dungeon']['name']}。",
            f"签约周押金灵石 {latest['deposit']}；固定伙伴编号 {'、'.join(map(str, latest['pet_ids']))}。",
        ))
        links.append(InlineCommand(len(lines) - 2, "继续挑战",
                                   f"灵宠契约 组合 出战 {latest['run_id']}"))
        links.append(InlineCommand(len(lines) - 1, "放弃契约",
                                   f"灵宠契约 组合 放弃 {latest['run_id']}"))
        if [pet.pet_id for pet in roster] != latest["pet_ids"]:
            lines.append("当前阵容与签约名单不同，恢复原名单后才能挑战。")
            links.append(InlineCommand(
                len(lines) - 1, "恢复签约阵容",
                "灵宠出战 " + " ".join(map(str, latest["pet_ids"])),
            ))
        for pet_id in latest["pet_ids"]:
            pet = ctx.repo.pet(pet_id)
            lines.append(f"原伙伴 {pet.name}（{pet_id}） · 装备与技能可以继续调整。")
            links.append(InlineCommand(len(lines) - 1, "整备伙伴", f"灵宠整备 {pet_id}"))
            if pet.archived:
                links.append(InlineCommand(len(lines) - 1, "复原伙伴", f"灵宠复原 {pet_id}"))
            elif ctx.repo.active_expedition(pet_id) is not None:
                links.append(InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"))
    else:
        used = _signed_this_week(ctx, beijing_week(ctx.now)[0])
        lines.append(
            f"复合契约本周已签 {used}/{WEEKLY_SIGN_LIMIT} 次；独行、速战、无伤任选两项，"
            "双条件同时达成才返押金并领奖。"
        )
    for contract in contracts(ctx):
        lines.append(f"{contract.name} · {condition_text(ctx, contract)} · {bonus_text(ctx, contract)}")
        for dungeon in dungeons_for(ctx, contract):
            lines.append(f"   {dungeon.name}（{dungeon.energy} 精力）")
            links.append(InlineCommand(
                len(lines) - 1, "签契挑战", f"灵宠契约 {contract.name} {dungeon.name}",
            ))
    return Reply("灵宠契约", tuple(lines),
                 ("灵宠契约 组合", "灵宠契约 组合 记录", "灵宠秘境", "灵宠目标"), tuple(links))


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
        counters.bump(ctx, "contracts_met")
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
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "组合":
        return _composite(ctx, parts[1:])
    return run(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "契约：尚未结契"
    row = ctx.repo.conn.execute(
        "SELECT snapshot FROM duel_actions WHERE user_id=? AND json_extract(snapshot,'$.kind')=? "
        "ORDER BY action_id DESC LIMIT 1", (user_id, COMPOSITE_KIND),
    ).fetchone()
    if row:
        state = json.loads(row["snapshot"])
        if state.get("status") == "active":
            return f"复合契约：待履约 {state['run_id']}（{state['dungeon']['name']}）"
        return f"复合契约：最近{'达成' if state.get('outcome') == 'fulfilled' else '未履约'} · {state['dungeon']['name']}"
    return f"契约：单项 {len(contracts(ctx))} 种 · 复合契约每周最多签 {WEEKLY_SIGN_LIMIT} 次"
