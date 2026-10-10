import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    C2CMsgReceiveEvent,
    GroupAtMessageCreateEvent,
    GroupMessageCreateEvent,
    GroupMsgReceiveEvent,
)

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import sql


def onebot_event(text="灵宠帮助", message_id=1):
    return GroupMessageEvent.model_validate({
        "time": 1800000000, "self_id": 9000, "post_type": "message",
        "message_type": "group", "sub_type": "normal", "message_id": message_id,
        "group_id": 8000, "user_id": 12345, "message": text, "raw_message": text,
        "font": 0, "sender": {"user_id": 12345, "nickname": "tester"},
    })


def qq_event(user_id="12345", group=True, text="灵宠帮助", message_id="2", event_class=None):
    data = {
        "id": message_id, "content": text, "timestamp": "2026-10-07T00:00:00+08:00",
        "author": {"id": user_id, "user_openid": user_id, "member_openid": user_id,
                   "bot": False, "member_role": "member"},
        "group_id": "group", "group_openid": "group",
    }
    cls = event_class or (GroupAtMessageCreateEvent if group else C2CMessageCreateEvent)
    return cls.model_validate(data)


def test_parse_only_recognizes_exact_commands():
    assert handlers._parse("/灵宠帮助") == ("help", "")
    assert handlers._parse("灵宠领养 青鸾") == ("adopt", "青鸾")
    assert handlers._parse("灵宠封存 2") == ("pet_archive", "2")
    assert handlers._parse("灵宠封存库 1") == ("pet_archive_list", "1")
    assert handlers._parse("灵宠复原 2") == ("pet_restore", "2")
    assert handlers._parse("/灵宠购买 灵粮 3") == ("buy", "灵粮 3")
    assert handlers._parse("灵宠图鉴") == ("catalog", "")
    assert handlers._parse("灵宠图鉴 2") == ("catalog", "2")
    assert handlers._parse("灵宠图鉴 青鸾") == ("catalog", "青鸾")
    assert handlers._parse("灵宠强化 灵器") == ("enhance", "灵器")
    assert handlers._parse("灵宠历练") == ("explore", "")
    assert handlers._parse("灵宠历练 星谷采集") == ("explore", "星谷采集")
    assert handlers._parse("灵宠奇闻") == ("adventure_codex", "")
    assert handlers._parse("灵宠奇闻 2") == ("adventure_codex", "2")
    assert handlers._parse("灵宠奇闻榜") == ("adventure_rank", "")
    assert handlers._parse("灵宠互动") == ("bond", "")
    assert handlers._parse("灵宠互动 2") == ("bond", "2")
    assert handlers._parse("灵宠喂养 2") == ("feed", "2")
    assert handlers._parse("灵宠修炼 2") == ("train", "2")
    assert handlers._parse("灵宠合修 2") == ("co_train", "2")
    assert handlers._parse("灵宠突破 2 破境丹") == ("breakthrough", "2 破境丹")
    assert handlers._parse("灵宠进化 2") == ("evolve", "2")
    assert handlers._parse("灵宠工坊 2") == ("recipe_catalog", "2")
    assert handlers._parse("灵宠打造 青岚翎 2") == ("craft", "青岚翎 2")
    assert handlers._parse("灵宠分解 青岚翎 +2 1") == ("salvage", "青岚翎 +2 1")
    assert handlers._parse("灵宠血脉 青鸾") == ("lineage_catalog", "青鸾")
    assert handlers._parse("灵宠分支 分支名称") == ("lineage_choose", "分支名称")
    assert handlers._parse("灵宠秘境 九霄劫海") == ("dungeons", "九霄劫海")
    assert handlers._parse("灵宠关卡 2") == ("stage_catalog", "2")
    assert handlers._parse("灵宠挑战关卡 青木试锋") == ("stage_challenge", "青木试锋")
    assert handlers._parse("灵宠组队关卡 4") == ("team_stage_challenge", "4")
    assert handlers._parse("灵宠收集 2") == ("collection", "2")
    assert handlers._parse("灵宠成就 3") == ("achievements", "3")
    assert handlers._parse("灵宠成就领奖 初结灵契") == ("achievement_claim", "初结灵契")
    assert handlers._parse("灵宠共鸣") == ("resonance", "")
    assert handlers._parse("灵宠共鸣 激活 青岚双翼") == ("resonance", "激活 青岚双翼")
    assert handlers._parse("灵宠战报 2") == ("battle_reports", "2")
    assert handlers._parse("灵宠签到后的聊天") is None
    assert handlers._parse("灵宠论剑 清风散人") == ("pvp", "清风散人")
    assert handlers._parse("我的道号") == ("identity", "")
    assert handlers._parse("灵宠装备 青岚翎") == ("equipment", "青岚翎")
    assert handlers._parse("灵宠学习 风刃术") == ("learn", "风刃术")
    assert handlers._parse("灵宠身份") is None
    for command, action, arg in (
        ("灵宠入队", "team_join", "青云"),
        ("灵宠邀请", "team_invite", "赤霄"),
        ("灵宠队务", "team_requests", "分页 2"),
        ("灵宠队伍", "team_status", "赤霄"),
        ("灵宠队伍同意", "team_accept", "赤霄"),
        ("灵宠队伍拒绝", "team_reject", "赤霄"),
        ("灵宠队伍撤回", "team_withdraw", "青云"),
        ("灵宠踢人", "team_kick", "赤霄"),
        ("灵宠转让", "team_transfer", "赤霄"),
    ):
        assert handlers._parse(f"/{command} {arg}") == (action, arg)
        assert handlers._parse(f"{command}之后聊天") is None
    assert handlers._parse("灵宠解散") == ("team_disband", "")


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


def test_qq_at_message_and_full_group_message_share_the_same_safe_event_key():
    bot = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"))
    at_message = qq_event(message_id="same-id", text="我的灵宠")
    full_message = qq_event(
        message_id="same-id", text="我的灵宠", event_class=GroupMessageCreateEvent,
    )

    async def run():
        assert await handlers._is_command(at_message, at_message.get_message())
        assert await handlers._is_command(full_message, full_message.get_message())

    asyncio.run(run())
    assert handlers._operation_id(bot, at_message) == handlers._operation_id(bot, full_message)


def test_duplicate_qq_event_shapes_replay_one_committed_command(tmp_path, monkeypatch):
    store = Store(tmp_path / "qq-event-dedup.db")
    store.initialize()
    service = Game(store, Config())
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config())
    bot = SimpleNamespace(
        self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock(),
    )
    at_message = qq_event(message_id="same-sign", text="灵宠签到")
    full_message = qq_event(
        message_id="same-sign", text="灵宠签到", event_class=GroupMessageCreateEvent,
    )

    async def run():
        await handlers._run(bot, qq_event(message_id="adopt-first"), "灵宠领养 青鸾")
        await handlers._run(bot, at_message, "灵宠签到")
        await handlers._run(bot, full_message, "灵宠签到")

    asyncio.run(run())
    player = sql(store, "SELECT stones, sign_day FROM players WHERE user_id='12345'")[0]
    assert player["stones"] == service.content.rules.starter_stones + 200
    assert player["sign_day"]
    assert bot.send.await_count == 3
    assert bot.send.call_args_list[1].args[1] == bot.send.call_args_list[2].args[1]


@pytest.mark.parametrize(
    "event",
    [
        GroupMsgReceiveEvent.model_validate({
            "timestamp": "2026-10-07T00:00:00+08:00",
            "group_openid": "group", "op_member_openid": "member",
        }),
        C2CMsgReceiveEvent.model_validate({
            "timestamp": "2026-10-07T00:00:00+08:00", "openid": "member",
        }),
    ],
    ids=["group-receive-notice", "c2c-receive-notice"],
)
def test_qq_receive_lifecycle_notification_is_not_a_command_message(event):
    assert not handlers._is_message_event(event)

    async def run():
        assert not await handlers._is_command(event, None)

    asyncio.run(run())


def test_team_approval_uses_shared_identity_across_real_adapter_events(tmp_path, monkeypatch):
    store = Store(tmp_path / "teams.db")
    store.initialize()
    monkeypatch.setattr(handlers, "game", Game(store, Config()))
    ob = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def run():
        await handlers._run(ob, onebot_event(message_id=101), "灵宠领养 青鸾")
        await handlers._run(qq, qq_event("member-openid", message_id="102"), "灵宠领养 玄狐")
        await handlers._run(ob, onebot_event(message_id=103), "灵宠道号 青云")
        await handlers._run(qq, qq_event("member-openid", message_id="104"), "灵宠道号 赤霄")
        await handlers._run(ob, onebot_event(message_id=105), "灵宠组队")
        await handlers._run(qq, qq_event("member-openid", message_id="106"), "灵宠入队 青云")
        assert len(sql(store, "SELECT * FROM team_members")) == 1
        await handlers._run(qq, qq_event("member-openid", message_id="107"), "灵宠队伍同意 青云")
        assert len(sql(store, "SELECT * FROM team_members")) == 1
        assert len(sql(store, "SELECT * FROM team_requests")) == 1
        event = qq_event("12345", group=False, message_id="108")
        await handlers._run(qq, event, "灵宠队伍同意 赤霄")
        reply = str(qq.send.call_args.args[1])
        assert "加入队伍" in reply and "青云" in reply and "赤霄" in reply
        assert "12345" not in reply and "member-openid" not in reply
        await handlers._run(qq, event, "灵宠队伍同意 赤霄")
        assert str(qq.send.call_args.args[1]) == reply
        assert {row["user_id"] for row in sql(store, "SELECT * FROM team_members")} == {"12345", "member-openid"}
        assert not sql(store, "SELECT * FROM team_requests")

    asyncio.run(run())
