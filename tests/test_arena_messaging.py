import asyncio
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from nonebot.adapters.qq.event import C2CMessageCreateEvent, GroupAtMessageCreateEvent

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config

from .support import pet, sql

USERS = ("private-arena-first", "private-arena-second")
NAMES = ("青云道友", "归元道友")


def prepare(game, play, now):
    for user, name in zip(USERS, NAMES):
        play("adopt", "青鸾", user=user, now=now)
        play("dao_name", name, user=user, now=now)
    sql(game[1], "UPDATE pets SET realm=1")


def buttons(message):
    keyboard = message["keyboard"][0].data["keyboard"].content
    assert 1 <= len(keyboard.rows) <= 4
    assert all(1 <= len(row.buttons) <= 2 for row in keyboard.rows)
    return [button for row in keyboard.rows for button in row.buttons]


def event(user, command, message_id, group):
    event_type = GroupAtMessageCreateEvent if group else C2CMessageCreateEvent
    return event_type.model_validate({
        "id": message_id, "content": command, "timestamp": "2026-10-07T00:00:00+08:00",
        "group_id": "arena-test-group", "group_openid": "arena-test-group",
        "author": {
            "id": user, "user_openid": user, "member_openid": user,
            "bot": False, "member_role": "member",
        },
    })


@pytest.mark.parametrize("mode", ["native", "template"])
@pytest.mark.parametrize("prefix", ["/", "!", ""])
def test_real_arena_views_preserve_names_and_season_ids_in_buttons_and_links(game, play, monkeypatch, mode, prefix):
    now = 1_800_000_000
    prepare(game, play, now)
    config = Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.arena-template",
        spirit_pet_qq_template_param="arena_content", spirit_pet_command_prefix=prefix,
    )
    monkeypatch.setattr(handlers, "config", config)
    replies = [play(action, user=USERS[0], now=now) for action in ("season", "season_rewards", "pvp_rank", "match")]
    replies.append(play("pvp", NAMES[1], user=USERS[0], now=now))
    replies.append(play("pvp", user=USERS[1], now=now))
    replies.append(play("spar", NAMES[0], user=USERS[1], now=now))
    exposed = set()
    for reply in replies:
        fallback, message = _qq_segments(reply, config)
        keyboard = buttons(message)
        assert len(keyboard) == len(reply.commands) <= 8
        assert "private-arena" not in fallback + str(message)
        for command, button in zip(reply.commands, keyboard):
            name, _, argument = command.partition(" ")
            expected = (COMMANDS[name], argument)
            assert button.render_data.label == command
            assert button.action.type == 2
            assert button.action.enter and button.action.reply
            assert button.action.data == prefix + command
            assert handlers._parse(button.action.data) == expected
            exposed.add(expected[0])
            if expected[0] == "pvp":
                assert argument in NAMES
        markdown = message["markdown"][0].data["markdown"]
        if mode == "native":
            links = re.findall(r"\]\((mqqapi://[^)]+)\)", markdown.content)
            assert len(links) == len(reply.commands)
            for command, link in zip(reply.commands, links):
                query = parse_qs(urlparse(link).query)
                assert query == {
                    "command": [prefix + command],
                    "enter": [str(not command.endswith((" ", "\t"))).lower()],
                    "reply": ["false"],
                }
                assert handlers._parse(query["command"][0]) == handlers._parse(prefix + command)
        else:
            assert markdown.custom_template_id == "test.arena-template"
            assert markdown.params[0].key == "arena_content"
            assert markdown.params[0].values == [fallback]
    assert {"season", "pvp_rank", "pvp", "match"} <= exposed
    assert "灵宠应战" not in COMMANDS and "灵宠拒战" not in COMMANDS and "灵宠战帖" not in COMMANDS


@pytest.mark.parametrize("mode", ["native", "template"])
@pytest.mark.parametrize("group", [False, True], ids=["c2c", "group"])
@pytest.mark.parametrize("battle_mode", ["spar", "pvp"])
def test_qq_direct_challenge_roundtrip_only_charges_actor_and_deduplicates(game, play, monkeypatch, mode, group, battle_mode):
    now = int(time.time())
    prepare(game, play, now)
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: now)
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.arena-template")
    monkeypatch.setattr(handlers, "config", config)
    monkeypatch.setattr(handlers, "game", game[0])
    candidates = play("match", user=USERS[0], now=now)
    _, message = _qq_segments(candidates, config)
    challenge = next(
        button.action.data for button in buttons(message)
        if handlers._parse(button.action.data) == ("pvp", NAMES[1])
    )
    if battle_mode == "spar":
        challenge = "/灵宠切磋 " + NAMES[1]
    bot = SimpleNamespace(
        self_id="arena-test-app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )
    before = [pet(game[1], user) for user in USERS]

    async def send(user, command, message_id):
        incoming = event(user, command, message_id, group)
        assert await handlers._is_command(incoming, incoming.get_message())
        await handlers._run(bot, incoming, handlers._plain_text(incoming))
        sent = bot.send.call_args.args[1]
        assert "private-arena" not in str(sent)
        return sent

    async def run():
        rejected = await send(USERS[1], challenge, "self-challenge")
        assert "自己" in str(rejected)
        assert [pet(game[1], user) for user in USERS] == before
        assert not sql(game[1], "SELECT * FROM pvp_results")

        sent = await send(USERS[0], challenge, "challenge-once")
        assert len(sent["markdown"]) == len(sent["keyboard"]) == 1
        expected_energy = 80 if battle_mode == "pvp" else 100
        after = [pet(game[1], user) for user in USERS]
        assert after[0]["energy"] == expected_energy
        assert after[1] == before[1]
        assert len(sql(game[1], "SELECT * FROM pvp_results")) == (1 if battle_mode == "pvp" else 0)
        assert await send(USERS[0], challenge, "challenge-once") == sent
        assert [pet(game[1], user) for user in USERS] == after
        if battle_mode == "pvp":
            denied = await send(USERS[0], challenge, "second-challenge")
            assert "调息" in str(denied)
            assert [pet(game[1], user) for user in USERS] == after

    asyncio.run(run())
