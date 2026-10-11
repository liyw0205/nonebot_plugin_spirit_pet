import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def own_species(game, species_id: str, user: str = "u1") -> None:
    species = game[0].content.species[species_id]
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species_id, species.name, NOW),
    )


def prepare_wind_resonance(game, play) -> None:
    play("adopt", "青鸾")
    own_species(game, "hanying")
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 2)",
    )


def keyboard_buttons(message):
    return [
        button
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def markdown_links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def test_resonance_catalog_and_detail_keep_state_read_only_and_contextual(game, play):
    play("adopt", "青鸾")
    before = player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM player_resonance")

    catalog = play("resonance")
    detail_links = [link for link in catalog.inline_commands if link.label == "查看详情"]
    assert len(detail_links) == 5
    assert {link.line for link in detail_links} == set(range(5))
    assert all(link.command in catalog.commands for link in detail_links)
    assert "灵宠共鸣 查看 青岚双翼" in catalog.text()

    detail = play("resonance", "查看 青岚双翼")
    assert len(detail.inline_commands) == 1
    assert detail.inline_commands[0].line == 3
    assert detail.inline_commands[0].command == "灵宠图鉴"
    assert "启用共鸣" not in detail.text()
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM player_resonance")) == before


def test_resonance_activation_and_deactivation_keep_replayable_context(game, play):
    prepare_wind_resonance(game, play)

    detail = play("resonance", "青岚双翼")
    assert detail.inline_commands[0].command == "灵宠共鸣 激活 青岚双翼"
    activated = play("resonance", "激活 青岚双翼", op="activate-wind")
    assert activated.inline_commands[0].command == "灵宠共鸣 查看 青岚双翼"
    assert sql(game[1], "SELECT resonance_id FROM player_resonance")[0]["resonance_id"] == "wind_wings"
    assert player(game[1])["stones"] == 800
    assert items(game[1])["bloodline_essence"] == 1
    assert play("resonance", "激活 青岚双翼", op="activate-wind") == activated

    stopped = play("resonance", "停用")
    assert stopped.inline_commands[0].command == "灵宠共鸣"
    assert not sql(game[1], "SELECT * FROM player_resonance")
    with pytest.raises(GameError, match="没有启用"):
        play("resonance", "停用")


@pytest.mark.parametrize("prefix", ["", "!"])
def test_qq_resonance_catalog_uses_links_for_details_and_buttons_for_navigation(game, play, prefix):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    reply = play("resonance")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))

    buttons = keyboard_buttons(message)
    assert [button.action.data for button in buttons] == [prefix + "灵宠共鸣 2"]
    assert [button.render_data.label for button in buttons] == ["共鸣第 2 页"]
    links = markdown_links(message)
    assert [command for _, command in links] == [prefix + command for command in reply.commands[:5]]
    assert not set(command for _, command in links) & {button.action.data for button in buttons}
    assert all(not button.render_data.label.startswith("/") for button in buttons)


def test_qq_resonance_detail_keeps_complete_activation_in_context_without_duplicate_button(game, play):
    pytest.importorskip("nonebot.adapters.qq")
    prepare_wind_resonance(game, play)
    reply = play("resonance", "青岚双翼")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))

    buttons = keyboard_buttons(message)
    assert [button.action.data for button in buttons] == ["!灵宠共鸣"]
    assert [button.render_data.label for button in buttons] == ["查看共鸣"]
    assert markdown_links(message) == [("启用共鸣", "!灵宠共鸣 激活 青岚双翼")]


def test_onebot_resonance_flow_keeps_contextual_commands_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        own_species(game, "hanying", user="12345")
        sql(store, "UPDATE players SET stones=1000 WHERE user_id='12345'")
        sql(
            store,
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('12345', 'bloodline_essence', 2)",
        )
        await handlers._run(bot, onebot_event("!灵宠共鸣", 2), "!灵宠共鸣")
        catalog = bot.send.call_args.args[1]
        assert "查看详情（!灵宠共鸣 查看 青岚双翼）" in catalog
        assert "mqqapi://" not in catalog
        await handlers._run(bot, onebot_event("!灵宠共鸣 青岚双翼", 3), "!灵宠共鸣 青岚双翼")
        detail = bot.send.call_args.args[1]
        assert "启用共鸣（!灵宠共鸣 激活 青岚双翼）" in detail

    asyncio.run(run())
