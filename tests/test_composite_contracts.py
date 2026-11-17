import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import contracts
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import player, sql
from .test_commands import onebot_event
from .test_contracts import NOW, dungeon, ready


def _start(game, play, *, conditions=("速战", "无伤"), deposit_op="composite-sign", pets=2, now=NOW):
    ids = ready(game, play, pets=pets)
    selected = tuple(sorted((next(item for item in game[0].content.contracts.values()
                                  if item.id == name or item.name == name) for name in conditions),
                            key=lambda item: item.id))
    selected_ids = [item.id for item in selected]
    target = dungeon(game)
    preview = play(
        "contracts", f"组合 预览 {selected_ids[0]} {selected_ids[1]} {target.name}",
        now=now, op=f"{deposit_op}-preview",
    )
    assert "签约押金" in preview.text()
    reply = play(
        "contracts", f"组合 签约 {selected_ids[0]} {selected_ids[1]} {target.name}",
        now=now, op=deposit_op,
    )
    run_id = reply.lines[0].split("契约局号 ", 1)[1].split(" · ", 1)[0]
    return ids, selected, target, run_id, reply


def _records(game, user="u1"):
    return sql(
        game[1],
        "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
        "AND json_extract(snapshot,'$.kind')=? ORDER BY action_id",
        (user, contracts.COMPOSITE_KIND),
    )


def _database_dump(game):
    with game[1].connect() as conn:
        return tuple(conn.iterdump())


def test_preview_sign_freeze_exact_terms_and_replay_after_cache_expiry(game, play):
    ids = ready(game, play, pets=2)
    target = dungeon(game)
    before_stones = player(game[1])["stones"]
    preview = play("contracts", f"组合 预览 速战 无伤 {target.name}", op="composite-preview")
    assert "押金：灵石 10" in preview.text()
    assert "精确追加奖励：修为 24、灵石 28" in preview.text()
    assert "灵宠契约 组合 签约 speed unhurt" in preview.inline_commands[0].command
    before_pets = sql(game[1], "SELECT pet_id,energy,energy_updated,exp FROM pets WHERE user_id='u1' ORDER BY pet_id")
    before_items = sql(game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1' ORDER BY item_id")
    before_cooldown = player(game[1])["last_pve"]

    signed = play("contracts", f"组合 签约 speed unhurt {target.name}", op="composite-sign")
    assert player(game[1])["stones"] == before_stones - 10
    assert sql(game[1], "SELECT pet_id,energy,energy_updated,exp FROM pets WHERE user_id='u1' ORDER BY pet_id") == before_pets
    assert sql(game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1' ORDER BY item_id") == before_items
    assert player(game[1])["last_pve"] == before_cooldown
    state = json.loads(_records(game)[0]["snapshot"])
    assert state["status"] == "active"
    assert state["pet_ids"] == ids
    assert state["week"] == beijing_week(NOW)[0]
    assert state["dungeon"]["id"] == target.id
    assert state["bonus_reward"]["stones"] == {"minimum": 28, "maximum": 28}
    assert state["bonus_reward"]["exp"] == {"minimum": 24, "maximum": 24}
    sql(game[1], "DELETE FROM operations")
    assert play("contracts", f"组合 签约 speed unhurt {target.name}", op="composite-sign") == signed
    assert player(game[1])["stones"] == before_stones - 10


def test_contract_catalog_preview_and_history_are_read_only(game, play):
    ids = ready(game, play, pets=2)
    sql(game[1], "UPDATE pets SET energy=10,energy_updated=? WHERE pet_id=?", (NOW - 300, ids[0]))
    before = _database_dump(game)
    catalog = play("contracts", "组合", op="readonly-composite-catalog", now=NOW + 600)
    preview = play("contracts", "组合 预览 速战 无伤 青岚林",
                   op="readonly-composite-preview", now=NOW + 600)
    assert "当前可用 青鸾 13" in preview.text()
    assert _database_dump(game) == before
    assert catalog.inline_commands

    ghost = play("contracts", "组合 预览 速战 无伤 青岚林", user="ghost",
                 op="readonly-ghost-preview", now=NOW + 600)
    assert "尚未结契" in ghost.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    assert _database_dump(game) == before


def test_real_dungeon_fulfills_both_conditions_returns_stake_and_pays_frozen_bonus(game, play):
    ids, _, target, run_id, _ = _start(game, play)
    after_sign = player(game[1])["stones"]
    before_energy = {row["pet_id"]: row["energy"] for row in sql(
        game[1], "SELECT pet_id,energy FROM pets WHERE user_id='u1'",
    )}
    before_exp = {row["pet_id"]: row["exp"] for row in sql(
        game[1], "SELECT pet_id,exp FROM pets WHERE user_id='u1'",
    )}
    before_items = {row["item_id"]: row["quantity"] for row in sql(
        game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1'",
    )}
    result = play("contracts", f"组合 出战 {run_id}", op="composite-fight", now=NOW + 1)
    assert "条件 速战：达成" in result.text()
    assert "条件 无伤：达成" in result.text()
    assert "押金灵石 10 已返还" in result.text()
    state = json.loads(_records(game)[-1]["snapshot"])
    assert state["status"] == "settled" and state["outcome"] == "fulfilled"
    assert state["condition_results"] == [True, True]
    assert state["settlement"]["energy_cost"] == {str(pet_id): target.energy for pet_id in state["pet_ids"]}
    assert state["settlement"]["pve_cooldown_seconds"] == game[0].config.spirit_pet_pve_cooldown
    paid = state["settlement"]
    assert player(game[1])["stones"] - after_sign == (
        paid["base"]["stones"] + paid["bonus"]["stones"] + paid["deposit_returned"]
    )
    after_energy = {row["pet_id"]: row["energy"] for row in sql(
        game[1], "SELECT pet_id,energy FROM pets WHERE user_id='u1'",
    )}
    assert {pet_id: after_energy[pet_id] for pet_id in ids} == {
        pet_id: before_energy[pet_id] - target.energy for pet_id in ids
    }
    assert player(game[1])["last_pve"] == NOW + 1
    after_exp = {row["pet_id"]: row["exp"] for row in sql(
        game[1], "SELECT pet_id,exp FROM pets WHERE user_id='u1'",
    )}
    assert sum(after_exp.values()) - sum(before_exp.values()) == paid["base"]["exp"] + paid["bonus"]["exp"]
    after_items = {row["item_id"]: row["quantity"] for row in sql(
        game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1'",
    )}
    for item_id in before_items.keys() | after_items.keys():
        assert after_items.get(item_id, 0) - before_items.get(item_id, 0) == (
            paid["base"]["items"].get(item_id, 0) + paid["bonus"]["items"].get(item_id, 0)
        )
    assert "复合契约：最近达成" in play("objectives").text()
    assert "已结算" in play("contracts", "组合 记录").text()
    before_history = _database_dump(game)
    history = play("contracts", "组合 记录", op="readonly-contract-history", now=NOW + 2)
    assert f"精力 -{target.energy}" in history.text()
    assert "共享 PVE 调息 600 秒" in history.text()
    net_stones = (paid["base"]["stones"] + paid["bonus"]["stones"]
                  - state["deposit"] + paid["deposit_returned"])
    assert f"本局净灵石 {net_stones:+d}" in history.text()
    assert _database_dump(game) == before_history


def test_active_contract_page_offers_frozen_roster_recovery_and_loadout(game, play):
    ids, _, _, run_id, _ = _start(game, play)
    play("lineup", str(ids[-1]), op="wrong-roster-for-recovery")
    page = play("contracts", "", op="contract-recovery-page", now=NOW + 1)
    commands = {link.command for link in page.inline_commands}
    assert run_id in page.text()
    assert "灵宠出战 " + " ".join(map(str, ids)) in commands
    assert {f"灵宠整备 {pet_id}" for pet_id in ids}.issubset(commands)
    assert len(page.commands) <= 4
    assert all(0 <= link.line < len(page.lines) for link in page.inline_commands)
    _, payload = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [button for row in payload["keyboard"][0].data["keyboard"].content.rows
               for button in row.buttons]
    assert len(buttons) <= 4
    assert {button.action.data.removeprefix("/") for button in buttons}.isdisjoint(commands)


def test_partial_condition_success_pays_base_only_and_forfeits_stake(game, play, monkeypatch):
    ids, _, target, run_id, _ = _start(game, play, conditions=("独行", "速战"), pets=1)
    after_sign = player(game[1])["stones"]
    before_energy = sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (ids[0],))[0]["energy"]
    original = contracts.satisfied

    def partial(ctx, condition, battle, allies):
        return False if condition.kind == "speed" else original(ctx, condition, battle, allies)

    monkeypatch.setattr(contracts, "satisfied", partial)
    result = play("contracts", f"组合 出战 {run_id}", op="partial-fight", now=NOW + 1)
    assert "条件 独行：达成" in result.text()
    assert "条件 速战：未达成" in result.text()
    assert "押金灵石 10 没收" in result.text()
    state = json.loads(_records(game)[-1]["snapshot"])
    assert state["status"] == "settled" and state["outcome"] == "forfeited"
    assert state["condition_results"] == [True, False]
    assert player(game[1])["stones"] - after_sign == state["settlement"]["base"]["stones"]
    assert state["settlement"]["bonus"] == {"stones": 0, "exp": 0, "items": {}}
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (ids[0],))[0]["energy"] == (
        before_energy - target.energy
    )
    assert player(game[1])["last_pve"] == NOW + 1


def test_real_dungeon_loss_forfeits_deposit_without_bonus(game, play):
    ids, _, target, run_id, _ = _start(game, play)
    stones_after_sign = player(game[1])["stones"]
    energy_before = {row["pet_id"]: row["energy"] for row in sql(
        game[1], "SELECT pet_id,energy FROM pets WHERE user_id='u1'",
    )}
    enemy_id = target.enemies[0]
    enemy = game[0].content.enemies[enemy_id]
    strong_stats = enemy.stats.model_copy(update={
        "hp": 1_000_000, "attack": 1_000_000, "defense": 0, "speed": 1_000_000,
    })
    game[0].content.enemies[enemy_id] = enemy.model_copy(update={"stats": strong_stats})

    result = play("contracts", f"组合 出战 {run_id}", op="real-loss-fight", now=NOW + 1)
    state = json.loads(_records(game)[-1]["snapshot"])
    assert state["status"] == "settled" and state["outcome"] == "forfeited"
    assert state["settlement"]["winner"] == 1
    assert state["condition_results"] == [False, False]
    assert state["settlement"]["bonus"] == {"stones": 0, "exp": 0, "items": {}}
    assert player(game[1])["stones"] - stones_after_sign == state["settlement"]["base"]["stones"]
    energy_after = {row["pet_id"]: row["energy"] for row in sql(
        game[1], "SELECT pet_id,energy FROM pets WHERE user_id='u1'",
    )}
    assert all(energy_after[pet_id] == energy_before[pet_id] - target.energy for pet_id in ids)
    assert player(game[1])["last_pve"] == NOW + 1
    assert "没收" in result.text()


def test_solo_and_unhurt_combo_fulfills_a_second_real_dungeon(game, play):
    _, conditions, target, run_id, _ = _start(game, play, conditions=("独行", "无伤"), pets=1)
    reply = play("contracts", f"组合 出战 {run_id}", op="solo-unhurt-fight", now=NOW + 1)
    assert all(f"条件 {entry.name}：达成" in reply.text() for entry in conditions)
    assert "押金灵石 10 已返还" in reply.text()
    state = json.loads(_records(game)[-1]["snapshot"])
    assert state["outcome"] == "fulfilled"
    assert state["settlement"]["energy_cost"] == {str(state["pet_ids"][0]): target.energy}


def test_challenge_uses_signed_conditions_dungeon_and_bonus_after_content_changes(game, play):
    _, _, target, run_id, _ = _start(game, play)
    signed = json.loads(_records(game)[-1]["snapshot"])
    old_speed = game[0].content.contracts["speed"]
    game[0].content.contracts["speed"] = old_speed.model_copy(update={"rounds": 0})
    current = game[0].content.dungeons[target.id]
    changed_reward = current.reward.model_copy(update={
        "stones": current.reward.stones.model_copy(update={"minimum": 9000, "maximum": 9000}),
    })
    game[0].content.dungeons[target.id] = current.model_copy(update={"reward": changed_reward})

    reply = play("contracts", f"组合 出战 {run_id}", op="frozen-terms-fight", now=NOW + 1)
    state = json.loads(_records(game)[-1]["snapshot"])
    assert "条件 速战：达成" in reply.text()
    assert state["outcome"] == "fulfilled"
    assert state["settlement"]["base"]["stones"] == target.reward.stones.minimum
    assert state["bonus_reward"] == signed["bonus_reward"]


def test_loadout_and_skill_can_change_after_signing(game, play):
    ids, _, _, run_id, _ = _start(game, play)
    play("buy", "青岚翎", op="buy-gear-after-sign")
    play("equipment", f"青岚翎 伙伴 {ids[0]}", op="equip-gear-after-sign")
    play("buy", "风刃术诀", op="buy-skill-after-sign")
    play("learn", f"风刃术 伙伴 {ids[0]}", op="learn-skill-after-sign")
    assert sql(game[1], "SELECT slot,item_id FROM equipment WHERE pet_id=?", (ids[0],)) == [
        {"slot": "weapon", "item_id": "wind_feather"},
    ]
    assert sql(game[1], "SELECT skill_id,equipped FROM learned_skills WHERE pet_id=?", (ids[0],)) == [
        {"skill_id": "wind_slash", "equipped": 1},
    ]

    reply = play("contracts", f"组合 出战 {run_id}", op="loadout-changed-fight", now=NOW + 1)
    assert "条件 速战：达成" in reply.text()
    assert "条件 无伤：达成" in reply.text()
    assert json.loads(_records(game)[-1]["snapshot"])["outcome"] == "fulfilled"


@pytest.mark.parametrize("blocker", ["energy", "cooldown", "archived", "expedition"])
def test_challenge_preflight_failure_keeps_contract_and_all_resources(game, play, blocker):
    ids, _, target, run_id, _ = _start(game, play)
    if blocker == "energy":
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id IN (?,?)",
            (NOW, *ids))
        error = "精力不足"
    else:
        if blocker == "cooldown":
            sql(game[1], "UPDATE players SET last_pve=? WHERE user_id='u1'", (NOW,))
            error = "调息"
        elif blocker == "archived":
            sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
            error = "已经封存"
        else:
            sql(game[1],
                "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,"
                "started_at,finishes_at,state,reward_snapshot,slot) "
                "VALUES ('u1',?,'contract-test','契约测试','contract-blocker',?,?,'running','{}',0)",
                (ids[0], NOW, NOW + 600))
            error = "正在外出派遣"
    before = _database_dump(game)
    with pytest.raises(GameError, match=error):
        play("contracts", f"组合 出战 {run_id}", op=f"preflight-{blocker}", now=NOW + 1)
    assert _database_dump(game) == before
    assert json.loads(_records(game)[-1]["snapshot"])["status"] == "active"


def test_abandon_forfeits_stake_and_old_run_button_cannot_advance_new_contract(game, play):
    _, _, target, old_id, _ = _start(game, play)
    after_sign = player(game[1])["stones"]
    pets_before = sql(game[1], "SELECT pet_id,energy,energy_updated,exp FROM pets WHERE user_id='u1' ORDER BY pet_id")
    items_before = sql(game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1' ORDER BY item_id")
    cooldown_before = player(game[1])["last_pve"]
    abandoned = play("contracts", f"组合 放弃 {old_id}", op="composite-abandon", now=NOW + 1)
    assert "押金灵石 10 没收" in abandoned.text()
    assert player(game[1])["stones"] == after_sign
    assert sql(game[1], "SELECT pet_id,energy,energy_updated,exp FROM pets WHERE user_id='u1' ORDER BY pet_id") == pets_before
    assert sql(game[1], "SELECT item_id,quantity FROM inventory WHERE user_id='u1' ORDER BY item_id") == items_before
    assert player(game[1])["last_pve"] == cooldown_before
    abandoned_state = json.loads(_records(game)[-1]["snapshot"])
    assert abandoned_state["status"] == "abandoned" and "settlement" not in abandoned_state
    replacement = play(
        "contracts", f"组合 签约 speed unhurt {target.name}",
        op="composite-sign-2", now=NOW + 2,
    )
    new_id = replacement.lines[0].split("契约局号 ", 1)[1].split(" · ", 1)[0]
    before = _database_dump(game)
    with pytest.raises(GameError, match="局号已过期"):
        play("contracts", f"组合 出战 {old_id}", op="stale-composite", now=NOW + 3)
    assert _database_dump(game) == before
    assert new_id != old_id
    assert "待履约" in play("contracts").text()


def test_roster_mismatch_clock_rollback_and_team_contract_reject_before_write(game, play):
    ids, _, target, run_id, _ = _start(game, play)
    before = _database_dump(game)
    with pytest.raises(GameError, match="当前没有待履约"):
        play("contracts", f"组合 出战 {run_id}", user="u2", op="other-owner-run", now=NOW + 1)
    assert _database_dump(game) == before
    assert sql(game[1], "SELECT * FROM players WHERE user_id='u2'") == []

    second = ids[-1]
    play("lineup", str(second), op="change-roster")
    before = _database_dump(game)
    with pytest.raises(GameError, match="名单不同"):
        play("contracts", f"组合 出战 {run_id}", op="wrong-roster", now=NOW + 1)
    assert _database_dump(game) == before
    with pytest.raises(GameError, match="系统时间早于"):
        play("contracts", f"组合 放弃 {run_id}", op="clock-rollback", now=NOW - 1)
    assert _database_dump(game) == before
    team = dungeon(game, team=True)
    with pytest.raises(GameError, match="只适用于单人秘境"):
        play("contracts", f"组合 预览 速战 无伤 {team.name}", op="team-contract", now=NOW + 1)
    assert _database_dump(game) == before
    with pytest.raises(GameError, match="两种不同条件"):
        play("contracts", f"组合 预览 speed speed {target.name}", op="duplicate-condition", now=NOW + 1)
    assert _database_dump(game) == before


def test_insufficient_stake_rejects_signing_without_writes(game, play):
    ready(game, play, pets=2)
    target = dungeon(game)
    sql(game[1], "UPDATE players SET stones=0 WHERE user_id='u1'")
    before = _database_dump(game)
    with pytest.raises(GameError, match="押金需要"):
        play("contracts", f"组合 签约 speed unhurt {target.name}", op="no-stake")
    assert _database_dump(game) == before


def test_three_signups_are_counted_by_entry_week_then_reset_at_beijing_boundary(game, play):
    ready(game, play, pets=2)
    target = dungeon(game)
    week = beijing_week(NOW)[0]
    for index in range(3):
        run_id = play(
            "contracts", f"组合 签约 speed unhurt {target.name}",
            op=f"weekly-sign-{index}", now=week + 10 + index,
        ).lines[0].split("契约局号 ", 1)[1].split(" · ", 1)[0]
        play("contracts", f"组合 放弃 {run_id}", op=f"weekly-abandon-{index}", now=week + 11 + index)
    with pytest.raises(GameError, match="签约次数已达"):
        play("contracts", f"组合 签约 speed unhurt {target.name}", op="weekly-sign-4",
             now=week + 20)
    next_week = week + 7 * 86400
    next_contract = play(
        "contracts", f"组合 签约 speed unhurt {target.name}",
        op="next-week-sign", now=next_week,
    )
    assert "本周签约 1/3 次" in next_contract.text()


def test_concurrent_signups_allow_one_active_contract(game, play):
    ready(game, play, pets=2)
    target = dungeon(game)

    def sign(index):
        try:
            return game[0].execute(
                "u1", "contracts", f"组合 签约 speed unhurt {target.name}",
                f"parallel-sign-{index}", NOW,
            )
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(sign, range(2)))
    assert sum(isinstance(reply, GameError) for reply in replies) == 1
    assert sum(not isinstance(reply, GameError) for reply in replies) == 1
    assert player(game[1])["stones"] == 4990
    assert len(_records(game)) == 1


def test_concurrent_challenge_and_abandon_can_settle_only_once(game, play):
    _, _, target, run_id, _ = _start(game, play)

    def settle(action):
        try:
            return game[0].execute(
                "u1", "contracts", f"组合 {action} {run_id}", f"parallel-{action}", NOW + 1,
            )
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(settle, ("出战", "放弃")))
    assert sum(isinstance(reply, GameError) for reply in replies) == 1
    assert len(_records(game)) == 2
    final = json.loads(_records(game)[-1]["snapshot"])
    assert final["status"] in {"settled", "abandoned"}
    assert final["run_id"] == run_id
    if final["status"] == "settled":
        assert final["settlement"]["winner"] in {0, 1, -1}


@pytest.mark.parametrize("failure", [
    "deposit_write", "sign_journal", "base_reward", "battle_record", "bonus_reward", "final_journal",
])
def test_injected_failure_rolls_back_contract_resources_battle_and_receipt(game, play, monkeypatch, failure):
    if failure in {"sign_journal", "deposit_write"}:
        ready(game, play, pets=2)
        target = dungeon(game)
        before = _database_dump(game)
        op = f"fail-{failure}"
        if failure == "sign_journal":
            original = Repository.record_duel_action
            def fail(*args, **kwargs):
                result = original(*args, **kwargs)
                raise RuntimeError("injected contract journal failure")
            monkeypatch.setattr(Repository, "record_duel_action", fail)
        else:
            original = Repository.save
            def fail(repo):
                result = original(repo)
                raise RuntimeError("injected deposit persistence failure")
            monkeypatch.setattr(Repository, "save", fail)
        command = f"组合 签约 speed unhurt {target.name}"
    elif failure == "base_reward":
        _, _, _, run_id, _ = _start(game, play)
        before = _database_dump(game)
        op = "fail-base-reward"
        original = contracts.adventure.grant
        def fail(ctx, reward, *args, **kwargs):
            result = original(ctx, reward, *args, **kwargs)
            raise RuntimeError("injected base reward failure")
        monkeypatch.setattr(contracts.adventure, "grant", fail)
        command = f"组合 出战 {run_id}"
    elif failure == "battle_record":
        _, _, target, run_id, _ = _start(game, play)
        before = _database_dump(game)
        op = "fail-battle-record"
        original = Repository.record_battle
        def fail(*args, **kwargs):
            result = original(*args, **kwargs)
            raise RuntimeError("injected battle record failure")
        monkeypatch.setattr(Repository, "record_battle", fail)
        command = f"组合 出战 {run_id}"
    elif failure == "bonus_reward":
        _, _, target, run_id, _ = _start(game, play)
        before = _database_dump(game)
        op = "fail-bonus-reward"
        original = contracts.grant
        def fail(ctx, reward, *args, **kwargs):
            result = original(ctx, reward, *args, **kwargs)
            raise RuntimeError("injected bonus reward failure")
        monkeypatch.setattr(contracts, "grant", fail)
        command = f"组合 出战 {run_id}"
    else:
        _, _, target, run_id, _ = _start(game, play)
        before = _database_dump(game)
        op = "fail-final-journal"
        original = Repository.record_duel_action
        calls = 0
        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original(*args, **kwargs)
            if calls == 1:
                raise RuntimeError("injected final journal failure")
            return result
        monkeypatch.setattr(Repository, "record_duel_action", fail)
        command = f"组合 出战 {run_id}"
    with pytest.raises(RuntimeError, match="injected"):
        play("contracts", command, op=op, now=NOW + 1)
    assert _database_dump(game) == before
    monkeypatch.undo()
    if failure in {"sign_journal", "deposit_write"}:
        retry = play("contracts", command, op=op, now=NOW)
        assert "契约局号" in retry.text()
        assert player(game[1])["stones"] == 4990
    else:
        retry = play("contracts", command, op=op, now=NOW + 1)
        assert "已结算" in retry.text() or "履约" in retry.text()
        assert json.loads(_records(game)[-1]["snapshot"])["status"] == "settled"


def test_restart_restores_active_contract_and_old_operation_replays_receipt(game, play):
    _, _, target, run_id, _ = _start(game, play)
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    resume_time = NOW + 8 * 86400
    page = restarted.execute("u1", "contracts", "", "after-restart-page", resume_time)
    assert run_id in page.text()
    sql(game[1], "DELETE FROM operations")
    replay = restarted.execute("u1", "contracts", f"组合 签约 speed unhurt {target.name}",
                               "composite-sign", resume_time)
    assert replay.title == "复合契约已签"
    result = restarted.execute("u1", "contracts", f"组合 出战 {run_id}",
                               "restart-fight", resume_time + 1)
    sql(game[1], "DELETE FROM operations")
    assert restarted.execute("u1", "contracts", f"组合 出战 {run_id}",
                             "restart-fight", resume_time + 2) == result
    assert len(_records(game)) == 2


def test_help_objectives_qq_and_onebot_contract_commands(game, play, monkeypatch):
    ready(game, play, pets=2)
    help_page = play("help", "秘境与关卡")
    assert "灵宠契约 组合 预览" in help_page.text()
    assert handlers._parse("灵宠契约 组合 签约 speed unhurt 青岚林") == (
        "contracts", "组合 签约 speed unhurt 青岚林",
    )
    assert "复合契约每周最多签" in play("objectives").text()
    page = play("contracts")
    _, payload = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert payload["markdown"]

    service, store = game
    play("adopt", "青鸾", user="12345", op="adopt-onebot-user")
    sql(store, "UPDATE players SET stones=5000 WHERE user_id='12345'")
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )
    command = "灵宠契约 组合 签约 speed unhurt 青岚林"
    async def run():
        await handlers._run(bot, onebot_event("!" + command, 701), "!" + command)
    asyncio.run(run())
    assert "复合契约已签" in bot.send.call_args.args[1]
    assert sql(store, "SELECT stones FROM players WHERE user_id='12345'")[0]["stones"] == 4990
