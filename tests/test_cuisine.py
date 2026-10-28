"""Spirit kitchen: cuisine levels, daily heat, meals and roster banquets."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86400


def add_items(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def dish_rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'cuisine_dish_%'"
        " ORDER BY quest_id",
        (user,),
    )


def heat_row(game, user="u1", day=None):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"cuisine_heat_{day or beijing_day(NOW)}"),
    )
    return rows[0]["progress"] if rows else 0


def set_heat(game, used, user="u1", day=None):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"cuisine_heat_{day or beijing_day(NOW)}", used),
    )


def seed_mastery(game, *dish_ids, user="u1"):
    for dish_id in dish_ids:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (user, f"cuisine_dish_{dish_id}"),
        )


def add_pet(game, user, species, name, *, realm=1):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp,"
        " affinity, energy, energy_updated, archived) VALUES (?, ?, ?, ?, 5, 0, 0, 0, 10, ?, 0)",
        (user, species, name, realm, NOW),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def send_away(game, pet_id, user="u1"):
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot)"
        " VALUES (?, ?, 'herb_gathering', '采灵药', ?, ?, ?, 'running', '{}')",
        (user, pet_id, f"away-{user}-{pet_id}", NOW, NOW + 3600),
    )


def low_energy(game, value=10, user="u1"):
    sql(
        game[1],
        "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?",
        (value, NOW, user),
    )


def test_content_defines_six_dishes_with_two_output_shapes(game):
    dishes = list(game[0].content.cuisine.values())
    assert len(dishes) == 6
    assert sorted({dish.level for dish in dishes}) == [1, 2, 3, 4, 5]
    for dish in dishes:
        assert 1 <= dish.heat <= 5
        assert dish.stones > 0 or dish.ingredients
        assert all(item in game[0].content.items for item in dish.ingredients)
        if dish.item is not None:
            assert dish.effects is None
            item = game[0].content.items[dish.item]
            assert item.kind == "consumable" and item.price is None
            assert item.effects.energy or item.effects.exp or item.effects.affinity
        else:
            assert dish.effects is not None
            assert dish.effects.energy + dish.effects.exp + dish.effects.affinity > 0


def test_unregistered_page_is_read_only(game, play):
    page = play("cuisine", user="u9")
    assert page.title == "灵宠膳房"
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT * FROM players") == []


def test_page_lists_states_and_links_only_cookable_rows(game, play):
    play("adopt", "青鸾")
    page = play("cuisine")
    assert "厨艺 1 级 · 已掌握 0/6 道 · 今日灶火 6/6" in page.text()
    assert "灵米粥 · 1 级 · 灶火 1 · 单膳" in page.text()
    assert "可烹饪" in page.text()
    assert "百草羹 · 2 级" in page.text() and "未解锁（需厨艺 2 级）" in page.text()
    assert [(link.line, link.command) for link in page.inline_commands] == [
        (1, "灵宠烹饪 灵米粥"),
    ]
    assert page.commands == ("灵宠膳房", "灵宠背包", "灵宠目标", "我的灵宠")
    assert not {link.command for link in page.inline_commands} & set(page.commands)
    with pytest.raises(GameError, match="不接受参数"):
        play("cuisine", "1")


def test_cook_single_meal_adds_items_and_spends_heat(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    before_stones = player(game[1])["stones"]
    before_food = items(game[1])["spirit_food"]
    reply = play("cuisine_cook", "灵米粥 2", op="cook-rice")
    assert "灵米粥 ×2 已入乾坤袋" in reply.text()
    assert "厨艺提升：1 级 → 2 级" in reply.text()
    assert player(game[1])["stones"] == before_stones - 20
    assert items(game[1])["spirit_food"] == before_food - 4
    assert items(game[1])["meal_rice"] == 2
    assert heat_row(game) == 2
    assert dish_rows(game) == [{"quest_id": "cuisine_dish_rice_porridge", "progress": 2}]
    page = play("cuisine")
    assert "厨艺 2 级 · 已掌握 1/6 道 · 今日灶火 4/6" in page.text()


def test_cooking_the_same_dish_again_does_not_raise_the_level(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 8})
    play("cuisine_cook", "灵米粥")
    second = play("cuisine_cook", "灵米粥")
    assert "厨艺提升" not in second.text()
    assert "厨艺 2 级 · 已掌握 1/6 道" in second.text()
    assert dish_rows(game)[0]["progress"] == 2


def test_level_gate_rejects_before_any_cost(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 2, "forge_ore": 1})
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="厨艺不足"):
        play("cuisine_cook", "百草羹")
    assert player(game[1])["stones"] == stones
    assert items(game[1])["forge_ore"] == 1
    assert heat_row(game) == 0
    assert dish_rows(game) == []


def test_insufficient_materials_reject_the_whole_order(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE inventory SET quantity=1 WHERE user_id='u1' AND item_id='spirit_food'")
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="灵粮不足"):
        play("cuisine_cook", "灵米粥")
    assert player(game[1])["stones"] == stones
    assert items(game[1])["spirit_food"] == 1
    assert heat_row(game) == 0
    assert "meal_rice" not in items(game[1])


def test_heat_budget_blocks_and_resets_the_next_day(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 8})
    set_heat(game, 6)
    assert "灶火不足" in play("cuisine").text()
    with pytest.raises(GameError, match="今日灶火不足"):
        play("cuisine_cook", "灵米粥")
    assert dish_rows(game) == []

    later = NOW + DAY
    page = play("cuisine", now=later)
    assert "今日灶火 6/6" in page.text()
    reply = play("cuisine_cook", "灵米粥", now=later)
    assert "灶火 -1" in reply.text()
    assert heat_row(game, day=beijing_day(later)) == 1


def test_quantity_over_the_heat_budget_is_rejected(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 30})
    with pytest.raises(GameError, match="今日灶火不足"):
        play("cuisine_cook", "灵米粥 9")
    with pytest.raises(GameError, match="数量须为 1-9"):
        play("cuisine_cook", "灵米粥 0")
    assert heat_row(game) == 0


def test_banquet_feeds_every_owned_pet_but_skips_expeditions(game, play):
    play("adopt", "青鸾")
    second = add_pet(game, "u1", "xuanhu", "小玄")
    seed_mastery(game, "rice_porridge", "herb_soup")
    add_items(game, {"spirit_food": 10, "bloodline_essence": 3})
    away = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id")
    send_away(game, second)
    low_energy(game)
    before = sql(game[1], "SELECT pet_id, energy, exp, affinity FROM pets WHERE user_id='u1' ORDER BY pet_id")

    reply = play("cuisine_cook", "百兽羹", op="banquet")
    assert "百兽羹已开席：1 只伙伴" in reply.text()
    assert "精力+15 修为+10 亲密+12" in reply.text()
    after = sql(game[1], "SELECT pet_id, energy, exp, affinity FROM pets WHERE user_id='u1' ORDER BY pet_id")
    home, out = before[0], before[1]
    assert after[0]["energy"] == home["energy"] + 15
    assert after[0]["exp"] == home["exp"] + 10
    assert after[0]["affinity"] == home["affinity"] + 12
    assert after[1] == out
    assert "meal_rice" not in items(game[1])
    assert heat_row(game) == 3


def test_banquet_rejects_when_every_pet_is_away(game, play):
    play("adopt", "青鸾")
    seed_mastery(game, "rice_porridge", "herb_soup")
    add_items(game, {"spirit_food": 6, "bloodline_essence": 2})
    only = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    send_away(game, only)
    with pytest.raises(GameError, match="没有可宴请的伙伴"):
        play("cuisine_cook", "百兽羹")
    assert heat_row(game) == 0


def test_banquet_caps_energy_and_affinity(game, play):
    play("adopt", "青鸾")
    seed_mastery(game, "rice_porridge", "herb_soup")
    add_items(game, {"spirit_food": 6, "bloodline_essence": 2})
    sql(game[1], "UPDATE pets SET energy=95, affinity=95, energy_updated=?", (NOW,))
    play("cuisine_cook", "百兽羹")
    row = sql(game[1], "SELECT energy, affinity FROM pets WHERE user_id='u1'")[0]
    assert row == {"energy": 100, "affinity": 100}


def test_crafted_meal_is_not_sold_or_recycled(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    play("cuisine_cook", "灵米粥")
    with pytest.raises(GameError, match="未找到"):
        play("shop", "灵米粥")
    with pytest.raises(GameError, match="不在灵坊出售"):
        play("recycle", "灵米粥")
    assert items(game[1])["meal_rice"] == 1


def test_crafted_meal_works_through_the_existing_use_path(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    play("cuisine_cook", "灵米粥")
    low_energy(game)
    reply = play("use", "灵米粥")
    assert "灵米粥 -1，精力 +45，修为 +20，亲密 +10" in reply.text()
    row = sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE user_id='u1'")[0]
    assert row == {"energy": 55, "exp": 20, "affinity": 10}
    assert items(game[1]).get("meal_rice", 0) == 0


def test_same_operation_replays_without_double_charging(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    first = play("cuisine_cook", "灵米粥", op="cuisine-replay")
    state = (player(game[1]), items(game[1]), heat_row(game), dish_rows(game))
    assert play("cuisine_cook", "灵米粥", now=NOW + 1, op="cuisine-replay") == first
    assert (player(game[1]), items(game[1]), heat_row(game), dish_rows(game)) == state
    second = play("cuisine_cook", "灵米粥", now=NOW + 1, op="cuisine-replay-2")
    assert "已入乾坤袋" in second.text()
    assert heat_row(game) == state[2] + 1


def test_state_persists_across_restart(game, play):
    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    play("cuisine_cook", "灵米粥")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "cuisine", "", "restart-cuisine", NOW)
    assert "厨艺 2 级 · 已掌握 1/6 道 · 今日灶火 5/6" in page.text()


def test_help_objectives_and_parse_contract(game, play):
    guide = play("help", "成长")
    assert "灵宠膳房" in guide.text() and "灵宠烹饪" in guide.text()
    assert handlers._parse("灵宠膳房") == ("cuisine", "")
    assert handlers._parse("灵宠烹饪 灵米粥 2") == ("cuisine_cook", "灵米粥 2")

    play("adopt", "青鸾")
    add_items(game, {"spirit_food": 6})
    play("cuisine_cook", "灵米粥")
    hub = play("objectives")
    assert "灵膳：灶火 5/6 · 已掌握 1/6 道 · 厨艺 2 级" in hub.text()
    link = next(link for link in hub.inline_commands if link.command == "灵宠膳房")
    assert hub.lines[link.line].startswith("灵膳：")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("cuisine")
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
