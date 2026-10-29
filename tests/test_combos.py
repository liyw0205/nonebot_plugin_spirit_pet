"""Skill combos: page states, per-pet stat bonus and content validation."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.combo_content import Combo
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import combos
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, sql

NOW = 1_800_000_000


def stats(game, user="u1", pet_id=None):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "read-combo")
        target = pet_id
        if target is None:
            player = ctx.repo.player(user)
            target = player.active_pet_id
        return combatant(ctx, user, pet_id=target).stats


def learn(game, skill_id, user="u1", equipped=1):
    row = pet(game[1], user)
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, ?, 1, 0)"
        " ON CONFLICT(pet_id, skill_id) DO UPDATE SET equipped=excluded.equipped",
        (row["pet_id"], skill_id, equipped),
    )


def ready(game, play, species="青鸾", user="u1"):
    play("adopt", species, user=user)
    sql(game[1], "UPDATE pets SET realm=5, layer=10, bloodline=4 WHERE user_id=?", (user,))


def test_content_declares_six_combos(game):
    rows = list(game[0].content.combos.values())
    assert [row.id for row in rows] == [
        "windfire_pair", "thunder_pair", "frost_pair", "wood_pair", "metal_pair", "earth_pair",
    ]
    assert all(len(row.skills) == 2 and row.skills[0] != row.skills[1] for row in rows)
    assert all(skill in game[0].content.skills for row in rows for skill in row.skills)
    assert all(sum(row.bonuses.model_dump().values()) <= 0.15 for row in rows)


def test_combo_validator_rejects_duplicates_and_oversized_bonuses():
    base = {
        "id": "pair", "name": "成对", "description": "测试", "skills": ["fireball", "windfire"],
        "bonuses": {"attack": 0.05},
    }
    assert Combo.model_validate(base).bonuses.attack == 0.05
    with pytest.raises(ValidationError, match="two different skills"):
        Combo.model_validate({**base, "skills": ["fireball", "fireball"]})
    with pytest.raises(ValidationError, match="at most 15%"):
        Combo.model_validate({**base, "bonuses": {"attack": 0.1, "defense": 0.1}})
    with pytest.raises(ValidationError, match="not all be zero"):
        Combo.model_validate({**base, "bonuses": {}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("combos", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_all_six_combos_as_unmatched(game, play):
    ready(game, play)
    page = play("combos")
    assert "青鸾：已连携 0/6 组" in page.text()
    for combo in game[0].content.combos.values():
        assert combo.name in page.text()
    assert "木灵相济：青木回春 + 青藤鞭 → 气血 +5%，防御 +4% · 未集齐（缺 青木回春、青藤鞭）" in page.text()
    assert page.inline_commands == ()


def test_one_equipped_skill_names_its_missing_partner(game, play):
    ready(game, play)
    learn(game, "wood_heal")
    page = play("combos")
    assert "木灵相济：青木回春 + 青藤鞭 → 气血 +5%，防御 +4% · 未集齐（缺 青藤鞭）" in page.text()
    assert "青鸾：已连携 0/6 组" in page.text()


def test_both_skills_mark_the_combo(game, play):
    ready(game, play)
    learn(game, "wood_heal")
    learn(game, "vine_lash")
    page = play("combos")
    assert "青鸾：已连携 1/6 组" in page.text()
    assert "木灵相济：青木回春 + 青藤鞭 → 气血 +5%，防御 +4% · 已连携" in page.text()


def test_combat_stats_include_the_combo(game, play):
    ready(game, play)
    before = stats(game)
    learn(game, "wood_heal")
    learn(game, "vine_lash")
    after = stats(game)
    assert after.hp == int(before.hp * 1.05 + 0.5)
    assert after.defense == int(before.defense * 1.04 + 0.5)
    assert (after.attack, after.speed) == (before.attack, before.speed)


def test_one_skill_alone_changes_nothing(game, play):
    ready(game, play)
    before = stats(game)
    learn(game, "wood_heal")
    assert stats(game) == before


def test_apply_stacks_in_content_order(game):
    service = game[0]
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, "u1", NOW, "combo-stack")
        plain = {"hp": 1000, "attack": 1000, "defense": 1000, "speed": 1000}
        once = combos.apply(ctx, dict(plain), ["wind_slash", "fireball"])
        assert once["attack"] == int(1000 * 1.05 + 0.5)
        assert once["speed"] == int(1000 * 1.03 + 0.5)
        both = combos.apply(ctx, dict(plain), ["wind_slash", "fireball", "metal_edge", "spirit_dispel"])
        assert both["attack"] == int(int(1000 * 1.05 + 0.5) * 1.04 + 0.5)
        assert both["speed"] == int(int(1000 * 1.03 + 0.5) * 1.04 + 0.5)


def test_the_bonus_belongs_to_the_pet_that_equipped_the_pair(game, play):
    ready(game, play, user="u1")
    ready(game, play, user="u2")
    learn(game, "wood_heal", user="u1")
    learn(game, "vine_lash", user="u1")
    assert stats(game, "u1").defense > stats(game, "u2").defense


def test_unequipping_a_skill_removes_the_combo(game, play):
    ready(game, play)
    learn(game, "wood_heal")
    learn(game, "vine_lash")
    assert "已连携 1/6" in play("combos").text()
    learn(game, "vine_lash", equipped=0)
    page = play("combos")
    assert "已连携 0/6" in page.text()
    assert "未集齐（缺 青藤鞭）" in page.text()
    assert sql(game[1], "SELECT * FROM quest_progress") == []


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "连携：已连携 0/6" in play("objectives").text()
    learn(game, "wood_heal")
    learn(game, "vine_lash")
    assert "连携：已连携 1/6" in play("objectives").text()
    assert "灵宠连携" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠连携") == ("combos", "")


def test_page_rejects_arguments(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="格式"):
        play("combos", "额外")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("combos")
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
    assert linked == set()
    assert not linked & buttons
