"""Alchemy: farm produce and materials become the pills the shop only sells."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.alchemy_content import AlchemyRecipe
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import alchemy
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
    return sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)


def ready(game, play, *, stones=5000, stock=4):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1'")
    for item_id in {item for entry in recipes(game) for item in entry.materials}:
        grant(game, item_id, stock)


def test_content_declares_four_pill_recipes(game):
    rows = recipes(game)
    assert [row.id for row in rows] == ["energy_draught", "bond_pill", "spirit_elixir", "breakthrough_elixir"]
    for row in rows:
        assert row.item_id in game[0].content.items
        assert game[0].content.items[row.item_id].kind in {"consumable", "breakthrough"}
        assert row.item_id not in row.materials


def test_recipe_validation_rejects_self_consumption():
    base = {
        "id": "x", "name": "试", "description": "d", "item_id": "energy_pill",
        "stones": 10, "materials": {"spirit_food": 1}, "yield": 1,
    }
    assert AlchemyRecipe.model_validate(base).yield_ == 1
    with pytest.raises(ValidationError, match="own product"):
        AlchemyRecipe.model_validate({**base, "materials": {"energy_pill": 1}})
    with pytest.raises(ValidationError):
        AlchemyRecipe.model_validate({**base, "yield": 0})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("alchemy", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_recipes_costs_and_effects(game, play):
    ready(game, play)
    page = play("alchemy")
    first = recipes(game)[0]
    assert first.name in page.text()
    assert "精力 +" in page.text()
    assert "灵石" in page.text()
    assert {link.command for link in page.inline_commands} == {
        f"灵宠炼丹 {entry.name}" for entry in recipes(game)
    }


def test_missing_materials_hide_the_link(game, play):
    ready(game, play)
    first = recipes(game)[0]
    missing = sorted(first.materials)[0]
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id=?", (missing,))
    page = play("alchemy")
    assert "暂不可炼" in page.text()
    assert f"灵宠炼丹 {first.name}" not in {link.command for link in page.inline_commands}


def test_brewing_consumes_materials_and_yields_the_pill(game, play):
    ready(game, play)
    first = recipes(game)[0]
    stones = player(game[1])["stones"]
    reply = play("alchemy", first.name, op="brew")
    assert reply.title == "炼丹完成"
    for item_id, need in first.materials.items():
        assert owned(game, item_id) == 4 - need
    assert owned(game, first.item_id) == first.yield_
    assert player(game[1])["stones"] == stones - first.stones


def test_batch_brewing_scales_everything(game, play):
    ready(game, play)
    first = recipes(game)[0]
    stones = player(game[1])["stones"]
    play("alchemy", f"{first.name} 2", op="batch")
    for item_id, need in first.materials.items():
        assert owned(game, item_id) == 4 - need * 2
    assert owned(game, first.item_id) == first.yield_ * 2
    assert player(game[1])["stones"] == stones - first.stones * 2


def test_material_shortage_writes_nothing(game, play):
    ready(game, play)
    first = recipes(game)[0]
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id=?",
        (next(iter(first.materials)),))
    with pytest.raises(GameError, match="材料不足"):
        play("alchemy", first.name)
    assert owned(game, first.item_id) == 0
    assert player(game[1])["stones"] == 5000


def test_stone_shortage_writes_nothing(game, play):
    ready(game, play, stones=0)
    first = recipes(game)[0]
    with pytest.raises(GameError, match="灵石不足"):
        play("alchemy", first.name)
    assert owned(game, first.item_id) == 0


def test_batch_shortage_is_all_or_nothing(game, play):
    ready(game, play, stock=1)
    first = recipes(game)[0]
    with pytest.raises(GameError, match="材料不足"):
        play("alchemy", f"{first.name} 2")
    assert owned(game, first.item_id) == 0
    assert owned(game, next(iter(first.materials))) == 1


def test_unknown_recipe_and_bad_amount_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("alchemy", "不存在的丹方")
    with pytest.raises(GameError, match="数量"):
        play("alchemy", f"{recipes(game)[0].name} 100")


def test_the_pill_is_usable_after_brewing(game, play):
    ready(game, play)
    first = recipes(game)[0]
    play("alchemy", first.name, op="use-brew")
    energy = sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")[0]["energy"]
    sql(game[1], "UPDATE pets SET energy=10 WHERE user_id='u1'")
    reply = play("use", ctx_of(game).content.items[first.item_id].name, op="use")
    assert "精力" in reply.text()
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")[0]["energy"] > 10
    assert energy >= 0


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "炼丹：" in play("objectives").text()
    assert "灵宠炼丹" in play("help", "血脉与道具").text()
    assert handlers._parse("灵宠炼丹") == ("alchemy", "")
    assert handlers._parse("灵宠炼丹 回元丹 2") == ("alchemy", "回元丹 2")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    first = recipes(game)[0]
    original = play("alchemy", first.name, op="replay")
    stones = player(game[1])["stones"]
    again = play("alchemy", first.name, op="replay")
    assert again.text() == original.text()
    assert player(game[1])["stones"] == stones
    assert owned(game, first.item_id) == first.yield_


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("alchemy")
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
