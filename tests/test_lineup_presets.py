"""Lineup presets: save/apply/clear three rosters, with every eligibility rule re-checked."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import lineup_presets
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def add_pet(game, species_id, name, user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated) VALUES (?, ?, ?, 0, ?)",
        (user, species_id, name, NOW),
    )
    return max(row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,)))


def ready(game, play):
    play("adopt", "青鸾")
    second = add_pet(game, "xuanhu", "玄狐二号")
    third = add_pet(game, "baize", "白泽三号")
    return second, third


def roster(game):
    return tuple(row["pet_id"] for row in sql(
        game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot",
    ))


def slot_rows(game, slot):
    return sorted(row["quest_id"] for row in sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?",
        (f"lineup_preset_{slot}%",),
    ))


def test_page_without_a_pet_is_read_only(game, play):
    page = play("lineup_presets", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_three_empty_slots(game, play):
    ready(game, play)
    page = play("lineup_presets")
    assert "预设 1：空" in page.text()
    assert "预设 3：空" in page.text()
    assert {link.command for link in page.inline_commands} == {f"灵宠出战预设 保存 {n}" for n in (1, 2, 3)}


def test_saving_snapshots_the_roster_without_switching(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="two")
    current = roster(game)
    reply = play("lineup_presets", "保存 2", op="save")
    assert reply.title == "预设已保存"
    assert lineup_presets.stored(ctx_of(game), 2) == current
    assert roster(game) == current


def test_saving_refuses_an_empty_roster_and_bad_slots(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="格式"):
        play("lineup_presets", "保存 4")
    with pytest.raises(GameError, match="格式"):
        play("lineup_presets", "保存")
    # roster emptied behind the player's back
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="没有出战阵容"):
        play("lineup_presets", "保存 1")


def test_applying_switches_the_roster(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair")
    play("lineup_presets", "保存 1", op="save-1")
    first = roster(game)[0]
    play("lineup", str(first), op="solo")
    assert roster(game) == (first,)
    reply = play("lineup_presets", "应用 1", op="apply-1")
    assert reply.title == "预设已应用"
    assert roster(game) == (second, third)


def test_applying_the_current_roster_is_a_no_op(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-2")
    play("lineup_presets", "保存 1", op="save-2")
    reply = play("lineup_presets", "应用 1", op="apply-2")
    assert "与当前阵容一致" in reply.text()
    assert roster(game) == (second, third)


def test_applying_an_empty_slot_is_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未保存"):
        play("lineup_presets", "应用 3")


def test_a_sealed_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-3")
    play("lineup_presets", "保存 1", op="save-3")
    play("lineup", str(second), op="keep-one")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (third,))
    with pytest.raises(GameError, match="已封存"):
        play("lineup_presets", "应用 1")
    assert roster(game) == (second,)


def test_an_expedition_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-4")
    play("lineup_presets", "保存 1", op="save-4")
    play("lineup", str(second), op="solo-4")
    play("expedition_start", "采灵药", op="trip", now=NOW)
    with pytest.raises(GameError, match="派遣"):
        play("lineup_presets", "应用 1", now=NOW + 10)


def test_a_removed_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-5")
    play("lineup_presets", "保存 1", op="save-5")
    play("lineup", str(second), op="solo-5")
    sql(game[1], "DELETE FROM pets WHERE pet_id=?", (third,))
    with pytest.raises(GameError, match="不在名册"):
        play("lineup_presets", "应用 1")
    assert roster(game) == (second,)


def test_clearing_removes_only_that_slot(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-6")
    play("lineup_presets", "保存 1", op="save-6a")
    play("lineup_presets", "保存 2", op="save-6b")
    before = roster(game)
    reply = play("lineup_presets", "清除 1", op="clear-1")
    assert reply.title == "预设已清除"
    assert slot_rows(game, 1) == []
    assert slot_rows(game, 2)
    assert roster(game) == before
    with pytest.raises(GameError, match="尚未保存"):
        play("lineup_presets", "清除 1")


def test_saving_over_a_slot_replaces_members(game, play):
    second, third = ready(game, play)
    first = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' AND name='青鸾'")[0]["pet_id"]
    play("lineup", str(first), op="one")
    play("lineup_presets", "保存 1", op="save-old")
    play("lineup", f"{second} {third}", op="two")
    play("lineup_presets", "保存 1", op="save-new")
    assert lineup_presets.stored(ctx_of(game), 1) == (second, third)
    assert slot_rows(game, 1) == sorted([
        "lineup_preset_1",
        f"lineup_preset_1_{second}",
        f"lineup_preset_1_{third}",
    ])


def test_objective_help_and_parse(game, play):
    second, third = ready(game, play)
    assert "出战预设：尚未保存" in play("objectives").text()
    play("lineup_presets", "保存 1", op="obj")
    assert "出战预设：已保存 1/3" in play("objectives").text()
    assert "灵宠出战预设" in play("help", "结契").text()
    assert handlers._parse("灵宠出战预设") == ("lineup_presets", "")
    assert handlers._parse("灵宠出战预设 应用 2") == ("lineup_presets", "应用 2")


def test_same_operation_replays_identically(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-7")
    first_reply = play("lineup_presets", "保存 1", op="replay-save")
    again = play("lineup_presets", "保存 1", op="replay-save")
    assert again.text() == first_reply.text()
    assert len(slot_rows(game, 1)) == 3


def test_state_survives_a_restart(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-8")
    play("lineup_presets", "保存 3", op="restart")
    assert "可应用" in play("lineup_presets").text()
    assert lineup_presets.stored(ctx_of(game), 3) == (second, third)


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("lineup_presets")
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
