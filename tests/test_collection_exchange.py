"""Duplicate-species collection stamp exchange and its player-facing contract."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.collection_exchange_content import CollectionExchangeOffer
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import collection_exchange
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def duplicate_pet(game, species_id="qingluan", name="青鸾二号"):
    sql(
        game[1],
        "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1',?,?,?)",
        (species_id, name, NOW),
    )


def ready(game, play, copies=1):
    play("adopt", "青鸾", now=NOW, op="adopt-for-collection")
    for index in range(copies):
        duplicate_pet(game, name=f"青鸾{index + 2}号")


def spent_row(game, user="u1"):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, collection_exchange.SPENT_KEY),
    )
    return rows[0]["progress"] if rows else 0


def test_content_declares_sorted_real_rewards(game):
    offers = collection_exchange.offers(_ctx(game))
    assert [offer.name for offer in offers] == ["灵粮补给", "锻灵矿包", "蕴灵丹", "血脉精华", "灵石小匣"]
    assert all(offer.cost > 0 for offer in offers)
    assert all(item_id in game[0].content.items for offer in offers for item_id in offer.items)


def test_offer_model_rejects_empty_reward():
    with pytest.raises(ValueError, match="must not be empty"):
        CollectionExchangeOffer.model_validate({
            "id": "empty", "name": "空兑换", "description": "测试", "cost": 1,
        })


def test_catalog_rejects_unknown_or_unusable_exchange_items(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "collection_exchange.json").read_text()
    (data / "collection_exchange.json").write_text(source.replace('"spirit_food"', '"ghost_item"', 1))
    with pytest.raises(ValueError, match="unknown"):
        Catalog.load(data)

    data = tmp_path / "wrong-kind"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    equipment = next(
        entry["id"] for entry in json.loads((data / "items.json").read_text())
        if entry["kind"] == "equipment"
    )
    source = (data / "collection_exchange.json").read_text()
    (data / "collection_exchange.json").write_text(source.replace('"spirit_food"', f'"{equipment}"', 1))
    with pytest.raises(ValueError, match="usable items"):
        Catalog.load(data)


def test_unregistered_page_is_read_only_and_shows_catalog(game, play):
    page = play("collection_exchange", user="ghost", now=NOW)
    assert page.title == "灵宠收集兑换"
    assert "只读预览" in page.text()
    assert "灵粮补给" in page.text()
    assert page.inline_commands == ()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_duplicate_species_are_the_only_spendable_source(game, play):
    ready(game, play, copies=2)
    page = play("collection_exchange", now=NOW)
    assert "派生 2" in page.text()
    assert "可用 2" in page.text()
    assert collection_exchange.duplicate_stamps(_ctx(game)) == 2
    assert "灵宠收集兑换" in play("collection", now=NOW + 1).commands
    assert "收集印记：可用 2" in play("objectives", now=NOW + 1).text()


def test_exchange_charges_stamps_and_credits_items(game, play):
    ready(game, play, copies=2)
    before = items(game[1]).get("spirit_food", 0)
    reply = play("collection_exchange", "灵粮补给 2", now=NOW, op="exchange-two")
    assert reply.title == "收集印记兑换"
    assert "消耗 2 枚收集印记" in reply.text()
    assert items(game[1])["spirit_food"] == before + 6
    assert spent_row(game) == 2
    assert collection_exchange.balance(_ctx(game)) == 0


def test_stone_offer_credits_stones_and_batch_cost_scales(game, play):
    ready(game, play, copies=4)
    stones = player(game[1])["stones"]
    play("collection_exchange", "灵石小匣", now=NOW, op="exchange-stones")
    assert player(game[1])["stones"] == stones + 200
    assert spent_row(game) == 4


def test_insufficient_unknown_and_bad_quantity_do_not_write(game, play):
    ready(game, play, copies=1)
    before = (spent_row(game), items(game[1]).get("spirit_food", 0), player(game[1])["stones"])
    with pytest.raises(GameError, match="收集印记不足"):
        play("collection_exchange", "灵石小匣", now=NOW, op="too-expensive")
    with pytest.raises(GameError, match="序号需在 1-5"):
        play("collection_exchange", "6", now=NOW, op="bad-index")
    with pytest.raises(GameError, match="数量"):
        play("collection_exchange", "灵粮补给 0", now=NOW, op="bad-amount")
    with pytest.raises(GameError, match="未找到该内容"):
        play("collection_exchange", "不存在", now=NOW, op="bad-name")
    assert (spent_row(game), items(game[1]).get("spirit_food", 0), player(game[1])["stones"]) == before


def test_replay_is_idempotent_and_survives_restart(game, play):
    ready(game, play, copies=1)
    first = play("collection_exchange", "灵粮补给", now=NOW, op="same-exchange")
    second = play("collection_exchange", "灵粮补给", now=NOW + 86400, op="same-exchange")
    assert second == first
    assert spent_row(game) == 1
    restarted = type(game[0])(game[1], game[0].config, game[0].rng)
    replay = restarted.execute("u1", "collection_exchange", "灵粮补给", "same-exchange", NOW + 2 * 86400)
    assert replay == first
    assert spent_row(game) == 1


def test_concurrent_distinct_operations_cannot_overspend(game, play):
    ready(game, play, copies=1)

    def exchange(index):
        try:
            return play("collection_exchange", "灵粮补给", now=NOW, op=f"concurrent-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(exchange, range(4)))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert spent_row(game) == 1
    assert items(game[1])["spirit_food"] == 6


def test_write_failure_rolls_back_spend_and_reward_then_retry(game, play, monkeypatch):
    ready(game, play, copies=1)
    original = Repository.add_item

    def fail(self, user_id, item_id, amount):
        raise RuntimeError("injected collection reward failure")

    monkeypatch.setattr(Repository, "add_item", fail)
    with pytest.raises(RuntimeError, match="injected collection reward failure"):
        play("collection_exchange", "灵粮补给", now=NOW, op="rollback-exchange")
    assert spent_row(game) == 0
    assert items(game[1]).get("spirit_food", 0) == 3
    monkeypatch.setattr(Repository, "add_item", original)
    reply = play("collection_exchange", "灵粮补给", now=NOW, op="rollback-exchange")
    assert "兑换成功" in reply.text()
    assert spent_row(game) == 1
    assert items(game[1])["spirit_food"] == 6


def test_native_links_and_buttons_are_disjoint_and_parser_is_real(game, play):
    ready(game, play, copies=2)
    page = play("collection_exchange", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}
    assert handlers._parse("灵宠收集兑换") == ("collection_exchange", "")
    assert handlers._parse("灵宠收集兑换 灵粮补给 2") == ("collection_exchange", "灵粮补给 2")


def test_onebot_uses_the_same_read_only_reply_and_parser(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config())
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        event = onebot_event("灵宠收集兑换", 901)
        await handlers._run(bot, event, handlers._plain_text(event))

    asyncio.run(run())
    message = bot.send.call_args.args[1]
    assert "只读预览" in message
    assert "灵粮补给" in message
    assert "mqqapi://" not in message


def test_missing_item_definition_is_refused_before_ledger_write(game, play, monkeypatch):
    ready(game, play, copies=1)
    offer = collection_exchange.offers(_ctx(game))[0]
    monkeypatch.setitem(
        game[0].content.collection_exchange,
        offer.id,
        offer.model_copy(update={"items": {"ghost_item": 1}}),
    )
    with pytest.raises(GameError, match="兑换物品定义缺失"):
        play("collection_exchange", "1", now=NOW, op="missing-item")
    assert spent_row(game) == 0


def _ctx(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context

    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng,
        user, now, "collection-read",
    )
