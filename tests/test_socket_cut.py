"""宝石雕琢: the slot keeps its cut level and every level adds a fixed step."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import sockets
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "cut")


def give(store, item_id, amount=1, user="u1"):
    sql(
        store,
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def setup_socket(game, play):
    play("adopt", "青鸾", now=NOW)
    give(game[1], "spirit_bell")
    play("equipment", "灵心铃", now=NOW)
    give(game[1], "gem_flame", 4)
    play("socket", "灵饰 赤炎石", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    return pet(game[1])["pet_id"]


def rate(game, pet_id):
    return sockets.rates(context(game), pet_id)["attack"]


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, stones FROM players"),
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY item_id"),
        sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY quest_id"),
    )


def test_each_cut_adds_four_percentage_points(game, play):
    pet_id = setup_socket(game, play)
    assert rate(game, pet_id) == pytest.approx(0.08)
    play("socket", "雕琢 灵饰", now=NOW)
    assert rate(game, pet_id) == pytest.approx(0.12)
    play("socket", "雕琢 灵饰", now=NOW)
    assert rate(game, pet_id) == pytest.approx(0.16)
    play("socket", "雕琢 灵饰", now=NOW)
    assert rate(game, pet_id) == pytest.approx(0.20)


def test_each_cut_charges_stones_and_one_gem(game, play):
    pet_id = setup_socket(game, play)
    before = player(game[1])["stones"]
    gems = items(game[1])["gem_flame"]
    play("socket", "雕琢 灵饰", now=NOW)
    assert player(game[1])["stones"] == before - 150
    assert items(game[1])["gem_flame"] == gems - 1
    assert sockets.cut_level(context(game), pet_id, "charm") == 1


def test_the_cut_stays_on_the_slot_after_removing_the_gem(game, play):
    pet_id = setup_socket(game, play)
    play("socket", "雕琢 灵饰", now=NOW)
    play("socket", "卸下 灵饰", now=NOW)
    assert sockets.cut_level(context(game), pet_id, "charm") == 1
    give(game[1], "gem_ward", 1)
    play("socket", "灵饰 玄岩壁", now=NOW)
    assert sockets.rates(context(game), pet_id)["defense"] == pytest.approx(0.12)


def test_max_level_is_refused(game, play):
    pet_id = setup_socket(game, play)
    for _ in range(3):
        play("socket", "雕琢 灵饰", now=NOW)
    with pytest.raises(GameError, match="无法再提升"):
        play("socket", "雕琢 灵饰", now=NOW)
    assert sockets.cut_level(context(game), pet_id, "charm") == 3


def test_short_stones_leave_everything_untouched(game, play):
    setup_socket(game, play)
    sql(game[1], "UPDATE players SET stones=10")
    before = snapshot(game)
    with pytest.raises(GameError, match="雕琢需要"):
        play("socket", "雕琢 灵饰", now=NOW)
    assert snapshot(game) == before


def test_short_gems_leave_everything_untouched(game, play):
    setup_socket(game, play)
    sql(game[1], "DELETE FROM inventory WHERE item_id='gem_flame'")
    before = snapshot(game)
    with pytest.raises(GameError, match="雕琢需要"):
        play("socket", "雕琢 灵饰", now=NOW)
    assert snapshot(game) == before


def test_an_empty_slot_cannot_be_cut(game, play):
    play("adopt", "青鸾", now=NOW)
    give(game[1], "spirit_bell")
    play("equipment", "灵心铃", now=NOW)
    with pytest.raises(GameError, match="没有宝石"):
        play("socket", "雕琢 灵饰", now=NOW)


def test_page_shows_the_next_cut_and_its_price(game, play):
    setup_socket(game, play)
    page = play("socket", now=NOW)
    assert "雕琢 0/3" in page.text()
    assert "150 灵石" in page.text()
    assert any(link.command == "灵宠镶嵌 雕琢 灵饰" for link in page.inline_commands)


def test_unregistered_page_is_read_only(game, play):
    page = play("socket", user="u9", now=NOW)
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='u9'") == []
