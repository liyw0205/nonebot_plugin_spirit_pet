"""The WS smoke and QQ event models exercise the same persisted lineup flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.core.config import Config

from .test_commands import qq_event


@pytest.mark.parametrize("mode", ["text", "native", "template"])
@pytest.mark.parametrize("group", [False, True], ids=["c2c", "group"])
def test_qq_response_modes_route_short_help_command(game, monkeypatch, mode, group):
    service, _ = game
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.lineup")
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", config)
    bot = SimpleNamespace(
        self_id="lineup-test-app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )
    event = qq_event("41001", group=group, text="/灵宠帮助", message_id="lineup-help")

    async def run():
        assert await handlers._is_command(event, event.get_message())
        await handlers._run(bot, event, handlers._plain_text(event))

    asyncio.run(run())
    bot.send.assert_awaited_once()
    assert bot.send.call_args.args[0] is event
    reply = bot.send.call_args.args[1]
    assert "灵宠" in str(reply)
    if mode == "text":
        assert isinstance(reply, str)
    else:
        assert len(reply["markdown"]) == 1
