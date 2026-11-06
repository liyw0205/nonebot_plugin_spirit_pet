"""Read-only roster overview of every pet's chosen specialization."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW)


def add_pet(game, play, name="木灵", user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) "
        "VALUES (?, 'wood_sprite', ?, ?)",
        (user, name, NOW),
    )


def pet_id(game, name):
    return sql(game[1], "SELECT pet_id FROM pets WHERE name=?", (name,))[0]["pet_id"]


def learn(game, pet, skill_id="wind_slash", level=3):
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) "
        "VALUES (?, ?, 0, ?, 0) ON CONFLICT(pet_id, skill_id) DO UPDATE SET level=excluded.level",
        (pet, skill_id, level),
    )


def spec(game, pet, skill_id="wind_slash"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"spec_{pet}_{skill_id}",),
    )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def line(page, text):
    return next(item for item in page.lines if text in item)


def test_unregistered_is_read_only(game, play):
    page = play("specialization", "总览", user="ghost", now=NOW)
    assert page.title == "灵宠专精 · 总览"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_overview_lists_all_owned_pets_and_active_marker(game, play):
    account(game, play)
    add_pet(game, play)
    first, second = pet_id(game, "青鸾"), pet_id(game, "木灵")
    learn(game, first)
    learn(game, second)
    spec(game, second)
    page = play("specialization", "总览", now=NOW)
    assert "青鸾（编号 1）" in page.text()
    assert "木灵（编号 2）" in page.text()
    assert "青鸾（编号 1） · 当前出战 · 未选择专精 · 可专精 1 门" in page.text()
    assert "木灵（编号 2） · 专精 风刃术 · 单体精研 +15% · 可专精 1 门" in page.text()


def test_stale_spec_is_reported_without_crashing(game, play):
    account(game, play)
    pet = pet_id(game, "青鸾")
    learn(game, pet)
    sql(game[1], "DELETE FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'spec_%'")
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"spec_{pet}_removed_skill",),
    )
    page = play("specialization", "总览", now=NOW)
    assert f"专精灵术已失效（removed_skill）" in page.text()


def test_overview_is_read_only(game, play):
    account(game, play)
    add_pet(game, play)
    learn(game, pet_id(game, "青鸾"))
    learn(game, pet_id(game, "木灵"))
    before = state(game[1])
    play("specialization", "总览", now=NOW)
    assert state(game[1]) == before


def test_overview_rejects_extra_arguments(game, play):
    account(game, play)
    with pytest.raises(GameError, match="格式"):
        play("specialization", "总览 1", now=NOW)


def test_help_parser_and_native_payload(game, play):
    account(game, play)
    add_pet(game, play)
    assert _parse("灵宠专精 总览") == ("specialization", "总览")
    guide = play("help", "灵物与灵术", now=NOW)
    assert "灵宠专精 总览" in guide.text()
    page = play("specialization", "总览", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons <= set(page.commands)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}
