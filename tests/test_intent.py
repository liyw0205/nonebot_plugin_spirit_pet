"""Battle intent: a damage-multiplier posture, neutral by default."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import combat, intent, loadout
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000


def ctx_of(game, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, NOW, "read")


def fighter(name, *, dealt=1.0, taken=1.0):
    return combat.Fighter.create(
        name, Stats(hp=1000, attack=100, defense=10, speed=100), dealt=dealt, taken=taken,
    )


def test_fighter_defaults_are_neutral():
    unit = fighter("甲")
    assert (unit.dealt, unit.taken) == (1.0, 1.0)


def test_fighter_rejects_out_of_range_multipliers():
    with pytest.raises(ValueError, match="dealt"):
        fighter("甲", dealt=0.1)
    with pytest.raises(ValueError, match="taken"):
        fighter("甲", taken=3.0)


def test_scale_damage_is_identity_at_one():
    assert combat.scale_damage(123, fighter("甲"), fighter("乙")) == 123


def test_scale_damage_applies_both_sides():
    assert combat.scale_damage(100, fighter("甲", dealt=1.5), fighter("乙")) == 150
    assert combat.scale_damage(100, fighter("甲"), fighter("乙", taken=0.5)) == 50
    assert combat.scale_damage(100, fighter("甲", dealt=1.5), fighter("乙", taken=0.5)) == 75
    assert combat.scale_damage(100, fighter("甲", dealt=0.5), fighter("乙", taken=1.0)) == 50


def test_scale_damage_never_reaches_zero():
    assert combat.scale_damage(1, fighter("甲", dealt=0.25), fighter("乙", taken=0.25)) == 1


def _first_hit_on_alpha(battle) -> int:
    for line in battle.history:
        match = re.search(r"乙攻击甲，造成 (\d+) 伤害", line)
        if match:
            return int(match.group(1))
    raise AssertionError(f"no hit on 甲 in {battle.history[:5]}")


def test_guard_posture_reduces_damage_taken_in_a_real_fight(game):
    rng = game[0].rng
    plain = combat.fight([fighter("甲"), fighter("甲2")], [fighter("乙")], rng)
    rng = game[0].rng
    guarded = combat.fight([fighter("甲", taken=0.5), fighter("甲2", taken=0.5)], [fighter("乙")], rng)
    assert _first_hit_on_alpha(guarded) * 2 == pytest.approx(_first_hit_on_alpha(plain), abs=2)


def test_every_declared_intent_trades_one_side_for_the_other(game):
    rows = list(game[0].content.intents.values())
    assert len(rows) == 3
    for row in rows:
        assert (row.dealt - 1) * (row.taken - 1) > 0
        assert 0.5 <= row.dealt <= 1.5 and 0.5 <= row.taken <= 1.5


def test_page_without_a_pet_is_read_only(game, play):
    page = play("intent", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_every_posture_and_the_neutral_state(game, play):
    play("adopt", "青鸾")
    page = play("intent")
    assert "当前战意：无" in page.text()
    for row in game[0].content.intents.values():
        assert row.name in page.text()
    assert all(link.command.startswith("灵宠战意 选择 ") for link in page.inline_commands)


def test_choosing_persists_and_shows_as_current(game, play):
    play("adopt", "青鸾")
    play("intent", "选择 守势", op="pick")
    assert intent.current(ctx_of(game)).name == "守势"
    page = play("intent")
    assert "当前战意：守势" in page.text()
    assert "清除" in [link.label for link in page.inline_commands]


def test_reselecting_the_same_posture_writes_nothing(game, play):
    play("adopt", "青鸾")
    play("intent", "选择 守势", op="same-1")
    before = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE 'intent_%'")
    reply = play("intent", "选择 守势", op="same-2")
    assert "当前已是守势" in reply.text()
    after = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE 'intent_%'")
    assert before == after


def test_switching_replaces_the_previous_posture(game, play):
    play("adopt", "青鸾")
    play("intent", "选择 强攻", op="switch-1")
    play("intent", "选择 游斗", op="switch-2")
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'intent_%'")
    assert len(rows) == 1
    assert intent.current(ctx_of(game)).name == "游斗"


def test_clear_removes_the_posture_and_refuses_when_absent(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="没有设置战意"):
        play("intent", "清除")
    play("intent", "选择 强攻", op="clear-set")
    reply = play("intent", "清除", op="clear-do")
    assert reply.title == "战意已清除"
    assert intent.current(ctx_of(game)) is None
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'intent_%'") == []


def test_unknown_and_malformed_arguments_are_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="未找到该内容"):
        play("intent", "选择 不存在")
    with pytest.raises(GameError, match="格式"):
        play("intent", "随便写")
    with pytest.raises(GameError, match="格式"):
        play("intent", "选择")


def test_the_posture_reaches_the_built_fighter(game, play):
    play("adopt", "青鸾")
    play("intent", "选择 强攻", op="apply")
    unit = loadout.combatant(ctx_of(game))
    ass = game[0].content.intents["intent_assault"]
    assert (unit.dealt, unit.taken) == (ass.dealt, ass.taken)
    play("intent", "清除", op="apply-clear")
    neutral = loadout.combatant(ctx_of(game))
    assert (neutral.dealt, neutral.taken) == (1.0, 1.0)


def test_objective_help_and_parse(game, play):
    play("adopt", "青鸾")
    assert "战意：未选择" in play("objectives").text()
    play("intent", "选择 守势", op="obj")
    assert "战意：守势" in play("objectives").text()
    assert "灵宠战意" in play("help", "成长").text()
    assert handlers._parse("灵宠战意") == ("intent", "")
    assert handlers._parse("灵宠战意 选择 守势") == ("intent", "选择 守势")


def test_the_posture_survives_a_restart(game, play):
    play("adopt", "青鸾")
    play("intent", "选择 游斗", op="persist")
    assert intent.current(ctx_of(game)).name == "游斗"


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("intent")
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
