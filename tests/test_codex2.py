import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

from .support import sql

NOW = 1_800_000_000


def snapshot(store):
    """Domain state only — `operations` is the idempotency log and legitimately grows."""
    return [
        sql(store, "SELECT * FROM players"),
        sql(store, "SELECT * FROM pets ORDER BY pet_id"),
        sql(store, "SELECT * FROM inventory"),
        sql(store, "SELECT * FROM quest_progress"),
    ]


def test_counter_lookup_matches_the_battle_engine_for_every_element(game, play):
    from nonebot_plugin_spirit_pet.gameplay.combat import effectiveness

    content = game[0].content
    for element in content.elements.values():
        page = play("catalog_counter", element.name)
        assert page.title == f"图鉴克制 · {element.name}"
        for key in content.elements:
            if effectiveness(element.id, key, content.elements) > 1:
                assert content.elements[key].name in page.lines[1]
            else:
                assert content.elements[key].name not in page.lines[1]
            if effectiveness(key, element.id, content.elements) > 1:
                assert content.elements[key].name in page.lines[2]
            else:
                assert content.elements[key].name not in page.lines[2]


def test_counter_lookup_accepts_ids_and_lists_primary_element_species(game, play):
    page = play("catalog_counter", "ice")
    assert page.title == "图鉴克制 · 冰"
    assert page.lines[0] == "冰属性灵宠：寒翎鹰、雪影狐、玄冰蚕"
    assert page.lines[1] == "克制：火（玄狐、毕方、赤焰虎、熔岩甲）"
    assert page.lines[2] == "被克制：土（负山狮、岩心偶）、雷（雷泽夔、霆光雕）"
    assert "灵宠图鉴" in page.commands and "灵宠帮助" in page.commands


def test_counter_lookup_reports_elements_without_a_matchup(game, play):
    page = play("catalog_counter", "风")
    assert page.title == "图鉴克制 · 风"
    assert page.lines[1] == "克制：土（负山狮、岩心偶）"
    assert page.lines[2] == "被克制：无"
    assert page.lines[3] == "属性加成以主属性结算，副属性不影响克制方向。"


def test_counter_lookup_routes_through_the_plain_catalog_alias(game, play):
    assert play("catalog", "克制 火").lines == play("catalog_counter", "火").lines


def test_drop_lookup_lists_every_source_for_a_common_item(game, play):
    page = play("catalog_drop", "锻灵矿")
    assert page.title == "图鉴掉落 · 锻灵矿"
    assert page.lines[0] == "锻灵矿：装备强化材料，可从秘境和每日任务获得。"
    assert page.lines[1] == "掉落来源（24 处）："
    assert "· 秘境 青岚林" in page.lines
    assert "· 万灵塔 初入塔门" in page.lines
    assert "· 委托 寻锻矿" in page.lines
    # A stage reward would be listed with its own prefix.
    stage_drop = play("catalog_drop", "青岚翎")
    assert "· 关卡 月影追猎" in stage_drop.lines


def test_drop_lookup_accepts_item_ids_and_names_an_item_without_drops(game, play):
    assert play("catalog_drop", "spirit_food").title == "图鉴掉落 · 灵粮"
    page = play("catalog_drop", "同心丹")
    assert page.lines[0].startswith("同心丹：")
    assert page.lines[1] == "暂无掉落来源；可在灵坊购买或从其他系统获得。"
    assert "灵宠秘境" in page.commands and "灵宠委托" in page.commands


def test_drop_lookup_routes_through_the_plain_catalog_alias(game, play):
    assert play("catalog", "掉落 锻灵矿").lines == play("catalog_drop", "锻灵矿").lines


def test_both_lookups_are_read_only(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    before = snapshot(game[1])
    for action, arg in (
        ("catalog_counter", "火"), ("catalog", "克制 火"),
        ("catalog_drop", "锻灵矿"), ("catalog", "掉落 锻灵矿"),
    ):
        play(action, arg, now=NOW + 1)
    assert snapshot(game[1]) == before


def test_lookups_work_without_an_account(game, play):
    page = play("catalog_counter", "火", user="u9", now=NOW)
    assert page.title == "图鉴克制 · 火"
    drop = play("catalog_drop", "锻灵矿", user="u9", now=NOW)
    assert drop.title == "图鉴掉落 · 锻灵矿"
    assert sql(game[1], "SELECT user_id FROM players") == []


@pytest.mark.parametrize("action, argument, message", [
    ("catalog_counter", "", "格式：灵宠图鉴 克制"),
    ("catalog_drop", "", "格式：灵宠图鉴 掉落"),
    ("catalog_counter", "不存在的属性", "未找到该属性"),
    ("catalog_drop", "不存在的物品", "未找到该物品"),
])
def test_lookups_reject_missing_or_unknown_arguments(play, action, argument, message):
    with pytest.raises(GameError, match=message):
        play(action, argument, now=NOW)


def test_catalog_alias_requires_an_argument_after_the_keyword(game, play):
    with pytest.raises(GameError, match="格式：灵宠图鉴 克制"):
        play("catalog", "克制", now=NOW)
    with pytest.raises(GameError, match="格式：灵宠图鉴 掉落"):
        play("catalog", "掉落", now=NOW)


def test_unknown_names_still_raise_before_any_state_change(game, play):
    play("adopt", "青鸾", now=NOW)
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("catalog_drop", "不存在的物品", now=NOW + 1)
    with pytest.raises(GameError):
        play("catalog_counter", "不存在的属性", now=NOW + 2)
    assert snapshot(game[1]) == before


def test_native_payload_keeps_buttons_and_no_row_links(game, play):
    play("adopt", "青鸾", now=NOW)
    for reply in (play("catalog_counter", "火", now=NOW + 1), play("catalog_drop", "锻灵矿", now=NOW + 2)):
        _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        buttons = [
            button.action.data.removeprefix("/")
            for segment in message["keyboard"]
            for row in segment.data["keyboard"].content.rows
            for button in row.buttons
        ]
        assert len(buttons) <= 4
        assert not set(buttons) & {link.command for link in reply.inline_commands}
        assert reply.inline_commands == ()


def test_parse_and_help_contract():
    assert handlers._parse("灵宠图鉴克制 火") == ("catalog_counter", "火")
    assert handlers._parse("灵宠图鉴掉落 锻灵矿") == ("catalog_drop", "锻灵矿")
    assert handlers._parse("灵宠图鉴 克制 火") == ("catalog", "克制 火")
    assert handlers._parse("灵宠图鉴 掉落 锻灵矿") == ("catalog", "掉落 锻灵矿")
    # The bare catalog still parses as the species listing and its detail view.
    assert handlers._parse("灵宠图鉴") == ("catalog", "")
    assert handlers._parse("灵宠图鉴 2") == ("catalog", "2")
    assert handlers._parse("灵宠图鉴 青鸾") == ("catalog", "青鸾")
    entries = _HELP_SECTIONS["血脉与道具"]
    assert ("灵宠图鉴 克制 属性名", "灵宠图鉴克制 ", "查看某属性的克制关系与对应种族。") in entries
    assert (
        "灵宠图鉴 掉落 物品名", "灵宠图鉴掉落 ",
        "查看某件物品在秘境、关卡、万灵塔与委托中的掉落来源。",
    ) in entries
