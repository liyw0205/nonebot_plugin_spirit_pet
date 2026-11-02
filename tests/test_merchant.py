"""灵宠商会: daily commission board, reputation gates, delivery and the all-clear bonus."""

import itertools
import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.commission_content import Commission
from nonebot_plugin_spirit_pet.domain.content import MerchantRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import merchant
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def rule(game):
    return game[0].content.rules.merchant


def board(game, now=NOW, reputation=0):
    """The expected board, derived from content and the day ordinal."""
    entries = sorted(
        (entry for entry in game[0].content.commissions.values() if entry.min_rep <= reputation),
        key=lambda entry: entry.id,
    )
    start = merchant.day_ordinal(now) % len(entries)
    return [entries[(start + index) % len(entries)] for index in range(rule(game).offers_per_day)]


def grant_items(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def seed_rep(game, value, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'merchant_rep', ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, value),
    )


def rep_row(game, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='merchant_rep'", (user,),
    )
    return rows[0]["progress"] if rows else None


def marker(game, entry, user="u1", now=NOW):
    return sql(
        game[1],
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, merchant.order_key(now, entry)),
    )


def test_content_board_is_complete_and_priced_below_shop_value(game):
    commissions = game[0].content.commissions
    assert len(commissions) == 10
    assert sum(1 for entry in commissions.values() if entry.min_rep == 0) == 4
    for entry in commissions.values():
        assert entry.items and entry.stones > 0 and entry.rep > 0
        worth = sum(
            (game[0].content.items[item_id].price or 0) * amount
            for item_id, amount in entry.items.items()
        )
        assert entry.stones < worth, entry.id


def test_merchant_rule_rejects_an_empty_bonus_and_bad_offer_counts():
    with pytest.raises(ValidationError, match="all-clear bonus"):
        MerchantRule.model_validate({"offers_per_day": 3, "all_clear_stones": 0, "all_clear_rep": 0})
    with pytest.raises(ValidationError):
        MerchantRule.model_validate({"offers_per_day": 9, "all_clear_stones": 60, "all_clear_rep": 4})


def test_catalog_rejects_unknown_items_arbitrage_and_an_unreachable_board(game, tmp_path):
    import shutil

    from nonebot_plugin_spirit_pet.content.catalog import Catalog

    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "commissions.json").read_text()

    unknown = source.replace('"spirit_food": 5', '"no_such_item": 5', 1)
    (data / "commissions.json").write_text(unknown)
    with pytest.raises(ValueError, match="unknown commission"):
        Catalog.load(data)

    (data / "commissions.json").write_text(source.replace('"stones": 55', '"stones": 999', 1))
    with pytest.raises(ValueError, match="goods worth"):
        Catalog.load(data)

    (data / "commissions.json").write_text(source.replace('"min_rep": 0', '"min_rep": 5', 4))
    with pytest.raises(ValueError, match="open to a new merchant"):
        Catalog.load(data)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("merchant", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert rep_row(game, "ghost") is None


def test_the_board_is_stable_within_a_day_and_rotates_next_day(game, play):
    play("adopt", "青鸾")
    names = [entry.name for entry in board(game)]
    first = play("merchant")
    again = play("merchant")
    assert first.text() == again.text()
    assert [entry.name for entry in board(game, NOW + DAY)] != names


def test_the_board_only_offers_orders_this_reputation_can_take(game, play):
    play("adopt", "青鸾")
    page = play("merchant")
    for entry in board(game):
        assert entry.min_rep == 0
        assert entry.name in page.text()
    seed_rep(game, 60)
    widened = play("merchant")
    offered = [entry for entry in board(game, reputation=60)]
    assert all(entry.min_rep <= 60 for entry in offered)
    assert any(entry.name in widened.text() for entry in offered)


def test_delivering_consumes_the_goods_and_pays_stones_and_reputation(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, {item_id: amount for item_id, amount in entry.items.items()})
    before_items = items(game[1])
    before = player(game[1])["stones"]
    reply = play("merchant", f"交付 {entry.name}")
    assert reply.title == "委托完成"
    assert player(game[1])["stones"] == before + entry.stones
    after_items = items(game[1])
    for item_id, amount in entry.items.items():
        assert after_items.get(item_id, 0) == before_items.get(item_id, 0) - amount
    assert rep_row(game) == entry.rep
    assert marker(game, entry)[0]["claimed"] == 1
    page = play("merchant")
    assert f"{entry.name}" in page.text() and "今日已交" in page.text()


def test_a_delivery_by_index_works_and_repeats_are_refused(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, {item_id: amount for item_id, amount in entry.items.items()}, )
    play("merchant", "交付 1")
    assert marker(game, entry)
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="已经交过"):
        play("merchant", f"交付 {entry.name}")
    assert player(game[1])["stones"] == stones


def test_refusals_write_nothing(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    with pytest.raises(GameError, match="物品不足"):
        play("merchant", f"交付 {entry.name}")
    with pytest.raises(GameError, match="今天没有上架"):
        play("merchant", "交付 丹药急单")
    with pytest.raises(GameError, match="未找到该委托"):
        play("merchant", "交付 不存在的委托")
    with pytest.raises(GameError, match="序号超出范围"):
        play("merchant", "交付 9")
    with pytest.raises(GameError, match="格式"):
        play("merchant", "交付")
    assert rep_row(game) is None
    assert marker(game, entry) == []
    assert items(game[1]).get(list(entry.items)[0], 0) < entry.items[list(entry.items)[0]]


def test_the_all_clear_bonus_pays_once_per_day(game, play):
    play("adopt", "青鸾")
    offered = board(game)
    for entry in offered:
        grant_items(game, dict(entry.items))
    before = player(game[1])["stones"]
    for index in range(1, len(offered) + 1):
        play("merchant", f"交付 {index}")
    expected = sum(entry.stones for entry in offered) + rule(game).all_clear_stones
    assert player(game[1])["stones"] == before + expected
    assert rep_row(game) == sum(entry.rep for entry in offered) + rule(game).all_clear_rep
    bonus = sql(
        game[1],
        "SELECT claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (merchant.bonus_key(NOW),),
    )
    assert bonus[0]["claimed"] == 1
    # A second delivery on the next day can earn the bonus again.
    next_day_board = board(game, NOW + DAY, reputation=rep_row(game))
    for entry in next_day_board:
        grant_items(game, dict(entry.items))
    for index in range(1, len(next_day_board) + 1):
        play("merchant", f"交付 {index}", now=NOW + DAY)
    second = sql(
        game[1],
        "SELECT claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (merchant.bonus_key(NOW + DAY),),
    )
    assert second and second[0]["claimed"] == 1


def test_reputation_is_cumulative_and_gates_the_wider_pool(game, play):
    play("adopt", "青鸾")
    seed_rep(game, 58)
    entry = board(game, reputation=58)[0]
    grant_items(game, dict(entry.items))
    play("merchant", f"交付 {entry.name}")
    assert rep_row(game) == 58 + entry.rep
    assert rep_row(game) >= 60
    # The wider pool is now reachable: every high-tier order is listed as eligible.
    eligible = [item for item in game[0].content.commissions.values() if item.min_rep <= rep_row(game)]
    assert len(eligible) == 10


def test_same_operation_replays_without_double_settling(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, dict(entry.items))
    first = play("merchant", f"交付 {entry.name}", op="merchant-op")
    stones = player(game[1])["stones"]
    again = play("merchant", f"交付 {entry.name}", op="merchant-op")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones
    assert rep_row(game) == entry.rep


def test_the_board_survives_a_restart(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, dict(entry.items))
    play("merchant", f"交付 {entry.name}")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "merchant", "", "restart-merchant", NOW)
    assert f"商会声望：{entry.rep}" in page.text()
    assert "今日已交" in page.text()


def test_no_battle_record_or_counter_is_written(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, dict(entry.items))
    play("merchant", f"交付 {entry.name}")
    assert sql(game[1], "SELECT * FROM battle_records") == []
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'stat_%'") == []


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "灵物与灵术")
    assert "灵宠商会" in guide.text() and "交付" in guide.text()
    objectives = play("objectives")
    assert "商会：声望 0 · 今日已交 0/3" in objectives.text()
    assert handlers._parse("灵宠商会") == ("merchant", "")
    assert handlers._parse("灵宠商会 交付 粮车押运") == ("merchant", "交付 粮车押运")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    entry = board(game)[0]
    grant_items(game, dict(entry.items))
    page = play("merchant")
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
    assert f"（灵宠商会 交付 {entry.name}）" in page.text()
