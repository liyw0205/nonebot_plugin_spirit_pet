import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .test_commands import onebot_event


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


def test_catalog_page_links_detail_on_each_species(game, play):
    first = play("catalog")
    assert len(first.inline_commands) == 5
    assert {link.label for link in first.inline_commands} == {"查看详情"}
    for link in first.inline_commands:
        species_name = first.lines[link.line].split(" · ", 1)[0]
        assert link.command == f"灵宠图鉴 {species_name}"
    # Detail links leave the button set; summon/roster/pagination stay as page actions.
    assert "灵宠召唤" in first.commands and "灵宠列表" in first.commands and "灵宠图鉴 2" in first.commands
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert len(button_commands) <= 4
    assert not button_commands & {link.command for link in first.inline_commands}


def test_catalog_detail_links_starter_adoption_and_pool_summon(game, play):
    starter = play("catalog", "青鸾")
    assert starter.inline_commands[0].label == "结契该族"
    assert starter.inline_commands[0].command == "灵宠领养 青鸾"
    assert starter.inline_commands[0].line == 5

    pool = play("catalog", "毕方")
    assert pool.inline_commands[0].label == "寻访该族"
    # Non-starters only prefill 灵宠召唤 (trailing space asks QQ to fill, not send).
    assert pool.inline_commands[0].command == "灵宠召唤 "
    assert pool.inline_commands[0].line == 5

    _, message = _qq_segments(starter, Config(spirit_pet_qq_mode="native"))
    links = markdown_links(message)
    assert links == [("结契该族", "/灵宠领养 青鸾"), ("查看掉落秘境", "/灵宠秘境")]
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert "灵宠召唤" in button_commands


def test_catalog_link_reaches_detail_for_late_species(game, play):
    page = play("catalog", "6")
    assert page.inline_commands
    detail = play("catalog", page.inline_commands[-1].command.removeprefix("灵宠图鉴 "))
    assert detail.title.startswith("万灵图鉴 ·")
    assert "天赋神通" in detail.text()


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_catalog_adopt_from_detail_link(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    detail = play("catalog", "青鸾")
    _, message = _qq_segments(detail, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.catalog",
    ))
    if mode == "native":
        assert markdown_links(message) == [
            ("结契该族", "/灵宠领养 青鸾"), ("查看掉落秘境", "/灵宠秘境"),
        ]
    adopted = play("adopt", "青鸾")
    assert adopted.title == "领养成功"


def test_onebot_catalog_keeps_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠图鉴", 1), "!灵宠图鉴")
        listing = bot.send.call_args.args[1]
        assert "查看详情（!灵宠图鉴 青鸾）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠图鉴 青鸾", 2), "!灵宠图鉴 青鸾")
        detail = bot.send.call_args.args[1]
        assert "结契该族（!灵宠领养 青鸾）" in detail

    asyncio.run(run())
