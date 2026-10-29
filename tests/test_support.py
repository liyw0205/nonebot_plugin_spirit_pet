"""Support roster: slots, eligibility, stat lending, readiness and persistence."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import SupportRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import pet_stats
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000


def stats(game, user="u1", pet_id=None):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "support-stats")
        return combatant(ctx, pet_id=pet_id).stats if pet_id else combatant(ctx).stats


def add_pet(game, user, species, name, *, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, 0, 1, 0, 0, 0, 100, ?, ?)",
        (user, species, name, NOW, archived),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def slots(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'support_%'"
        " ORDER BY quest_id",
        (user,),
    )


def base_stats_of(game, pet_id):
    with closing(game[1].connect()) as conn:
        return pet_stats(Repository(conn).pet(pet_id), game[0].content)


def test_rules_define_two_slots_and_a_ten_percent_rate(game):
    rule = game[0].content.rules.support
    assert (rule.slots, rule.rate) == (2, 0.1)
    with pytest.raises(ValidationError):
        SupportRule(slots=4, rate=0.1)
    with pytest.raises(ValidationError):
        SupportRule(slots=2, rate=0.6)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("support", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_starts_empty_and_excludes_the_deployed_pet(game, play):
    play("adopt", "青鸾")
    page = play("support")
    assert "助战席 0/2" in page.text()
    assert "1 席：空" in page.text() and "2 席：空" in page.text()
    assert "当前没有可担任助战的伙伴" in page.text()
    assert page.inline_commands == ()


def test_candidates_show_contribution_and_a_slot_link(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    page = play("support")
    assert "小狐 · 气血 +" in page.text()
    assert {link.command for link in page.inline_commands} == {"灵宠助战 设置 1 小狐"}


def test_assigning_binds_the_pet_and_reports_the_bonus(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    reply = play("support", "设置 1 小狐")
    assert "1 席已设为小狐" in reply.text()
    assert [row["quest_id"] for row in slots(game)] == ["support_1"]
    page = play("support")
    assert "1 席：小狐 · 气血 +" in page.text()
    assert "助战席 1/2" in page.text()
    assert "助战：1/2 席" in play("objectives").text()


def test_the_bonus_is_ten_percent_of_the_support_pets_base_stats(game, play):
    play("adopt", "青鸾")
    fox = add_pet(game, "u1", "xuanhu", "小狐")
    before = stats(game)
    play("support", "设置 1 小狐")
    after = stats(game)
    base = base_stats_of(game, fox)
    assert after.hp == before.hp + int(base.hp * 0.1)
    assert after.attack == before.attack + int(base.attack * 0.1)
    assert after.defense == before.defense + int(base.defense * 0.1)
    assert after.speed == before.speed + int(base.speed * 0.1)


def test_a_non_active_pet_gets_no_support_bonus(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    third = add_pet(game, "u1", "baize", "小泽")
    before = stats(game, pet_id=third)
    play("support", "设置 1 小狐")
    after = stats(game, pet_id=third)
    assert (after.hp, after.attack, after.defense, after.speed) == (
        before.hp, before.attack, before.defense, before.speed,
    )


def test_two_support_pets_stack(game, play):
    play("adopt", "青鸾")
    fox = add_pet(game, "u1", "xuanhu", "小狐")
    crane = add_pet(game, "u1", "baize", "小泽")
    before = stats(game)
    play("support", "设置 1 小狐")
    play("support", "设置 2 小泽")
    after = stats(game)
    expected = int(base_stats_of(game, fox).attack * 0.1) + int(base_stats_of(game, crane).attack * 0.1)
    assert after.attack == before.attack + expected


def test_the_active_pet_cannot_be_a_support(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="已在出战阵容"):
        play("support", "设置 1 青鸾")


def test_archived_and_expedition_pets_are_refused(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "旧友", archived=1)
    with pytest.raises(GameError, match="封存"):
        play("support", "设置 1 旧友")
    lead = pet(game[1])["pet_id"]
    crane = add_pet(game, "u1", "baize", "小泽")
    play("lineup", str(crane))
    play("expedition_start", "采灵药")
    play("lineup", str(lead))
    with pytest.raises(GameError, match="外出派遣"):
        play("support", "设置 1 小泽")


def test_unknown_names_slots_and_duplicates_are_refused(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    with pytest.raises(GameError, match="没有找到"):
        play("support", "设置 1 无名")
    with pytest.raises(GameError, match="只有 2 席"):
        play("support", "设置 3 小狐")
    play("support", "设置 1 小狐")
    with pytest.raises(GameError, match="已在 1 席"):
        play("support", "设置 2 小狐")
    with pytest.raises(GameError, match="格式"):
        play("support", "设置 1")


def test_clearing_removes_the_slot_and_the_bonus(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    before = stats(game)
    play("support", "设置 1 小狐")
    assert stats(game).attack > before.attack
    reply = play("support", "清除 1")
    assert "1 席已清空" in reply.text()
    assert stats(game).attack == before.attack
    assert slots(game) == []
    with pytest.raises(GameError, match="空的"):
        play("support", "清除 1")


def test_changing_a_slot_clears_team_readiness(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    sql(game[1], "INSERT INTO teams(leader_id) VALUES ('u1')")
    sql(
        game[1],
        "INSERT INTO team_members(user_id, team_id, ready_pet_id, ready_pet_ids) VALUES ('u1', 1, NULL, ?)",
        (str(pet(game[1])["pet_id"]),),
    )
    play("support", "设置 1 小狐")
    assert sql(game[1], "SELECT ready_pet_ids FROM team_members WHERE user_id='u1'")[0]["ready_pet_ids"] == ""


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    play("support", "设置 1 小狐")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "support", "", "restart-support", NOW)
    assert "1 席：小狐" in page.text()
    assert "助战席 1/2" in page.text()


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    first = play("support", "设置 1 小狐", op="support-op")
    again = play("support", "设置 1 小狐", op="support-op")
    assert again.text() == first.text()
    assert len(slots(game)) == 1


def test_help_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "成长")
    assert "灵宠助战" in guide.text()
    assert handlers._parse("灵宠助战") == ("support", "")
    assert handlers._parse("灵宠助战 设置 1 小狐") == ("support", "设置 1 小狐")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "小狐")
    page = play("support")
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
