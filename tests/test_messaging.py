import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments, inline_command, qq_keyboard, send_reply
from nonebot_plugin_spirit_pet.domain.models import Reply


def test_qq_blue_link_uses_an_encoded_command_with_no_accidental_execution():
    link = inline_command("灵宠修炼", "灵宠修炼")
    parsed = urlparse(link.removeprefix("[").split("](", 1)[1][:-1])
    assert parsed.scheme == "mqqapi"
    assert parsed.netloc == "aio"
    assert parse_qs(parsed.query) == {
        "command": ["/灵宠修炼"],
        "enter": ["false"],
        "reply": ["false"],
    }


def test_qq_markdown_keyboard_and_raw_text_are_built_from_the_same_reply():
    pytest.importorskip("nonebot.adapters.qq")
    reply = Reply("山海小宠", ("精力 100/100", "亲密 20/100"))
    config = Config(spirit_pet_qq_mode="native", spirit_pet_qq_keyboard=True)
    fallback, message = _qq_segments(reply, config)

    assert "【山海小宠】" in fallback
    assert "[我的灵宠](mqqapi://aio/inlinecmd?" in message["markdown"][0].data["markdown"].content
    assert len(message["keyboard"]) == 1
    assert message["keyboard"][0].data["keyboard"].content.rows[0].buttons[0].action.data == "/我的灵宠"


@pytest.mark.parametrize("command,encoded", [
    ("灵宠分解 青岚翎 +2 1", "%2B2%201"),
    ("灵宠赛季领奖 2028-01", "2028-01"),
    ("灵宠论剑榜 2028-01 分页 2", "2028-01%20"),
])
def test_structured_arguments_survive_blue_links_and_keyboard(command, encoded):
    reply = Reply("灵物工坊", (), (command,))
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    markdown = message["markdown"][0].data["markdown"].content
    assert encoded in markdown
    button = message["keyboard"][0].data["keyboard"].content.rows[0].buttons[0]
    assert button.action.data == "/" + command
    link = inline_command(command, command)
    assert parse_qs(urlparse(link.split("](")[1][:-1]).query)["command"] == ["/" + command]


def test_qq_text_mode_needs_no_rich_message_permission():
    pytest.importorskip("nonebot.adapters.qq")
    reply = Reply("灵宠仙途", ("欢迎道友",))
    fallback, message = _qq_segments(reply, Config(spirit_pet_qq_mode="text"))

    assert "欢迎道友" in fallback
    assert len(message["keyboard"]) == 0
    assert str(message) == fallback


def test_keyboard_is_created_only_for_known_safe_commands():
    pytest.importorskip("nonebot.adapters.qq")
    keyboard = qq_keyboard(("我的灵宠", "灵宠签到"))
    button = keyboard.data["keyboard"].content.rows[0].buttons[0]
    assert button.action.permission.type == 2
    assert button.action.reply is True
    assert button.action.enter is True

    with pytest.raises(ValueError):
        inline_command("攻击", "灵宠签到\n恶意指令")


def test_template_uses_configured_id_and_preserves_all_content():
    reply = Reply("灵宠", ("很长的文本" * 200,))
    config = Config(spirit_pet_qq_mode="template", spirit_pet_qq_template_id="123.456")
    fallback, message = _qq_segments(reply, config)
    markdown = message["markdown"][0].data["markdown"]
    assert markdown.custom_template_id == "123.456"
    assert markdown.params[0].key == "content"
    assert markdown.params[0].values == [fallback]
    assert "mqqapi" not in fallback


def test_onebot_never_gets_qq_segments():
    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    reply = Reply("测试", ("灵石 +200",))
    asyncio.run(send_reply(bot, object(), reply, Config(spirit_pet_qq_mode="native")))
    assert bot.send.call_args.args[1] == reply.text()


def test_native_markdown_escapes_untrusted_fields():
    reply = Reply("[name](https://invalid)", ("*unsafe* [link](mqqapi://aio/inlinecmd)",))
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_qq_blue_links=False))
    content = message["markdown"][0].data["markdown"].content
    assert "\\[name\\]" in content
    assert "\\*unsafe\\*" in content
    assert "[我的灵宠]" not in content


@pytest.mark.parametrize("status,retry", [(400, True), (403, True), (422, True), (429, False), (500, False)])
def test_qq_fallback_only_retries_explicit_rejections(status, retry):
    from nonebot.adapters.qq.exception import ActionFailed
    from nonebot.drivers import Response

    error = ActionFailed(Response(status, content='{"code":123,"message":"rejected"}'))
    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(side_effect=[error, None]))
    reply = Reply("测试", ("修为 +30",))
    action = send_reply(bot, object(), reply, Config(spirit_pet_qq_mode="native"))
    if retry:
        asyncio.run(action)
        assert bot.send.await_count == 2
        assert "修为 +30" in bot.send.call_args.args[1]
    else:
        with pytest.raises(ActionFailed):
            asyncio.run(action)
        assert bot.send.await_count == 1


def test_network_timeout_does_not_duplicate_qq_messages():
    from nonebot.adapters.qq.exception import NetworkError

    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(side_effect=NetworkError("timeout")))
    with pytest.raises(NetworkError):
        asyncio.run(send_reply(bot, object(), Reply("测试", ("结果",)), Config(spirit_pet_qq_mode="native")))
    assert bot.send.await_count == 1


def test_real_qq_send_retains_message_id_and_increments_fallback_sequence():
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo
    from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
    from nonebot.adapters.qq.exception import ActionFailed
    from nonebot.drivers import Response

    bot = Bot(Adapter(nonebot.get_driver()), "app", BotInfo(id="app", secret="test-only", token="test-token"))
    event = GroupAtMessageCreateEvent.model_validate({
        "id": "incoming", "content": "灵宠帮助", "timestamp": "2026-10-07T00:00:00+08:00",
        "group_id": "group", "group_openid": "group",
        "author": {"id": "player", "member_openid": "player", "bot": False, "member_role": "member"},
    })
    bot.post_group_messages = AsyncMock(side_effect=[ActionFailed(Response(403)), {}])
    asyncio.run(send_reply(bot, event, Reply("测试", ("奖励",)), Config(spirit_pet_qq_mode="native")))
    first, second = bot.post_group_messages.call_args_list
    assert first.kwargs["msg_id"] == second.kwargs["msg_id"] == "incoming"
    assert first.kwargs["msg_seq"] == 1 and second.kwargs["msg_seq"] == 2
    assert first.kwargs["msg_type"] == 2 and second.kwargs["msg_type"] == 0
