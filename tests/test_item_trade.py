import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import item_trade
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, player_uid, sql
from .test_co_training_contract import buttons, links
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
DAY = 86400


def setup(game, play):
    for owner in ("u1", "u2"):
        play("adopt", "青鸾", user=owner)
        play("sign", user=owner)
    uid = player_uid(game[1], "u2")
    play("friends", f"添加 {uid}")
    play("friends", f"同意 {player_uid(game[1])}", user="u2")
    play("buy", "锻灵矿 2", user="u2")
    return uid


def snapshot(store):
    with closing(store.connect()) as conn:
        return tuple(conn.iterdump())


def trade(game):
    return json.loads(sql(game[1], "SELECT snapshot FROM duel_actions "
                          "WHERE json_extract(snapshot,'$.kind')='item_trade' "
                          "ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


def begin(game, play, uid, offer="灵粮 2", request="锻灵矿 2", now=NOW, op="trade-start"):
    reply = play("item_trade", f"发起 {uid} {offer} {request}", now=now, op=op)
    return trade(game)["trade_id"], reply


def test_real_material_sources_exchange_then_craft_and_feed(game, play):
    uid = setup(game, play)
    before = snapshot(game[1])
    preview = play("item_trade", f"预览 {uid} 灵粮 2 锻灵矿 2")
    assert snapshot(game[1]) == before
    assert preview.commands[0] == f"灵宠换物 发起 {uid} 灵粮 2 锻灵矿 2"
    stock1, stock2 = items(game[1]), items(game[1], "u2")
    stones = [player(game[1], owner)["stones"] for owner in ("u1", "u2")]
    number, _ = begin(game, play, uid)
    assert items(game[1])["spirit_food"] == stock1["spirit_food"] - 2
    assert items(game[1], "u2") == stock2
    result = play("item_trade", f"同意 {number}", user="u2", op="trade-accept")
    assert "已成交" in result.text()
    assert "你的付出：锻灵矿 ×2；你的所得：灵粮 ×2" in result.text()
    assert items(game[1])["forge_ore"] == stock1.get("forge_ore", 0) + 2
    assert items(game[1], "u2")["spirit_food"] == stock2["spirit_food"] + 2
    assert items(game[1], "u2").get("forge_ore", 0) == 0
    assert [player(game[1], owner)["stones"] for owner in ("u1", "u2")] == stones
    assert "青岚翎" in play("craft", "青岚翎 1").text()
    assert "灵粮" in play("feed", user="u2").text()
    assert "已收到 锻灵矿 ×2" in play("item_trade", f"详情 {number}").text()
    assert "得到 灵粮 ×2" in play("item_trade", "记录", user="u2").text()


@pytest.mark.parametrize("offer,wanted", [("灵石 80", "锻灵矿 2"), ("灵粮 2", "灵石 80")])
def test_stones_and_items_move_in_both_directions_without_extra_rewards(game, play, offer, wanted):
    uid = setup(game, play)
    before = [player(game[1], owner)["stones"] for owner in ("u1", "u2")]
    number, _ = begin(game, play, uid, offer, wanted)
    play("item_trade", f"同意 {number}", user="u2")
    delta = -80 if offer.startswith("灵石") else 80
    assert [player(game[1], owner)["stones"] for owner in ("u1", "u2")] == [before[0] + delta, before[1] - delta]
    assert not sql(game[1], "SELECT * FROM market_sales")
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'gift_log_%'")


@pytest.mark.parametrize("action,actor,offset,state", [
    ("取消", "u1", 1, "cancelled"), ("拒绝", "u2", 1, "rejected"),
    ("退款", "u1", DAY, "expired"), ("退款", "u2", DAY, "expired"),
    ("同意", "u2", DAY, "expired"), ("取消", "u1", DAY, "expired"),
])
@pytest.mark.parametrize("offer", ["灵粮 2", "灵石 80"])
def test_terminal_paths_return_exact_escrow_and_never_debit_recipient(game, play, action, actor, offset, state, offer):
    uid = setup(game, play)
    original = (items(game[1]), items(game[1], "u2"), player(game[1])["stones"], player(game[1], "u2")["stones"])
    number, _ = begin(game, play, uid, offer)
    before_read = snapshot(game[1])
    play("item_trade", user=actor, now=NOW + offset)
    play("item_trade", f"详情 {number}", user=actor, now=NOW + offset)
    assert snapshot(game[1]) == before_read
    reply = play("item_trade", f"{action} {number}", user=actor, now=NOW + offset, op="terminal")
    assert trade(game)["status"] == state
    assert (items(game[1]), items(game[1], "u2"), player(game[1])["stones"], player(game[1], "u2")["stones"]) == original
    assert "退款" in reply.text()
    before_repeat = snapshot(game[1])
    with pytest.raises(GameError, match="已经处理"):
        play("item_trade", f"{action} {number}", user=actor, now=NOW + offset + 1)
    assert snapshot(game[1]) == before_repeat
    assert "共 1 份" in play("item_trade", "记录", user="u2").text()


@pytest.mark.parametrize("argument", [
    "预览", "发起", "预览 10001 灵粮 0 锻灵矿 1", "发起 10001 灵粮 21 锻灵矿 1",
    "发起 10001 灵石 2001 灵粮 1", "发起 10001 灵粮 1 灵粮 2",
    "发起 10001 青岚翎 1 锻灵矿 1", "发起 10001 破境丹 1 锻灵矿 1",
    "发起 10001 风刃术诀 1 锻灵矿 1", "发起 10001 不存在 1 锻灵矿 1",
    "发起 10000 灵粮 1 锻灵矿 1", "发起 99999 灵粮 1 锻灵矿 1",
    "发起 10001 灵粮 2 锻灵矿 1 extra", "退款 0", "同意 1 2", "记录 0", "记录 2", "未知",
])
def test_invalid_actions_preserve_every_table(game, play, argument):
    setup(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("item_trade", argument)
    assert snapshot(game[1]) == before


def test_unregistered_preview_and_history_never_create_state(game, play):
    before = snapshot(game[1])
    assert "领养" in play("item_trade", user="ghost").text()
    assert "共 0 份" in play("item_trade", "记录", user="ghost").text()
    assert snapshot(game[1]) == before


def test_roles_foreign_ids_missing_stock_and_early_refunds_preserve_escrow(game, play):
    uid = setup(game, play)
    play("adopt", user="third")
    number, _ = begin(game, play, uid)
    for actor, action in (("u1", "同意"), ("u1", "拒绝"), ("u2", "取消"),
                          ("third", "详情"), ("third", "退款"), ("u1", "退款")):
        before = snapshot(game[1])
        with pytest.raises(GameError):
            play("item_trade", f"{action} {number}", user=actor, now=NOW + 1)
        assert snapshot(game[1]) == before
    play("craft", "青岚翎 1", user="u2")
    before = snapshot(game[1])
    assert not any("同意" in command for command in play("item_trade", user="u2").commands)
    with pytest.raises(GameError, match="不足"):
        play("item_trade", f"同意 {number}", user="u2")
    assert snapshot(game[1]) == before
    play("salvage", "青岚翎 1", user="u2")
    play("buy", "锻灵矿 1", user="u2")
    play("item_trade", f"同意 {number}", user="u2")
    assert trade(game)["status"] == "finished"


def test_pending_trade_blocks_both_participants_and_old_ids_cannot_touch_new_trade(game, play):
    uid = setup(game, play)
    number, _ = begin(game, play, uid)
    for actor, other in (("u1", uid), ("u2", player_uid(game[1]))):
        before = snapshot(game[1])
        with pytest.raises(GameError, match="待处理"):
            play("item_trade", f"发起 {other} 灵粮 1 灵石 10", user=actor)
        assert snapshot(game[1]) == before
    play("item_trade", f"取消 {number}")
    newer, _ = begin(game, play, uid, now=NOW + 1, op="new-trade")
    assert newer != number
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经处理"):
        play("item_trade", f"同意 {number}", user="u2", now=NOW + 2)
    assert snapshot(game[1]) == before
    assert f"邀约 {newer}" in play("item_trade", user="u2", now=NOW + 2).text()


def test_friendship_required_for_start_and_accept_but_never_for_refunds(game, play):
    uid = setup(game, play)
    number, _ = begin(game, play, uid)
    play("friends", f"解除 {uid}")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="解除好友"):
        play("item_trade", f"同意 {number}", user="u2")
    assert snapshot(game[1]) == before
    play("item_trade", f"拒绝 {number}", user="u2")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="好友"):
        play("item_trade", f"发起 {uid} 灵粮 1 锻灵矿 1")
    assert snapshot(game[1]) == before


def test_restart_cross_day_permanent_replays_and_clock_high_water(game, play):
    uid = setup(game, play)
    number, started = begin(game, play, uid)
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, content=game[0].content)
    assert restarted.execute("u1", "item_trade", f"发起 {uid} 灵粮 2 锻灵矿 2", "trade-start", NOW + 10) == started
    accepted = restarted.execute("u2", "item_trade", f"同意 {number}", "trade-accept", NOW + 100)
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    assert restarted.execute("u2", "item_trade", f"同意 {number}", "trade-accept", NOW + 8 * DAY) == accepted
    # Replaying writes only the ordinary short cache; resources and durable rows stay fixed.
    sql(game[1], "DELETE FROM operations")
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="different user"):
        restarted.execute("u1", "item_trade", f"同意 {number}", "trade-accept", NOW + 8 * DAY)
    with pytest.raises(GameError, match="系统时间"):
        play("item_trade", f"发起 {uid} 灵粮 1 锻灵矿 1", now=NOW + 99)
    new_id, _ = begin(game, play, uid, offer="灵粮 1", request="锻灵矿 1", now=NOW + 101, op="later")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="系统时间"):
        play("item_trade", f"取消 {new_id}", now=NOW + 100)
    assert snapshot(game[1]) == before


def test_pending_trade_survives_midnight_restart_and_content_name_changes(game, play):
    uid = setup(game, play)
    number, _ = begin(game, play, uid)
    original = game[0].content.items["spirit_food"]
    game[0].content.items["spirit_food"] = original.model_copy(update={"name": "新灵粮"})
    restarted = Game(game[1], game[0].config, content=game[0].content)
    before = items(game[1], "u2")["spirit_food"]
    result = restarted.execute("u2", "item_trade", f"同意 {number}", "after-midnight", NOW + DAY - 1)
    assert "灵粮 ×2" in result.text() and "新灵粮" not in result.text()
    assert items(game[1], "u2")["spirit_food"] == before + 2
    assert trade(game)["status"] == "finished"


def test_simultaneous_reverse_invitations_reserve_one_shared_slot(game, play):
    uid = setup(game, play)
    barrier = Barrier(2)

    def start(index):
        actor, target = ("u1", uid) if index == 0 else ("u2", player_uid(game[1]))
        barrier.wait(timeout=5)
        try:
            game[0].execute(actor, "item_trade", f"发起 {target} 灵粮 1 灵石 10", f"start-race-{index}", NOW)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(start, range(2))) == 1
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE json_extract(snapshot,'$.kind')='item_trade'")) == 1


@pytest.mark.parametrize("owner", ["u1", "u2"])
def test_recipient_stone_payment_and_owner_credit_roll_back_together(game, play, owner):
    uid = setup(game, play)
    number, _ = begin(game, play, uid, request="灵石 80")
    sql(game[1], "CREATE TRIGGER fail_money BEFORE UPDATE ON players WHEN NEW.user_id='" + owner + "' "
                 "BEGIN SELECT RAISE(ABORT, 'money failure'); END")
    before = snapshot(game[1])
    with pytest.raises(sqlite3.IntegrityError, match="money failure"):
        play("item_trade", f"同意 {number}", user="u2")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("field,value", [("offer", {"item": "spirit_food", "name": "灵粮", "amount": -1}),
                                          ("expires_at", NOW), ("version", 2), ("status", "bad"),
                                          ("offer", {"item": "missing", "name": "失物", "amount": 1})])
def test_damaged_snapshots_preserve_all_state(game, play, field, value):
    uid = setup(game, play)
    number, _ = begin(game, play, uid)
    run = trade(game)
    run[field] = value
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE operation_id='trade-start'", (json.dumps(run),))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="损坏|内容缺失"):
        play("item_trade", f"同意 {number}", user="u2")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("actions,offset", [(("同意", "同意"), 1), (("同意", "取消"), 1), (("同意", "退款"), DAY)])
def test_concurrent_settlement_has_one_terminal_transition(game, play, actions, offset):
    uid = setup(game, play)
    before_food = sum(items(game[1], owner).get("spirit_food", 0) for owner in ("u1", "u2"))
    before_ore = sum(items(game[1], owner).get("forge_ore", 0) for owner in ("u1", "u2"))
    number, _ = begin(game, play, uid)
    barrier = Barrier(2)

    def resolve(index):
        action = actions[index]
        actor = "u2" if action == "同意" else "u1"
        barrier.wait(timeout=5)
        try:
            game[0].execute(actor, "item_trade", f"{action} {number}", f"race-{index}", NOW + offset)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(resolve, range(2))) == 1
    assert sum(items(game[1], owner).get("spirit_food", 0) for owner in ("u1", "u2")) == before_food
    assert sum(items(game[1], owner).get("forge_ore", 0) for owner in ("u1", "u2")) == before_ore
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE json_extract(snapshot,'$.kind')='item_trade'")) == 2


@pytest.mark.parametrize("phase,offer,table,event,condition", [
    ("start", "灵粮 2", "inventory", "UPDATE", "NEW.user_id='u1'"),
    ("start", "灵石 80", "players", "UPDATE", "NEW.user_id='u1'"),
    ("start", "灵粮 2", "duel_actions", "INSERT", "1"),
    ("start", "灵粮 2", "operations", "INSERT", "1"),
    ("accept", "灵粮 2", "inventory", "UPDATE", "NEW.user_id='u2' AND NEW.item_id='forge_ore'"),
    ("accept", "灵粮 2", "inventory", "INSERT", "NEW.user_id='u2' AND NEW.item_id='spirit_food'"),
    ("accept", "灵粮 2", "inventory", "INSERT", "NEW.user_id='u1' AND NEW.item_id='forge_ore'"),
    ("accept", "灵石 80", "players", "UPDATE", "NEW.user_id='u2'"),
    ("accept", "灵粮 2", "players", "UPDATE", "NEW.user_id='u1'"),
    ("accept", "灵粮 2", "duel_actions", "INSERT", "1"),
    ("accept", "灵粮 2", "operations", "INSERT", "1"),
    ("refund", "灵粮 2", "inventory", "INSERT", "NEW.user_id='u1'"),
    ("refund", "灵石 80", "players", "UPDATE", "NEW.user_id='u1'"),
    ("refund", "灵粮 2", "duel_actions", "INSERT", "1"),
    ("refund", "灵粮 2", "operations", "INSERT", "1"),
])
def test_each_settlement_write_failure_rolls_back_every_table(game, play, phase, offer, table, event, condition):
    uid = setup(game, play)
    if phase != "start":
        number, _ = begin(game, play, uid, offer)
    sql(game[1], f"CREATE TRIGGER fail_trade BEFORE {event} ON {table} WHEN {condition} "
                 "BEGIN SELECT RAISE(ABORT, 'injected trade failure'); END")
    before = snapshot(game[1])
    with pytest.raises(sqlite3.IntegrityError, match="injected trade failure"):
        if phase == "start":
            begin(game, play, uid, offer)
        else:
            action, actor = ("同意", "u2") if phase == "accept" else ("退款", "u1")
            play("item_trade", f"{action} {number}", user=actor, now=NOW + DAY if phase == "refund" else NOW + 1)
    assert snapshot(game[1]) == before
    sql(game[1], "DROP TRIGGER fail_trade")
    if phase == "start":
        begin(game, play, uid, offer)
    else:
        play("item_trade", f"{action} {number}", user=actor, now=NOW + DAY if phase == "refund" else NOW + 1)


def test_read_only_views_do_not_call_repository_save(game, play, monkeypatch):
    uid = setup(game, play)
    number, _ = begin(game, play, uid)

    def fail_save(repo):
        raise AssertionError("read-only trade view called save")

    monkeypatch.setattr(Repository, "save", fail_save)
    before = snapshot(game[1])
    for argument in ("", f"详情 {number}", "记录"):
        play("item_trade", argument, user="u2", now=NOW + DAY)
    assert snapshot(game[1]) == before


def test_history_is_paginated_and_buttons_are_role_scoped_without_duplicate_links(game, play):
    uid = setup(game, play)
    for index in range(6):
        number, _ = begin(game, play, uid, now=NOW + index, op=f"start-{index}")
        play("item_trade", f"取消 {number}", now=NOW + index)
    first = play("item_trade", "记录")
    second = play("item_trade", "记录 2", user="u2")
    assert len(first.inline_commands) == 5 and len(second.inline_commands) == 1
    assert first.commands == ("灵宠换物 记录 2", "灵宠换物", "灵宠背包")
    assert second.commands[0] == "灵宠换物 记录 1"
    for link in first.inline_commands:
        assert link.command.endswith(first.lines[link.line].split(" · ")[0].split()[-1])
    number, _ = begin(game, play, uid, now=NOW + 7, op="button-start")
    for owner, expected in (("u1", [f"灵宠换物 取消 {number}"]), ("u2", [f"灵宠换物 同意 {number}", f"灵宠换物 拒绝 {number}"])):
        detail = play("item_trade", user=owner, now=NOW + 8)
        _, message = _qq_segments(detail, Config(spirit_pet_qq_mode="native"))
        commands = [button.action.data.removeprefix("/") for button in buttons(message)]
        assert commands[:len(expected)] == expected
        assert len(commands) <= 4 and len(commands) == len(set(commands))
        assert not {command for _, value in links(message) for command in value["command"]} & {"/" + command for command in commands}
    assert "灵宠换物" in play("bag").commands
    assert "灵宠换物" in play("friends").commands
    assert "灵宠换物" in play("help", "组队与派遣").text()
    assert "换物：邀约" in play("objectives").text()


def test_onebot_and_qq_handlers_execute_the_same_exchange(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def execute():
        for index, text in enumerate(("灵宠领养 青鸾", "灵宠签到", "灵宠好友 添加 10001")):
            if index == 2:
                await handlers.handle_command(qq, qq_event("helper", group=False, text="灵宠领养 玄狐", message_id="adopt"), "灵宠领养 玄狐")
            await handlers.handle_command(onebot, onebot_event(text, index + 1), text)
        for stamp, text in (("friend", "灵宠好友 同意 10000"), ("sign", "灵宠签到"), ("stock", "灵宠购买 锻灵矿 2")):
            await handlers.handle_command(qq, qq_event("helper", group=False, text=text, message_id=stamp), text)
        await handlers.handle_command(onebot, onebot_event("灵宠换物 预览 10001 灵粮 2 锻灵矿 2", 10), "灵宠换物 预览 10001 灵粮 2 锻灵矿 2")
        await handlers.handle_command(onebot, onebot_event("灵宠换物 发起 10001 灵粮 2 锻灵矿 2", 11), "灵宠换物 发起 10001 灵粮 2 锻灵矿 2")
        number = trade(game)["trade_id"]
        text = f"灵宠换物 同意 {number}"
        await handlers.handle_command(qq, qq_event("helper", group=False, text=text, message_id="accept"), text)

    asyncio.run(execute())
    assert trade(game)["status"] == "finished"
    assert items(game[1], "12345")["forge_ore"] == 2
    assert "已成交" in str(qq.send.call_args.args[1])
    assert onebot.send.await_count == 5 and qq.send.await_count == 5
