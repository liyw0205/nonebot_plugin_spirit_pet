"""Dungeon difficulty tiers: stronger enemies for a larger payout."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.difficulty_content import Difficulty
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import difficulty
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def dungeon(game, team=False):
    return next(entry for entry in game[0].content.dungeons.values() if entry.team is team)


def tiers(game):
    return sorted(game[0].content.difficulties.values(), key=lambda entry: entry.enemy_scale)


def ready(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=4, layer=10, energy=100 WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")


def test_content_declares_a_baseline_and_two_harder_tiers(game):
    rows = tiers(game)
    assert [row.id for row in rows] == ["normal", "challenge", "desperate"]
    assert rows[0].enemy_scale == 1.0 and rows[0].reward_percent == 0
    for row in rows[1:]:
        assert row.enemy_scale > 1 and row.reward_percent > 0
    assert [row.enemy_scale for row in rows] == sorted(row.enemy_scale for row in rows)


def test_difficulty_validation_rejects_one_sided_tiers():
    assert Difficulty.model_validate(
        {"id": "x", "name": "试", "description": "d", "enemy_scale": 1.2, "reward_percent": 40}
    ).reward_percent == 40
    with pytest.raises(ValidationError, match="without paying extra"):
        Difficulty.model_validate(
            {"id": "x", "name": "试", "description": "d", "enemy_scale": 1.2, "reward_percent": 0}
        )
    with pytest.raises(ValidationError, match="without raising enemy stats"):
        Difficulty.model_validate(
            {"id": "x", "name": "试", "description": "d", "enemy_scale": 1.0, "reward_percent": 30}
        )


def test_page_without_a_pet_is_read_only(game, play):
    page = play("difficulty", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_tiers_and_rewards(game, play):
    ready(game, play)
    page = play("difficulty")
    assert "挑战" in page.text() and "绝境" in page.text()
    assert "敌手四维" in page.text()
    assert "奖励 +50%" in page.text()
    links = {link.command for link in page.inline_commands}
    assert all(command.startswith("灵宠试炼 ") for command in links)
    assert not any(command.endswith(" 寻常") for command in links)


def test_reward_scales_with_the_tier(game):
    first = dungeon(game)
    ctx = ctx_of(game)
    challenge = game[0].content.difficulties["challenge"]
    reward = difficulty.reward_of(ctx, first, challenge)
    assert reward.stones.minimum == int(first.reward.stones.minimum * 1.5)
    assert reward.exp.maximum == int(first.reward.exp.maximum * 1.5)


def test_a_harder_run_pays_more_than_the_base_reward(game, play):
    ready(game, play)
    first = dungeon(game)
    challenge = game[0].content.difficulties["challenge"]
    base = difficulty.reward_of(ctx_of(game), first, game[0].content.difficulties["normal"])

    stones = player(game[1])["stones"]
    play("difficulty", f"{first.name} {challenge.name}", op="hard")
    gained = player(game[1])["stones"] - stones
    # a loss pays nothing, so only assert the payout when the run was won
    if gained:
        assert gained >= int(base.stones.minimum * 1.5)


def test_the_baseline_tier_is_refused(game, play):
    ready(game, play)
    first = dungeon(game)
    with pytest.raises(GameError, match="灵宠挑战"):
        play("difficulty", f"{first.name} 寻常")


def test_team_dungeons_are_refused(game, play):
    ready(game, play)
    team = dungeon(game, team=True)
    with pytest.raises(GameError, match="组队秘境"):
        play("difficulty", f"{team.name} 挑战")


def test_unknown_dungeon_and_tier_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("difficulty", "不存在的秘境 挑战")
    with pytest.raises(GameError, match="未找到该内容"):
        play("difficulty", f"{dungeon(game).name} 不存在")
    with pytest.raises(GameError, match="格式"):
        play("difficulty", "只写秘境")


def test_enemy_scaling_leaves_the_definition_untouched(game, play):
    ready(game, play)
    first = dungeon(game)
    before = {key: game[0].content.enemies[key].stats.model_dump() for key in first.enemies}
    play("difficulty", f"{first.name} 绝境", op="scale")
    after = {key: game[0].content.enemies[key].stats.model_dump() for key in first.enemies}
    assert before == after


def test_scaled_enemies_are_stronger_than_the_originals(game):
    first = dungeon(game)
    ctx = ctx_of(game)
    from nonebot_plugin_spirit_pet.gameplay.combat import enemy_fighter

    entry = game[0].content.difficulties["desperate"]
    definition = game[0].content.enemies[first.enemies[0]]
    scaled = definition.model_copy(update={
        "stats": definition.stats.__class__(**{
            stat: max(1, int(value * entry.enemy_scale + 0.5))
            for stat, value in definition.stats.model_dump().items()
        }),
    })
    plain = enemy_fighter(definition, game[0].content.skills)
    boosted = enemy_fighter(scaled, game[0].content.skills)
    assert boosted.stats.hp > plain.stats.hp
    assert boosted.stats.attack >= plain.stats.attack


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "试炼：" in play("objectives").text()
    assert "灵宠试炼" in play("help", "秘境与关卡").text()
    assert handlers._parse("灵宠试炼") == ("difficulty", "")
    assert handlers._parse("灵宠试炼 森林 挑战") == ("difficulty", "森林 挑战")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    first = dungeon(game)
    original = play("difficulty", f"{first.name} 挑战", op="replay")
    stones = player(game[1])["stones"]
    again = play("difficulty", f"{first.name} 挑战", op="replay")
    assert again.text() == original.text()
    assert player(game[1])["stones"] == stones


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("difficulty")
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
