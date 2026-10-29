"""Pet tempering: egg/stone costs, caps, gating and the combat multiplier."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000


def stats(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "temper-stats")
        return combatant(ctx)


def set_stones(game, amount, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (amount, user))


def give_eggs(game, species_id, amount, user="u1"):
    item = f"egg_{species_id}"
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=?",
        (user, item, amount, amount),
    )


def add_pet(game, user, species, name, *, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, 0, 1, 0, 0, 0, 100, ?, ?)",
        (user, species, name, NOW, archived),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def seed_layers(game, pet_id, layers, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"temper_{pet_id}", layers),
    )


def layers(game, pet_id, user="u1"):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"temper_{pet_id}"),
    )
    return rows[0]["progress"] if rows else 0


def test_page_without_a_pet_is_read_only(game, play):
    page = play("temper", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_layers_stock_and_cost(game, play):
    play("adopt", "青鸾")
    give_eggs(game, "qingluan", 2)
    page = play("temper")
    assert "每层全属性 +1%，最多 10 层" in page.text()
    assert "青鸾 · 0 层（+0%）· 青鸾灵卵 2 枚 · 下一层 灵石 50 + 青鸾灵卵 1" in page.text()
    assert {link.command for link in page.inline_commands} == {"灵宠淬魂 青鸾"}


def test_page_hides_the_link_without_eggs_or_stones(game, play):
    play("adopt", "青鸾")
    page = play("temper")
    assert page.inline_commands == ()
    give_eggs(game, "qingluan", 1)
    set_stones(game, 10)
    page = play("temper")
    assert page.inline_commands == ()
    set_stones(game, 500)
    assert {link.command for link in play("temper").inline_commands} == {"灵宠淬魂 青鸾"}


def test_tempering_spends_stones_and_eggs_and_adds_layers(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 3)
    pet_id = pet(game[1])["pet_id"]
    reply = play("temper", "青鸾")
    assert "淬魂 +1 层：0 → 1 层，全属性 +1%" in reply.text()
    assert player(game[1])["stones"] == 450
    assert items(game[1])["egg_qingluan"] == 2
    assert layers(game, pet_id) == 1


def test_multiple_layers_are_paid_together(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 5)
    pet_id = pet(game[1])["pet_id"]
    reply = play("temper", "青鸾 3")
    assert "0 → 3 层，全属性 +3%" in reply.text()
    assert player(game[1])["stones"] == 350
    assert items(game[1])["egg_qingluan"] == 2
    assert layers(game, pet_id) == 3


def test_a_full_pet_is_refused(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 5)
    pet_id = pet(game[1])["pet_id"]
    seed_layers(game, pet_id, 10)
    with pytest.raises(GameError, match="已淬满"):
        play("temper", "青鸾")
    assert player(game[1])["stones"] == 500 and items(game[1])["egg_qingluan"] == 5
    page = play("temper")
    assert "青鸾 · 10 层（+10%）· 已满" in page.text()


def test_a_request_beyond_the_remaining_layers_is_refused(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 5)
    pet_id = pet(game[1])["pet_id"]
    seed_layers(game, pet_id, 8)
    with pytest.raises(GameError, match="最多还能淬 2 层"):
        play("temper", "青鸾 3")
    assert layers(game, pet_id) == 8
    assert player(game[1])["stones"] == 500


def test_short_resources_refuse_the_whole_request(game, play):
    play("adopt", "青鸾")
    set_stones(game, 40)
    give_eggs(game, "qingluan", 5)
    with pytest.raises(GameError, match="灵石不足"):
        play("temper", "青鸾")
    assert items(game[1])["egg_qingluan"] == 5 and player(game[1])["stones"] == 40

    set_stones(game, 500)
    give_eggs(game, "qingluan", 0)
    with pytest.raises(GameError, match="灵卵不足"):
        play("temper", "青鸾")
    assert player(game[1])["stones"] == 500


def test_eggs_of_another_species_are_not_consumed(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "xuanhu", 5)
    with pytest.raises(GameError, match="青鸾灵卵不足"):
        play("temper", "青鸾")
    assert items(game[1])["egg_xuanhu"] == 5
    assert player(game[1])["stones"] == 500


def test_unknown_archived_and_expedition_pets_are_refused(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 5)
    with pytest.raises(GameError, match="没有找到"):
        play("temper", "无名的伙伴")
    add_pet(game, "u1", "xuanhu", "旧友", archived=1)
    with pytest.raises(GameError, match="封存"):
        play("temper", "旧友")
    pet_id = pet(game[1])["pet_id"]
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("temper", "青鸾")
    assert layers(game, pet_id) == 0


def test_the_bonus_applies_to_all_four_stats_for_that_pet_only(game, play):
    play("adopt", "青鸾")
    base = stats(game).stats
    pet_id = pet(game[1])["pet_id"]
    seed_layers(game, pet_id, 1)
    one = stats(game).stats
    assert one.hp == int(base.hp * 1.01 + 0.5)
    assert one.attack == int(base.attack * 1.01 + 0.5)
    assert one.defense == int(base.defense * 1.01 + 0.5)
    assert one.speed == int(base.speed * 1.01 + 0.5)

    fox = add_pet(game, "u1", "xuanhu", "小狐")
    seed_layers(game, pet_id, 10)
    ten = stats(game).stats
    assert ten.attack == int(base.attack * 1.10 + 0.5)
    assert layers(game, fox) == 0


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 3)
    play("temper", "青鸾 2")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "temper", "", "restart-temper", NOW)
    assert "青鸾 · 2 层（+2%）" in page.text()


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    set_stones(game, 500)
    give_eggs(game, "qingluan", 3)
    first = play("temper", "青鸾", op="temper-op")
    again = play("temper", "青鸾", op="temper-op")
    assert again.text() == first.text()
    assert items(game[1])["egg_qingluan"] == 2


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "成长")
    assert "灵宠淬魂" in guide.text()
    assert "淬魂：累计 0 层 · 最高 0 层" in play("objectives").text()
    set_stones(game, 500)
    give_eggs(game, "qingluan", 3)
    play("temper", "青鸾 2")
    assert "淬魂：累计 2 层 · 最高 2 层" in play("objectives").text()
    assert handlers._parse("灵宠淬魂") == ("temper", "")
    assert handlers._parse("灵宠淬魂 青鸾 2") == ("temper", "青鸾 2")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    give_eggs(game, "qingluan", 2)
    page = play("temper")
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
