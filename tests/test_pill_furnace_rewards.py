"""Bounded contracts for rewards derived from real furnace result receipts."""

import asyncio
import itertools
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.pill_furnace_reward_content import PillFurnaceReward
from nonebot_plugin_spirit_pet.gameplay import pill_furnace_rewards
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql
from .test_alchemy import ready
from .test_commands import onebot_event, qq_event
from .test_pill_furnace import finish

NOW = 1_800_000_000
DAY = 86400


def successful_furnace(game, play, recipe="回元丹", operation="furnace-reward", prepared=False):
    if not prepared:
        ready(game, play)
    play("pill_furnace", f"开炉 {recipe}", op=operation + "-start")
    finish(play)


def state(store, *, receipts=False):
    tables = ("players", "pets", "inventory", "quest_progress", "duel_actions")
    if receipts:
        tables += ("operations",)
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}


def assert_paid(store, before_stones, before_items, entry, user="u1"):
    expected = dict(before_items)
    for item, amount in entry.items.items():
        expected[item] = expected.get(item, 0) + amount
    assert player(store, user)["stones"] == before_stones + entry.stones
    assert items(store, user) == expected


def restart(game):
    store = Store(game[1].path)
    store.initialize()
    return Game(store, game[0].config, game[0].rng, content=game[0].content)


def test_content_covers_every_real_furnace_product_and_thresholds(game):
    products = {entry.item_id for entry in game[0].content.alchemy.values()}
    rewards = game[0].content.pill_furnace_rewards
    assert {entry.product for entry in rewards.values()} == products
    assert all([entry.threshold for entry in rewards.values() if entry.product == product] == [1, 2]
               for product in products)
    with pytest.raises(ValueError):
        PillFurnaceReward.model_validate({
            "id": "empty", "product": "energy_pill", "threshold": 1,
            "name": "空奖励", "stones": 0, "items": {},
        })


def test_unregistered_page_is_read_only_and_parser_exposes_both_entries(game, play):
    before = state(game[1])
    page = play("pill_furnace_rewards", user="ghost")
    assert page.title == "丹炉成品赏" and "尚未结契" in page.text()
    assert page.inline_commands[-1].command == "灵宠领养 "
    assert _parse("灵宠丹炉赏") == ("pill_furnace_rewards", "")
    assert _parse("灵宠丹炉领奖 回元丹 1") == ("pill_furnace_reward_claim", "回元丹 1")
    assert state(game[1]) == before


def test_real_finished_furnace_snapshot_unlocks_one_product_milestone(game, play):
    successful_furnace(game, play)
    rows = sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='pill_furnace' "
               "AND json_extract(snapshot,'$.status')='finished'")
    assert rows and json.loads(rows[-1]["snapshot"])["recipe"]["item"] == "energy_pill"
    page = play("pill_furnace_rewards")
    assert "回元丹 · 成功 1 炉" in page.text()
    assert "回元初成" in page.text()
    assert "灵宠丹炉领奖 回元丹 1" in {link.command for link in page.inline_commands}


def test_claim_pays_once_records_ledger_and_survives_restart(game, play):
    successful_furnace(game, play, operation="claim-persist")
    before = player(game[1])["stones"]
    first = play("pill_furnace_reward_claim", "回元丹 1", op="claim-furnace-1")
    assert "回元初成" in first.text() and player(game[1])["stones"] == before + 80
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?",
               ("pill_furnace_reward_energy_pill_1",)) == [{"progress": 1, "claimed": 1}]
    assert play("pill_furnace_reward_claim", "回元丹 1", op="claim-furnace-1") == first
    with pytest.raises(GameError, match="已经领取"):
        play("pill_furnace_reward_claim", "回元丹 1", op="claim-furnace-1b")
    restarted = restart(game)
    assert "已领取" in restarted.execute("u1", "pill_furnace_rewards", "", "furnace-restart-page", NOW).text()
    sql(game[1], "DELETE FROM operations WHERE operation_id='claim-furnace-1'")
    before = state(game[1])
    with pytest.raises(GameError, match="已经领取"):
        restarted.execute("u1", "pill_furnace_reward_claim", "回元丹 1", "claim-furnace-1", NOW + 8 * DAY)
    assert state(game[1]) == before


def test_unmet_bad_and_corrupt_reward_paths_do_not_write(game, play):
    ready(game, play)
    before = state(game[1])
    for arg, message in (("回元丹 1", "成功 0"), ("回元丹 9", "没有此档"), ("不存在 1", "未找到"),
                         ("回元丹", "格式"), ("回元丹 １", "数量")):
        with pytest.raises(GameError, match=message):
            play("pill_furnace_reward_claim", arg, op=f"bad-furnace-{arg}")
        assert state(game[1]) == before
    entry = game[0].content.pill_furnace_rewards["energy_pill_1"]
    game[0].content.pill_furnace_rewards[entry.id] = entry.model_copy(update={"items": {"missing": 1}})
    successful_furnace(game, play, operation="corrupt-source", prepared=True)
    before = state(game[1])
    with pytest.raises(GameError, match="奖励定义暂不可用"):
        play("pill_furnace_reward_claim", "回元丹 1", op="corrupt-furnace")
    assert state(game[1]) == before
    page = play("pill_furnace_rewards")
    assert "奖励暂不可用" in page.text()
    assert "灵宠丹炉领奖 回元丹 1" not in {link.command for link in page.inline_commands}


@pytest.mark.parametrize("same_operation", [False, True])
def test_concurrent_claims_are_serialized(game, play, same_operation):
    successful_furnace(game, play, operation="concurrent-source")
    before_stones, before_items = player(game[1])["stones"], items(game[1])
    def attempt(index):
        try:
            return play("pill_furnace_reward_claim", "回元丹 1",
                        op=f"furnace-concurrent-{0 if same_operation else index}").text()
        except GameError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum("已领取" in result for result in results) == (2 if same_operation else 1)
    assert sql(game[1], "SELECT COUNT(*) AS count FROM quest_progress WHERE quest_id=?",
               ("pill_furnace_reward_energy_pill_1",)) == [{"count": 1}]
    assert_paid(game[1], before_stones, before_items, game[0].content.pill_furnace_rewards["energy_pill_1"])


@pytest.mark.parametrize("failure", ["grant", "marker", "save", "receipt"])
def test_grant_failure_rolls_back_reward_and_marker(game, play, monkeypatch, failure):
    successful_furnace(game, play, operation="failure-source")
    before = state(game[1], receipts=True)
    with monkeypatch.context() as patch:
        if failure == "grant":
            original = pill_furnace_rewards.grant
            def fail_after_grant(*args):
                original(*args)
                raise RuntimeError("reward failure")
            patch.setattr(pill_furnace_rewards, "grant", fail_after_grant)
        elif failure == "save":
            original_save = Repository.save
            def fail_after_save(repo):
                original_save(repo)
                raise RuntimeError("reward failure")
            patch.setattr(Repository, "save", fail_after_save)
        else:
            table = "quest_progress" if failure == "marker" else "operations"
            condition = ("NEW.quest_id='pill_furnace_reward_energy_pill_1'" if failure == "marker"
                         else "NEW.operation_id='furnace-failure'")
            sql(game[1], f"CREATE TRIGGER reject_reward BEFORE INSERT ON {table} WHEN {condition} "
                         "BEGIN SELECT RAISE(ABORT, 'reward failure'); END")
        with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="reward failure"):
            play("pill_furnace_reward_claim", "回元丹 1", op="furnace-failure")
    assert state(game[1], receipts=True) == before
    if failure in {"marker", "receipt"}:
        sql(game[1], "DROP TRIGGER reject_reward")
    play("pill_furnace_reward_claim", "回元丹 1", op="furnace-failure")
    assert_paid(game[1], before["players"][0]["stones"],
                {row["item_id"]: row["quantity"] for row in before["inventory"]},
                game[0].content.pill_furnace_rewards["energy_pill_1"])


def test_native_buttons_do_not_duplicate_result_links(game, play):
    successful_furnace(game, play, operation="native-source")
    page = play("pill_furnace_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}


@pytest.mark.parametrize("recipe_id", ["energy_draught", "spirit_elixir", "bond_pill", "breakthrough_elixir"])
def test_public_supplies_two_days_and_both_milestones_pay_exactly(game, play, recipe_id):
    play("adopt", "青鸾", now=NOW - 6 * DAY)
    for day in range(7):
        play("sign", now=NOW - (6 - day) * DAY)
    recipe = game[0].content.alchemy[recipe_id]
    for count, now in ((1, NOW), (2, NOW + DAY)):
        for item_id, amount in recipe.materials.items():
            play("buy", f"{game[0].content.items[item_id].name} {amount}", now=now)
        play("pill_furnace", f"开炉 {recipe.name}", now=now)
        if count == 2:
            recovered = restart(game)
            operations = itertools.count()
            def restored(action, arg="", **kwargs):
                return recovered.execute("u1", action, arg, f"restored-{next(operations)}", now)
            finish(restored, ("温养",) * 3)
        else:
            finish(play, now=now)
        assert f"{recipe.name} · 成功 {count} 炉" in play("pill_furnace_rewards", now=now).text()
        before_stones, before_items = player(game[1])["stones"], items(game[1])
        entry = game[0].content.pill_furnace_rewards[f"{recipe.item_id}_{count}"]
        result = play("pill_furnace_reward_claim", f"{recipe.name} {count}", now=now)
        assert entry.name in result.text()
        assert_paid(game[1], before_stones, before_items, entry)
        assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?",
                   (f"pill_furnace_reward_{recipe.item_id}_{count}",)) == [{"progress": count, "claimed": 1}]
    assert items(game[1])[recipe.item_id] == recipe.yield_ * 3
    assert "可领 0 档" in play("objectives", now=NOW + DAY).text()


def test_reward_food_and_seed_reach_existing_consumers(game, play):
    ready(game, play)
    play("pill_furnace", "开炉 回元丹")
    finish(play)
    play("pill_furnace_reward_claim", "回元丹 1")
    before = items(game[1])["spirit_food"]
    play("feed")
    assert items(game[1])["spirit_food"] == before - 1
    play("pill_furnace", "开炉 回元丹", now=NOW + DAY)
    finish(play, now=NOW + DAY)
    play("pill_furnace_reward_claim", "回元丹 2", now=NOW + DAY)
    before = items(game[1])["seed_blood_herb"]
    play("farm_open", "1", now=NOW + DAY)
    play("farm_plant", "1 灵血草种", now=NOW + DAY)
    assert items(game[1])["seed_blood_herb"] == before - 1


def test_only_own_successful_furnaces_count_and_duplicate_receipts_do_not(game, play):
    ready(game, play, stock=8)
    play("pill_furnace", "开炉 回元丹")
    assert "回元丹 · 成功 0 炉" in play("pill_furnace_rewards").text()
    finish(play, ("催灵", "催灵"))
    play("pill_furnace", "开炉 回元丹", now=NOW + DAY)
    play("pill_furnace", "弃炉", now=NOW + DAY)
    play("alchemy", "回元丹", now=NOW + DAY)
    assert "回元丹 · 成功 0 炉" in play("pill_furnace_rewards", now=NOW + DAY).text()
    play("pill_furnace", "开炉 回元丹", now=NOW + 2 * DAY)
    finish(play, now=NOW + 2 * DAY)
    receipt = sql(game[1], "SELECT * FROM duel_actions ORDER BY action_id DESC LIMIT 1")[0]
    # Simulate duplicate final receipts from an older writer, without creating a new furnace.
    sql(game[1], "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
        ("duplicate-final", "u1", NOW + 2 * DAY, receipt["snapshot"], receipt["reply"]))
    play("adopt", "青鸾", user="u2")
    sql(game[1], "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
        ("other-user-final", "u2", NOW, receipt["snapshot"], receipt["reply"]))
    assert "回元丹 · 成功 1 炉" in play("pill_furnace_rewards", now=NOW + 2 * DAY).text()
    with pytest.raises(GameError, match="尚未达到 2"):
        play("pill_furnace_reward_claim", "回元丹 2", now=NOW + 2 * DAY)


def test_registered_page_help_and_objectives_are_read_only_and_no_pet_is_needed_to_claim(game, play):
    successful_furnace(game, play)
    assert "灵宠丹炉领奖" in play("help", "血脉与道具").text()
    # The shared objective hub refreshes daily quests on its first visit.
    assert "丹炉成品赏：成功 1 炉 · 可领 1 档" in play("objectives").text()
    before = state(game[1])
    assert "丹炉成品赏：成功 1 炉 · 可领 1 档" in play("objectives").text()
    assert "灵宠丹炉赏" in play("pill_furnace").commands
    page = play("pill_furnace_rewards")
    assert "灵宠丹炉领奖 回元丹 1" in {link.command for link in page.inline_commands}
    assert state(game[1]) == before
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    play("pill_furnace_reward_claim", "回元丹 1")
    assert player(game[1])["active_pet_id"] is None


@pytest.mark.parametrize("argument", ["", "回元丹", "回元丹 1 extra", "回元丹 0", "回元丹 -1",
                                      "回元丹 1.0", "回元丹 １", "回元丹 ١", "回元丹 " + "9" * 5000])
def test_invalid_claim_arguments_do_not_write(game, play, argument):
    successful_furnace(game, play)
    before = state(game[1], receipts=True)
    with pytest.raises(GameError):
        play("pill_furnace_reward_claim", argument)
    assert state(game[1], receipts=True) == before


def test_incomplete_claim_record_is_not_reissued(game, play):
    successful_furnace(game, play)
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','pill_furnace_reward_energy_pill_1',1,0)")
    before = state(game[1])
    with pytest.raises(GameError, match="领取记录异常"):
        play("pill_furnace_reward_claim", "回元丹 1")
    page = play("pill_furnace_rewards")
    assert "领取记录异常" in page.text()
    assert not any(link.command == "灵宠丹炉领奖 回元丹 1" for link in page.inline_commands)
    assert state(game[1]) == before


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
def test_real_adapter_chain_reaches_furnace_reward_and_replays_once(game, monkeypatch, adapter):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="reward-bot", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    commands = ("灵宠丹炉赏", "灵宠领养 青鸾", "灵宠签到", "灵宠购买 灵血草种 1",
                "灵宠丹炉 开炉 回元丹", "灵宠丹炉 催灵", "灵宠丹炉 调和", "灵宠丹炉 催灵",
                "灵宠丹炉赏", "灵宠丹炉领奖 回元丹 1")
    def event(index, command):
        return (onebot_event(command, 2000 + index) if adapter == "OneBot V11" else
                qq_event(text=command, message_id=str(2000 + index)))
    async def run():
        for index, command in enumerate(commands):
            await handlers._run(bot, event(index, command), command)
        before_stones, before_items = player(game[1], "12345")["stones"], items(game[1], "12345")
        await handlers._run(bot, event(9, commands[9]), commands[9])
        assert player(game[1], "12345")["stones"] == before_stones
        assert items(game[1], "12345") == before_items
    asyncio.run(run())
    messages = []
    for call in bot.send.call_args_list:
        message = call.args[1]
        messages.append(message["markdown"][0].data["markdown"].content.replace("\\+", "+")
                        if adapter == "QQ" else str(message))
    assert "尚未结契" in messages[0]
    assert "回元初成" in messages[-1] and "灵石 +80" in messages[-1]
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE user_id='12345' "
               "AND quest_id='pill_furnace_reward_energy_pill_1'") == [{"progress": 1, "claimed": 1}]
    assert items(game[1], "12345")["energy_pill"] == 2


@pytest.mark.parametrize("mode", ["native", "text", "template"])
def test_qq_modes_prefix_and_reachable_reward_links(game, play, mode):
    successful_furnace(game, play)
    for page in (play("pill_furnace_rewards"), play("pill_furnace", "成品")):
        assert len([command for command in page.commands if command == "灵宠丹炉赏"]) + sum(
            link.command == "灵宠丹炉赏" for link in page.inline_commands) <= 1
        _, message = _qq_segments(page, Config(spirit_pet_qq_mode=mode,
                                             spirit_pet_command_prefix="/",
                                             spirit_pet_qq_template_id="reward-template"))
        for link in page.inline_commands:
            assert _parse(link.command) is not None
            assert link.command.rstrip() in page.text()
        if mode == "native":
            markdown = message["markdown"][0].data["markdown"].content
            commands = [parse_qs(urlparse(url).query)["command"][0]
                        for url in re.findall(r"\]\((mqqapi:[^)]+)\)", markdown)]
            for link in page.inline_commands:
                assert commands.count("/" + link.command) == 1
            buttons = [button.action.data.removeprefix("/")
                       for segment in message["keyboard"]
                       for row in segment.data["keyboard"].content.rows for button in row.buttons]
            assert len(buttons) == len(set(buttons)) <= 4
            assert not set(buttons) & {link.command for link in page.inline_commands}
        else:
            for link in page.inline_commands:
                assert "/" + link.command in str(message)


@pytest.mark.parametrize("change,error", [
    ({"product": "missing"}, "unknown product"),
    ({"items": {"missing": 1}}, "items"),
    ({"threshold": 2}, "sorted unique"),
    ({"threshold": 3}, "sorted unique"),
])
def test_catalog_rejects_invalid_furnace_reward_references(game, change, error):
    entries = game[0].content.pill_furnace_rewards
    entries["energy_pill_1"] = entries["energy_pill_1"].model_copy(update=change)
    with pytest.raises(ValueError, match=error):
        game[0].content.validate()


@pytest.mark.parametrize("missing", [("energy_pill_1",), ("energy_pill_1", "energy_pill_2")])
def test_catalog_requires_both_milestones_per_product(game, missing):
    for key in missing:
        game[0].content.pill_furnace_rewards.pop(key)
    with pytest.raises(ValueError, match="thresholds 1 and 2|every pill furnace product"):
        game[0].content.validate()


@pytest.mark.parametrize("change", [{"threshold": 0}, {"threshold": True}, {"threshold": "1"},
                                    {"threshold": 100}, {"stones": -1}, {"items": {"spirit_food": 0}},
                                    {"items": {"spirit_food": -1}}, {"created_at": NOW}])
def test_reward_model_rejects_invalid_fields(game, change):
    entry = game[0].content.pill_furnace_rewards["energy_pill_1"].model_dump()
    with pytest.raises(ValueError):
        PillFurnaceReward.model_validate({**entry, **change})
