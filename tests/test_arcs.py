"""Fate arcs: chapter progression, option rewards, prerequisites and persistence."""

import itertools
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
    reply = None
    for label in choices:
        reply = play("arcs", f"{arc_name} {label}")
    return reply


def test_content_defines_five_chained_arcs(game):
    entries = arcs(game)
    assert [arc.id for arc in entries] == ["wind_road", "snow_lantern", "star_ferry", "cloud_ridge", "heaven_gate"]
    assert [arc.requires for arc in entries] == [None, "wind_road", "snow_lantern", "star_ferry", "cloud_ridge"]
    assert [arc.min_realm for arc in entries] == ["qiling", "zhuji", "jindan", "yuanying", "huashen"]
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


def test_ending_paths_are_validated_against_the_chapters():
    base = {
        "id": "test_arc", "name": "测试奇缘", "order": 1, "description": "测试",
        "requires": None, "min_realm": "ningqi",
        "chapters": [
            {"order": 1, "title": "第一章", "text": "文", "options": [
                {"id": "a", "label": "甲", "text": "甲文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
                {"id": "b", "label": "乙", "text": "乙文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
            ]},
            {"order": 2, "title": "第二章", "text": "文", "options": [
                {"id": "c", "label": "丙", "text": "丙文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
                {"id": "d", "label": "丁", "text": "丁文", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
            ]},
        ],
        "finale": {"text": "终", "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
    }
    assert Arc.model_validate(base).finale.paths == []
    one = {**base, "finale": {**base["finale"], "paths": [{"choices": [1, 2], "text": "分支"}]}}
    assert [ending.choices for ending in Arc.model_validate(one).finale.paths] == [[1, 2]]
    short = {**base, "finale": {**base["finale"], "paths": [{"choices": [1], "text": "分支"}]}}
    with pytest.raises(ValidationError, match="one option per chapter"):
        Arc.model_validate(short)
    dup = {**base, "finale": {**base["finale"], "paths": [
        {"choices": [1, 2], "text": "甲"}, {"choices": [1, 2], "text": "乙"},
    ]}}
    with pytest.raises(ValidationError, match="duplicate ending"):
        Arc.model_validate(dup)
    wrong = {**base, "finale": {**base["finale"], "paths": [{"choices": [1, 3], "text": "分支"}]}}
    with pytest.raises(ValidationError):
        Arc.model_validate(wrong)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("arcs", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_arcs_with_state_and_only_links_the_open_one(game, play):
    play("adopt", "青鸾")
    page = play("arcs")
    assert "奇缘：已完成 0/5 条" in page.text()
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


def test_the_next_chapter_hint_reopens_read_only(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    stones = player(game[1])["stones"]
    exp = pet(game[1])["exp"]
    food = items(game[1])["spirit_food"]
    reply = play("arcs", "风起青萍 继续")
    assert "雪夜归途" in reply.text()
    assert "借灯" in reply.text() and "独行" in reply.text()
    assert {link.command for link in reply.inline_commands} == {
        "灵宠奇缘 风起青萍 借灯", "灵宠奇缘 风起青萍 独行",
    }
    # read-only: no reward paid, no step taken
    assert player(game[1])["stones"] == stones
    assert pet(game[1])["exp"] == exp
    assert items(game[1])["spirit_food"] == food
    assert step(game, "wind_road") == 2


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
    with pytest.raises(GameError, match="需先完成风起青萍"):
        play("arcs", "雪夜灯影 继续")


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
    assert "奇缘：已完成 1/5 条" in page.text()
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


def test_earlier_choices_are_recalled_in_later_chapters(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 旁观")
    detail = play("arcs", "风起青萍")
    assert "前情：第1章 旁观" in detail.text()
    reply = play("arcs", "风起青萍 借灯")
    assert "前情：第1章 旁观" in reply.text()
    assert step(game, "wind_road") == 3
    nxt = play("arcs", "风起青萍 继续")
    assert "前情：第1章 旁观 · 第2章 借灯" in nxt.text()


def test_first_chapter_has_no_recall_line(game, play):
    play("adopt", "青鸾")
    assert "前情：" not in play("arcs", "风起青萍").text()


def test_invalid_legacy_pick_degrades_without_inventing_a_choice(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    sql(
        game[1],
        "UPDATE quest_progress SET progress=9 WHERE quest_id='arc_wind_road_pick_1'",
    )
    detail = play("arcs", "风起青萍")
    assert "前情：" not in detail.text()
    assert step(game, "wind_road") == 2


def test_the_finale_text_follows_the_recorded_path(game, play):
    play("adopt", "青鸾")
    last = finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    stored = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id LIKE 'arc_wind_road_pick_%' ORDER BY quest_id",
    )
    assert [row["progress"] for row in stored] == [1, 1, 1]
    # the authored ending for path (1,1,1) replaced the default finale text
    assert "往后这条山道总有第二串脚印跟着你" in last.text()


def test_path_dependent_ending_is_used_and_keeps_the_reward(game, play):
    play("adopt", "青鸾")
    stones = player(game[1])["stones"]
    last = finish_arc(game, play, "风起青萍", ["旁观", "独行", "沉默"])
    assert done(game, "wind_road")
    # path (2,2,2): all three options pay nothing, finale still pays 200 once
    assert player(game[1])["stones"] == stones + 200
    assert "路上没有人知道" in last.text()
    assert "此后的路，你不再只为自己走" not in last.text()


def test_missing_ending_path_falls_back_to_the_default_finale(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    arc = content.arcs["wind_road"]
    trimmed = arc.model_copy(update={
        "finale": arc.finale.model_copy(update={"paths": []}),
    })
    content.arcs["wind_road"] = trimmed
    reply = None
    for label in ["相助", "借灯", "直言"]:
        reply = play("arcs", f"风起青萍 {label}")
    assert "此后的路，你不再只为自己走" in reply.text()


def test_every_shipped_arc_authors_all_choice_combinations(game):
    for arc in arcs(game):
        keys = [tuple(ending.choices) for ending in arc.finale.paths]
        combinations = [
            tuple(index + 1 for index in picks)
            for picks in itertools.product(range(2), repeat=arc.length)
        ]
        assert len(keys) == len(set(keys)) == len(combinations)
        assert set(keys) == set(combinations)
        assert all(ending.text and ending.text != arc.finale.text for ending in arc.finale.paths)


def test_the_path_ending_survives_a_reopen(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["旁观", "独行", "沉默"])
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    with pytest.raises(GameError, match="已完成"):
        restarted.execute("u1", "arcs", "风起青萍 继续", "restart-finale", NOW)
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id LIKE 'arc_wind_road_pick_%' ORDER BY quest_id")
    assert [row["progress"] for row in rows] == [2, 2, 2]


def test_read_only_views_never_write(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    before = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    stones = player(game[1])["stones"]
    play("arcs", "风起青萍")
    play("arcs", "风起青萍 继续")
    play("arcs")
    after = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert after == before
    assert player(game[1])["stones"] == stones


def test_replaying_the_finale_choice_pays_once_and_stays_persisted(game, play):
    play("adopt", "青鸾")
    stones = player(game[1])["stones"]
    play("arcs", "风起青萍 相助", op="finale-op")
    play("arcs", "风起青萍 借灯", op="finale-op-2")
    first = play("arcs", "风起青萍 直言", op="finale-op-3")
    again = play("arcs", "风起青萍 直言", op="finale-op-3")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones + 80 + 100 + 120 + 200
    with pytest.raises(GameError, match="已完成"):
        play("arcs", "风起青萍 相助")
    assert player(game[1])["stones"] == stones + 80 + 100 + 120 + 200


def test_the_continuation_link_is_a_valid_detail_command_for_each_arc(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    reply = play("arcs", "风起青萍 继续")
    links = {link.command for link in reply.inline_commands}
    assert links == {"灵宠奇缘 风起青萍 借灯", "灵宠奇缘 风起青萍 独行"}
    # the advertised continuation itself is a valid command that opens the same chapter
    again = play("arcs", "风起青萍 继续")
    assert again.text() == reply.text()


def test_a_mid_story_arc_continuation_reopens_its_own_chapter(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    boost(game)
    play("arcs", "雪夜灯影 添油")
    reply = play("arcs", "雪夜灯影 继续")
    assert "雪夜灯影 · 第 2/3 章" in reply.text()
    assert "灯市遇故" in reply.text()
    assert step(game, "snow_lantern") == 2


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
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    section = _HELP_SECTIONS["秘境与关卡"]
    assert ("灵宠奇缘 奇缘名 继续", "灵宠奇缘 ", "只重读当前章节，不消耗选项、不发奖励。") in section
    assert "奇缘：已完成 0/5 条 · 章节 0/15 · 尚未开启" in play("objectives").text()
    play("arcs", "风起青萍 相助")
    assert "奇缘：已完成 0/5 条 · 章节 1/15 · 进行中 风起青萍" in play("objectives").text()
    assert handlers._parse("灵宠奇缘") == ("arcs", "")
    assert handlers._parse("灵宠奇缘 风起青萍 相助") == ("arcs", "风起青萍 相助")
    assert handlers._parse("灵宠奇缘 风起青萍 继续") == ("arcs", "风起青萍 继续")


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


def test_continuation_reply_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助")
    reply = play("arcs", "风起青萍 继续")
    assert reply.commands == ("灵宠奇缘", "灵宠目标")
    assert [link.command for link in reply.inline_commands] == [
        "灵宠奇缘 风起青萍 借灯", "灵宠奇缘 风起青萍 独行",
    ]
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(reply.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in reply.inline_commands}
    assert not linked & buttons


def test_the_new_high_realm_arcs_are_chained_and_reachable(game, play):
    play("adopt", "青鸾")
    for name, choices in (
        ("风起青萍", ["相助", "借灯", "直言"]),
        ("雪夜灯影", ["添油", "相认", "守灯"]),
        ("星槎渡", ["造船", "掌舵", "靠岸"]),
    ):
        boost(game, realm=6)
        finish_arc(game, play, name, choices)
    boost(game, realm=6)
    page = play("arcs")
    assert "云岭旧约 · 可开启 · 元婴起" in page.text()
    assert "天门问道 · 未开启（需先完成云岭旧约）" in page.text()
    detail = play("arcs", "云岭旧约")
    assert "岭下茶棚" in detail.text()
    assert "问路" in detail.text() and "自寻" in detail.text()


def test_a_high_realm_arc_pays_its_finale_once_and_reopens_read_only(game, play):
    play("adopt", "青鸾")
    for name, choices in (
        ("风起青萍", ["相助", "借灯", "直言"]),
        ("雪夜灯影", ["添油", "相认", "守灯"]),
        ("星槎渡", ["造船", "掌舵", "靠岸"]),
    ):
        boost(game, realm=6)
        finish_arc(game, play, name, choices)
    boost(game, realm=6)
    stones = player(game[1])["stones"]
    play("arcs", "云岭旧约 问路", op="ridge-1")
    play("arcs", "云岭旧约 认约", op="ridge-2")
    play("arcs", "云岭旧约 留字", op="ridge-3")
    paid = player(game[1])["stones"]
    assert paid == stones + 200 + 240 + 300 + 380
    assert done(game, "cloud_ridge")
    with pytest.raises(GameError, match="已完成"):
        play("arcs", "云岭旧约 问路")
    assert player(game[1])["stones"] == paid


def test_review_shows_every_choice_and_the_authored_ending(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["旁观", "独行", "沉默"])
    page = play("arcs", "风起青萍 回顾")
    assert "风起青萍 · 回顾" in page.text()
    assert "第1章 山门初雪 · 你选了「旁观」" in page.text()
    assert "第2章 雪夜归途 · 你选了「独行」" in page.text()
    assert "第3章 灯下问心 · 你选了「沉默」" in page.text()
    # the authored path ending, not the generic default
    assert "你旁观、独行，且从不解释" in page.text()
    assert page.inline_commands == ()


def test_review_is_read_only_and_pays_nothing(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    before = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    stones = player(game[1])["stones"]
    play("arcs", "风起青萍 回顾")
    play("arcs", "风起青萍 往事")
    after = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert after == before
    assert player(game[1])["stones"] == stones


def test_review_refuses_a_locked_or_unfinished_arc(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未开启"):
        play("arcs", "雪夜灯影 回顾")
    play("arcs", "风起青萍 相助")
    with pytest.raises(GameError, match="尚未完成"):
        play("arcs", "风起青萍 回顾")
    assert step(game, "wind_road") == 2


def test_review_rejects_an_extra_argument(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    with pytest.raises(GameError, match="格式"):
        play("arcs", "风起青萍 回顾 多")


def test_review_survives_a_restart(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "arcs", "风起青萍 回顾", "restart-review", NOW)
    assert "第1章 山门初雪 · 你选了「相助」" in page.text()
    assert "【风起青萍 · 终章】" in page.text()


def test_review_degrades_honestly_on_a_legacy_pick(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    sql(
        game[1],
        "UPDATE quest_progress SET progress=0 WHERE quest_id='arc_wind_road_pick_2'",
    )
    page = play("arcs", "风起青萍 回顾")
    assert "第2章 · 无记录（旧存档）" in page.text()
    # the default finale text, since the recorded path no longer matches a full combination
    assert "【风起青萍 · 终章】" in page.text()


def test_each_choice_bumps_the_counter_once_and_replays_do_not(game, play):
    play("adopt", "青鸾")
    play("arcs", "风起青萍 相助", op="count-1")
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_arc_choices'",
    )
    assert rows and rows[0]["progress"] == 1
    play("arcs", "风起青萍 相助", op="count-1")
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_arc_choices'",
    )
    assert rows[0]["progress"] == 1
    play("arcs", "风起青萍 借灯", op="count-2")
    play("arcs", "风起青萍 直言", op="count-3")
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_arc_choices'",
    )
    assert rows[0]["progress"] == 3


def test_a_refused_choice_does_not_bump_the_counter(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError):
        play("arcs", "风起青萍 不存在")
    with pytest.raises(GameError, match="尚未开启"):
        play("arcs", "星槎渡 造船")
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_arc_choices'") == []


def test_the_arc_achievements_and_title_are_reachable(game, play):
    assert "arc_choices" in {
        achievement.metric for achievement in game[0].content.achievements.values()
    }
    assert "arc_choices" in {title.metric for title in game[0].content.titles.values()}
    ceiling = game[0].content._metric_ceilings()["arc_choices"]
    assert ceiling == sum(len(arc.chapters) for arc in game[0].content.arcs.values())
    assert ceiling == 15


def test_review_accepts_the_documented_leading_keyword(game, play):
    play("adopt", "青鸾")
    finish_arc(game, play, "风起青萍", ["相助", "借灯", "直言"])
    leading = play("arcs", "回顾 风起青萍")
    trailing = play("arcs", "风起青萍 回顾")
    assert leading.text() == trailing.text()
    assert "第1章 山门初雪 · 你选了「相助」" in leading.text()
    with pytest.raises(GameError, match="格式"):
        play("arcs", "回顾 风起青萍 多")
    with pytest.raises(GameError, match="未找到"):
        play("arcs", "回顾 不存在")
    assert handlers._parse("灵宠奇缘 回顾 风起青萍") == ("arcs", "回顾 风起青萍")
