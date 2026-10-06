import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.qq.event import C2CMessageCreateEvent, GroupAtMessageCreateEvent

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.storage.database import Store


def onebot_event(text="灵宠帮助", message_id=1):
    return GroupMessageEvent.model_validate({
        "time": 1800000000, "self_id": 9000, "post_type": "message",
        "message_type": "group", "sub_type": "normal", "message_id": message_id,
        "group_id": 8000, "user_id": 12345, "message": text, "raw_message": text,
        "font": 0, "sender": {"user_id": 12345, "nickname": "tester"},
    })


def qq_event(user_id="12345", group=True, text="灵宠帮助", message_id="2"):
    data = {
        "id": message_id, "content": text, "timestamp": "2026-10-07T00:00:00+08:00",
        "author": {"id": user_id, "user_openid": user_id, "member_openid": user_id,
                   "bot": False, "member_role": "member"},
        "group_id": "group", "group_openid": "group",
    }
    cls = GroupAtMessageCreateEvent if group else C2CMessageCreateEvent
    return cls.model_validate(data)


def test_parse_only_recognizes_exact_commands():
    assert handlers._parse("/灵宠帮助") == ("help", "")
    assert handlers._parse("灵宠领养 青鸾") == ("adopt", "青鸾")
    assert handlers._parse("/灵宠购买 灵粮 3") == ("buy", "灵粮 3")
    assert handlers._parse("灵宠图鉴") == ("catalog", "")
    assert handlers._parse("灵宠图鉴 2") == ("catalog", "2")
    assert handlers._parse("灵宠图鉴 青鸾") == ("catalog", "青鸾")
    assert handlers._parse("灵宠强化 灵器") == ("enhance", "灵器")
    assert handlers._parse("灵宠签到后的聊天") is None
    assert handlers._parse("灵宠论剑 清风散人") == ("pvp", "清风散人")
    assert handlers._parse("我的道号") == ("identity", "")
    assert handlers._parse("灵宠装备 青岚翎") == ("equipment", "青岚翎")
    assert handlers._parse("灵宠学习 风刃术") == ("learn", "风刃术")
    assert handlers._parse("灵宠身份") is None


def test_real_adapter_events_share_ids_not_account_bindings(tmp_path, monkeypatch):
    store = Store(tmp_path / "shared.db")
    store.initialize()
    monkeypatch.setattr(handlers, "game", Game(store, Config()))
    bot1 = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    bot2 = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def run():
        await handlers._run(bot1, onebot_event(), "灵宠领养 青鸾")
        await handlers._run(bot2, qq_event(), "我的灵宠")
        assert "青鸾" in str(bot2.send.call_args.args[1])
        await handlers._run(bot2, qq_event("different-id", message_id="3"), "我的灵宠")
        assert "尚未结契" in str(bot2.send.call_args.args[1])

    asyncio.run(run())


def test_event_dedupe_key_keeps_adapter_and_session_not_player_identity():
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"))
    assert handlers._operation_id(bot, onebot_event()) == handlers._operation_id(bot, onebot_event())
    event = onebot_event()
    event.group_id = 999
    assert handlers._operation_id(bot, event) != handlers._operation_id(bot, onebot_event())


def test_real_qq_group_and_c2c_event_contracts():
    for event in (qq_event(), qq_event(group=False)):
        assert event.get_user_id() == "12345"
        assert event.get_plaintext() == "灵宠帮助"
    assert nonebot.get_driver().config.driver == "~fastapi+~httpx+~websockets"
