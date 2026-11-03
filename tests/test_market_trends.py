"""灵宠行情: cleared-price bands read from the sale ledgers."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import market_trends

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400
ITEM = "锻灵矿"


def account(game, play, user="u1", species="青鸾"):
    play("adopt", species, user=user)


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def sell(game, play, price, quantity=1, seller="u1", buyer="u2", item=ITEM, now=NOW):
    """List and immediately buy, so the ledger row is produced by the real flow."""
    set_stones(game, 1_000_000, user=buyer)
    play("market", f"上架 {item} {quantity} {price}", user=seller, now=now)
    listing_id = sql(game[1], "SELECT MAX(listing_id) AS n FROM market_listings")[0]["n"]
    play("market", f"购买 {listing_id}", user=buyer, now=now)
    return listing_id


def sorted_detail(game, play, item=ITEM):
    return play("market", f"行情 {item}")


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT listing_id FROM market_listings ORDER BY listing_id"),
        sql(game[1], "SELECT listing_id FROM market_sales ORDER BY listing_id"),
        sql(game[1], "SELECT bid_id FROM market_bids ORDER BY bid_id"),
    )


# ---------------------------------------------------------------- rule

def test_the_window_is_wired_and_bounded(game):
    rule = game[0].content.market
    assert 1 <= rule.trend_days <= 30


def test_the_rule_model_rejects_out_of_range_windows():
    from nonebot_plugin_spirit_pet.domain.market_content import MarketRule

    base = {
        "listing_days": 3, "min_unit_price": 1, "max_unit_price": 50000, "max_quantity": 30,
        "sellable_kinds": ["material"], "bid_days": 3, "max_bid_quantity": 30, "bid_slots": 1,
        "stalls": [{"id": "s", "name": "摊", "unlock_cost": 0, "slots": 2, "fee_percent": 10}],
    }
    with pytest.raises(ValidationError):
        MarketRule.model_validate({**base, "trend_days": 0})
    with pytest.raises(ValidationError):
        MarketRule.model_validate({**base, "trend_days": 31})


# ---------------------------------------------------------------- median

def test_summary_uses_the_documented_middle_convention():
    assert market_trends.summary([100]) == (100, 100, 100)
    assert market_trends.summary([300, 100, 200]) == (100, 200, 300)
    # even count: integer average of the two middle prices
    assert market_trends.summary([400, 100, 300, 200]) == (100, 250, 400)
    assert market_trends.summary([100, 101]) == (100, 100, 101)


# ---------------------------------------------------------------- empty

def test_no_sales_says_so_instead_of_zero(game, play):
    account(game, play)
    page = play("market", "行情")
    assert "没有任何成交" in page.text()
    assert "0 灵石" not in page.text()


def test_an_item_without_sales_says_so(game, play):
    account(game, play)
    page = play("market", f"行情 {ITEM}")
    assert "没有任何成交" in page.text()
    assert "灵宠集市" in page.text()


def test_an_unregistered_player_can_read_the_board(game, play):
    page = play("market", "行情", user="ghost")
    assert "没有任何成交" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []


# ---------------------------------------------------------------- numbers

def test_a_single_sale_defines_the_band(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 3})
    sell(game, play, 100, 1)
    page = sorted_detail(game, play)
    assert "成交 1 笔" in page.text()
    assert "单价中位 100 · 最低 100 · 最高 100" in page.text()


def test_three_sales_report_the_median_not_the_mean(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    for price in (100, 200, 300):
        sell(game, play, price, 1)
    page = sorted_detail(game, play)
    assert "单价中位 200 · 最低 100 · 最高 300" in page.text()
    assert "成交 3 笔，共 3 件" in page.text()


def test_quantities_are_summed_separately_from_the_price_band(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 120, 2)
    sell(game, play, 140, 3)
    page = sorted_detail(game, play)
    assert "成交 2 笔，共 5 件" in page.text()


def test_the_detail_lists_the_most_recent_sales(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 100, 1, now=NOW - 2 * DAY)
    sell(game, play, 300, 1, now=NOW)
    text = sorted_detail(game, play).text()
    assert "挂单 · 300 灵石 × 1" in text
    assert "挂单 · 100 灵石 × 1" in text


# ---------------------------------------------------------------- window

def test_sales_outside_the_window_are_excluded(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 100, 1)
    sql(game[1], "UPDATE market_sales SET sold_at=?", (NOW - 8 * DAY,))
    page = sorted_detail(game, play)
    assert "没有任何成交" in page.text()


def test_a_sale_exactly_on_the_boundary_still_counts(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 100, 1)
    sql(game[1], "UPDATE market_sales SET sold_at=?", (NOW - 7 * DAY,))
    assert "成交 1 笔" in sorted_detail(game, play).text()


# ---------------------------------------------------------------- bids

def test_filled_buy_orders_reach_the_board(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 5}, user="u1")
    grant(game, {"forge_ore": 5}, user="u2")
    set_stones(game, 5000, user="u1")
    play("market", f"求购 {ITEM} 1 260", user="u1")
    bid_id = sql(game[1], "SELECT MAX(bid_id) AS n FROM market_bids")[0]["n"]
    play("market", f"应单 {bid_id}", user="u2")
    page = sorted_detail(game, play)
    assert "单价中位 260" in page.text()
    assert "求购 · 260 灵石 × 1" in page.text()
    assert "成交 1 笔" in page.text()


# ---------------------------------------------------------------- board

def test_the_board_lists_items_by_sample_count(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9, "bloodline_essence": 9})
    sell(game, play, 100, 1, item="锻灵矿")
    sell(game, play, 120, 1, item="锻灵矿")
    sell(game, play, 900, 1, item="血脉精华")
    text = play("market", "行情").text()
    lines = [line for line in text.split("\n") if "中位" in line]
    assert lines[0].startswith("锻灵矿")
    assert "成交 2 笔" in lines[0]
    assert lines[1].startswith("血脉精华")


def test_the_board_pages_and_refuses_an_over_range_page(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    names = ["锻灵矿", "血脉精华", "赤炎石", "玄岩壁", "风灵石", "生灵髓"]
    ids = {"锻灵矿": "forge_ore", "血脉精华": "bloodline_essence", "赤炎石": "gem_flame",
           "玄岩壁": "gem_ward", "风灵石": "gem_swift", "生灵髓": "gem_vital"}
    grant(game, {ids[name]: 2 for name in names})
    for name in names:
        sell(game, play, 100, 1, item=name)
    first = play("market", "行情")
    assert "第 1/2 页" in first.text()
    second = play("market", "行情 2")
    assert "第 2/2 页" in second.text()
    with pytest.raises(GameError, match="行情共 2 页"):
        play("market", "行情 3")


def test_an_unknown_item_is_refused_without_writing(game, play):
    account(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="未找到该物品"):
        play("market", "行情 不存在的灵物")
    assert snapshot(game) == before


def test_reading_the_board_writes_nothing(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 150, 1)
    before = snapshot(game)
    play("market", "行情")
    play("market", f"行情 {ITEM}")
    assert snapshot(game) == before


# ---------------------------------------------------------------- surfaces

def test_help_lists_the_board(game, play):
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["血脉与道具"]}
    assert "灵宠集市 行情" in rows
    assert "灵宠集市 行情 物品" in rows


def test_every_rendered_link_reparses(game, play):
    from nonebot_plugin_spirit_pet.adapters.handlers import _parse

    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 150, 1)
    for action in ("行情", f"行情 {ITEM}"):
        page = play("market", action)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    account(game, play, "u1")
    account(game, play, "u2", "玄狐")
    grant(game, {"forge_ore": 9})
    sell(game, play, 150, 1)
    page = play("market", "行情")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_the_onebot_text_page_spells_the_command(game, play):
    account(game, play)
    rendered = _qq_segments(play("market", "行情"), Config(spirit_pet_qq_mode="text"))[0]
    assert "【灵宠行情】" in rendered
    assert "（/灵宠集市 记录）" in rendered


def test_the_board_is_not_a_progress_track(game, play):
    """行情 is a lookup; the objectives page must not grow a line for it."""
    account(game, play)
    assert all(not line.startswith("行情") for line in play("objectives").lines)
