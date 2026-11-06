"""Side-by-side comparison of two owned pets."""

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
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_compare_shows_both_pets_and_all_sections(game, play):
    account(game, play)
    add_pet(game, play)
    first, second = pet_id(game, "青鸾"), pet_id(game, "木灵")
    page = play("pet_compare", f"{first} {second}", now=NOW)
    assert page.title == "灵宠对比"
    assert f"{first}" in page.lines[0] and f"{second}" in page.lines[0]
    assert any(line.startswith("气血 ") for line in page.lines)
    assert any(line.startswith("攻击 ") for line in page.lines)
    assert any(line.startswith("防御 ") for line in page.lines)
    assert any(line.startswith("速度 ") for line in page.lines)
    assert any(line.startswith("技能：") for line in page.lines)
    assert any(line.startswith("装备：") for line in page.lines)
    assert any(line.startswith("羁绊：") for line in page.lines)
    assert any(line.startswith("专精：") for line in page.lines)


def test_same_pet_is_rejected(game, play):
    account(game, play)
    first = pet_id(game, "青鸾")
    with pytest.raises(GameError, match="两只不同"):
        play("pet_compare", f"{first} {first}", now=NOW)


def test_unknown_other_owner_and_archived_are_rejected(game, play):
    account(game, play)
    add_pet(game, play)
    account(game, play, "u2")
    first, second = pet_id(game, "青鸾"), pet_id(game, "木灵")
    with pytest.raises(GameError, match="不存在"):
        play("pet_compare", f"{first} 9999", now=NOW)
    sql(game[1], "UPDATE pets SET user_id='u2' WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="不属于你"):
        play("pet_compare", f"{first} {second}", now=NOW)
    sql(game[1], "UPDATE pets SET user_id='u1', archived=1 WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="封存库"):
        play("pet_compare", f"{first} {second}", now=NOW)


def test_format_rejections_are_stable(game, play):
    account(game, play)
    first = pet_id(game, "青鸾")
    for arg in ("", str(first), f"{first} x", f"{first} 1 2"):
        with pytest.raises(GameError, match="格式"):
            play("pet_compare", arg, now=NOW)


def test_unregistered_is_read_only(game, play):
    page = play("pet_compare", "1 2", user="ghost", now=NOW)
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_compare_is_read_only(game, play):
    account(game, play)
    add_pet(game, play)
    before = state(game[1])
    play("pet_compare", f"{pet_id(game, '青鸾')} {pet_id(game, '木灵')}", now=NOW)
    assert state(game[1]) == before


def test_help_parser_and_native_payload(game, play):
    account(game, play)
    add_pet(game, play)
    first, second = pet_id(game, "青鸾"), pet_id(game, "木灵")
    assert _parse("灵宠对比 1 2") == ("pet_compare", "1 2")
    assert "灵宠对比 编号A 编号B" in play("help", "结契", now=NOW).text()
    page = play("pet_compare", f"{first} {second}", now=NOW)
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
