import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql
from .test_arena_matching import NOW as ARENA_NOW
from .test_arena_matching import register, uid

NOW = 1_800_000_000


def account(game, play):
    play("adopt", "青鸾", now=NOW)


def add_same_species(game, user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated) "
        "VALUES (?, 'qingluan', '青鸾二号', 100, 100, ?)",
        (user, NOW),
    )


def test_title_page_links_earned_titles_and_persists_switch(game, play):
    account(game, play)
    assert "当前称号：初入仙途" in play("titles").text()
    add_same_species(game)

    listing = play("titles")
    assert "当前称号：双灵同修" in listing.text()
    assert {link.command for link in listing.inline_commands} == {
        "灵宠称号佩戴 初入仙途",
        "灵宠称号佩戴 双灵同修",
    }

    switched = play("title_equip", "双灵同修", now=NOW, op="equip-title")
    assert switched.title == "已佩戴称号：双灵同修"
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id='title_equipped'") == [
        {"progress": 2, "claimed": 1},
    ]
    assert "称号：双灵同修" in play("status", now=NOW + 1).text()
    assert "主动佩戴" in play("titles", now=NOW + 1).text()
    assert play("title_equip", "初入仙途", now=NOW + 1) != switched


def test_title_loadout_rejects_unearned_or_bad_arguments_without_writes(game, play):
    account(game, play)
    before = player(game[1], "u1")
    with pytest.raises(GameError, match="尚未获得"):
        play("title_equip", "双灵同修", now=NOW)
    with pytest.raises(GameError):
        play("title_equip", "不存在", now=NOW)
    with pytest.raises(GameError):
        play("title_equip", "初入仙途 额外", now=NOW)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id='title_equipped'") == []
    assert player(game[1], "u1") == before


def test_invalid_stored_choice_falls_back_and_can_be_repaired(game, play):
    account(game, play)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1','title_equipped',999,1)",
    )
    assert "当前称号：初入仙途" in play("titles", now=NOW).text()
    assert "主动佩戴" not in play("status", now=NOW).text()
    add_same_species(game)
    play("title_equip", "双灵同修", now=NOW, op="repair-title")
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id='title_equipped'") == [
        {"progress": 2, "claimed": 1},
    ]


def test_title_replay_is_idempotent_and_native_links_leave_buttons_clean(game, play):
    account(game, play)
    add_same_species(game)
    first = play("title_equip", "双灵同修", now=NOW, op="same-title-operation")
    assert play("title_equip", "初入仙途", now=NOW + 1, op="same-title-operation") == first
    listing = play("titles", now=NOW + 1)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    linked = {link.command for link in listing.inline_commands}
    assert linked == {"灵宠称号佩戴 初入仙途"}
    assert not buttons & linked
    assert "佩戴" in str(message)


def test_title_loadout_command_and_help_are_discoverable(game, play):
    assert handlers._parse("灵宠称号佩戴 双灵同修") == ("title_equip", "双灵同修")
    assert "灵宠称号佩戴 称号名" in play("help", "身份与收集").text()


def test_selected_title_is_captured_in_new_battle_reports(game, play):
    register(game, play)
    add_same_species(game, "private-0")
    play("title_equip", "双灵同修", user="private-0", now=ARENA_NOW, op="battle-title-equip")
    play("pvp", uid(1), user="private-0", now=ARENA_NOW, op="battle-with-title")
    battle_id = sql(game[1], "SELECT battle_id FROM battle_records WHERE operation_id='battle-with-title'")[0]["battle_id"]
    detail = play("battle_reports", f"查看 {battle_id}", user="private-0", now=ARENA_NOW + 1)
    assert "称号 双灵同修" in detail.text()
