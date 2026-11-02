"""Sect contribution exchange: spend contribution, keep the rank, weekly stock."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import sect_exchange, sects
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def ready(game, play, *, contribution=500):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁", op="join")
    sect = sects.current(ctx_of(game))
    sects._set(ctx_of(game), f"{sects.CONTRIB}{sect.id}", contribution)
    return sect


def owned(game, item_id, user="u1"):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user, item_id))
    return rows[0]["quantity"] if rows else 0


def offers(game):
    return sorted(game[0].content.sect_exchange.values(), key=lambda offer: offer.cost)


def test_content_declares_five_distinct_offers(game):
    rows = offers(game)
    assert len(rows) == 5
    assert len({row.item_id for row in rows}) == 5
    for row in rows:
        assert row.cost >= 1 and 1 <= row.weekly_limit <= 10
        assert row.item_id in game[0].content.items


def test_page_without_a_pet_is_read_only(game, play):
    page = play("sect_exchange", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_requires_a_sect(game, play):
    play("adopt", "青鸾")
    page = play("sect_exchange")
    assert "尚未拜入师门" in page.text()
    assert page.commands == ("灵宠师门", "灵宠帮助")


def test_page_lists_costs_stock_and_balance(game, play):
    sect = ready(game, play, contribution=500)
    page = play("sect_exchange")
    assert "可用贡献 500" in page.text()
    assert "本周剩余" in page.text()
    assert any(link.command.startswith("灵宠贡献 兑换 ") for link in page.inline_commands)


def test_the_sect_page_shows_the_spendable_balance(game, play):
    ready(game, play, contribution=300)
    text = play("sect").text()
    assert "可用贡献 300" in text


def test_redeeming_deducts_balance_but_keeps_the_rank(game, play):
    sect = ready(game, play, contribution=500)
    before_rank = sects.rank_of(ctx_of(game), sect)
    offer = offers(game)[0]
    before_items = owned(game, offer.item_id)
    reply = play("sect_exchange", f"兑换 {offer.name}", op="redeem")
    assert reply.title == "兑换完成"
    ctx = ctx_of(game)
    assert sects.contribution(ctx, sect) == 500
    assert sect_exchange.balance(ctx, sect) == 500 - offer.cost
    assert sects.rank_of(ctx, sect).rank == before_rank.rank
    assert owned(game, offer.item_id) == before_items + 1


def test_batch_redeem_scales_cost_and_items(game, play):
    sect = ready(game, play, contribution=500)
    offer = offers(game)[0]
    before_items = owned(game, offer.item_id)
    play("sect_exchange", f"兑换 {offer.name} 2", op="batch")
    ctx = ctx_of(game)
    assert sect_exchange.balance(ctx, sect) == 500 - offer.cost * 2
    assert owned(game, offer.item_id) == before_items + 2


def test_insufficient_balance_writes_nothing(game, play):
    sect = ready(game, play, contribution=10)
    offer = offers(game)[-1]
    with pytest.raises(GameError, match="可用贡献不足"):
        play("sect_exchange", f"兑换 {offer.name}")
    ctx = ctx_of(game)
    assert sect_exchange.spent(ctx, sect) == 0
    assert owned(game, offer.item_id) == 0


def test_weekly_stock_is_enforced(game, play):
    sect = ready(game, play, contribution=2000)
    offer = next(entry for entry in offers(game) if entry.weekly_limit == 1)
    play("sect_exchange", f"兑换 {offer.name}", op="stock-1")
    with pytest.raises(GameError, match="本周库存不足"):
        play("sect_exchange", f"兑换 {offer.name}", op="stock-2")


def test_weekly_stock_resets_but_the_spent_total_persists(game, play):
    sect = ready(game, play, contribution=2000)
    offer = next(entry for entry in offers(game) if entry.weekly_limit == 1)
    play("sect_exchange", f"兑换 {offer.name}", op="week-1")
    later = NOW + WEEK
    assert sect_exchange.bought_this_week(ctx_of(game, later), offer) == 0
    reply = play("sect_exchange", f"兑换 {offer.name}", op="week-2", now=later)
    assert reply.title == "兑换完成"
    ctx = ctx_of(game, later)
    assert sect_exchange.spent(ctx, sect) == offer.cost * 2


def test_amount_over_the_remaining_stock_is_refused(game, play):
    ready(game, play, contribution=2000)
    offer = next(entry for entry in offers(game) if entry.weekly_limit == 2)
    with pytest.raises(GameError, match="本周库存不足"):
        play("sect_exchange", f"兑换 {offer.name} 3")


def test_amount_above_five_is_refused(game, play):
    ready(game, play, contribution=5000)
    offer = offers(game)[0]
    with pytest.raises(GameError, match="数量"):
        play("sect_exchange", f"兑换 {offer.name} 6")


def test_unjoined_and_unknown_offers_are_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未拜入师门"):
        play("sect_exchange", "兑换 灵粮")
    play("sect", "拜入 剑阁", op="join-late")
    with pytest.raises(GameError, match="未找到该内容"):
        play("sect_exchange", "兑换 不存在的物品")
    with pytest.raises(GameError, match="格式"):
        play("sect_exchange", "随便写")


def test_redeeming_an_item_not_in_the_shop_is_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("sect_exchange", "兑换 灵米粥")


def test_replaying_a_redeem_is_identical(game, play):
    ready(game, play, contribution=500)
    offer = offers(game)[0]
    first = play("sect_exchange", f"兑换 {offer.name}", op="replay")
    ctx = ctx_of(game)
    spent = sect_exchange.spent(ctx, sects.current(ctx))
    again = play("sect_exchange", f"兑换 {offer.name}", op="replay")
    assert again.text() == first.text()
    assert sect_exchange.spent(ctx_of(game), sects.current(ctx_of(game))) == spent


def test_objective_help_and_parse(game, play):
    ready(game, play, contribution=250)
    assert "贡献兑换：可用贡献 250" in play("objectives").text()
    assert "灵宠贡献" in play("help", "成长").text()
    assert handlers._parse("灵宠贡献") == ("sect_exchange", "")
    assert handlers._parse("灵宠贡献 兑换 灵粮 2") == ("sect_exchange", "兑换 灵粮 2")


def test_spent_total_survives_a_restart(game, play):
    sect = ready(game, play, contribution=400)
    offer = offers(game)[0]
    play("sect_exchange", f"兑换 {offer.name}", op="persist")
    ctx = ctx_of(game)
    assert sect_exchange.spent(ctx, sect) == offer.cost
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?", (f"sect_spent_{sect.id}",))
    assert rows and rows[0]["progress"] == offer.cost


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play, contribution=500)
    page = play("sect_exchange")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
