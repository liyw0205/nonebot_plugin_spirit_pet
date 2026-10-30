"""Skill specialization: page states, first pick, switching cost, cancel and combat effect."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.specialization_content import Specialization, skill_archetype
from nonebot_plugin_spirit_pet.gameplay import specialization
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000


def ctx_of(game, user="u1"):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, NOW, "read-spec")


def multipliers(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "read-spec-m")
        target = ctx.repo.player(user).active_pet_id
        return combatant(ctx, user, pet_id=target).skill_multipliers


def learn(game, skill_id, level=3, user="u1", equipped=1):
    row = pet(game[1], user)
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, ?, ?, 0)"
        " ON CONFLICT(pet_id, skill_id) DO UPDATE SET equipped=excluded.equipped, level=excluded.level",
        (row["pet_id"], skill_id, equipped, level),
    )


def spec_rows(game, user="u1"):
    return [row["quest_id"] for row in sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE 'spec_%' ORDER BY quest_id",
        (user,),
    )]


def ready(game, play, *, stones=5000, skills=("wind_slash",), level=3):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=?", (stones,))
    for skill_id in skills:
        learn(game, skill_id, level=level)


def test_content_declares_four_archetypes_with_rates(game):
    entries = game[0].content.specializations
    assert sorted(entries) == ["control", "multi", "single", "support"]
    assert entries["single"].rate == 0.15
    assert entries["support"].rate == 0.20
    assert all(0.05 <= entry.rate <= 0.30 for entry in entries.values())


def test_every_skill_classifies_to_a_declared_archetype(game):
    content = game[0].content
    for skill in content.skills.values():
        assert skill_archetype(skill) in content.specializations


def test_archetype_classifier_matches_skill_shapes(game):
    skills = game[0].content.skills
    assert skill_archetype(skills["wind_slash"]) == "single"
    assert skill_archetype(skills["spirit_wave"]) == "multi"
    assert skill_archetype(skills["mountain_taunt"]) == "control"
    assert skill_archetype(skills["wood_heal"]) in {"support", "single"}


def test_specialization_validator_rejects_out_of_range_rates():
    base = {"id": "single", "name": "单体", "description": "测试", "rate": 0.15}
    assert Specialization.model_validate(base).rate == 0.15
    with pytest.raises(ValidationError):
        Specialization.model_validate({**base, "rate": 0.5})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("specialization", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_levels_archetypes_and_states(game, play):
    ready(game, play, skills=("wind_slash",))
    learn(game, "spirit_wave", level=1)
    page = play("specialization")
    assert "青鸾：尚未选择专精。" in page.text()
    assert "风刃术 · 3级 · 熟练度 0/100 · 单体精研 +15% · 可专精（单体精研 +15%）" in page.text()
    assert "灵潮荡阵 · 1级 · 熟练度 0/20 · 群攻精研 +12% · 需 3 级（当前 1 级）" in page.text()
    assert [link.command for link in page.inline_commands] == ["灵宠专精 风刃术"]


def test_first_specialisation_is_free(game, play):
    ready(game, play)
    stones = player(game[1])["stones"]
    reply = play("specialization", "风刃术", op="spec-1")
    assert reply.title == "灵术专精"
    assert "首次专精免费" in reply.text()
    assert "+15%" in reply.text()
    assert player(game[1])["stones"] == stones
    assert spec_rows(game) == [f"spec_{pet(game[1])['pet_id']}_wind_slash"]


def test_specialisation_leaves_skill_rows_untouched(game, play):
    ready(game, play)
    before = sql(game[1], "SELECT level, proficiency, equipped FROM learned_skills WHERE pet_id=?", (pet(game[1])["pet_id"],))
    bag = items(game[1])
    play("specialization", "风刃术", op="spec-keep")
    after = sql(game[1], "SELECT level, proficiency, equipped FROM learned_skills WHERE pet_id=?", (pet(game[1])["pet_id"],))
    assert before == after
    assert items(game[1]) == bag


def test_page_shows_the_chosen_skill_and_cancel_link(game, play):
    ready(game, play)
    play("specialization", "风刃术", op="spec-2")
    page = play("specialization")
    assert "青鸾：专精 风刃术。" in page.text()
    assert "风刃术 · 3级 · 熟练度 0/100 · 单体精研 +15% · 已专精" in page.text()
    assert "取消专精" in [link.label for link in page.inline_commands]


def test_switching_to_another_skill_costs_stones(game, play):
    ready(game, play, skills=("wind_slash", "meditation"))
    play("specialization", "风刃术", op="spec-a")
    stones = player(game[1])["stones"]
    reply = play("specialization", "凝神术", op="spec-b")
    assert "改投消耗 300 灵石" in reply.text()
    assert player(game[1])["stones"] == stones - 300
    assert spec_rows(game) == [f"spec_{pet(game[1])['pet_id']}_meditation"]


def test_insufficient_stones_refuses_with_zero_writes(game, play):
    ready(game, play, skills=("wind_slash", "meditation"), stones=5000)
    play("specialization", "风刃术", op="spec-c")
    sql(game[1], "UPDATE players SET stones=100")
    before = spec_rows(game)
    with pytest.raises(GameError, match="灵石不足"):
        play("specialization", "凝神术", op="spec-d")
    assert spec_rows(game) == before
    assert player(game[1])["stones"] == 100


def test_repeating_the_same_skill_is_refused(game, play):
    ready(game, play)
    play("specialization", "风刃术", op="spec-e")
    with pytest.raises(GameError, match="已经专精"):
        play("specialization", "风刃术", op="spec-f")


def test_below_level_and_unlearned_skills_are_refused(game, play):
    ready(game, play, skills=("wind_slash",))
    learn(game, "meditation", level=1)
    with pytest.raises(GameError, match="专精需要 3 级"):
        play("specialization", "凝神术")
    with pytest.raises(GameError, match="尚未学会"):
        play("specialization", "赤焰术")
    assert spec_rows(game) == []


def test_cancel_is_free_and_refuses_when_empty(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="没有专精"):
        play("specialization", "取消")
    play("specialization", "风刃术", op="spec-g")
    stones = player(game[1])["stones"]
    reply = play("specialization", "取消", op="spec-cancel")
    assert reply.title == "取消专精"
    assert player(game[1])["stones"] == stones
    assert spec_rows(game) == []


def test_an_expedition_pet_cannot_specialise(game, play):
    ready(game, play)
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("specialization", "风刃术")
    assert spec_rows(game) == []


def test_combat_multiplier_includes_the_bonus(game, play):
    ready(game, play)
    before = multipliers(game)
    play("specialization", "风刃术", op="spec-h")
    after = multipliers(game)
    from nonebot_plugin_spirit_pet.domain.specialization_content import skill_archetype

    skill = game[0].content.skills["wind_slash"]
    rate = game[0].content.specializations[skill_archetype(skill)].rate
    assert after["wind_slash"] == pytest.approx(before["wind_slash"] * (1 + rate))
    assert {key: value for key, value in after.items() if key != "wind_slash"} == {
        key: value for key, value in before.items() if key != "wind_slash"
    }


def test_only_the_specialised_skill_is_scaled_and_only_for_that_pet(game, play):
    ready(game, play, skills=("wind_slash", "meditation"))
    play("specialization", "凝神术", op="spec-i")
    current = multipliers(game)
    content = game[0].content
    plain = content.skill_levels[3].power_multiplier
    rate = content.specializations[skill_archetype(content.skills["meditation"])].rate
    assert current["meditation"] == pytest.approx(plain * (1 + rate))
    assert current["wind_slash"] == plain


def test_specialisation_survives_a_restart_and_replays(game, play):
    ready(game, play)
    first = play("specialization", "风刃术", op="spec-persist")
    again = play("specialization", "风刃术", op="spec-persist")
    assert again.text() == first.text()
    assert len(spec_rows(game)) == 1
    assert "专精：风刃术（+15%）" in play("objectives").text()


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "专精：未选择" in play("objectives").text()
    play("specialization", "风刃术", op="spec-j")
    assert "专精：风刃术（+15%）" in play("objectives").text()
    assert "灵宠专精" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠专精") == ("specialization", "")
    assert handlers._parse("灵宠专精 风刃术") == ("specialization", "风刃术")
    with pytest.raises(GameError, match="未找到|格式"):
        play("specialization", "额外 参数")
    with pytest.raises(GameError, match="格式"):
        play("specialization", "取消 额外")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play, skills=("wind_slash", "meditation"))
    page = play("specialization")
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
