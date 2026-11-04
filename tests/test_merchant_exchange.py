"""Merchant reputation exchange: spendable balance, weekly stock and boundaries."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.merchant_exchange_content import MerchantOffer
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import merchant, merchant_exchange
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400
WEEK = 7 * DAY


def seed_rep(game, value, user="u1", spent=None):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'merchant_rep', ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, value),
    )
    if spent is not None:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'merchant_spent', ?, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (user, spent),
        )


def rep_row(game, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='merchant_rep'",
        (user,),
    )
    return rows[0]["progress"] if rows else None


def spent_row(game, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='merchant_spent'",
        (user,),
    )
    return rows[0]["progress"] if rows else 0


def purchase_row(game, offer, user="u1", now=NOW):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, merchant_exchange._buy_key(offer.id, now)),
    )
    return rows[0]["progress"] if rows else 0


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def first_offer(game, name="灵粮补给"):
    return next(offer for offer in game[0].content.merchant_exchange.values() if offer.name == name)


def test_content_has_five_priced_weekly_offers(game):
    exchange = game[0].content.merchant_exchange
    assert len(exchange) == 5
    assert {offer.item for offer in exchange.values()} == {
        "spirit_food", "forge_ore", "exp_pill", "bloodline_essence", "gem_swift",
    }
    assert all(offer.cost_rep > 0 and offer.amount > 0 and 1 <= offer.weekly_limit <= 20
               for offer in exchange.values())
    assert exchange["food_pack"].cost_rep == 8
    assert exchange["gem_pack"].weekly_limit == 1


def test_offer_model_rejects_empty_or_invalid_fields():
    base = {
        "id": "x", "name": "测试兑换", "description": "测试", "cost_rep": 1,
        "item": "spirit_food", "amount": 1, "weekly_limit": 1,
    }
    assert MerchantOffer.model_validate(base).cost_rep == 1
    for key, value in (("cost_rep", 0), ("amount", 0), ("weekly_limit", 0), ("weekly_limit", 21)):
        with pytest.raises(ValidationError):
            MerchantOffer.model_validate({**base, key: value})


def test_catalog_rejects_unknown_or_wrong_kind_item(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "merchant_exchange.json").read_text()
    (data / "merchant_exchange.json").write_text(
        source.replace('"item": "spirit_food"', '"item": "no_such_item"', 1)
    )
    with pytest.raises(ValueError, match="unknown item"):
        Catalog.load(data)


def test_unregistered_exchange_page_is_read_only(game, play):
    page = play("merchant", "兑换", user="ghost")
    assert page.title == "商会兑换"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_catalog_rejects_an_item_that_is_not_a_consumable_or_material(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    equipment = next(
        entry["id"]
        for entry in json.loads((data / "items.json").read_text())
        if entry["kind"] == "equipment"
    )
    source = (data / "merchant_exchange.json").read_text()
    (data / "merchant_exchange.json").write_text(
        source.replace('"item": "spirit_food"', f'"item": "{equipment}"', 1)
    )
    with pytest.raises(ValueError, match="consumable or material"):
        Catalog.load(data)


def test_blank_exchange_argument_opens_the_page_instead_of_erroring(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 20)
    page = play("merchant", "兑换")
    assert page.title == "商会兑换"
    assert "灵粮补给" in page.text()


def test_empty_catalog_data_is_rejected(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    (data / "merchant_exchange.json").write_text("[]")
    with pytest.raises(ValueError, match="empty or duplicate|needs at least one"):
        Catalog.load(data)


def test_page_lists_offers_costs_and_balance(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 20)
    page = play("merchant", "兑换")
    assert "累计 20 · 已兑 0 · 可用 20" in page.text()
    assert "灵粮补给" in page.text() and "声望 8" in page.text()
    assert "蕴灵丹匣" in page.text() and "本周 2/2" in page.text()
    commands = [link.command for link in page.inline_commands]
    assert "灵宠商会 兑换 灵粮补给" in commands
    assert "灵宠商会 兑换 血脉精华匣" not in commands  # costs 24 > 20
    assert page.inline_commands[-1].command == "灵宠商会"
    assert page.commands == ("灵宠背包", "灵宠目标", "灵宠帮助")


def test_exchange_spends_available_but_never_lifetime_reputation(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 20)
    offer = first_offer(game)
    before_items = items(game[1])
    reply = play("merchant", "兑换 灵粮补给", op="exchange-food")
    assert "灵粮 ×3 已入包" in reply.text()
    assert items(game[1])["spirit_food"] == before_items["spirit_food"] + 3
    assert spent_row(game) == 8
    assert rep_row(game) == 20
    assert purchase_row(game, offer) == 1
    assert rep_row(game) - spent_row(game) == 12


def test_spending_does_not_relock_the_high_tier_commissions(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 60)
    play("merchant", "兑换 灵粮补给", op="exchange-at-gate")
    assert rep_row(game) == 60
    assert rep_row(game) - spent_row(game) == 52
    # The lifetime total still reads 60, so the wider pool remains reachable.
    assert len([entry for entry in game[0].content.commissions.values() if entry.min_rep <= rep_row(game)]) == 10


def test_weekly_limit_resets_on_the_next_beijing_week(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 100)
    for index in range(5):
        play("merchant", "兑换 灵粮补给", op=f"exchange-{index}")
    with pytest.raises(GameError, match="本周已兑完"):
        play("merchant", "兑换 灵粮补给", op="exchange-over")
    assert purchase_row(game, first_offer(game)) == 5
    # Next day is still the same week: the weekly cap remains.
    with pytest.raises(GameError, match="本周已兑完"):
        play("merchant", "兑换 灵粮补给", op="exchange-next-day", now=NOW + DAY)
    play("merchant", "兑换 灵粮补给", op="exchange-next-week", now=NOW + WEEK)
    assert purchase_row(game, first_offer(game), now=NOW + WEEK) == 1


def test_insufficient_balance_and_bad_arguments_write_nothing(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 7)
    before = state(game[1])
    with pytest.raises(GameError, match="可用声望不足"):
        play("merchant", "兑换 灵粮补给", op="poor")
    for argument in ("不存在", "0", "99", "灵粮补给 2"):
        with pytest.raises(GameError, match="未找到|超出"):
            play("merchant", f"兑换 {argument}", op=f"bad-{argument}")
    assert state(game[1]) == before


def test_same_operation_replays_without_double_settling(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    first = play("merchant", "兑换 灵粮补给", op="exchange-same")
    stones = player(game[1])["stones"]
    again = play("merchant", "兑换 灵粮补给", op="exchange-same")
    assert again.text() == first.text()
    assert spent_row(game) == 8
    assert purchase_row(game, first_offer(game)) == 1
    assert player(game[1])["stones"] == stones


def test_duplicate_exchange_stacks_the_same_item(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    before = items(game[1])["spirit_food"]
    play("merchant", "兑换 灵粮补给", op="exchange-stack-a")
    play("merchant", "兑换 灵粮补给", op="exchange-stack-b")
    assert items(game[1])["spirit_food"] == before + 6
    assert spent_row(game) == 16
    assert purchase_row(game, first_offer(game)) == 2


def test_exchange_survives_a_restart(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    play("merchant", "兑换 灵粮补给", op="exchange-persist")
    reopened = Store(game[1].path)
    reopened.initialize()
    from nonebot_plugin_spirit_pet.application.game import Game
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "merchant", "兑换", "restart-exchange", NOW)
    assert "累计 40 · 已兑 8 · 可用 32" in page.text()
    assert "本周 4/5" in page.text()


def test_pages_are_read_only(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    before = state(game[1])
    play("merchant", "兑换")
    assert state(game[1]) == before


def test_exchange_has_no_side_effects_beyond_spent_stock_and_item(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    before = state(game[1])
    play("merchant", "兑换 灵粮补给", op="exchange-clean")
    after = state(game[1])
    assert after["players"] == before["players"]
    assert after["pets"] == before["pets"]
    assert after["battle_records"] == before["battle_records"]
    added = [row for row in after["quest_progress"] if row not in before["quest_progress"]]
    assert {row["quest_id"] for row in added} == {
        "merchant_spent", merchant_exchange._buy_key("food_pack", NOW),
    }
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'stat_%'") == []


def test_missing_item_definition_refuses_without_spending(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 40)
    content = game[0].content
    content.merchant_exchange["food_pack"] = content.merchant_exchange["food_pack"].model_copy(
        update={"item": "missing_item"}
    )
    before = state(game[1])
    with pytest.raises(GameError, match="物品定义缺失"):
        play("merchant", "兑换 灵粮补给", op="missing-item")
    assert state(game[1]) == before


def test_main_page_shows_available_and_exchange_link(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 20, spent=8)
    page = play("merchant")
    assert "商会声望：20（累计）· 可用 12" in page.text()
    link = next(link for link in page.inline_commands if link.command == "灵宠商会 兑换")
    assert page.lines[link.line] == "可用声望可在商会兑换灵粮、材料与丹药。"
    assert handlers._parse("灵宠商会 兑换") == ("merchant", "兑换")
    assert handlers._parse("灵宠商会 兑换 灵粮补给") == ("merchant", "兑换 灵粮补给")


def test_help_and_objective_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "灵物与灵术")
    assert "灵宠商会 兑换：查看声望兑换项" in guide.text()
    assert "灵宠商会 兑换 名称：用可用声望兑换" in guide.text()
    assert "商会：声望 0 · 今日已交 0/3" in play("objectives").text()


def test_native_buttons_and_inline_links_are_disjoint(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 20)
    page = play("merchant", "兑换")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}
