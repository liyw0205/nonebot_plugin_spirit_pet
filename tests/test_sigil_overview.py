"""Roster-wide sigil loadout overview."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(game, play, name="木灵", user="u1"):
    species = next(iter(game[0].content.species))
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species, name, NOW),
    )


def pet_id(game, name):
    return sql(game[1], "SELECT pet_id FROM pets WHERE name=?", (name,))[0]["pet_id"]


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
    }


def test_overview_lists_every_pet_with_slots_bonus_and_marker(game, play):
    account(game, play)
    add_pet(game, play)
    second = pet_id(game, "木灵")
    sigil_id, sigil = next(iter(game[0].content.sigils.items()))
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"sigil_{second}_1_{sigil_id}",),
    )
    page = play("sigils", "总览", now=NOW)
    assert page.title == "灵宠符印 总览"
    assert "青鸾" in page.text() and "木灵" in page.text()
    first_line = [line for line in page.lines if "青鸾" in line][0]
    second_line = [line for line in page.lines if "木灵" in line][0]
    assert "当前出战" in first_line
    assert "当前出战" not in second_line
    assert "符印 1/2" in second_line
    assert sigil.name in page.text()
    assert "总加成" in second_line


def test_overview_is_read_only(game, play):
    account(game, play)
    add_pet(game, play)
    before = state(game[1])
    play("sigils", "总览", now=NOW)
    assert state(game[1]) == before


def test_overview_rejects_arguments_and_unregistered_is_read_only(game, play):
    account(game, play)
    with pytest.raises(GameError, match="格式"):
        play("sigils", "总览 x", now=NOW)
    page = play("sigils", "总览", user="ghost", now=NOW)
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == [{"user_id": "u1"}]


def test_overview_help_parser_and_native_payload(game, play):
    account(game, play)
    add_pet(game, play)
    assert _parse("灵宠符印 总览") == ("sigils", "总览")
    assert "灵宠符印 总览" in play("help", "灵物与灵术", now=NOW).text()
    page = play("sigils", "总览", now=NOW)
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
