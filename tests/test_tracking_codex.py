"""Discovery, payment and transport contracts for the complete tracking codex."""

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
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.tracking_reward_content import TrackingReward
from nonebot_plugin_spirit_pet.gameplay import tracking_codex
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql
from .test_commands import onebot_event, qq_event
from .test_tracking import TargetRandom, survey

NOW = 1_800_000_000
DAY = 86400


def snapshot(store, *, receipts=False):
    tables = ("players", "pets", "inventory", "quest_progress", "duel_actions")
    if receipts:
        tables += ("operations",)
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}


def found(play, map_id="bamboo", now=NOW):
    play("tracking", f"出发 {map_id}", now=now)
    survey(play, now=now)
    return play("tracking", "挖掘 1", now=now)


def prepared(play):
    play("adopt", "青鸾")
    return found(play)


def assert_paid(store, stones, inventory, entry):
    expected = dict(inventory)
    for item, amount in entry.items.items():
        expected[item] = expected.get(item, 0) + amount
    assert player(store)["stones"] == stones + entry.stones
    assert items(store) == expected


def reopened(game):
    store = Store(game[1].path)
    store.initialize()
    return Game(store, game[0].config, game[0].rng, content=game[0].content)


@pytest.mark.parametrize("map_id", ["bamboo", "ruins", "orchard"])
def test_every_site_from_real_commands_survives_days_restart_and_pays_all_tiers(game, map_id):
    current = game[0]
    counter = itertools.count()
    now = NOW
    def play(action, argument="", **kwargs):
        return current.execute("u1", action, argument, f"codex-chain-{next(counter)}", now)
    play("adopt", "青鸾")
    route = current.content.tracking_maps[map_id]
    for site in range(1, 17):
        now = NOW + (site - 1) * DAY
        current.rng = TargetRandom(site)
        play("tracking", f"出发 {route.name}")
        if site == 4:
            current = reopened((current, game[1]))
        survey(play)
        result = play("tracking", f"挖掘 {site}")
        assert "寻获藏物！" in result.text()
        page = play("tracking_codex", route.name)
        assert f"已寻获 {site}/16 处" in page.text()
        for number, name in enumerate(route.sites, 1):
            assert f"{number} 号 · {name} · " + ("已寻获" if number <= site else "未寻获") in page.lines
        if site in (1, 4, 16):
            entry = current.content.tracking_rewards[f"{map_id}_{site}"]
            assert f"灵宠寻踪领奖 {route.name} {site}" in {link.command for link in page.inline_commands}
            stones, inventory = player(game[1])["stones"], items(game[1])
            play("tracking_reward_claim", f"{route.name} {site}")
            assert_paid(game[1], stones, inventory, entry)
            assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id=?",
                       (f"tracking_reward_{map_id}_{site}",)) == [{"progress": site, "claimed": 1}]
    assert player(game[1])["stones"] == current.content.rules.starter_stones + 740
    before = snapshot(game[1])
    page = reopened((current, game[1])).execute("u1", "tracking_codex", route.name, "restart-full-codex", now)
    assert page.text().count("已领取") == 3 and not page.inline_commands
    assert snapshot(game[1]) == before


def test_read_only_unregistered_help_detail_and_real_entry_links(game, play):
    before = snapshot(game[1])
    for arg in ("", "bamboo", "残垣石庭", "露华果圃"):
        page = play("tracking_codex", arg)
        assert "尚未结契" in page.text()
        assert page.inline_commands[-1].command == "灵宠领养 "
    assert "灵宠寻踪图录" in play("help", "血脉与道具").text()
    with pytest.raises(GameError):
        play("tracking_reward_claim", "竹溪旧径 1")
    assert snapshot(game[1]) == before
    result = prepared(play)
    play("objectives")  # Prime the shared hub's daily quest refresh.
    before = snapshot(game[1])
    assert "寻踪图录：已寻获 1 处 · 可领 1 档" in play("objectives").text()
    assert "灵宠寻踪图录" in {link.command for link in play("tracking").inline_commands}
    assert "灵宠寻踪图录 竹溪旧径" in {link.command for link in result.inline_commands}
    assert "灵宠寻踪图录" in play("tracking", "记录").commands
    assert "1 号 · 新笋 · 已寻获" in play("tracking_codex", "bamboo").lines
    assert snapshot(game[1]) == before


def test_repeat_site_and_nonwinning_receipts_do_not_inflate_discoveries(game, play):
    prepared(play)
    found(play, now=NOW + DAY)
    receipt = sql(game[1], "SELECT * FROM duel_actions ORDER BY action_id DESC LIMIT 1")[0]
    original = json.loads(receipt["snapshot"])
    invalid = [{}, {"kind": "duel", "picked": 2, "target": 2},
               {"status": "active", "picked": 2, "target": 2},
               {"status": "abandoned", "picked": 2, "target": 2},
               {"event": "survey", "picked": 2, "target": 2},
               {"found": False, "picked": 2, "target": 2},
               {"found": 1, "picked": 2, "target": 2}, {"picked": 2, "target": 3},
               {"picked": 2, "target": 2.0},
               {"picked": "2", "target": 2}, {"picked": 17, "target": 17},
               {"picked": 0, "target": 0}, {"map": {"id": "missing"}, "picked": 2, "target": 2}]
    for index, change in enumerate(invalid):
        sql(game[1], "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
            (f"old-codex-{index}", "u1", NOW + DAY, json.dumps({**original, **change}), receipt["reply"]))
    play("adopt", "青鸾", user="u2")
    sql(game[1], "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
        ("other-player-site", "u2", NOW, json.dumps({**original, "picked": 2, "target": 2}), receipt["reply"]))
    assert "竹溪旧径 · 已寻获 1/16 处" in play("tracking_codex").text()
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError, match="仅寻获 1 处"):
        play("tracking_reward_claim", "竹溪旧径 4")
    assert snapshot(game[1], receipts=True) == before


def test_replay_restart_expired_receipt_and_no_active_pet_do_not_duplicate_rewards(game, play):
    prepared(play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    stones, inventory = player(game[1])["stones"], items(game[1])
    result = play("tracking_reward_claim", "竹溪旧径 1", op="codex-replay")
    assert_paid(game[1], stones, inventory, game[0].content.tracking_rewards["bamboo_1"])
    after = snapshot(game[1], receipts=True)
    assert reopened(game).execute("u1", "tracking_reward_claim", "竹溪旧径 1", "codex-replay", NOW) == result
    assert snapshot(game[1], receipts=True) == after
    sql(game[1], "DELETE FROM operations WHERE operation_id='codex-replay'")
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError, match="已经领取"):
        reopened(game).execute("u1", "tracking_reward_claim", "竹溪旧径 1", "codex-replay", NOW + 8 * DAY)
    assert snapshot(game[1], receipts=True) == before


@pytest.mark.parametrize("same_operation", [False, True])
def test_concurrent_claims_pay_exactly_once(game, play, same_operation):
    prepared(play)
    stones, inventory = player(game[1])["stones"], items(game[1])
    def attempt(index):
        try:
            return play("tracking_reward_claim", "竹溪旧径 1", op=f"codex-race-{0 if same_operation else index}").text()
        except GameError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum("已领取" in result for result in results) == (2 if same_operation else 1)
    assert_paid(game[1], stones, inventory, game[0].content.tracking_rewards["bamboo_1"])
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id='tracking_reward_bamboo_1'") == [
        {"progress": 1, "claimed": 1}]


@pytest.mark.parametrize("failure", ["grant", "marker", "save", "receipt"])
def test_write_failures_roll_back_the_whole_reward_and_allow_retry(game, play, monkeypatch, failure):
    prepared(play)
    before = snapshot(game[1], receipts=True)
    stones, inventory = player(game[1])["stones"], items(game[1])
    with monkeypatch.context() as patch:
        if failure == "grant":
            original = tracking_codex.grant
            def fail(*args):
                original(*args)
                raise RuntimeError("codex reward failure")
            patch.setattr(tracking_codex, "grant", fail)
        elif failure == "save":
            original_save = Repository.save
            def fail_save(repo):
                original_save(repo)
                raise RuntimeError("codex reward failure")
            patch.setattr(Repository, "save", fail_save)
        else:
            table = "quest_progress" if failure == "marker" else "operations"
            condition = ("NEW.quest_id='tracking_reward_bamboo_1'" if failure == "marker" else
                         "NEW.operation_id='codex-failure'")
            sql(game[1], f"CREATE TRIGGER reject_codex BEFORE INSERT ON {table} WHEN {condition} "
                         "BEGIN SELECT RAISE(ABORT, 'codex reward failure'); END")
        with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="codex reward failure"):
            play("tracking_reward_claim", "竹溪旧径 1", op="codex-failure")
    assert snapshot(game[1], receipts=True) == before
    if failure in {"marker", "receipt"}:
        sql(game[1], "DROP TRIGGER reject_codex")
    play("tracking_reward_claim", "竹溪旧径 1", op="codex-failure")
    assert_paid(game[1], stones, inventory, game[0].content.tracking_rewards["bamboo_1"])


@pytest.mark.parametrize("argument", ["", "竹溪旧径", "竹溪旧径 1 extra", "不存在 1", "竹溪旧径 0",
                                      "竹溪旧径 2", "竹溪旧径 -1", "竹溪旧径 １", "竹溪旧径 ١",
                                      "竹溪旧径 1.0", "竹溪旧径 " + "9" * 5000])
def test_bad_claim_inputs_preserve_all_state(game, play, argument):
    prepared(play)
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError):
        play("tracking_reward_claim", argument)
    assert snapshot(game[1], receipts=True) == before


@pytest.mark.parametrize("argument", ["bamboo extra", "不存在", "bamboo 1"])
def test_invalid_catalog_queries_do_not_write(game, play, argument):
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError):
        play("tracking_codex", argument)
    assert snapshot(game[1], receipts=True) == before


def test_unmet_corrupt_reward_and_incomplete_ledger_have_no_claim_link_or_payment(game, play):
    play("adopt", "青鸾")
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError, match="仅寻获 0"):
        play("tracking_reward_claim", "竹溪旧径 1")
    assert snapshot(game[1], receipts=True) == before
    found(play)
    entry = game[0].content.tracking_rewards["bamboo_1"]
    game[0].content.tracking_rewards[entry.id] = entry.model_copy(update={"items": {"missing": 1}})
    before = snapshot(game[1], receipts=True)
    with pytest.raises(GameError, match="奖励定义暂不可用"):
        play("tracking_reward_claim", "竹溪旧径 1")
    assert snapshot(game[1], receipts=True) == before
    page = play("tracking_codex", "bamboo")
    assert "奖励暂不可用" in page.text()
    assert not page.inline_commands
    game[0].content.tracking_rewards[entry.id] = entry
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','tracking_reward_bamboo_1',1,0)")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="领取记录异常"):
        play("tracking_reward_claim", "竹溪旧径 1")
    assert not play("tracking_codex", "bamboo").inline_commands
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
def test_real_adapter_chain_and_transport_replay(game, monkeypatch, adapter):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="codex-bot", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    commands = ("灵宠寻踪图录", "灵宠领养 青鸾", "灵宠寻踪 出发 竹溪旧径", "灵宠寻踪 勘察 1",
                "灵宠寻踪 挖掘 1", "灵宠寻踪图录 竹溪旧径", "灵宠寻踪领奖 竹溪旧径 1")
    def event(index, command):
        return (onebot_event(command, 3000 + index) if adapter == "OneBot V11" else
                qq_event(text=command, message_id=str(3000 + index)))
    async def run():
        for index, command in enumerate(commands):
            await handlers._run(bot, event(index, command), command)
        before = snapshot(game[1], receipts=True)
        await handlers._run(bot, event(6, commands[6]), commands[6])
        assert snapshot(game[1], receipts=True) == before
    asyncio.run(run())
    messages = []
    for call in bot.send.call_args_list:
        message = call.args[1]
        messages.append(message["markdown"][0].data["markdown"].content.replace("\\+", "+")
                        if adapter == "QQ" else str(message))
    assert "尚未结契" in messages[0] and "已寻获 1/16 处" in messages[5]
    assert "竹溪初访" in messages[-1] and "灵石 +60" in messages[-1]
    assert player(game[1], "12345")["stones"] == 160


@pytest.mark.parametrize("mode", ["native", "text", "template"])
def test_qq_rendering_uses_one_reachable_command_per_link_and_separate_buttons(game, play, mode):
    prepared(play)
    for page in (play("tracking_codex"), play("tracking_codex", "bamboo")):
        _, message = _qq_segments(page, Config(spirit_pet_qq_mode=mode, spirit_pet_command_prefix="/",
                                             spirit_pet_qq_template_id="codex-template"))
        for link in page.inline_commands:
            assert handlers._parse(link.command) is not None
            assert 0 <= link.line < len(page.lines)
        if mode == "native":
            markdown = message["markdown"][0].data["markdown"].content
            commands = [parse_qs(urlparse(url).query)["command"][0]
                        for url in re.findall(r"\]\((mqqapi:[^)]+)\)", markdown)]
            for link in page.inline_commands:
                assert commands.count("/" + link.command) == 1
            buttons = [button.action.data.removeprefix("/") for segment in message["keyboard"]
                       for row in segment.data["keyboard"].content.rows for button in row.buttons]
            assert len(buttons) == len(set(buttons)) <= 4
            assert not set(buttons) & {link.command for link in page.inline_commands}
        else:
            for link in page.inline_commands:
                assert "/" + link.command in str(message)


@pytest.mark.parametrize("change", [{"threshold": 0}, {"threshold": 17}, {"threshold": True},
                                    {"threshold": "1"}, {"stones": -1}, {"items": {"spirit_food": 0}},
                                    {"created_at": NOW}, {"stones": 0, "items": {}}])
def test_reward_model_is_strict(game, change):
    entry = game[0].content.tracking_rewards["bamboo_1"].model_dump()
    with pytest.raises(ValueError):
        TrackingReward.model_validate({**entry, **change})


@pytest.mark.parametrize("change,error", [({"map_id": "missing"}, "unknown map"),
                                        ({"items": {"missing": 1}}, "items"),
                                        ({"threshold": 4}, "ordered thresholds"),
                                        ({"threshold": 2}, "ordered thresholds")])
def test_catalog_rejects_bad_references_or_tiers(game, change, error):
    entries = game[0].content.tracking_rewards
    entries["bamboo_1"] = entries["bamboo_1"].model_copy(update=change)
    with pytest.raises(ValueError, match=error):
        game[0].content.validate()


def test_catalog_requires_all_maps_and_complete_tiers(game):
    game[0].content.tracking_rewards.pop("orchard_16")
    with pytest.raises(ValueError, match="ordered thresholds"):
        game[0].content.validate()


def test_collected_food_and_seed_are_usable_by_real_growth_commands(game, play):
    play("adopt", "青鸾")
    for target in range(1, 5):
        game[0].rng = TargetRandom(target)
        now = NOW + (target - 1) * DAY
        play("tracking", "出发 bamboo", now=now)
        survey(play, now=now)
        play("tracking", f"挖掘 {target}", now=now)
    play("tracking_reward_claim", "竹溪旧径 1", now=now)
    play("tracking_reward_claim", "竹溪旧径 4", now=now)
    inventory, before_pet = items(game[1]), pet(game[1])
    play("feed", now=now)
    assert items(game[1])["spirit_food"] == inventory["spirit_food"] - 1
    assert pet(game[1])["exp"] > before_pet["exp"]
    play("farm_open", "1", now=now)
    play("farm_plant", "1 灵血草种", now=now)
    assert items(game[1])["seed_blood_herb"] == inventory["seed_blood_herb"] - 1
