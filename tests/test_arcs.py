"""Fate arcs: chapter progression, option rewards, prerequisites and persistence."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.arc_content import Arc
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql

NOW = 1_800_000_000


def arcs(game):
    return sorted(game[0].content.arcs.values(), key=lambda arc: arc.order)


def step(game, arc_id, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"arc_{arc_id}_step"),
    )
    return rows[0]["progress"] if rows else 1


def done(game, arc_id, user="u1"):
    return bool(sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"arc_{arc_id}_done"),
    ))


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def finish_arc(game, play, arc_name, choices):
    for label in choices:
        play("arcs", f"{arc_name} {label}")


def test_content_defines_three_chained_arcs(game):
    entries = arcs(game)
    assert [arc.id for arc in entries] == ["wind_road", "snow_lantern", "star_ferry"]
    assert [arc.requires for arc in entries] == [None, "wind_road", "snow_lantern"]
    assert [arc.min_realm for arc in entries] == ["qiling", "zhuji", "jindan"]
    for arc in entries:
        assert arc.length == 3
        assert [chapter.order for chapter in arc.chapters] == [1, 2, 3]
        assert all(len(chapter.options) == 2 for chapter in arc.chapters)
        assert all(
            item in game[0].content.items
            for chapter in arc.chapters for option in chapter.options for item in option.reward.items
        )


def test_content_validation_rejects_broken_arcs():
    base = {
        "id": "test_arc", "name": "测试奇缘", "order": 1, "description": "测试",
        "requires": None, "min_realm": "ningqi",
        "chapters": [
            {"order": 1, "title": "第一章", "text": "文", "options": [
                {"id": "a", "label": "甲", "text": "甲文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
                {"id": "b", "label": "乙", "text": "乙文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
            ]},
        ],
        "finale": {"text": "终", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
    }
    assert Arc.model_validate(base).length == 1
    gap = {**base, "chapters": [{**base["chapters"][0], "order": 2}]}
    with pytest.raises(ValidationError, match="contiguous"):
        Arc.model_validate(gap)
    duplicate = {**base, "chapters": [{**base["chapters"][0], "options": [
        base["chapters"][0]["options"][0], {**base["chapters"][0]["options"][1], "id": "a"},
    ]}]}
    with pytest.raises(ValidationError, match="duplicate options"):
        Arc.model_validate(duplicate)
    with pytest.raises(ValidationError, match="require itself"):
        Arc.model_validate({**base, "requires": "test_arc"})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("arcs", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_arcs_with_state_and_only_links_the_open_one(game, play):
    play("adopt", "青鸾")
    page = play("arcs")
    assert "奇缘：已完成 0/3 条" in page.text()
    assert "风起青萍 · 可开启 · 启灵起" in page.text()
    assert "雪夜灯影 · 未开启（需先完成风起青萍） · 筑基起" in page.text()
    assert {link.command for link in page.inline_commands} == {"灵宠奇缘 风起青萍"}


def test_detail_shows_the_chapter_and_two_rewarded_options(game, play):
    play("adopt", "青鸾")
    reply = play("arcs", "风起青萍")
    assert "风起青萍 · 第 1/3 章" in reply.text()
    assert "山门初雪" in reply.text()
    assert "相助：" in reply.text() and "旁观：" in reply.text()
    assert "灵石 80" in reply.text()
    assert {link.command for link in reply.inline_commands} == {
        "灵宠奇缘 风起青萍 相助", "灵宠奇缘 风起青萍 旁观",
    }


def test_choosing_pays_the_option_and_advances_one_chapter(game, play):
    play("adopt", "青鸾")
    stones = player(game[1])["stones"]
    exp = pet(game[1])["exp"]
    food = items(game[1])["spirit_food"]
    reply = play("arcs", "风起青萍 相助")
    assert "灵石 +80" in reply.text() and "修为 +40" in reply.text()
    assert player(game[1])["stones"] == stones + 80
    assert pet(game[1])["exp"] == exp + 40
    assert items(game[1])["spirit_food"] == food + 1
    assert step(game, "wind_road") == 2
    assert "下一章" in reply.text()


def test_an_unknown_option_is_refused_without_advancing(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="没有该选项"):
        play("arcs", "风起青萍 逃学")
    assert step(game, "wind_road") == 1


def test_a_locked_arc_cannot_be_opened(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="需先完成风起青萍"):
        play("arcs", "雪夜灯影")
    with pytest.raises(GameError, match="需先完成风起青萍"):
        play("arcs", "雪夜灯影 添油")


def test_the_realm_gate_blocks_until_a_pet_is_strong_enough(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    with pytest.raises(GameError, match="需要筑基伙伴"):
        play("arcs", "雪夜灯影")
    boost(game)
    detail = play("arcs", "雪夜灯影")
    assert "旧灯重燃" in detail.text()


def test_finishing_the_third_chapter_pays_the_finale_once(game, play):
    play("adopt", "青鸾")
    stones = player(game[1])["stones"]
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    assert done(game, "wind_road")
    assert step(game, "wind_road") == 4
    # 80 + 100 + 120 from chapters, plus the 200 finale
    assert player(game[1])["stones"] == stones + 80 + 100 + 120 + 200
    with pytest.raises(GameError, match="已完成"):
        play("arcs", "风起青萍 旁观")
    assert player(game[1])["stones"] == stones + 80 + 100 + 120 + 200


def test_the_next_arc_opens_after_completion_and_realm_gate(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    boost(game)
    page = play("arcs")
    assert "奇缘：已完成 1/3 条" in page.text()
    assert "风起青萍 · 已完成" in page.text()
    assert "雪夜灯影 · 可开启" in page.text()
    assert "星槎渡 · 未开启（需先完成雪夜灯影）" in page.text()


def test_the_pick_is_recorded_per_chapter(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 旁观")
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='arc_wind_road_pick_1'",
    )
    assert rows and rows[0]["progress"] == 2


def test_progress_survives_a_restart(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "arcs", "", "restart-arcs", NOW)
    assert "风起青萍 · 进行中 · 第 2/3 章" in page.text()
    detail = restarted.execute("u1", "arcs", "风起青萍", "restart-arcs-2", NOW)
    assert "雪夜归途" in detail.text()


def test_same_operation_replays_without_paying_twice(game, play):
    play("adopt", "青鸾")
    stones = player(game[1])["stones"]
    first = play("arcs", "风起青萍 相助", op="arc-op")
    again = play("arcs", "风起青萍 相助", op="arc-op")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones + 80
    assert step(game, "wind_road") == 2


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠奇缘" in guide.text()
    assert "奇缘：已完成 0/3 · 尚未开启" in play("objectives").text()
    play("arcs", "风起青萍 相助")
    assert "奇缘：已完成 0/3 · 进行中 风起青萍" in play("objectives").text()
    assert handlers._parse("灵宠奇缘") == ("arcs", "")
    assert handlers._parse("灵宠奇缘 风起青萍 相助") == ("arcs", "风起青萍 相助")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("arcs")
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
