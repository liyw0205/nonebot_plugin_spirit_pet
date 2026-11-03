"""灵宠集市求购: standing buy orders, escrowed stones, filling, cancel and expiry."""

import re
import sqlite3
from contextlib import closing
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.market_content import MarketRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import market
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema24, legacy_schema25

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def account(game, play, user="u1", species="青鸾"):
    play("adopt", species, user=user)


def grant_items(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def bids(game):
    return sql(game[1], "SELECT * FROM market_bids ORDER BY bid_id")


def bid_sales(game):
    return sql(game[1], "SELECT * FROM market_bid_sales ORDER BY bid_id")


def two(game, play, stones=5000):
    account(game, play, "u1")
    account(game, play, "u2")
    set_stones(game, stones, "u1")
    set_stones(game, stones, "u2")


def bid(play, item, amount, price, user="u1", op=None, now=NOW):
    return play("market", f"求购 {item} {amount} {price}", user=user, op=op, now=now)


def fill(play, bid_id, user="u2", op=None, now=NOW):
    return play("market", f"应单 {bid_id}", user=user, op=op, now=now)


def snapshot(game):
    """Every table a buy order should leave alone."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT * FROM market_listings"),
        sql(game[1], "SELECT * FROM market_sales"),
        sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
                     " ORDER BY user_id, quest_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
    )


# ---------------------------------------------------------------- rules

def test_market_rule_carries_the_buy_order_band(game):
    rule = game[0].content.market
    assert 1 <= rule.bid_days <= 30
    assert 1 <= rule.max_bid_quantity <= 99
    assert 1 <= rule.bid_slots <= 6
    assert rule.max_bid_quantity <= rule.max_quantity


def test_rule_model_rejects_bad_bid_bounds():
    base = {
        "listing_days": 3, "min_unit_price": 1, "max_unit_price": 50000, "max_quantity": 30,
        "sellable_kinds": ["material"], "stalls": [
            {"id": "s1", "name": "散铺", "unlock_cost": 0, "slots": 2, "fee_percent": 10},
        ],
        "bid_days": 3, "max_bid_quantity": 30, "bid_slots": 2, "trend_days": 7,
    }
    with pytest.raises(ValidationError):
        MarketRule.model_validate({**base, "bid_days": 0})
    with pytest.raises(ValidationError):
        MarketRule.model_validate({**base, "max_bid_quantity": 0})
    with pytest.raises(ValidationError):
        MarketRule.model_validate({**base, "bid_slots": 0})
    with pytest.raises(ValidationError, match="bid slots must not exceed the largest stall"):
        MarketRule.model_validate({**base, "bid_slots": 5})


def test_catalog_rejects_bids_larger_than_the_listing_cap(game):
    catalog = game[0].content
    bare = replace(
        catalog,
        market=catalog.market.model_copy(
            update={"max_bid_quantity": catalog.market.max_quantity + 1},
        ),
    )
    with pytest.raises(ValueError, match="buy orders must not exceed the listing quantity cap"):
        Catalog._validate_market(bare)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_the_bid_preview_and_writes_nothing(game, play):
    page = play("market", "求购", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert bids(game) == [] and bid_sales(game) == []


def test_a_fresh_player_sees_an_empty_bid_board(game, play):
    account(game, play, "u1")
    page = play("market", "求购")
    assert "在等货的求购 0 条" in page.text()
    assert "暂时没有人在收东西" in page.text()
    assert page.inline_commands[0].command == "灵宠集市 求购 "


# ---------------------------------------------------------------- place

def test_place_escrows_the_whole_price(game, play):
    two(game, play, stones=5000)
    reply = bid(play, "锻灵矿", 5, 90)
    assert reply.title == "求购已挂出"
    rows = bids(game)
    assert len(rows) == 1
    row = rows[0]
    assert (row["buyer_id"], row["item_id"]) == ("u1", "forge_ore")
    assert (row["quantity"], row["unit_price"], row["escrow"]) == (5, 90, 450)
    assert row["state"] == "active" and row["closed_at"] is None and row["seller_id"] is None
    assert row["expires_at"] == NOW + 3 * DAY
    assert player(game[1], "u1")["stones"] == 4550
    assert "已托管 450 灵石" in reply.text()


def test_place_refuses_bad_input_with_zero_writes(game, play):
    two(game, play, stones=5000)
    before = snapshot(game)
    cases = [
        ("求购 锻灵矿", "格式：灵宠集市 求购"),
        ("求购 锻灵矿 5", "格式：灵宠集市 求购"),
        ("求购 不存在的物品 5 90", "未找到该物品"),
        ("求购 破境丹 1 90", "不能求购"),
        ("求购 锻灵矿 0 90", "数量须为"),
        ("求购 锻灵矿 500 90", "数量须为"),
        ("求购 锻灵矿 abc 90", "数量须为"),
        ("求购 锻灵矿 5 0", "单价须为"),
        ("求购 锻灵矿 5 999999", "单价须为"),
    ]
    for arg, message in cases:
        with pytest.raises(GameError, match=message):
            play("market", arg)
    assert snapshot(game) == before
    assert bids(game) == []


def test_place_refuses_when_stones_are_short(game, play):
    two(game, play, stones=100)
    with pytest.raises(GameError, match="灵石不足"):
        bid(play, "锻灵矿", 5, 90)
    assert bids(game) == []
    assert player(game[1], "u1")["stones"] == 100


def test_bid_slots_cap_the_open_orders(game, play):
    two(game, play, stones=5000)
    rule = game[0].content.market
    for index in range(rule.bid_slots):
        assert bid(play, "锻灵矿", 1, 10).title == "求购已挂出"
    before = snapshot(game)
    with pytest.raises(GameError, match=f"同时最多挂 {rule.bid_slots} 条求购"):
        bid(play, "锻灵矿", 1, 10)
    assert snapshot(game) == before
    # cancelling one frees a slot
    market_id = bids(game)[0]["bid_id"]
    play("market", f"撤单 {market_id}")
    assert bid(play, "锻灵矿", 1, 10).title == "求购已挂出"


# ---------------------------------------------------------------- fill

def test_fill_moves_goods_and_pays_the_filler(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 10}, "u2")
    bid(play, "锻灵矿", 5, 90)
    reply = fill(play, bids(game)[0]["bid_id"])
    assert reply.title == "应单成功"
    row = bids(game)[0]
    assert row["state"] == "filled"
    assert row["seller_id"] == "u2" and row["closed_at"] == NOW
    # goods: filler -5, buyer +5
    assert items(game[1], "u2")["forge_ore"] == 5
    assert items(game[1], "u1")["forge_ore"] == 5
    # stones: buyer was already charged 450 at post time; filler nets 405 (10% tax)
    assert player(game[1], "u1")["stones"] == 4550
    assert player(game[1], "u2")["stones"] == 5405
    sale = bid_sales(game)[0]
    assert (sale["gross"], sale["fee"], sale["net"]) == (450, 45, 405)
    assert (sale["buyer_id"], sale["seller_id"]) == ("u1", "u2")


def test_fill_tax_follows_the_filler_stall_tier(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 10}, "u2")
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u2', ?, 4, 1)",
        (market.STALL_KEY,))
    bid(play, "锻灵矿", 4, 100)
    fill(play, bids(game)[0]["bid_id"])
    sale = bid_sales(game)[0]
    assert (sale["gross"], sale["fee"], sale["net"]) == (400, 16, 384)


def test_fill_refuses_the_obvious_cases_with_zero_writes(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    grant_items(game, {"forge_ore": 2}, "u2")   # not enough
    before = snapshot(game)
    with pytest.raises(GameError, match="不能应自己的求购"):
        fill(play, bid_id, user="u1")
    with pytest.raises(GameError, match="未找到这条求购"):
        fill(play, 9999)
    with pytest.raises(GameError, match="不足"):
        fill(play, bid_id)
    with pytest.raises(GameError, match="格式：灵宠集市 应单"):
        play("market", "应单 abc")
    assert snapshot(game) == before
    assert bids(game)[0]["state"] == "active"


def test_a_filled_order_cannot_be_filled_again(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 20}, "u2")
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    fill(play, bid_id)
    before = snapshot(game)
    with pytest.raises(GameError, match="已经不在等货"):
        fill(play, bid_id)
    assert snapshot(game) == before
    assert len(bid_sales(game)) == 1


# ---------------------------------------------------------------- cancel

def test_cancel_refunds_the_escrow(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    reply = play("market", f"撤单 {bid_id}")
    assert reply.title == "求购已撤回"
    row = bids(game)[0]
    assert row["state"] == "cancelled" and row["closed_at"] == NOW
    assert player(game[1], "u1")["stones"] == 5000
    before = snapshot(game)
    with pytest.raises(GameError, match="已经不在等货"):
        play("market", f"撤单 {bid_id}")
    assert snapshot(game) == before


def test_cancel_refuses_a_non_owner_and_unknown_id(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    before = snapshot(game)
    with pytest.raises(GameError, match="只能撤回自己挂的求购"):
        play("market", f"撤单 {bid_id}", user="u2")
    with pytest.raises(GameError, match="未找到这条求购"):
        play("market", "撤单 9999")
    with pytest.raises(GameError, match="格式：灵宠集市 撤单"):
        play("market", "撤单 nope")
    assert snapshot(game) == before


# ---------------------------------------------------------------- expiry

def test_expiry_refunds_once_and_clears_the_board(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    late = NOW + 4 * DAY
    page = play("market", "求购", now=late)
    assert "暂时没有人在收东西" in page.text()
    row = bids(game)[0]
    assert row["state"] == "expired" and row["closed_at"] == late
    assert player(game[1], "u1")["stones"] == 5000
    # a later page must not refund a second time
    play("market", "求购", now=late + DAY)
    assert player(game[1], "u1")["stones"] == 5000
    before = snapshot(game)
    with pytest.raises(GameError, match="未找到这条求购"):
        fill(play, bid_id, now=late + DAY)
    assert snapshot(game) == before


def test_any_market_page_sweeps_expired_bids(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    late = NOW + 4 * DAY
    play("market", "", now=late)          # the sell-side board
    assert bids(game)[0]["state"] == "expired"
    assert player(game[1], "u1")["stones"] == 5000


def test_an_order_for_a_removed_item_is_refunded_in_stones(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    # simulate content dropping the item: sweep must still refund the stones
    catalog = game[0].content
    stripped = replace(
        catalog, items={k: v for k, v in catalog.items.items() if k != "forge_ore"},
    )
    game[0].content = stripped
    play("market", "求购")
    assert bids(game)[0]["state"] == "expired"
    assert player(game[1], "u1")["stones"] == 5000


# ---------------------------------------------------------------- state

def test_buy_orders_survive_a_restart(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    restarted = Game(game[1], Config(), game[0].rng)
    page = restarted.execute("u2", "market", "求购", "restart", NOW)
    assert f"应单 {bid_id}" not in {link.command for link in page.inline_commands}
    assert "1 条" in page.text()


def test_replaying_one_operation_places_one_order(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90, op="once")
    bid(play, "锻灵矿", 5, 90, op="once")
    assert len(bids(game)) == 1
    grant_items(game, {"forge_ore": 10}, "u2")
    bid_id = bids(game)[0]["bid_id"]
    fill(play, bid_id, op="fill")
    fill(play, bid_id, op="fill")
    assert len(bid_sales(game)) == 1
    assert len(bids(game)) == 1


def test_buy_orders_move_only_their_own_resources(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 10}, "u2")
    before = snapshot(game)
    bid(play, "锻灵矿", 5, 90)
    fill(play, bids(game)[0]["bid_id"])
    after = snapshot(game)
    # the only tables that may change are the two bid tables and the purse/inventory
    assert after[2] == before[2]        # market_listings untouched
    assert after[3] == before[3]        # market_sales untouched
    assert after[4] == before[4]        # quest_progress (incl. stall tier) untouched
    assert after[5] == before[5]        # no battle records


# ---------------------------------------------------------------- surfaces

def test_help_and_parser_cover_buy_orders(game, play):
    two(game, play)
    assert _parse("灵宠集市 求购") == ("market", "求购")
    assert _parse("灵宠集市 求购 锻灵矿 5 90") == ("market", "求购 锻灵矿 5 90")
    assert _parse("灵宠集市 应单 3") == ("market", "应单 3")
    assert _parse("灵宠集市 撤单 3") == ("market", "撤单 3")
    assert _parse("灵宠集市 求购记录") == ("market", "求购记录")
    assert _parse("灵宠集市 求购记录 2") == ("market", "求购记录 2")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["血脉与道具"]}
    assert "灵宠集市 求购 物品 数量 单价" in rows
    assert "灵宠集市 应单 编号" in rows
    assert "灵宠集市 撤单 编号" in rows
    assert "灵宠集市 求购记录" in rows


def test_the_board_only_offers_a_fill_for_what_the_viewer_holds(game, play):
    two(game, play, stones=5000)
    bid(play, "锻灵矿", 5, 90)
    bid_id = bids(game)[0]["bid_id"]
    empty = play("market", "求购", user="u2")
    assert bid_id not in {link.command.rsplit(" ", 1)[-1] for link in empty.inline_commands}
    grant_items(game, {"forge_ore": 5}, "u2")
    stocked = play("market", "求购", user="u2")
    assert f"灵宠集市 应单 {bid_id}" in {link.command for link in stocked.inline_commands}
    # one's own order never offers a fill link
    own = play("market", "求购", user="u1")
    assert f"灵宠集市 应单 {bid_id}" not in {link.command for link in own.inline_commands}


def test_bid_records_show_both_sides(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 10}, "u2")
    bid(play, "锻灵矿", 5, 90)
    fill(play, bids(game)[0]["bid_id"])
    buyer_view = play("market", "求购记录")
    assert "收货 1 笔" in buyer_view.text() and "付出 450 灵石" in buyer_view.text()
    assert "收货 锻灵矿 ×5" in buyer_view.text()
    seller_view = play("market", "求购记录", user="u2")
    assert "交货 1 笔" in seller_view.text() and "实收 405 灵石" in seller_view.text()
    assert "交货 锻灵矿 ×5" in seller_view.text()


def test_objectives_row_reports_open_buy_orders(game, play):
    two(game, play, stones=5000)
    line = next(line for line in play("objectives").lines if line.startswith("集市："))
    assert line.endswith("求购 0/2")
    bid(play, "锻灵矿", 5, 90)
    line = next(line for line in play("objectives").lines if line.startswith("集市："))
    assert line.endswith("求购 1/2")


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    two(game, play, stones=5000)
    grant_items(game, {"forge_ore": 10}, "u2")
    bid(play, "锻灵矿", 5, 90)
    page = play("market", "求购", user="u2")
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
    rendered = _qq_segments(page, Config(spirit_pet_qq_mode="text"))[0]
    assert "应单（/灵宠集市 应单 1）" in rendered


def test_every_rendered_bid_link_reparses(game, play):
    two(game, play, stones=20000)
    grant_items(game, {"forge_ore": 40, "spirit_food": 40}, "u2")
    for index in range(game[0].content.market.bid_slots):
        bid(play, "锻灵矿", 1, 10 + index)
    for page_arg in ("", "求购", "我的", "记录", "求购记录"):
        page = play("market", page_arg, user="u2")
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None
    # a page past the end is refused rather than rendered empty
    with pytest.raises(GameError, match="共 1 页"):
        play("market", "求购 2", user="u2")


# ---------------------------------------------------------------- storage

def test_fresh_install_carries_both_bid_tables(game):
    connection = game[1].connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )
    }
    assert {"market_bids", "market_bid_sales", "market_bid_board", "market_bid_buyer",
            "market_bid_sales_seller", "market_bid_sales_buyer"} <= names
    connection.close()


def test_the_bid_table_rejects_an_inconsistent_row(game):
    with closing(game[1].connect()) as conn:
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('x', 0, NULL)")
        with pytest.raises(sqlite3.IntegrityError):   # escrow != quantity * price
            conn.execute(
                "INSERT INTO market_bids(buyer_id, item_id, quantity, unit_price, escrow,"
                " created_at, expires_at, state) VALUES ('x','forge_ore',5,90,999,1,2,'active')",
            )
        with pytest.raises(sqlite3.IntegrityError):   # filled without a seller
            conn.execute(
                "INSERT INTO market_bids(buyer_id, item_id, quantity, unit_price, escrow,"
                " created_at, expires_at, state, closed_at) VALUES ('x','forge_ore',5,90,450,1,2,'filled',3)",
            )
        with pytest.raises(sqlite3.IntegrityError):   # active but already closed
            conn.execute(
                "INSERT INTO market_bids(buyer_id, item_id, quantity, unit_price, escrow,"
                " created_at, expires_at, state, closed_at) VALUES ('x','forge_ore',5,90,450,1,2,'active',3)",
            )
        conn.rollback()


def test_schema24_database_walks_to_the_bid_tables(tmp_path):
    path = tmp_path / "old24.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema24(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=24")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 88, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"battle_shares", "market_bids", "market_bid_sales"} <= names
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 88
    assert list(tmp_path.glob("*schema24-backup*"))


def test_schema25_database_gains_the_bid_tables(tmp_path):
    path = tmp_path / "old25.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema25(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=25")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 99, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"market_bids", "market_bid_sales"} <= names
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 99
    assert list(tmp_path.glob("*schema25-backup*"))
