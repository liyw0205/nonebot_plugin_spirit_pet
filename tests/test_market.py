"""灵宠集市: escrowed listings, player-to-player sales, stall tiers and expiry."""

import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.market_content import MarketRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import market
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema21

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


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


def listings(game):
    return sql(game[1], "SELECT * FROM market_listings ORDER BY listing_id")


def sales(game):
    return sql(game[1], "SELECT * FROM market_sales ORDER BY listing_id")


def stall_row(game, user="u1"):
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (user, market.STALL_KEY))
    return rows[0]["progress"] if rows else None


def snapshot(game):
    """Domain tables only: the operation cache is expected to move on every call."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT listing_id, state, quantity, buyer_id FROM market_listings ORDER BY listing_id"),
        sql(game[1], "SELECT listing_id FROM market_sales ORDER BY listing_id"),
    )


def sell(play, amount=5, price=90, user="u1", op=None):
    return play("market", f"上架 锻灵矿 {amount} {price}", user=user, op=op)


def test_content_market_ladder_is_ordered_and_reachable(game):
    content = game[0].content
    stalls = content.market.stalls
    assert len(stalls) == 4
    assert stalls[0].unlock_cost == 0
    assert [stall.slots for stall in stalls] == sorted(stall.slots for stall in stalls)
    assert [stall.fee_percent for stall in stalls] == sorted(
        (stall.fee_percent for stall in stalls), reverse=True
    )
    assert content.market.sellable_kinds == ["material", "consumable"]
    for kind in content.market.sellable_kinds:
        assert any(item.kind == kind for item in content.items.values())


@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit_market(directory, change):
    path = directory / "market.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_a_paid_first_stall_is_rejected(content_dir):
    edit_market(content_dir, lambda data: data["stalls"][0].update({"unlock_cost": 100}))
    with pytest.raises(ValueError, match="first market stall must be free"):
        Catalog.load(content_dir)


def test_shrinking_slots_or_rising_tax_is_rejected(content_dir):
    edit_market(content_dir, lambda data: data["stalls"][1].update({"slots": 1}))
    with pytest.raises(ValueError, match="slots must strictly increase"):
        Catalog.load(content_dir)


def test_rising_tax_is_rejected(content_dir):
    edit_market(content_dir, lambda data: data["stalls"][2].update({"fee_percent": 12}))
    with pytest.raises(ValueError, match="fees must not increase"):
        Catalog.load(content_dir)


def test_market_rule_rejects_bad_bounds_and_duplicate_kinds():
    base = {
        "listing_days": 3,
        "min_unit_price": 10,
        "max_unit_price": 5,
        "max_quantity": 30,
        "sellable_kinds": ["material"],
        "stalls": [{"id": "stall_free", "name": "散铺", "unlock_cost": 0, "slots": 2, "fee_percent": 10}],
        "bid_days": 3,
        "max_bid_quantity": 30,
        "bid_slots": 2,
    }
    with pytest.raises(ValidationError, match="minimum unit price"):
        MarketRule.model_validate(base)
    base["min_unit_price"] = 1
    base["sellable_kinds"] = ["material", "material"]
    with pytest.raises(ValidationError, match="sellable kinds must be unique"):
        MarketRule.model_validate(base)
    base["sellable_kinds"] = ["material"]
    base["bid_slots"] = 5
    with pytest.raises(ValidationError, match="bid slots must not exceed the largest stall"):
        MarketRule.model_validate(base)


def test_unregistered_market_is_read_only_and_creates_no_player(game, play):
    reply = play("market", user="u9")
    assert reply.title == "灵宠集市"
    assert "尚未结契" in reply.text()
    assert reply.commands == ("灵宠帮助",)
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert listings(game) == []


def test_listing_escrows_the_stack_and_appears_on_the_board(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 10})
    set_stones(game, 5000)
    set_stones(game, 3000, user="u2")

    reply = sell(play)
    assert reply.title == "上架成功"
    assert items(game[1])["forge_ore"] == 5
    row = listings(game)[0]
    assert (row["seller_id"], row["item_id"], row["quantity"], row["unit_price"]) == (
        "u1", "forge_ore", 5, 90,
    )
    assert row["state"] == "active" and row["expires_at"] == NOW + 3 * DAY
    assert row["created_at"] == NOW and row["closed_at"] is None and row["buyer_id"] is None

    board = play("market", user="u2")
    assert "锻灵矿 ×5 · 单价 90 · 总价 450 灵石" in board.text()
    assert f"购买（灵宠集市 购买 {row['listing_id']}）" in board.text()
    assert "自家摊位" not in board.text()


def test_listing_refusals_write_nothing(game, play):
    account(game, play)
    grant(game, {"forge_ore": 20, "spirit_food": 5})
    set_stones(game, 5000)
    before = snapshot(game)

    with pytest.raises(GameError, match="未找到该物品"):
        play("market", "上架 不存在的灵物 1 10")
    with pytest.raises(GameError, match="只有材料和丹药"):
        book = next(item for item in game[0].content.items.values() if item.kind == "skill_book")
        grant(game, {book.id: 1})
        before = snapshot(game)
        play("market", f"上架 {book.name} 1 10")
    with pytest.raises(GameError, match="数量须为"):
        play("market", "上架 锻灵矿 0 10")
    with pytest.raises(GameError, match="数量须为"):
        play("market", "上架 锻灵矿 31 10")
    with pytest.raises(GameError, match="单价须为"):
        play("market", "上架 锻灵矿 1 0")
    with pytest.raises(GameError, match="单价须为"):
        play("market", "上架 锻灵矿 1 50001")
    with pytest.raises(GameError, match="不足"):
        play("market", "上架 锻灵矿 30 10")
    with pytest.raises(GameError, match="格式"):
        play("market", "上架 锻灵矿 1")
    assert snapshot(game) == before

    assert sell(play, op="fill-1").title == "上架成功"
    assert sell(play, amount=5, op="fill-2").title == "上架成功"
    before_full = snapshot(game)
    with pytest.raises(GameError, match="陈列位"):
        sell(play, op="fill-3")
    assert snapshot(game) == before_full


def test_sale_moves_items_stones_and_ledger_with_the_stall_tax(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    set_stones(game, 1000)
    set_stones(game, 3000, user="u2")
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    reply = play("market", f"购买 {listing_id}", user="u2")
    assert reply.title == "购买成功"
    assert "付 450 灵石" in reply.text()
    assert player(game[1], "u1")["stones"] == 1000 + 405
    assert player(game[1], "u2")["stones"] == 3000 - 450
    assert items(game[1], "u2")["forge_ore"] == 5
    assert items(game[1], "u1").get("forge_ore", 0) == 0
    sale = sales(game)[0]
    assert (sale["gross"], sale["fee"], sale["net"], sale["quantity"]) == (450, 45, 405, 5)
    assert sale["seller_id"] == "u1" and sale["buyer_id"] == "u2"
    row = listings(game)[0]
    assert row["state"] == "sold" and row["buyer_id"] == "u2" and row["closed_at"] == NOW
    ledger = play("market", "记录")
    assert "累计成交 1 笔 · 实收 405 灵石 · 缴税 45 灵石" in ledger.text()
    assert "锻灵矿 ×5 · 总价 450 · 税 45 · 实收 405" in ledger.text()


def test_buy_refuses_own_listing_short_stones_and_a_sold_listing(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    set_stones(game, 1000)
    set_stones(game, 3000, user="u2")
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    with pytest.raises(GameError, match="自家摊位"):
        play("market", f"购买 {listing_id}", user="u1")
    set_stones(game, 100, user="u2")
    before = snapshot(game)
    with pytest.raises(GameError, match="灵石不足"):
        play("market", f"购买 {listing_id}", user="u2")
    assert snapshot(game) == before
    set_stones(game, 3000, user="u2")
    play("market", f"购买 {listing_id}", user="u2")
    with pytest.raises(GameError, match="不在售"):
        play("market", f"购买 {listing_id}", user="u2")
    with pytest.raises(GameError, match="未找到这件陈列"):
        play("market", "购买 999999", user="u2")


def test_cancel_returns_the_escrow_and_refuses_a_foreign_listing(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    with pytest.raises(GameError, match="只能下架自家"):
        play("market", f"下架 {listing_id}", user="u2")
    reply = play("market", f"下架 {listing_id}")
    assert reply.title == "下架成功"
    assert items(game[1])["forge_ore"] == 5
    assert listings(game)[0]["state"] == "cancelled"
    with pytest.raises(GameError, match="不在售"):
        play("market", f"下架 {listing_id}")


def test_expired_listing_returns_the_escrow_and_leaves_the_board(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    set_stones(game, 3000, user="u2")
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    later = NOW + 4 * DAY
    board = play("market", user="u2", now=later)
    assert "集市暂时空空如也" in board.text()
    row = listings(game)[0]
    assert row["state"] == "expired" and row["closed_at"] == later
    assert items(game[1])["forge_ore"] == 5
    with pytest.raises(GameError, match="未找到这件陈列"):
        play("market", f"购买 {listing_id}", user="u2", now=later)


def test_a_retired_item_listing_is_closed_without_paying_the_escrow(game, play):
    account(game, play)
    grant(game, {"forge_ore": 1})
    sell(play, amount=1)
    sql(game[1], "UPDATE market_listings SET item_id='ghost_item'")

    page = play("market")
    assert "集市暂时空空如也" in page.text()
    row = listings(game)[0]
    assert row["state"] == "expired"
    assert items(game[1]).get("ghost_item") is None


def test_upgrade_charges_once_and_raises_the_cap(game, play):
    account(game, play)
    set_stones(game, 5000)
    reply = play("market", "升级")
    assert reply.title == "摊位升级"
    assert player(game[1], "u1")["stones"] == 5000 - 800
    assert stall_row(game) == 2
    page = play("market", "我的")
    assert "摊位：长摊 · 陈列 0/4 · 成交税 8%" in page.text()
    assert "下一级 铺面：2400 灵石" in page.text()


def test_upgrade_refuses_without_stones_and_writes_nothing(game, play):
    account(game, play)
    set_stones(game, 100)
    before = snapshot(game)
    with pytest.raises(GameError, match="灵石不足"):
        play("market", "升级")
    assert snapshot(game) == before
    assert stall_row(game) is None


def test_upgrade_reaches_the_top_and_stops(game, play):
    account(game, play)
    set_stones(game, 100_000)
    play("market", "升级")
    play("market", "升级")
    play("market", "升级")
    assert stall_row(game) == 4
    assert player(game[1], "u1")["stones"] == 100_000 - 800 - 2400 - 6000
    with pytest.raises(GameError, match="最高等级"):
        play("market", "升级")
    assert stall_row(game) == 4


def test_replaying_one_operation_returns_the_same_reply_and_settles_once(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    set_stones(game, 1000)
    set_stones(game, 3000, user="u2")
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    first = play("market", f"购买 {listing_id}", user="u2", op="settle-once")
    after_first = (player(game[1], "u1")["stones"], player(game[1], "u2")["stones"], len(sales(game)))
    again = play("market", f"购买 {listing_id}", user="u2", op="settle-once")
    assert again.text() == first.text()
    assert (player(game[1], "u1")["stones"], player(game[1], "u2")["stones"], len(sales(game))) == after_first
    with pytest.raises(GameError, match="不在售"):
        play("market", f"购买 {listing_id}", user="u2", op="settle-twice")


def test_market_state_survives_a_new_game_instance(game, play):
    account(game, play)
    grant(game, {"forge_ore": 5})
    sell(play)
    listing_id = listings(game)[0]["listing_id"]

    restarted = Game(game[1], Config())
    page = restarted.execute("u1", "market", "我的", "restart-page", NOW)
    assert f"#{listing_id} 锻灵矿 ×5" in page.text()
    assert "成交税 10%" in page.text()


def test_help_objectives_and_parse_contract(game, play):
    account(game, play)
    guide = play("help", "血脉与道具")
    assert "灵宠集市" in guide.text() and "上架" in guide.text()
    objectives = play("objectives")
    assert "集市：散铺 · 在售 0/2" in objectives.text()
    assert handlers._parse("灵宠集市") == ("market", "")
    assert handlers._parse("灵宠集市 上架 锻灵矿 5 90") == ("market", "上架 锻灵矿 5 90")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5})
    set_stones(game, 3000, user="u2")
    sell(play)
    page = play("market", user="u2")
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
    assert f"（灵宠集市 购买 {listings(game)[0]['listing_id']}）" in page.text()


def test_board_pages_five_listings_at_a_time(game, play):
    account(game, play)
    account(game, play, user="u2", species="玄狐")
    set_stones(game, 100_000)
    set_stones(game, 100_000, user="u2")
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 4, 1)",
        (market.STALL_KEY,),
    )
    sellable = [
        item for item in game[0].content.items.values()
        if item.kind in game[0].content.market.sellable_kinds
    ]
    for item in sellable[:6]:
        grant(game, {item.id: 1})
        play("market", f"上架 {item.name} 1 10", op=f"page-{item.id}")

    first = play("market", user="u2")
    second = play("market", "2", user="u2")
    assert first.text().count("购买（灵宠集市 购买") == 5
    assert second.text().count("购买（灵宠集市 购买") == 1
    assert "灵宠集市 2" in first.commands
    assert "灵宠集市 1" in second.commands
    assert "第 1/2 页。" in first.text() and "第 2/2 页。" in second.text()


def test_schema_21_migrates_to_22_with_market_tables_and_a_backup(tmp_path):
    path = tmp_path / "legacy.db"
    schema = legacy_schema21(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "market_listings" not in schema and "market_sales" not in schema
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=21")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('u1', 777)")
        conn.execute(
            "INSERT INTO pets(user_id, species_id, name, energy_updated)"
            " VALUES ('u1', 'qingluan', '青鸾', ?)", (NOW,),
        )
        conn.commit()

    Store(path).initialize()

    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"market_listings", "market_sales"} <= tables
        assert {"market_listing_board", "market_listing_seller", "market_sales_seller"} <= indexes
        assert conn.execute("SELECT stones FROM players WHERE user_id='u1'").fetchone()[0] == 777
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute(
            "INSERT INTO market_listings(seller_id, item_id, quantity, unit_price, created_at,"
            " expires_at, state) VALUES ('u1', 'forge_ore', 1, 10, ?, ?, 'active')",
            (NOW, NOW + DAY),
        )
    backups = list(Path(tmp_path).glob("legacy.db.schema21-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 21
