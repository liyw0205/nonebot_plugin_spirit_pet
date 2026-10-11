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

from .team_support import UIDS, USERS, create_players, memberships, requests


def team_replies(play):
    create_players(play, count=6)
    replies = [play("team_create", user=USERS[0])]
    for index in range(1, 6):
        if index % 2:
            replies.append(play("team_join", UIDS[0], user=USERS[index]))
        else:
            replies.append(play("team_invite", UIDS[index], user=USERS[0]))
    replies.extend((
        play("team_requests", user=USERS[0]),
        play("team_requests", "分页 2", user=USERS[0]),
        play("team_requests", UIDS[1], user=USERS[0]),
        play("team_requests", UIDS[0], user=USERS[1]),
        play("team_requests", UIDS[2], user=USERS[0]),
        play("team_requests", UIDS[0], user=USERS[2]),
        play("team_accept", UIDS[1], user=USERS[0]),
        play("team_reject", UIDS[3], user=USERS[0]),
        play("team_withdraw", UIDS[2], user=USERS[0]),
        play("team_status", user=USERS[0]),
        play("team_status", user=USERS[1]),
        play("team_status", UIDS[1], user=USERS[0]),
        play("team_status", UIDS[0], user=USERS[1]),
        play("team_kick", UIDS[1], user=USERS[0]),
    ))
    play("team_join", UIDS[0], user=USERS[1])
    play("team_accept", UIDS[1], user=USERS[0])
    replies.append(play("team_transfer", UIDS[1], user=USERS[0]))
    replies.append(play("team_leave", user=USERS[0]))
    replies.append(play("team_disband", user=USERS[1]))
    return replies


def keyboard_buttons(message):
    keyboard = message["keyboard"][0].data["keyboard"].content
    assert 1 <= len(keyboard.rows) <= 4
    assert all(1 <= len(row.buttons) <= 2 for row in keyboard.rows)
    return [button for row in keyboard.rows for button in row.buttons]


@pytest.mark.parametrize("mode", ["native", "template"])
@pytest.mark.parametrize("prefix", ["/", "!", ""])
def test_actual_team_replies_preserve_uid_button_payloads(play, monkeypatch, mode, prefix):
    config = Config(
        spirit_pet_qq_mode=mode,
        spirit_pet_qq_template_id="test.team-template",
        spirit_pet_qq_template_param="team_content",
        spirit_pet_command_prefix=prefix,
    )
    monkeypatch.setattr(handlers, "config", config)
    exposed_actions = set()
    for reply in team_replies(play):
        fallback, message = _qq_segments(reply, config)
        buttons = keyboard_buttons(message)
        assert len(buttons) <= 4
        assert len({button.id for button in buttons}) == len(buttons)
        assert "private-platform-account" not in fallback
        assert "private-platform-account" not in str(message)
        for button in buttons:
            command = button.action.data.removeprefix(prefix)
            assert command in reply.commands
            name, _, argument = command.partition(" ")
            expected = COMMANDS[name], argument
            assert button.action.type == 2
            assert button.action.enter is True and button.action.reply is True
            assert handlers._parse(button.action.data) == expected
            exposed_actions.add(expected[0])
        markdown = message["markdown"][0].data["markdown"]
        if mode == "native":
            links = re.findall(r"\]\((mqqapi://[^)]+)\)", markdown.content)
            inline_commands = {action.command for action in reply.inline_commands}
            for link in links:
                query = parse_qs(urlparse(link).query)
                command = query["command"][0].removeprefix(prefix)
                assert command in inline_commands
                assert query["enter"] == [str(not command.endswith((" ", "\t"))).lower()]
                assert query["reply"] == ["false"]
                assert handlers._parse(query["command"][0]) == handlers._parse(prefix + command)
        else:
            assert markdown.custom_template_id == config.spirit_pet_qq_template_id
            assert markdown.params[0].key == "team_content"
            assert markdown.params[0].values == [fallback]
            assert "mqqapi" not in fallback
    assert {
        "team_accept", "team_reject", "team_withdraw", "team_kick", "team_transfer",
        "team_disband", "team_status", "team_requests", "team_leave",
    } <= exposed_actions


def qq_command_event(user_id, content, message_id, group):
    event_type = GroupAtMessageCreateEvent if group else C2CMessageCreateEvent
    return event_type.model_validate({
        "id": message_id, "content": content, "timestamp": "2026-10-07T00:00:00+08:00",
        "group_id": "team-test-group", "group_openid": "team-test-group",
        "author": {
            "id": user_id, "user_openid": user_id, "member_openid": user_id,
            "bot": False, "member_role": "member",
        },
    })


@pytest.mark.parametrize("mode", ["native", "template"])
@pytest.mark.parametrize("group", [False, True], ids=["c2c", "group"])
@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_qq_approval_button_roundtrip_enforces_actor_and_message_dedupe(game, play, monkeypatch, mode, group, kind):
    create_players(play, count=2)
    play("team_create", user=USERS[0])
    now = int(time.time())
    if kind == "apply":
        play("team_join", UIDS[0], user=USERS[1], now=now)
        recipient, sender, target = 0, 1, UIDS[1]
    else:
        play("team_invite", UIDS[1], user=USERS[0], now=now)
        recipient, sender, target = 1, 0, UIDS[0]
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.team-template")
    monkeypatch.setattr(handlers, "config", config)
    monkeypatch.setattr(handlers, "game", game[0])
    detail = play("team_requests", target, user=USERS[recipient], now=now)
    _, message = _qq_segments(detail, config)
    approval = next(
        button.action.data for button in keyboard_buttons(message)
        if handlers._parse(button.action.data) == ("team_accept", target)
    )
    bot = SimpleNamespace(
        self_id="team-test-app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )
    before = requests(game[1])

    async def run():
        unauthorized = qq_command_event(USERS[sender], approval, "wrong-actor", group)
        assert await handlers._is_command(unauthorized, unauthorized.get_message())
        await handlers._run(bot, unauthorized, handlers._plain_text(unauthorized))
        assert len(memberships(game[1])) == 1
        assert requests(game[1]) == before
        assert "private-platform-account" not in str(bot.send.call_args.args[1])

        authorized = qq_command_event(USERS[recipient], approval, "correct-actor", group)
        assert handlers._parse(handlers._plain_text(authorized)) == ("team_accept", target)
        await handlers._run(bot, authorized, handlers._plain_text(authorized))
        sent = bot.send.call_args.args[1]
        assert len(sent["markdown"]) == len(sent["keyboard"]) == 1
        assert "private-platform-account" not in str(sent)
        assert {row["user_id"] for row in memberships(game[1])} == set(USERS[:2])
        assert not requests(game[1])

        await handlers._run(bot, authorized, handlers._plain_text(authorized))
        assert bot.send.call_args.args[1] == sent
        assert len(memberships(game[1])) == 2
        assert not requests(game[1])

    asyncio.run(run())
