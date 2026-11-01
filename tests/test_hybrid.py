"""Seed hybridisation: two seeds plus stones make a seed no shop sells."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.hybrid_content import Hybrid
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import hybrid
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def grant(game, item_id, amount=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def owned(game, item_id, user="u1"):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user, item_id))
    return rows[0]["quantity"] if rows else 0


def recipes(game):
    return sorted(game[0].content.hybrids.values(), key=lambda entry: entry.stones)


def ready(game, play, *, stones=5000):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    for entry in recipes(game):
        for seed in entry.seeds:
            grant(game, seed, 2)


def test_content_declares_two_recipes_with_distinct_seeds(game):
    rows = recipes(game)
    assert [row.id for row in rows] == ["frost_wheat", "crimson_lotus"]
    for row in rows:
        assert len(row.seeds) == 2 and row.seeds[0] != row.seeds[1]
        assert row.output not in row.seeds
        assert row.output in game[0].content.items
        assert any(crop.seed_item == row.output for crop in game[0].content.crops.values())


def test_hybrid_validation_rejects_identical_or_self_output():
    base = {"id": "x", "name": "试", "description": "d", "seeds": ["a", "b"], "stones": 10, "output": "c"}
    assert Hybrid.model_validate(base).stones == 10
    with pytest.raises(ValidationError, match="two different seeds"):
        Hybrid.model_validate({**base, "seeds": ["a", "a"]})
    with pytest.raises(ValidationError, match="new seed"):
        Hybrid.model_validate({**base, "output": "a"})
    with pytest.raises(ValidationError):
        Hybrid.model_validate({**base, "stones": 0})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("hybrid", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_recipes_costs_and_readiness(game, play):
    ready(game, play)
    page = play("hybrid")
    first = recipes(game)[0]
    assert first.name in page.text()
    assert "灵石" in page.text()
    assert "可调配" in page.text()
    assert {link.command for link in page.inline_commands} == {
        f"灵宠杂交 {entry.name}" for entry in recipes(game)
    }


def test_missing_seeds_are_reported_and_block_the_link(game, play):
    ready(game, play)
    first = recipes(game)[0]
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id=?", (first.seeds[0],))
    page = play("hybrid")
    assert "暂不可配" in page.text()
    assert f"灵宠杂交 {first.name}" not in {link.command for link in page.inline_commands}


def test_brewing_consumes_inputs_and_yields_the_seed(game, play):
    ready(game, play)
    first = recipes(game)[0]
    stones = player(game[1])["stones"]
    reply = play("hybrid", first.name, op="brew")
    assert reply.title == "杂交完成"
    for seed in first.seeds:
        assert owned(game, seed) == 1
    assert owned(game, first.output) == 1
    assert player(game[1])["stones"] == stones - first.stones


def test_the_output_cannot_be_bought(game):
    content = game[0].content
    for entry in recipes(game):
        assert content.items[entry.output].price is None


def test_stone_shortage_writes_nothing(game, play):
    ready(game, play, stones=0)
    first = recipes(game)[0]
    with pytest.raises(GameError, match="灵石不足"):
        play("hybrid", first.name)
    for seed in first.seeds:
        assert owned(game, seed) == 2
    assert owned(game, first.output) == 0


def test_seed_shortage_writes_nothing(game, play):
    ready(game, play)
    first = recipes(game)[0]
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id=?", (first.seeds[1],))
    with pytest.raises(GameError, match="种子不足"):
        play("hybrid", first.name)
    assert owned(game, first.seeds[0]) == 2
    assert owned(game, first.output) == 0


def test_unknown_recipe_and_format_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("hybrid", "不存在的配方")
    assert owned(game, recipes(game)[0].output) == 0


def test_the_hybrid_crop_can_be_planted_and_harvested(game, play):
    ready(game, play)
    first = recipes(game)[0]
    play("hybrid", first.name, op="plant-brew")
    play("farm_open", "1", op="open")
    output = game[0].content.items[first.output]
    play("farm_plant", f"1 {output.name}", op="plant")
    crop = next(crop for crop in game[0].content.crops.values() if crop.seed_item == first.output)
    reply = play("farm_harvest", "1", op="harvest", now=NOW + crop.duration + 1)
    assert crop.name in reply.text()
    assert owned(game, first.output) == 0


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "杂交：" in play("objectives").text()
    assert "灵宠杂交" in play("help", "血脉与道具").text()
    assert handlers._parse("灵宠杂交") == ("hybrid", "")
    assert handlers._parse("灵宠杂交 霜纹麦") == ("hybrid", "霜纹麦")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    first = recipes(game)[0]
    original = play("hybrid", first.name, op="replay")
    stones = player(game[1])["stones"]
    again = play("hybrid", first.name, op="replay")
    assert again.text() == original.text()
    assert player(game[1])["stones"] == stones
    assert owned(game, first.output) == 1


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("hybrid")
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
