"""Daily featured shop contracts: rotation, discount, stock and daily persistence."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.shop_content import ShopOffer
from nonebot_plugin_spirit_pet.gameplay import daily_shop
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def account(play):
    play("adopt", "青鸾")


def offers_at(game, now=NOW):
    with game[1].connect() as conn:
        ctx = Context(
            Repository(conn), game[0].content, game[0].config, game[0].rng,
            "u1", now, "offers",
        )
        return daily_shop.offers(ctx)


def offer_rows(game, prefix="shop_offer_"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE ? ORDER BY quest_id",
        (f"{prefix}%",),
    )


def price_of(game, offer):
    item = game[0].content.items[offer.item]
    return daily_shop.discounted_price(offer, item)


def test_content_defines_nine_distinct_priced_offers(game):
    offers = list(game[0].content.shop_offers.values())
    assert len(offers) == 9
    assert len({offer.item for offer in offers}) == 9
    for offer in offers:
        item = game[0].content.items[offer.item]
        assert item.price is not None
        assert 1 <= offer.discount <= 50
        assert 1 <= offer.stock <= 9


def test_offer_model_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        ShopOffer(id="x", item="spirit_food", discount=0, stock=1)
    with pytest.raises(ValidationError):
        ShopOffer(id="x", item="spirit_food", discount=10, stock=0)


def test_content_validation_rejects_short_duplicate_or_unpriced_pools(game):
    content = game[0].content
    two = dict(list(content.shop_offers.items())[:2])
    with pytest.raises(ValueError, match="at least three offers"):
        replace(content, shop_offers=two).validate()
    offers = list(content.shop_offers.values())
    duplicate = {
        offers[0].id: offers[0],
        offers[1].id: offers[1].model_copy(update={"item": offers[0].item}),
        offers[2].id: offers[2],
    }
    with pytest.raises(ValueError, match="repeats an item"):
        replace(content, shop_offers=duplicate).validate()
    unpriced = next(item.id for item in content.items.values() if item.price is None)
    bad = {
        offers[0].id: offers[0].model_copy(update={"item": unpriced}),
        offers[1].id: offers[1],
        offers[2].id: offers[2],
    }
    with pytest.raises(ValueError, match="has no price"):
        replace(content, shop_offers=bad).validate()


def test_rotation_is_stable_within_a_day_and_moves_next_day(game):
    today = offers_at(game)
    assert today == offers_at(game)
    assert len(today) == len({offer.id for offer in today}) == 3
    tomorrow = offers_at(game, NOW + DAY)
    assert len(tomorrow) == 3
    assert {offer.id for offer in today} != {offer.id for offer in tomorrow}


def test_page_shows_discounts_stock_preview_and_row_links(game, play):
    account(play)
    page = play("daily_shop")
    today = offers_at(game)
    assert page.title == "灵宠特供"
    assert "每日按北京时间轮换三件" in page.text()
    for offer in today:
        item = game[0].content.items[offer.item]
        assert f"{item.name} · 原价 {item.price} → 特供 {price_of(game, offer)} 灵石" in page.text()
        assert f"今日 {offer.stock} 件，剩 {offer.stock} 件 · 已购 0" in page.text()
    tomorrow = offers_at(game, NOW + DAY)
    assert "明日预告：" + "、".join(game[0].content.items[o.item].name for o in tomorrow) in page.text()
    assert {link.command for link in page.inline_commands} == {
        f"灵宠特供 {game[0].content.items[offer.item].name}" for offer in today
    }
    assert all(link.line < len(page.lines) for link in page.inline_commands)


def test_unregistered_preview_does_not_create_an_account(game, play):
    page = play("daily_shop", user="u9")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_buy_pays_the_discounted_price_and_reduces_stock(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = next(offer for offer in offers_at(game) if offer.stock >= 2)
    item = game[0].content.items[offer.item]
    before = items(game[1]).get(item.id, 0)
    reply = play("daily_shop", f"{item.name} 1")
    assert reply.title == "灵坊特供"
    assert player(game[1])["stones"] == 100000 - price_of(game, offer)
    assert items(game[1])[item.id] == before + 1
    page = play("daily_shop")
    assert f"{item.name} · 原价 {item.price} → 特供 {price_of(game, offer)} 灵石" in page.text()
    assert f"今日 {offer.stock} 件，剩 {offer.stock - 1} 件 · 已购 1" in page.text()
    assert offer_rows(game) == [{
        "quest_id": f"shop_offer_{daily_shop.beijing_day(NOW)}_{offer.id}",
        "progress": 1,
    }]


def test_over_stock_and_sold_out_purchases_are_rejected_without_charging(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = offers_at(game)[0]
    item = game[0].content.items[offer.item]
    with pytest.raises(GameError, match=f"仅剩 {offer.stock} 件"):
        play("daily_shop", f"{item.name} {offer.stock + 1}")
    assert player(game[1])["stones"] == 100000
    assert items(game[1]).get(item.id, 0) == 0
    play("daily_shop", f"{item.name} {offer.stock}")
    with pytest.raises(GameError, match="已售罄"):
        play("daily_shop", f"{item.name} 1")
    assert player(game[1])["stones"] == 100000 - price_of(game, offer) * offer.stock
    page = play("daily_shop")
    assert f"{item.name} · 原价 {item.price} → 特供 {price_of(game, offer)} 灵石 · 今日 {offer.stock} 件，售罄 · 已购 {offer.stock}" in page.text()


def test_non_featured_unknown_and_malformed_requests_are_rejected(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    featured = {offer.id for offer in offers_at(game)}
    other = next(offer for offer in game[0].content.shop_offers.values() if offer.id not in featured)
    other_item = game[0].content.items[other.item]
    with pytest.raises(GameError, match="今日特供没有该物品"):
        play("daily_shop", f"{other_item.name} 1")
    with pytest.raises(GameError, match="今日特供没有该物品"):
        play("daily_shop", "并不存在的物品 1")
    with pytest.raises(GameError, match="道具名称 数量"):
        play("daily_shop", "灵粮 1 2")
    assert player(game[1])["stones"] == 100000
    assert offer_rows(game) == []


def test_insufficient_stones_rejects_before_any_mutation(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=0 WHERE user_id='u1'")
    offer = offers_at(game)[0]
    item = game[0].content.items[offer.item]
    with pytest.raises(GameError, match="灵石不足"):
        play("daily_shop", f"{item.name} 1")
    assert items(game[1]).get(item.id, 0) == 0
    assert offer_rows(game) == []


def test_next_day_restores_stock_under_a_new_credential(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    today = offers_at(game)
    overlapping = today[1]  # tomorrow's first offer with a one-entry shift
    item = game[0].content.items[overlapping.item]
    play("daily_shop", f"{item.name} {overlapping.stock}")
    with pytest.raises(GameError, match="已售罄"):
        play("daily_shop", f"{item.name} 1")
    reply = play("daily_shop", f"{item.name} 1", now=NOW + DAY)
    assert reply.title == "灵坊特供"
    assert "今日特供剩余" in reply.text()
    rows = offer_rows(game)
    assert len(rows) == 2
    assert rows[0]["quest_id"] != rows[1]["quest_id"]
    page = play("daily_shop", now=NOW + DAY)
    assert f"{item.name} · 原价 {item.price} → 特供 {price_of(game, overlapping)} 灵石 · 今日 {overlapping.stock} 件，剩 {overlapping.stock - 1} 件 · 已购 1" in page.text()


def test_bought_stock_persists_across_restart(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = next(offer for offer in offers_at(game) if offer.stock >= 2)
    item = game[0].content.items[offer.item]
    play("daily_shop", f"{item.name} 1")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "daily_shop", "", "restart-shop", NOW)
    assert f"今日 {offer.stock} 件，剩 {offer.stock - 1} 件 · 已购 1" in page.text()


def test_same_operation_replays_without_double_charge(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = offers_at(game)[0]
    item = game[0].content.items[offer.item]
    first = play("daily_shop", f"{item.name} 1", op="shop-once")
    again = play("daily_shop", f"{item.name} 1", op="shop-once")
    assert again.title == first.title and again.lines == first.lines
    assert items(game[1])[item.id] == 1
    assert player(game[1])["stones"] == 100000 - price_of(game, offer)
    assert offer_rows(game)[0]["progress"] == 1


def test_normal_shop_purchase_keeps_the_full_price(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = offers_at(game)[0]
    item = game[0].content.items[offer.item]
    play("buy", f"{item.name} 1")
    assert player(game[1])["stones"] == 100000 - item.price
    assert item.price > price_of(game, offer)


def test_shop_entry_help_and_native_payload(game, play):
    account(play)
    assert "灵宠特供" in play("help", "血脉与道具").text()
    shop = play("shop")
    assert "灵宠特供" in shop.commands
    page = play("daily_shop")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert buttons == set(page.commands)
    assert buttons & links == set()
    assert links == {
        f"灵宠特供 {game[0].content.items[offer.item].name}" for offer in offers_at(game)
    }
