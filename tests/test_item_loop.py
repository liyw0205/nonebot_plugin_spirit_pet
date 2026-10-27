import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, sql

TEAM_HELP = "灵宠帮助 组队与派遣"


def markdown_links(message):
    segment = message["markdown"][0].data["markdown"]
    markdown = segment.content if hasattr(segment, "content") else segment["content"]
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def keyboard_commands(reply):
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    return buttons


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def priced(game):
    return [item for item in game[0].content.items.values() if item.price is not None]


def item_of(game, kind):
    return next(item for item in game[0].content.items.values() if item.kind == kind)


def stock(game, *item_ids):
    for item_id in item_ids:
        sql(
            game[1],
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,1) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+1",
            (item_id,),
        )


def test_shop_list_links_each_item_detail_on_its_own_row(game, play):
    listing = play("shop")
    selected = priced(game)[:5]
    assert listing.title == "山海灵坊 1/11"
    assert links(listing) == [
        (index, "查看详情", f"灵宠商店 {item.name}") for index, item in enumerate(selected)
    ]
    for link, item in zip(listing.inline_commands, selected):
        assert item.name in listing.lines[link.line]
    # Row details leave the button set; only pagination and the bag remain.
    assert listing.commands == ("灵宠商店 2", "灵宠背包", "灵宠特供")
    assert keyboard_commands(listing) == ["灵宠商店 2", "灵宠背包", "灵宠特供"]
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    assert markdown_links(message) == [
        ("查看详情", f"/灵宠商店 {item.name}") for item in selected
    ]


def test_shop_second_page_links_its_own_rows_and_keeps_both_page_buttons(game, play):
    listing = play("shop", "2")
    selected = priced(game)[5:10]
    assert listing.title == "山海灵坊 2/11"
    assert [command for _, _, command in links(listing)] == [
        f"灵宠商店 {item.name}" for item in selected
    ]
    assert listing.commands == ("灵宠商店 1", "灵宠商店 3", "灵宠背包", "灵宠特供")
    assert keyboard_commands(listing) == ["灵宠商店 1", "灵宠商店 3", "灵宠背包", "灵宠特供"]


def test_bag_groups_items_with_purpose_and_gated_actions(game, play):
    play("adopt", "青鸾")
    play("sign")
    bag = play("bag")
    assert bag.title == "乾坤袋"
    assert "消耗品" in bag.lines
    amount = items(game[1])["spirit_food"]
    food_line = next(
        index for index, line in enumerate(bag.lines) if line.startswith(f"灵粮：{amount}")
    )
    assert bag.lines[food_line] == f"灵粮：{amount} · 精力 +20，修为 +10，亲密 +5。"
    assert links(bag) == [(food_line, "喂养", "灵宠喂养")]
    # The page button for feeding is deduplicated into the row link on the keyboard.
    assert bag.commands == ("灵宠商店", "灵宠喂养", "灵宠进化")
    assert keyboard_commands(bag) == ["灵宠商店", "灵宠进化"]


def test_bag_hides_consumable_action_while_the_pet_is_away(game, play):
    play("adopt", "青鸾")
    play("sign")
    play("expedition_start", "采灵药")
    bag = play("bag")
    assert links(bag) == []
    assert keyboard_commands(bag) == ["灵宠商店", "灵宠喂养", "灵宠进化"]
    with pytest.raises(GameError):
        play("feed")


def test_bag_hides_energy_pill_action_while_energy_is_full(game, play):
    play("adopt", "青鸾")
    play("sign")
    play("buy", "回元丹 1")
    sql(game[1], "UPDATE pets SET energy=100")
    assert not any(command == "灵宠使用 回元丹 1" for _, _, command in links(play("bag")))
    sql(game[1], "UPDATE pets SET energy=40")
    bag = play("bag")
    pill_line = next(index for index, line in enumerate(bag.lines) if line.startswith("回元丹："))
    assert (pill_line, "使用", "灵宠使用 回元丹 1") in links(bag)
    # The row action is reachable as a link; the keyboard keeps only page actions.
    assert keyboard_commands(bag) == ["灵宠商店", "灵宠进化"]
    _, message = _qq_segments(bag, Config(spirit_pet_qq_mode="native"))
    assert ("使用", "/灵宠使用 回元丹 1") in markdown_links(message)


def test_bag_links_egg_hatching_only_while_the_roster_has_room(game, play):
    play("adopt", "青鸾")
    egg = item_of(game, "pet_egg")
    stock(game, egg.id)
    bag = play("bag")
    egg_line = next(
        index for index, line in enumerate(bag.lines) if line.startswith(f"{egg.name}：")
    )
    assert (egg_line, "孵化", f"灵宠使用 {egg.name} 1") in links(bag)
    game[0].config.spirit_pet_max_pets = 1
    assert not any(command == f"灵宠使用 {egg.name} 1" for _, _, command in links(play("bag")))


def test_bag_links_read_only_catalogs_for_gear_and_books_only(game, play):
    play("adopt", "青鸾")
    gear, book, material = item_of(game, "equipment"), item_of(game, "skill_book"), item_of(game, "material")
    stock(game, gear.id, book.id, material.id)
    bag = play("bag")
    commands = {command for _, _, command in links(bag)}
    assert f"灵宠装备图鉴 {game[0].content.equipment[gear.equipment_id].name}" in commands
    assert f"灵宠技能图鉴 {game[0].content.skills[book.skill_id].name}" in commands
    assert {"装备灵物", "灵术秘笈", "材料与丹药"} <= set(bag.lines)
    # Materials and breakthrough pills stay hint-only: no runnable entry is offered.
    assert not any(command.startswith(("灵宠进化", "灵宠突破")) for command in commands)
    assert not any(material.name in command for command in commands)
    assert material.name in " ".join(bag.lines)


def test_purchase_use_and_hatch_replies_carry_their_next_steps(game, play):
    play("adopt", "青鸾")
    play("sign")
    bought = play("buy", "灵粮 2")
    assert bought.commands == ("灵宠背包", "灵宠喂养", "灵宠商店")
    assert items(game[1])["spirit_food"] == 8
    fed = play("feed")
    assert fed.commands == ("灵宠背包", "灵宠喂养", "我的灵宠")
    gear = item_of(game, "equipment")
    sql(game[1], "UPDATE players SET stones=1000")
    assert play("buy", gear.name).commands == (
        "灵宠背包", f"灵宠装备图鉴 {game[0].content.equipment[gear.equipment_id].name}", "灵宠商店",
    )
    sql(game[1], "UPDATE pets SET energy=40")
    play("buy", "回元丹 1")
    used = play("use", "回元丹 1")
    assert used.commands == ("灵宠背包", "灵宠使用 回元丹 1", "我的灵宠")
    egg = item_of(game, "pet_egg")
    stock(game, egg.id)
    hatched = play("use", f"{egg.name} 1")
    assert hatched.title == "灵卵孵化" and "灵宠背包" in hatched.commands


def test_affinity_pill_is_sold_used_and_capped_at_full_affinity(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000")
    sql(game[1], "UPDATE pets SET affinity=0")
    detail = play("shop", "同心丹")
    assert detail.title == "山海灵坊 · 同心丹" and "售价：120 灵石" in detail.text()
    assert "灵宠购买 同心丹" in detail.commands
    assert play("buy", "同心丹 2").commands == (
        "灵宠背包", "灵宠使用 同心丹 1", "灵宠商店",
    )
    bag = play("bag")
    assert "同心丹：2 · 亲密 +20；亲密已满时不可使用。" in bag.lines
    assert "灵宠使用 同心丹 1" in {command for _, _, command in links(bag)}
    assert "亲密 +20" in play("use", "同心丹 1").text()
    assert pet(game[1])["affinity"] == 20
    sql(game[1], "UPDATE pets SET affinity=95")
    assert "亲密 +5" in play("use", "同心丹 1").text()
    assert pet(game[1])["affinity"] == 100
    with pytest.raises(GameError, match="属性已满"):
        play("use", "同心丹 1")
    assert not any(command == "灵宠使用 同心丹 1" for _, _, command in links(play("bag")))
