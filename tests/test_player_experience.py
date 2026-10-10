import asyncio
import re
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments, send_reply
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, InlineCommand, Reply
from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql
from .test_commands import onebot_event, qq_event


def test_onebot_first_adoption_identity_pet_selection_and_use(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config())
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: 1800000000)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        commands = ("灵宠帮助", "我的信息", "灵宠领养 青鸾", "我的信息", "我的宠", "灵宠出战 1", "灵宠修炼")
        for index, command in enumerate(commands):
            event = onebot_event(command, index + 1)
            await handlers.handle_command(bot, event, event.get_message())
            if index < 2:
                assert not sql(store, "SELECT * FROM players")

    asyncio.run(run())
    replies = [call.args[1] for call in bot.send.call_args_list]
    allocated = player(store, "12345")
    assert f"你的道号：{allocated['dao_name']}。" in replies[2]
    assert "已自动出战" in replies[2]
    assert allocated["registered_at"] == 1800000000
    assert "注册时间：2027-01-15 16:00:00（UTC+8）" in replies[3]
    assert "平台用户 ID：12345" in replies[3]
    assert "道号" not in replies[4]
    assert "当前出战：青鸾（1）" in replies[4]
    assert "吐纳修炼" in replies[-1]
    assert sql(store, "SELECT * FROM active_pet_slots")[0]["pet_id"] == 1


@pytest.mark.parametrize("action", ["status", "train", "switch", "dao_name", "bag", "use", "challenge", "team_join"])
def test_registered_features_guide_to_real_first_adoption_without_writing(game, play, action):
    with pytest.raises(GameError) as rejected:
        play(action)
    reply = rejected.value.reply
    assert reply and "首次领养" in reply.text()
    assert reply.inline_commands[0].command == "灵宠领养 "
    assert reply.inline_commands[0].label == "开始领养"
    assert not reply.commands
    assert not sql(game[1], "SELECT * FROM players")
    assert not sql(game[1], "SELECT * FROM operations")


def clear_active(store):
    sql(store, "DELETE FROM active_pet_slots")
    sql(store, "UPDATE players SET active_pet_id=NULL")


def test_target_owner_missing_account_or_active_pet_does_not_guide_requester(game, play):
    service, store = game
    play("adopt", user="requester")
    play("adopt", user="registered-target")
    sql(store, "DELETE FROM active_pet_slots WHERE user_id=?", ("registered-target",))
    sql(store, "UPDATE players SET active_pet_id=NULL WHERE user_id=?", ("registered-target",))

    with closing(store.connect()) as conn:
        ctx = Context(
            Repository(conn), service.content, service.config, service.rng,
            "requester", 1_800_000_000, "owner-check",
        )
        for operation in (
            lambda: ctx.player("unregistered-target"),
            lambda: ctx.pet("unregistered-target"),
            lambda: ctx.active_pets("unregistered-target"),
        ):
            with pytest.raises(GameError) as rejected:
                operation()
            assert str(rejected.value) == "对方尚未结契，当前无法继续。"
            assert "unregistered-target" not in str(rejected.value)
            assert rejected.value.reply is None
        for operation in (
            lambda: ctx.pet("registered-target"),
            lambda: ctx.active_pets("registered-target"),
        ):
            with pytest.raises(GameError) as rejected:
                operation()
            assert str(rejected.value) == "对方尚未选择出战灵宠，当前无法继续。"
            assert "registered-target" not in str(rejected.value)
            assert rejected.value.reply is None


def test_contextual_reply_links_survive_idempotent_cache_and_read_legacy_rows(game):
    _, store = game
    expected = Reply(
        "选择伙伴", ("去名册看看。",), (),
        (InlineCommand(0, "查看名册", "灵宠列表"),),
    )
    first = store.transact("cache-user", "inline-reply", 1_800_000_000, lambda _: expected)
    second = store.transact(
        "cache-user", "inline-reply", 1_800_000_001,
        lambda _: pytest.fail("idempotent reply was not replayed"),
    )
    assert first == second == expected
    old = Reply.from_data({"title": "旧回复", "lines": ["内容"], "commands": []})
    assert old.inline_commands == ()


def test_account_only_features_work_without_an_active_pet(game, play):
    play("adopt", "青鸾")
    clear_active(game[1])
    info = play("identity")
    assert "出战伙伴：0 只" in info.text() and "未记录" not in info.text()
    play("dao_name", "听雨散人")
    assert "听雨散人" in play("identity").text()
    assert play("dao_name").title == "修改道号"
    assert play("bag").title == "乾坤袋"
    assert play("sign").title == "今日仙缘"
    with pytest.raises(GameError) as rejected:
        play("status")
    assert not rejected.value.reply.commands
    assert [action.command for action in rejected.value.reply.inline_commands] == ["灵宠列表", "灵宠出战 "]
    assert "领养" not in rejected.value.reply.text()
    _, message = _qq_segments(rejected.value.reply, Config(spirit_pet_qq_mode="native"))
    markdown = message["markdown"][0].data["markdown"].content
    assert "[查看灵宠名册](mqqapi://aio/inlinecmd?" in markdown
    assert "[填写出战编号](mqqapi://aio/inlinecmd?" in markdown
    assert not message["keyboard"]
    sql(game[1], "UPDATE pets SET archived=1")
    with pytest.raises(GameError) as archived:
        play("train")
    assert "灵宠封存库" in tuple(action.command for action in archived.value.reply.inline_commands)


def test_registration_time_survives_rename_replay_expiry_and_restart(game, play):
    initial = play("adopt", "青鸾", now=1234567890, op="first-adoption")
    assert play("adopt", "青鸾", now=1234567899, op="first-adoption") == initial
    play("dao_name", "听雨散人", now=1234567900)
    play("identity", now=1234567999)
    sql(game[1], "DELETE FROM operations")
    with pytest.raises(GameError, match="已与灵宠结契"):
        play("adopt", now=1234568000, op="first-adoption")
    Store(game[1].path).initialize()
    assert player(game[1])["registered_at"] == 1234567890
    assert player(game[1])["dao_name"] == "听雨散人"


@pytest.mark.parametrize("prefix", ["", "/", "!"])
@pytest.mark.parametrize("section", ["", *_HELP_SECTIONS])
def test_native_help_links_prefill_near_descriptions_without_keyboards(play, prefix, section):
    reply = play("help", section)
    fallback, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))
    markdown = message["markdown"][0].data["markdown"].content
    assert not message["keyboard"]
    assert not markdown.startswith("#") and "\n> " not in markdown
    assert "我的道号" not in markdown + fallback and "固定前缀" not in markdown
    links = re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    assert links
    expected = {command for _, command, _ in _HELP_SECTIONS[section]} if section else {f"灵宠帮助 {name}" for name in _HELP_SECTIONS}
    payloads = set()
    for label, url in links:
        assert not label.startswith("/")
        params = parse_qs(urlparse(url).query)
        assert params["enter"] == [str(not params["command"][0].endswith((" ", "\t"))).lower()]
        assert params["reply"] == ["false"]
        payloads.add(params["command"][0])
        assert f"]({url}) · " in markdown
    assert {prefix + command for command in expected} <= payloads
    if section:
        assert payloads == {prefix + command for command in expected | {"灵宠帮助"}}
        assert all(label in fallback and description in fallback for label, _, description in _HELP_SECTIONS[section])


def test_qq_native_first_adoption_and_guidance_use_the_real_outgoing_payload(game, play, monkeypatch):
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo
    import nonebot

    # One real SDK send per affected Reply, no second QQ business chain.
    adopted = play("adopt", "青鸾", user="opaque-platform-id")
    config = Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!")
    bot = Bot(Adapter(nonebot.get_driver()), "test-app", BotInfo(id="test-app", secret="test-only", token="test-only"))
    bot.post_group_messages = AsyncMock(return_value={})
    event = qq_event(user_id="opaque-platform-id")
    asyncio.run(send_reply(bot, event, adopted, config))
    payload = bot.post_group_messages.call_args.kwargs
    assert payload["msg_type"] == 2
    markdown = payload["markdown"].content
    assert f"**你的道号：{player(game[1], 'opaque-platform-id')['dao_name']}。**" in markdown
    assert "已自动出战" in markdown
    assert "[我的信息](mqqapi://" in markdown
    info = play("identity", user="opaque-platform-id")
    fallback, info_message = _qq_segments(info, config)
    assert "平台用户 ID：opaque-platform-id" in fallback
    assert "[修改道号](mqqapi://" in info_message["markdown"][0].data["markdown"].content
    pet_reply = play("status", user="opaque-platform-id")
    _, pet_message = _qq_segments(pet_reply, config)
    assert "道号" not in pet_reply.text()
    assert "修改道号" not in pet_message["markdown"][0].data["markdown"].content
    assert all("灵宠道号" not in button.action.data for row in pet_message["keyboard"][0].data["keyboard"].content.rows for button in row.buttons)
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", config)
    asyncio.run(handlers._run(bot, qq_event(user_id="new-user", message_id="prerequisite"), "我的灵宠"))
    guide = bot.post_group_messages.call_args.kwargs
    assert guide["msg_type"] == 2 and "初遇灵宠" in guide["markdown"].content
    assert "[开始领养](mqqapi://aio/inlinecmd?" in guide["markdown"].content
    assert not sql(game[1], "SELECT * FROM players WHERE user_id='new-user'")
    assert "keyboard" not in guide


def test_help_template_text_and_disabled_links_keep_examples_without_help_keyboard(play):
    reply = play("help", "成长")
    for config in (Config(spirit_pet_qq_mode="text"), Config(spirit_pet_qq_mode="template", spirit_pet_qq_template_id="test"), Config(spirit_pet_qq_mode="native", spirit_pet_qq_blue_links=False)):
        fallback, message = _qq_segments(reply, config)
        assert "灵宠修炼 编号" in fallback and "不填编号" in fallback
        assert not message["keyboard"]
