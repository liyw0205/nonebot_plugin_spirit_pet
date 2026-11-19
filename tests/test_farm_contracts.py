import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.farm_contract_content import FarmContractPlan
from nonebot_plugin_spirit_pet.domain.farm_contract_snapshot import FarmContractSnapshot
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def ready(play, game, *, plots=(1,), seeds=("灵稻种", "矿苗种")):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    for plot in plots:
        play("farm_open", str(plot), now=NOW)
    for seed in seeds:
        play("buy", f"{seed} 2", now=NOW)


def active_snapshot(game):
    rows = sql(
        game[1],
        "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='farm_contract' "
        "OR (json_extract(snapshot,'$.kind')='farm_care' AND json_type(snapshot,'$.contract')='object') "
        "ORDER BY action_id DESC LIMIT 1",
    )
    if not rows:
        return None
    envelope = json.loads(rows[0]["snapshot"])
    return envelope.get("contract", {key: value for key, value in envelope.items() if key != "kind"})


def database_snapshot(game):
    tables = sql(game[1], "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return {
        row["name"]: sql(game[1], f"SELECT * FROM {row['name']} ORDER BY rowid")
        for row in tables
    }


def test_three_plans_are_strict_and_read_only(game, play):
    page = play("farm_contracts", now=NOW)
    assert len(game[0].content.farm_contracts) == 3
    assert "青禾双季" in page.text() and "灵矿轮作" in page.text() and "灵蕊互生" in page.text()
    assert not sql(game[1], "SELECT * FROM players")
    for plan in game[0].content.farm_contracts.values():
        assert len(plan.crops) == 2 and len(set(plan.crops)) == 2
        assert plan.delivery
        assert set(plan.delivery) <= set(game[0].content.items)
    invalid = game[0].content.farm_contracts["green_pair"].model_dump()
    invalid["crops"] = ["spirit_rice", "spirit_rice"]
    with pytest.raises(ValidationError, match="distinct"):
        FarmContractPlan.model_validate(invalid)


def test_full_two_season_contract_with_replant_care_replay_and_delivery(game, play):
    ready(play, game)
    open_page = play("farm_contracts", now=NOW)
    assert "可用空闲田位" in open_page.text()
    before_sign = player(game[1])["stones"]
    signed = play("farm_contracts", "签订 青禾双季 1", now=NOW, op="farm-sign")
    assert "押金 100" in signed.text()
    assert player(game[1])["stones"] == before_sign - 100
    contract_id = active_snapshot(game)["contract_id"]
    assert contract_id == 1
    assert "农契：契约 1" in play("objectives", now=NOW).text()
    assert "农契 1 已完成 0/2 季" in play("today", now=NOW).text()
    assert "青禾双季" in play("farm_contracts", now=NOW).text()

    play("farm_plant", "1 灵稻种", now=NOW, op="farm-plant-rice")
    care_page = play("farm_care", "1", now=NOW)
    care_command = next(link.command for link in care_page.inline_commands if link.label == "培肥")
    play("farm_care", care_command.split(" ", 1)[1], now=NOW, op="farm-care")
    first = play("farm_harvest", "1 矿苗种", now=NOW + 1800, op="farm-first-season")
    assert "第 1/2 季达成" in first.text()
    event = sql(game[1], "SELECT snapshot FROM duel_actions WHERE operation_id='farm-first-season'")
    envelope = json.loads(event[0]["snapshot"])
    assert envelope["kind"] == "farm_care"
    assert envelope["contract"]["seasons"][0]["cycle"] == NOW
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='farm-first-season'")) == 1
    next_cycle = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='farm_cycle_1'")[0]["progress"]
    assert next_cycle > envelope["contract"]["seasons"][0]["cycle"]

    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, game[0].rng)
    assert restarted.execute(
        "u1", "farm_harvest", "1 矿苗种", "farm-first-season", NOW + 86400,
    ) == first
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='farm_crop_1_ore_sprout'")[0]["progress"] == NOW + 1800
    with pytest.raises(GameError, match="different user"):
        restarted.execute("u2", "farm_harvest", "1 矿苗种", "farm-first-season", NOW + 86400)

    second = play("farm_harvest", "1", now=NOW + 5400, op="farm-second-season")
    assert "第 2/2 季达成" in second.text()
    assert active_snapshot(game)["seasons"][1]["crop_id"] == "ore_sprout"
    assert "农契 1 可交付" in play("today", now=NOW + 5401).text()

    stones_before = player(game[1])["stones"]
    inventory_before = items(game[1])
    delivered = play("farm_contracts", "交付 1", now=NOW + 5401, op="farm-deliver")
    assert "已交付" in delivered.text() and "押金退还 100" in delivered.text()
    assert player(game[1])["stones"] == stones_before + 300
    inventory_after = items(game[1])
    assert inventory_after["spirit_food"] == inventory_before["spirit_food"] - 1
    assert inventory_after["forge_ore"] == inventory_before["forge_ore"] - 1
    assert active_snapshot(game)["status"] == "completed"
    sql(game[1], "DELETE FROM operations")
    replay_game = Game(game[1], game[0].config, game[0].rng)
    assert replay_game.execute("u1", "farm_contracts", "交付 1", "farm-deliver", NOW + 86400) == delivered
    assert player(game[1])["stones"] == stones_before + 300
    history = play("farm_contracts", "记录", now=NOW + 5402)
    assert "第1季灵稻" in history.text() and "第2季矿苗" in history.text() and "已交付" in history.text()
    with pytest.raises(GameError, match="没有进行中的农契"):
        play("farm_contracts", "交付 1", now=NOW + 5403, op="farm-deliver-again")


def test_wrong_plot_wrong_crop_and_wilt_never_advance_contract(game, play):
    ready(play, game, plots=(1, 2))
    play("farm_contracts", "签订 青禾双季 1", now=NOW, op="wrong-sign")
    delayed = play("farm_contracts", now=NOW + 30 * 86400)
    assert "契约 1 · 青禾双季" in delayed.text()
    assert active_snapshot(game)["status"] == "active"
    play("farm_plant", "2 灵稻种", now=NOW + 1)
    play("farm_harvest", "2", now=NOW + 1801)
    assert active_snapshot(game)["seasons"] == []

    play("farm_plant", "1 矿苗种", now=NOW + 1802)
    play("farm_harvest", "1", now=NOW + 5402)
    assert active_snapshot(game)["seasons"] == []

    planted = NOW + 5403
    play("farm_plant", "1 灵稻种", now=planted)
    wilted_at = planted + 1800 + 48 * 3600
    wilt = play("farm_harvest", "1", now=wilted_at)
    assert "只返还了种子" in wilt.text()
    assert active_snapshot(game)["seasons"] == []
    play("farm_plant", "1 灵稻种", now=wilted_at + 1)
    ripe = play("farm_harvest", "1", now=wilted_at + 1801)
    assert "第 1/2 季达成" in ripe.text()
    assert len(active_snapshot(game)["seasons"]) == 1


def test_sign_requires_empty_open_plot_single_active_and_deposit(game, play):
    ready(play, game)
    play("farm_plant", "1 灵稻种", now=NOW)
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="空闲田位"):
        play("farm_contracts", "签订 青禾双季 1", now=NOW)
    assert player(game[1])["stones"] == before
    play("farm_harvest", "1", now=NOW + 1800)
    with pytest.raises(GameError, match="尚未开垦"):
        play("farm_contracts", "签订 青禾双季 2", now=NOW + 1801)
    sql(game[1], "UPDATE players SET stones=0 WHERE user_id='u1'")
    with pytest.raises(GameError, match="押金"):
        play("farm_contracts", "签订 青禾双季 1", now=NOW + 1801)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    play("farm_contracts", "签订 青禾双季 1", now=NOW + 1801)
    with pytest.raises(GameError, match="已有进行中的农契"):
        play("farm_contracts", "签订 青禾双季 1", now=NOW + 1802)
    play("farm_plant", "1 灵稻种", now=NOW + 1802)
    before_abandon = player(game[1])["stones"]
    play("farm_contracts", "放弃 1", now=NOW + 1803)
    assert active_snapshot(game)["status"] == "abandoned"
    assert player(game[1])["stones"] == before_abandon
    field = sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id='farm_crop_1_spirit_rice'")
    assert field


def test_delivery_missing_material_and_receipt_failure_roll_back_all_writes(game, play, monkeypatch):
    ready(play, game)
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)
    play("farm_harvest", "1 矿苗种", now=NOW + 1800)
    play("farm_harvest", "1", now=NOW + 5400)
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    before = (items(game[1]), player(game[1])["stones"], active_snapshot(game))
    with pytest.raises(GameError, match="交付材料不足"):
        play("farm_contracts", "交付 1", now=NOW + 5401)
    assert (items(game[1]), player(game[1])["stones"], active_snapshot(game)) == before
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',1)")
    before = (items(game[1]), player(game[1])["stones"], active_snapshot(game))

    def fail(*args, **kwargs):
        raise RuntimeError("injected contract receipt failure")

    monkeypatch.setattr(Repository, "record_duel_action", fail)
    with pytest.raises(RuntimeError, match="injected contract receipt"):
        play("farm_contracts", "交付 1", now=NOW + 5401, op="fail-contract-receipt")
    assert (items(game[1]), player(game[1])["stones"], active_snapshot(game)) == before


def test_sign_and_harvest_receipt_failures_restore_deposit_crop_and_progress(game, play, monkeypatch):
    ready(play, game)

    def fail(*args, **kwargs):
        raise RuntimeError("injected receipt failure")

    before = (player(game[1])["stones"], sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_contract_sequence'"))
    monkeypatch.setattr(Repository, "record_duel_action", fail)
    with pytest.raises(RuntimeError, match="injected receipt"):
        play("farm_contracts", "签订 青禾双季 1", now=NOW, op="fail-sign")
    monkeypatch.undo()
    assert (player(game[1])["stones"], sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_contract_sequence'")) == before
    assert active_snapshot(game) is None

    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)
    crop_before = sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_crop_1_spirit_rice'")
    inventory_before = items(game[1])
    monkeypatch.setattr(Repository, "record_duel_action", fail)
    with pytest.raises(RuntimeError, match="injected receipt"):
        play("farm_harvest", "1 矿苗种", now=NOW + 1800, op="fail-harvest-receipt")
    monkeypatch.undo()
    assert items(game[1]) == inventory_before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_crop_1_spirit_rice'") == crop_before
    assert active_snapshot(game)["seasons"] == []


def test_concurrent_harvest_advances_one_season_once(game, play):
    ready(play, game)
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)

    def harvest(index):
        try:
            return play("farm_harvest", "1 矿苗种", now=NOW + 1800, op=f"race-harvest-{index}")
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(harvest, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(active_snapshot(game)["seasons"]) == 1
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE json_extract(snapshot,'$.contract.contract_id')=1 AND json_extract(snapshot,'$.contract.seasons[0].crop_id')='spirit_rice'")) == 1


def test_concurrent_sign_and_delivery_settle_once(game, play):
    ready(play, game)

    def sign(index):
        try:
            return play("farm_contracts", "签订 青禾双季 1", now=NOW, op=f"parallel-sign-{index}")
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        signed = list(pool.map(sign, range(2)))
    assert sum(reply is not None for reply in signed) == 1
    assert player(game[1])["stones"] == 10000 - 200 - 80 - 160 - 100
    play("farm_plant", "1 灵稻种", now=NOW)
    play("farm_harvest", "1 矿苗种", now=NOW + 1800)
    play("farm_harvest", "1", now=NOW + 5400)
    stones_before = player(game[1])["stones"]

    def deliver(index):
        try:
            return play("farm_contracts", "交付 1", now=NOW + 5401, op=f"parallel-deliver-{index}")
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        delivered = list(pool.map(deliver, range(2)))
    assert sum(reply is not None for reply in delivered) == 1
    assert player(game[1])["stones"] == stones_before + 300
    assert active_snapshot(game)["status"] == "completed"


def test_contract_time_and_damaged_snapshot_protect_harvest_transaction(game, play):
    ready(play, game)
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)
    play("farm_harvest", "1 矿苗种", now=NOW + 1800)
    with pytest.raises(GameError, match="时钟恢复"):
        play("farm_contracts", "交付 1", now=NOW + 1799)

    row = sql(
        game[1],
        "SELECT operation_id,snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='farm_contract' "
        "ORDER BY action_id DESC LIMIT 1",
    )[0]
    payload = json.loads(row["snapshot"])
    payload["contract"]["seasons"] = [{
        "number": 2, "crop_id": "ore_sprout", "cycle": NOW + 1800,
        "planted_at": NOW + 1800, "harvested_at": NOW + 5400,
    }]
    sql(
        game[1], "UPDATE duel_actions SET snapshot=? WHERE operation_id=?",
        (json.dumps(payload), row["operation_id"]),
    )
    crop_before = sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_crop_1_ore_sprout'")
    inventory_before = items(game[1])
    stones_before = player(game[1])["stones"]
    with pytest.raises(GameError, match="快照损坏"):
        play("farm_harvest", "1", now=NOW + 5400, op="damaged-contract-harvest")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_crop_1_ore_sprout'") == crop_before
    assert items(game[1]) == inventory_before
    assert player(game[1])["stones"] == stones_before


def test_qq_onebot_and_native_page_share_contract_entry(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    assert handlers._parse("灵宠农契") == ("farm_contracts", "")
    assert handlers._parse("灵宠农契 签订 青禾双季 1") == (
        "farm_contracts", "签订 青禾双季 1",
    )
    bot_onebot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )
    bot_qq = SimpleNamespace(
        self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )

    game[0].execute("12345", "adopt", "青鸾", "platform-adopt", NOW)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='12345'")
    game[0].execute("12345", "farm_open", "1", "platform-open", NOW)
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='12345'")[0]["stones"]

    async def run():
        event = onebot_event("!灵宠农契 签订 青禾双季 1", 101)
        await handlers.handle_command(bot_onebot, event, event.get_message())
        event = qq_event(user_id="12345", text="灵宠农契 签订 青禾双季 1", message_id="102")
        await handlers.handle_command(bot_qq, event, event.get_message())

    asyncio.run(run())
    assert bot_onebot.send.await_count == 1 and bot_qq.send.await_count == 1
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='12345'")[0]["stones"] == before - 100
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE user_id='12345' AND json_extract(snapshot,'$.kind')='farm_contract'")) == 1
    page = game[0].execute("12345", "farm_contracts", "", "native-page", NOW)
    assert len(page.commands) <= 4 and len(set(page.commands)) == len(page.commands)
    assert not set(page.commands) & {link.command for link in page.inline_commands}
    body, payload = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert body or payload


@pytest.mark.parametrize("plan_id", ["green_pair", "ore_rotation", "flower_union"])
def test_each_plan_uses_real_seed_supply_harvests_and_exact_frozen_payout(game, play, plan_id):
    ready(play, game, seeds=())
    plan = game[0].content.farm_contracts[plan_id]
    if plan.min_farm_level > 1:
        before = database_snapshot(game)
        with pytest.raises(GameError, match="需要农事"):
            play("farm_contracts", f"签订 {plan.name} 1", now=NOW)
        assert database_snapshot(game) == before
        threshold = game[0].content.farm_levels[plan.min_farm_level].harvests
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1','stat_farm_harvests',?,0)", (threshold,))
    for crop_id in plan.crops:
        crop = game[0].content.crops[crop_id]
        seed = game[0].content.items[crop.seed_item]
        if seed.price is not None:
            play("buy", seed.name, now=NOW)
        else:
            recipe = next(entry for entry in game[0].content.hybrids.values() if entry.output == seed.id)
            for ingredient in recipe.seeds:
                play("buy", game[0].content.items[ingredient].name, now=NOW)
            play("hybrid", recipe.name, now=NOW)
    before_sign = player(game[1])["stones"]
    play("farm_contracts", f"签订 {plan.name} 1", now=NOW)
    assert player(game[1])["stones"] == before_sign - plan.deposit
    # Editing today's plan must not rewrite an already signed contract.
    game[0].content.farm_contracts[plan_id] = plan.model_copy(update={"deposit": 999, "reward_stones": 9999})
    now = NOW
    for crop_id in plan.crops:
        crop = game[0].content.crops[crop_id]
        play("farm_plant", f"1 {game[0].content.items[crop.seed_item].name}", now=now)
        now += crop.duration
        play("farm_harvest", "1", now=now)
    before_stones, before_items = player(game[1])["stones"], items(game[1])
    play("farm_contracts", "交付 1", now=now)
    assert player(game[1])["stones"] == before_stones + plan.deposit + plan.reward_stones
    for item_id in set(plan.delivery) | set(plan.reward_items):
        assert items(game[1])[item_id] == before_items.get(item_id, 0) - plan.delivery.get(item_id, 0) + plan.reward_items.get(item_id, 0)
    assert active_snapshot(game)["status"] == "completed"
    assert len(active_snapshot(game)["seasons"]) == 2


@pytest.mark.parametrize("kind", ["wrong_crop", "wrong_plot", "wilted", "awaiting_delivery"])
def test_nonqualifying_harvest_receipt_cannot_consume_a_later_crop(game, play, kind):
    ready(play, game, plots=(1, 2))
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    plot, crop, ripe = 1, "矿苗种", NOW + 3600
    if kind == "wrong_plot":
        plot, crop, ripe = 2, "灵稻种", NOW + 1800
    elif kind == "wilted":
        crop, ripe = "灵稻种", NOW + 1800 + 48 * 3600
    elif kind == "awaiting_delivery":
        play("farm_plant", "1 灵稻种", now=NOW)
        play("farm_harvest", "1 矿苗种", now=NOW + 1800)
        play("farm_harvest", "1", now=NOW + 5400)
        play("buy", "灵稻种", now=NOW + 5400)
        crop, ripe = "灵稻种", NOW + 7200
    planted = ripe - (1800 if crop == "灵稻种" else 3600)
    if kind == "wilted":
        planted = NOW
    play("farm_plant", f"{plot} {crop}", now=planted)
    reply = play("farm_harvest", str(plot), now=ripe, op="nonqualifying-harvest")
    assert "季达成" not in reply.text()
    play("buy", "灵稻种", now=ripe)
    play("farm_plant", f"{plot} 灵稻种", now=ripe)
    sql(game[1], "DELETE FROM operations")
    before = database_snapshot(game)
    restarted = Game(game[1], game[0].config, game[0].rng)
    assert restarted.execute("u1", "farm_harvest", str(plot), "nonqualifying-harvest", ripe + 1800) == reply
    # Replaying may repopulate operations, but must leave all gameplay state unchanged.
    after = database_snapshot(game)
    before.pop("operations")
    after.pop("operations")
    assert after == before
    assert "共 1 份农契" in play("farm_contracts", "记录", now=ripe + 1800).text()


def test_history_navigation_read_pages_invalid_arguments_and_old_contracts(game, play):
    ready(play, game)
    for number in range(1, 7):
        play("farm_contracts", "签订 青禾双季 1", now=NOW + number)
        play("farm_contracts", f"放弃 {number}", now=NOW + number)
    before = database_snapshot(game)
    page = play("farm_contracts", "记录", now=NOW + 7)
    assert "共 6 份农契" in page.text() and "契约 6" in page.text()
    assert "灵宠农契 记录 2" in page.commands
    assert "契约 1" in play("farm_contracts", "记录 2", now=NOW + 7).text()
    assert "灵宠农契 记录" in play("farm_contracts", now=NOW + 7).commands
    assert database_snapshot(game) == before
    for argument in ("记录 0", "记录 3", "记录 abc", "签订 青禾双季 0", "签订 不存在 1", "交付 -1", "乱写"):
        with pytest.raises(GameError):
            play("farm_contracts", argument, now=NOW + 7)
        assert database_snapshot(game) == before
    play("farm_contracts", "签订 青禾双季 1", now=NOW + 7)
    before = database_snapshot(game)
    for argument in ("交付 1", "放弃 1"):
        with pytest.raises(GameError, match="旧农契"):
            play("farm_contracts", argument, now=NOW + 7)
        assert database_snapshot(game) == before
    assert "灵宠农契" in play("farm_progress", now=NOW + 7).commands
    assert "灵宠农契" in play("farm", now=NOW + 7).commands
    assert "灵宠农契" in play("help", "血脉与道具", now=NOW + 7).text()


def test_planting_and_second_season_reject_clock_rollback_or_reused_cycle(game, play):
    ready(play, game)
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    before = database_snapshot(game)
    with pytest.raises(GameError, match="时钟恢复"):
        play("farm_plant", "1 灵稻种", now=NOW - 1)
    assert database_snapshot(game) == before
    play("farm_plant", "1 灵稻种", now=NOW)
    before = database_snapshot(game)
    with pytest.raises(GameError):
        play("farm_harvest", "1 虚灵仙葩种", now=NOW + 1800)
    assert database_snapshot(game) == before
    play("farm_harvest", "1 矿苗种", now=NOW + 1800)
    sql(game[1], "UPDATE quest_progress SET progress=? WHERE quest_id='farm_cycle_1'", (NOW,))
    before = database_snapshot(game)
    with pytest.raises(GameError, match="快照损坏"):
        play("farm_harvest", "1", now=NOW + 5400)
    assert database_snapshot(game) == before


@pytest.mark.parametrize(("stage", "trigger"), [
    ("sign", "BEFORE INSERT ON quest_progress WHEN NEW.quest_id='farm_contract_sequence'"),
    ("sign", "BEFORE UPDATE OF stones ON players"),
    ("sign", "BEFORE INSERT ON duel_actions"),
    ("sign", "BEFORE INSERT ON operations"),
    ("harvest", "BEFORE DELETE ON quest_progress WHEN OLD.quest_id='farm_crop_1_spirit_rice'"),
    ("harvest", "BEFORE INSERT ON inventory WHEN NEW.item_id='spirit_food'"),
    ("harvest", "BEFORE INSERT ON quest_progress WHEN NEW.quest_id='stat_farm_harvests'"),
    ("harvest", "BEFORE UPDATE OF quantity ON inventory WHEN NEW.item_id='seed_ore_sprout'"),
    ("harvest", "BEFORE INSERT ON duel_actions"),
    ("deliver", "BEFORE UPDATE OF quantity ON inventory WHEN NEW.item_id='forge_ore'"),
    ("deliver", "BEFORE UPDATE OF stones ON players"),
    ("deliver", "BEFORE INSERT ON inventory WHEN NEW.item_id='spirit_food'"),
    ("deliver", "BEFORE INSERT ON duel_actions"),
    ("deliver", "BEFORE INSERT ON operations"),
    ("abandon", "BEFORE INSERT ON duel_actions"),
])
def test_all_write_boundaries_rollback_every_table_and_allow_retry(game, play, stage, trigger):
    ready(play, game)
    if stage != "sign":
        play("farm_contracts", "签订 青禾双季 1", now=NOW)
        play("farm_plant", "1 灵稻种", now=NOW)
    if stage == "deliver":
        play("farm_harvest", "1 矿苗种", now=NOW + 1800)
        play("farm_harvest", "1", now=NOW + 5400)
    before = database_snapshot(game)
    sql(game[1], f"CREATE TRIGGER farm_contract_failure {trigger} BEGIN SELECT RAISE(ABORT,'farm contract injected failure'); END")
    action, argument, now = {
        "sign": ("farm_contracts", "签订 青禾双季 1", NOW),
        "harvest": ("farm_harvest", "1 矿苗种", NOW + 1800),
        "deliver": ("farm_contracts", "交付 1", NOW + 5401),
        "abandon": ("farm_contracts", "放弃 1", NOW + 1),
    }[stage]
    with pytest.raises(sqlite3.IntegrityError, match="farm contract injected failure"):
        play(action, argument, now=now, op="atomic-failure")
    assert database_snapshot(game) == before
    sql(game[1], "DROP TRIGGER farm_contract_failure")
    assert play(action, argument, now=now, op="atomic-failure")


def test_platform_handlers_complete_the_two_season_chain(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config())
    clock = [NOW]
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: clock[0])
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def send(bot, command, number):
        event = onebot_event(command, number) if bot is onebot else qq_event(user_id="12345", text=command, message_id=str(number))
        await handlers.handle_command(bot, event, event.get_message())

    async def run():
        await send(onebot, "灵宠领养 青鸾", 201)
        sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='12345'")
        await send(qq, "灵宠开垦 1", 202)
        await send(onebot, "灵宠购买 灵稻种", 203)
        await send(qq, "灵宠购买 矿苗种", 204)
        await send(onebot, "灵宠农契 签订 青禾双季 1", 205)
        await send(qq, "灵宠播种 1 灵稻种", 206)
        clock[0] += 1800
        await send(onebot, "灵宠收获 1 矿苗种", 207)
        clock[0] += 3600
        await send(qq, "灵宠收获 1", 208)
        await send(onebot, "灵宠农契 交付 1", 209)

    asyncio.run(run())
    row = sql(game[1], "SELECT snapshot FROM duel_actions WHERE user_id='12345' ORDER BY action_id DESC LIMIT 1")[0]
    assert json.loads(row["snapshot"])["contract"]["status"] == "completed"
    assert "押金退还 100" in str(onebot.send.call_args.args[1])
    assert onebot.send.await_count == 5 and qq.send.await_count == 4


def test_snapshot_validation_rejects_overlapping_seasons_and_future_harvests(game, play):
    ready(play, game)
    play("farm_contracts", "签订 青禾双季 1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)
    play("farm_harvest", "1 矿苗种", now=NOW + 1800)
    play("farm_harvest", "1", now=NOW + 5400)
    snapshot = active_snapshot(game)
    for changes in (
        {"cycle": NOW}, {"planted_at": NOW + 1799}, {"harvested_at": NOW + 5401},
    ):
        changed = json.loads(json.dumps(snapshot))
        changed["seasons"][1].update(changes)
        with pytest.raises(ValidationError):
            FarmContractSnapshot.model_validate(changed)
