import asyncio
import importlib
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .support import pet, player, sql
from .test_commands import onebot_event, qq_event


@pytest.mark.parametrize("command,action,argument", [
    ("灵宠委托", "expedition_catalog", "采灵药"),
    ("灵宠派遣", "expedition_start", "采灵药"),
    ("灵宠行程", "expedition_status", "17"),
    ("灵宠归来", "expedition_claim", "17"),
    ("灵宠召回", "expedition_cancel", "17"),
])
def test_expedition_command_arguments(command, action, argument):
    assert handlers._parse(f"/{command} {argument}") == (action, argument)
    assert handlers._parse(command) == (action, "")
    assert handlers._parse(command + "之后聊天") is None


@pytest.mark.parametrize("mode", ["native", "template"])
def test_expedition_views_buttons_and_blue_links_roundtrip(game, play, mode):
    play("adopt", "青鸾")
    now = 1_800_000_000
    replies = [play("expedition_catalog"), play("expedition_catalog", "采灵药"), play("expedition_status")]
    replies.append(play("expedition_start", "采灵药", now=now))
    job = sql(game[1], "SELECT * FROM expeditions")[0]
    key = str(job["job_id"])
    replies.append(play("expedition_status", key, now=now))
    complete = play("expedition_status", key, now=job["finishes_at"])
    assert f"灵宠归来 {key}" in complete.commands
    assert not any(command.startswith("灵宠召回") for command in complete.commands)
    replies.append(complete)
    replies.append(play("expedition_claim", key, now=job["finishes_at"]))
    replies.append(play("expedition_status", key, now=job["finishes_at"]))
    for reply in replies:
        _, message = _qq_segments(reply, Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.expedition"))
        buttons = [button for row in message["keyboard"][0].data["keyboard"].content.rows for button in row.buttons]
        assert len(buttons) == len(reply.commands) <= 8
        for command, button in zip(reply.commands, buttons):
            assert button.action.data == "/" + command
            assert handlers._parse(button.action.data) == handlers._parse(command)
        if mode == "native":
            links = re.findall(r"\]\((mqqapi://[^)]+)\)", message["markdown"][0].data["markdown"].content)
            assert [parse_qs(urlparse(link).query)["command"][0] for link in links] == ["/" + cmd for cmd in reply.commands]


@pytest.mark.parametrize("mode", ["text", "native", "template"])
@pytest.mark.parametrize("group", [False, True])
def test_onebot_dispatch_qq_return_uses_raw_identity_and_never_regrants(game, monkeypatch, mode, group):
    service, store = game
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.expedition")
    monkeypatch.setattr(handlers, "config", config)
    monkeypatch.setattr(handlers, "game", service)
    clock = [1_800_000_000]
    monkeypatch.setattr(importlib.import_module("nonebot_plugin_spirit_pet.application.game").time, "time", lambda: clock[0])
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def run():
        await handlers._run(onebot, onebot_event(message_id=100), "灵宠领养 青鸾")
        await handlers._run(onebot, onebot_event(message_id=101), "灵宠派遣 采灵药")
        assert "灵宠启程" in str(onebot.send.call_args.args[1])
        job = sql(store, "SELECT * FROM expeditions")[0]
        assert job["user_id"] == "12345"
        clock[0] = job["finishes_at"]
        foreign = qq_event("different-id", group=group, message_id="foreign")
        await handlers._run(qq, foreign, "灵宠领养 玄狐")
        await handlers._run(qq, qq_event("different-id", group=group, message_id="deny"), f"灵宠归来 {job['job_id']}")
        assert "没有属于你的" in str(qq.send.call_args.args[1])
        assert sql(store, "SELECT state FROM expeditions")[0]["state"] == "running"
        event = qq_event("12345", group=group, message_id="return")
        await handlers._run(qq, event, f"灵宠归来 {job['job_id']}")
        message = qq.send.call_args.args[1]
        assert "委托归来" in str(message) and "12345" not in str(message)
        assert sql(store, "SELECT state FROM expeditions")[0]["state"] == "claimed"
        before = player(store, "12345"), pet(store, "12345")
        await handlers._run(qq, event, f"灵宠归来 {job['job_id']}")
        assert qq.send.call_args.args[1] == message
        assert (player(store, "12345"), pet(store, "12345")) == before
        assert player(store, "different-id")["stones"] == 100

    asyncio.run(run())


def test_expedition_duration_config_boundaries():
    assert Config().spirit_pet_expedition_duration == 3600
    assert Config(spirit_pet_expedition_duration="1").spirit_pet_expedition_duration == 1
    for value in (0, -1, "invalid"):
        with pytest.raises(ValidationError):
            Config(spirit_pet_expedition_duration=value)
