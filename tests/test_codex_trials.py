"""Codex species trials: mirrors, first-clear rewards, milestones and records."""

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import codex_trials
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql

NOW = 1_800_000_000
COOLDOWN = 700


def trial(game):
    return sorted(game[0].content.codex_trials.values(), key=lambda entry: entry.id)[0]


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def add_pet(game, user, species, name, *, realm=5):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, ?, 10, 4, 0, 0, 100, ?, 0)",
        (user, species, name, realm, NOW),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def marker(game, species_id, user="u1"):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"codex_trial_{species_id}"),
    )
    return rows[0]["progress"] if rows else None


def seed_marker(game, species_id, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 3, 1)",
        (user, f"codex_trial_{species_id}"),
    )


def stub(winner, rounds=3):
    return SimpleNamespace(winner=winner, rounds=rounds, lines=["战斗线"], history=[], skill_uses=[{}, {}])


def test_content_defines_one_trial_config(game):
    entry = trial(game)
    assert entry.boost == 2.2 and entry.energy == 10
    assert entry.reward.stones.minimum == 200 and entry.reward.exp.minimum == 150
    assert [milestone.count for milestone in entry.milestones] == [9, 18, 27]
    assert all(item in game[0].content.items for milestone in entry.milestones for item in milestone.items)
    assert len(game[0].content.species) == 27


def test_page_without_a_pet_is_read_only(game, play):
    page = play("codex_trials", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_paginates_and_marks_ownership(game, play):
    play("adopt", "青鸾")
    first = sorted(game[0].content.species.values(), key=lambda item: item.id)[0]
    page = play("codex_trials")
    assert "已通关 0/27 · 第 1/3 页" in page.text()
    assert f"{first.name} · 未拥有" in page.text()
    assert page.inline_commands == ()
    owned = play("codex_trials", "2")
    assert "青鸾 · 可挑战" in owned.text()
    assert {link.command for link in owned.inline_commands} == {"灵宠图鉴试炼 挑战 青鸾"}
    with pytest.raises(GameError, match="共 3 页"):
        play("codex_trials", "4")


def test_unknown_or_unowned_species_cannot_be_challenged(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError):
        play("codex_trials", "挑战 不存在的种族")
    with pytest.raises(GameError, match="尚未拥有"):
        play("codex_trials", "挑战 玄狐")
    assert marker(game, "xuanhu") is None


def test_first_clear_pays_once_and_records_the_battle(game, play):
    play("adopt", "青鸾")
    boost(game)
    stones = player(game[1])["stones"]
    exp = pet(game[1])["exp"]
    reply = play("codex_trials", "挑战 青鸾")
    assert reply.title == "图鉴试炼首通"
    assert "灵石 +200" in reply.text() and "修为 +150" in reply.text()
    assert player(game[1])["stones"] == stones + 200
    assert pet(game[1])["exp"] == exp + 150
    assert items(game[1])["forge_ore"] == 1
    assert marker(game, "qingluan") is not None
    record = sql(game[1], "SELECT kind, battle_key FROM battle_records")
    assert record == [{"kind": "pve_stage", "battle_key": "codex_qingluan"}]
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_a_repeat_clear_is_practice_and_pays_nothing(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("codex_trials", "挑战 青鸾")
    stones = player(game[1])["stones"]
    reply = play("codex_trials", "挑战 青鸾", now=NOW + COOLDOWN)
    assert reply.title == "图鉴试炼再胜"
    assert "练习" in reply.text()
    assert player(game[1])["stones"] == stones
    assert marker(game, "qingluan") is not None


def test_a_defeat_spends_energy_without_progress(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *args, **kwargs: stub(1))
    reply = play("codex_trials", "挑战 青鸾")
    assert reply.title == "图鉴试炼败退"
    assert "未通关" in reply.text()
    assert marker(game, "qingluan") is None
    assert pet(game[1])["energy"] == 90


def test_energy_and_expedition_gates_apply_before_the_fight(game, play):
    play("adopt", "青鸾")
    boost(game)
    sql(game[1], "UPDATE pets SET energy=9 WHERE user_id='u1'")
    with pytest.raises(GameError, match="精力不足"):
        play("codex_trials", "挑战 青鸾")
    assert marker(game, "qingluan") is None
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("codex_trials", "挑战 青鸾")


def test_the_species_pet_is_used_even_when_not_active(game, play):
    play("adopt", "青鸾")
    boost(game)
    fox = add_pet(game, "u1", "xuanhu", "小狐")
    reply = play("codex_trials", "挑战 玄狐")
    assert "小狐" in reply.text()
    energy = sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (fox,))[0]["energy"]
    assert energy == 90
    assert pet(game[1])["energy"] == 100


def test_nine_clears_pay_the_first_milestone_once(game, play):
    play("adopt", "青鸾")
    boost(game)
    for species in [s for s in game[0].content.species if s != "qingluan"][:8]:
        seed_marker(game, species)
    reply = play("codex_trials", "挑战 青鸾")
    assert "里程碑 9 族：锻灵矿 +4" in reply.text()
    assert items(game[1])["forge_ore"] == 1 + 4
    marker_row = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='codex_trial_milestone_9'",
    )
    assert marker_row and marker_row[0]["progress"] == 1
    again = play("codex_trials", "挑战 青鸾", now=NOW + COOLDOWN)
    assert "里程碑" not in again.text()
    assert items(game[1])["forge_ore"] == 5


def test_milestones_below_the_count_are_not_paid_early(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("codex_trials", "挑战 青鸾")
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'codex_trial_milestone_%'")
    assert rows == []


def test_the_page_and_objectives_track_progress(game, play):
    play("adopt", "青鸾")
    boost(game)
    assert "图鉴试炼：已通关 0/27" in play("objectives").text()
    play("codex_trials", "挑战 青鸾")
    assert "图鉴试炼：已通关 1/27" in play("objectives").text()
    page = play("codex_trials", "2")
    assert "已通关 1/27" in page.text()
    assert "青鸾 · 已通关（" in page.text()


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("codex_trials", "挑战 青鸾")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "codex_trials", "", "restart-codex", NOW)
    assert "已通关 1/27" in page.text()


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    boost(game)
    first = play("codex_trials", "挑战 青鸾", op="codex-op")
    again = play("codex_trials", "挑战 青鸾", op="codex-op")
    assert again.text() == first.text()
    assert marker(game, "qingluan") is not None


def test_help_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠图鉴试炼" in guide.text()
    assert handlers._parse("灵宠图鉴试炼") == ("codex_trials", "")
    assert handlers._parse("灵宠图鉴试炼 挑战 青鸾") == ("codex_trials", "挑战 青鸾")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("codex_trials")
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
