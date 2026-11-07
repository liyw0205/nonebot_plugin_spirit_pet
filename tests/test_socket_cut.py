"""宝石雕琢: the slot keeps its cut level and every level adds a fixed step."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import counters, sockets
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


# ------------------------------------------------------------- batched cut
def test_a_target_level_costs_the_sum_of_single_steps(game, play):
    pet_id = setup_socket(game, play)
    before = player(game[1])["stones"]
    gems = items(game[1])["gem_flame"]
    # 0 -> 3 in one command: 150 + 300 + 600 stones, 3 gems.
    reply = play("socket", "雕琢 灵饰 3", now=NOW)
    assert "雕琢至 +3" in reply.text()
    assert player(game[1])["stones"] == before - 1050
    assert items(game[1])["gem_flame"] == gems - 3
    assert sockets.cut_level(context(game), pet_id, "charm") == 3
    assert rate(game, pet_id) == pytest.approx(0.20)


def test_the_no_target_form_keeps_single_step_behaviour(game, play):
    pet_id = setup_socket(game, play)
    before = player(game[1])["stones"]
    play("socket", "雕琢 灵饰", now=NOW)
    assert player(game[1])["stones"] == before - 150
    assert sockets.cut_level(context(game), pet_id, "charm") == 1


def test_a_batch_is_equivalent_to_repeated_single_cuts(game, play):
    """Three single cuts from a fresh state cost exactly what one 0->3 batch costs."""
    pet_id = setup_socket(game, play)
    batch_before = player(game[1])["stones"]
    play("socket", "雕琢 灵饰 3", now=NOW)
    batch_cost = batch_before - player(game[1])["stones"]

    # Rebuild a fresh identical state to price three single steps.
    play("adopt", "青鸾", user="u2", now=NOW)
    give(game[1], "spirit_bell", user="u2")
    play("equipment", "灵心铃", user="u2", now=NOW)
    give(game[1], "gem_flame", 4, user="u2")
    play("socket", "灵饰 赤炎石", user="u2", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u2'")
    single_before = sql(game[1], "SELECT stones FROM players WHERE user_id='u2'")[0]["stones"]
    for _ in range(3):
        play("socket", "雕琢 灵饰", user="u2", now=NOW)
    single_cost = single_before - sql(game[1], "SELECT stones FROM players WHERE user_id='u2'")[0]["stones"]
    assert batch_cost == single_cost


def test_partial_stones_refuse_a_batch_with_zero_writes(game, play):
    setup_socket(game, play)
    # Enough stones for one level (150) but not for the whole 0->2 batch (450).
    sql(game[1], "UPDATE players SET stones=449")
    before = snapshot(game)
    with pytest.raises(GameError, match="雕琢需要"):
        play("socket", "雕琢 灵饰 2", now=NOW)
    assert snapshot(game) == before


def test_partial_gems_refuse_a_batch_with_zero_writes(game, play):
    setup_socket(game, play)
    # Plenty of stones, but only two gems while a 0->3 batch needs three.
    sql(game[1], "UPDATE inventory SET quantity=2 WHERE item_id='gem_flame'")
    before = snapshot(game)
    with pytest.raises(GameError, match="雕琢需要"):
        play("socket", "雕琢 灵饰 3", now=NOW)
    assert snapshot(game) == before


def test_a_target_below_or_equal_to_current_is_refused(game, play):
    setup_socket(game, play)
    play("socket", "雕琢 灵饰", now=NOW)  # now +1
    before = snapshot(game)
    for target in ("1", "0"):
        with pytest.raises(GameError):  # "须更高" for 1, "须为 1-3" for 0; both refuse
            play("socket", f"雕琢 灵饰 {target}", now=NOW)
    assert snapshot(game) == before


def test_a_target_equal_to_the_current_level_names_the_higher_target_rule(game, play):
    setup_socket(game, play)
    play("socket", "雕琢 灵饰", now=NOW)  # +1
    with pytest.raises(GameError, match="目标等级须更高"):
        play("socket", "雕琢 灵饰 1", now=NOW)


def test_a_target_above_max_is_refused(game, play):
    setup_socket(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="目标等级须为"):
        play("socket", "雕琢 灵饰 4", now=NOW)
    assert snapshot(game) == before


def test_a_non_numeric_target_is_refused(game, play):
    setup_socket(game, play)
    with pytest.raises(GameError, match="目标等级须为"):
        play("socket", "雕琢 灵饰 满级", now=NOW)


def test_a_batch_bumps_the_counter_by_its_step_count(game, play):
    setup_socket(game, play)
    play("socket", "雕琢 灵饰 3", now=NOW)
    assert counters.value(context(game), "gem_cuts") == 3
