import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import ACTIONS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.pagination import paginate

from .support import items, pet, player, sql

LISTS = (
    ("shop", "灵宠商店", "山海灵坊", "items", "："),
    ("skill_catalog", "灵宠技能图鉴", "万法灵谱", "skills", "："),
    ("equipment_catalog", "灵宠装备图鉴", "灵物图鉴", "equipment", " · "),
)


def entries(game, collection):
    values = list(getattr(game[0].content, collection).values())
    return [entry for entry in values if entry.price is not None] if collection == "items" else values


@pytest.mark.parametrize("action,command,title,collection,separator", LISTS)
def test_all_pages_cover_every_entry_exactly_once(game, play, action, command, title, collection, separator):
    expected = entries(game, collection)
    total = (len(expected) + 4) // 5
    found = []
    for number in range(1, total + 1):
        reply = play(action, str(number))
        assert reply.title == f"{title} {number}/{total}"
        assert 1 <= len(reply.lines) <= 5
        found.extend(line.split(separator, 1)[0] for line in reply.lines)
        assert (f"{command} {number - 1}" in reply.commands) == (number > 1)
        assert (f"{command} {number + 1}" in reply.commands) == (number < total)
        assert len(reply.commands) <= 8
        assert all(_parse(value) is not None for value in reply.commands)
    assert found == [entry.name for entry in expected]
    assert len(found) == len(set(found))
    assert play(action).title == f"{title} 1/{total}"


@pytest.mark.parametrize("action,command,title,collection,separator", LISTS)
def test_every_entry_has_a_name_and_identifier_detail(game, play, action, command, title, collection, separator):
    for entry in entries(game, collection):
        detail = play(action, entry.name)
        assert detail.title == f"{title} · {entry.name}"
        assert play(action, entry.id) == detail
        assert command in detail.commands
        assert len(detail.commands) <= 8
        assert _parse(f"{command} {entry.name}") == (action, entry.name)
        assert _parse(f"{command} 2") == (action, "2")
        assert ACTIONS[action].arguments


@pytest.mark.parametrize("action", [entry[0] for entry in LISTS])
@pytest.mark.parametrize("argument", ["0", "999", "-1", "1.5", "1000", "２", "未知物品", "1 2"])
def test_invalid_pages_and_unknown_names_are_rejected(play, action, argument):
    with pytest.raises(GameError):
        play(action, argument)


def test_details_offer_matching_shop_skill_equipment_and_workshop_actions(play):
    food = play("shop", "灵粮")
    assert "售价：20 灵石" in food.text()
    assert "灵宠购买 灵粮" in food.commands
    book = play("shop", "风刃术诀")
    assert "灵宠技能图鉴 风刃术" in book.commands
    skill = play("skill_catalog", "风刃术")
    assert "学习秘笈：风刃术诀" in skill.text()
    assert "灵宠学习 风刃术" in skill.commands
    assert "灵宠商店 风刃术诀" in skill.commands
    shop_gear = play("shop", "青岚翎")
    assert "灵宠装备图鉴 青岚翎" in shop_gear.commands
    gear = play("equipment_catalog", "青岚翎")
    assert "部位：灵器" in gear.text()
    assert "攻击 +6" in gear.text()
    assert "灵宠购买 青岚翎" in gear.commands
    assert "灵宠工坊 青岚翎" in gear.commands


def test_shop_does_not_list_or_offer_unpurchasable_items(game, play):
    unpriced = [item for item in game[0].content.items.values() if item.price is None]
    assert unpriced
    for item in unpriced:
        with pytest.raises(GameError):
            play("shop", item.name)


def test_browsing_preserves_runtime_state_and_equipment_view_still_equips(game, play):
    play("adopt", "青鸾")
    before = player(game[1]), pet(game[1]), items(game[1])
    for action, _, _, collection, _ in LISTS:
        play(action)
        play(action, "2")
        play(action, entries(game, collection)[0].name)
    assert (player(game[1]), pet(game[1]), items(game[1])) == before
    play("sign")
    play("buy", "青岚翎")
    assert play("equipment", "青岚翎").title == "装备灵物"
    assert "青岚翎 +0" in play("equipment").text()
    assert len(sql(game[1], "SELECT * FROM equipment")) == 1


@pytest.mark.parametrize("action,command,title,collection,separator", LISTS)
def test_qq_page_and_detail_sizes_stay_within_readability_budget(game, play, action, command, title, collection, separator):
    pytest.importorskip("nonebot.adapters.qq")
    values = entries(game, collection)
    queries = [str(index) for index in range(1, (len(values) + 4) // 5 + 1)]
    queries.extend(entry.name for entry in values)
    for query in queries:
        reply = play(action, query)
        plain, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        markdown = native["markdown"][0].data["markdown"].content
        keyboard = native["keyboard"][0].data["keyboard"].content
        # These are project readability budgets, not claimed QQ platform limits.
        assert len(plain) <= 1200
        assert len(markdown) <= 4000
        assert sum(len(row.buttons) for row in keyboard.rows) == len(reply.commands) <= 8
        fallback, template = _qq_segments(reply, Config(
            spirit_pet_qq_mode="template", spirit_pet_qq_template_id="test-template",
        ))
        assert fallback == plain
        assert template["markdown"][0].data["markdown"].params[0].values == [plain]


def test_shared_page_helper_preserves_order_and_handles_empty_collections():
    first = paginate(range(11), "", "列表", "翻页")
    assert first.entries == (0, 1, 2, 3, 4)
    assert first.number == 1 and first.total == 3
    assert first.navigation == ("翻页 2",)
    middle = paginate(iter(range(11)), "2", "列表", "翻页")
    assert middle.entries == (5, 6, 7, 8, 9)
    assert middle.navigation == ("翻页 1", "翻页 3")
    last = paginate(range(11), "3", "列表", "翻页")
    assert last.entries == (10,) and last.navigation == ("翻页 2",)
    empty = paginate([], "", "列表", "翻页")
    assert empty.entries == () and empty.total == 1 and empty.navigation == ()
    with pytest.raises(GameError, match="共 3 页"):
        paginate(range(11), "4", "列表", "翻页")
    for invalid in (0, -1, True):
        with pytest.raises(ValueError, match="page size"):
            paginate([], "", "列表", "翻页", invalid)
