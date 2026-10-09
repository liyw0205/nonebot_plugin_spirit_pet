"""The WS smoke and QQ event models exercise the same persisted lineup flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.smoke_test import run_multi_pet_chain
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.core.config import Config

from .test_commands import qq_event


@pytest.mark.parametrize("mode", ["text", "native", "template"])
@pytest.mark.parametrize("group", [False, True], ids=["c2c", "group"])
def test_real_qq_events_execute_multi_pet_chain(game, monkeypatch, mode, group):
    service, store = game
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.lineup")
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", config)
    bot = SimpleNamespace(
        self_id="lineup-test-app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )
    responses = {}

    async def send(user_id, message_id, command, expected):
        event = qq_event(str(user_id), group=group, text="/" + command, message_id=f"lineup-{message_id}")
        assert await handlers._is_command(event, event.get_message())
        await handlers._run(bot, event, handlers._plain_text(event))
        reply = bot.send.call_args.args[1]
        assert expected in str(reply), str(reply)
        assert all(str(user) not in str(reply) for user in (41001, 41002, 41003, 41004))
        if mode != "text" and not isinstance(reply, str):
            assert len(reply["markdown"]) == 1
            for row in reply["keyboard"][0].data["keyboard"].content.rows:
                for button in row.buttons:
                    assert handlers._parse(button.action.data) is not None
        if message_id in responses:
            assert reply == responses[message_id]
        responses[message_id] = reply
        return reply

    def exchange(*arguments):
        return asyncio.run(send(*arguments))

    run_multi_pet_chain(store.path, exchange, "nonebot_plugin_spirit_pet")
