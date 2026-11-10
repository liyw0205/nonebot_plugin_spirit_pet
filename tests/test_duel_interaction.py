import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.gameplay import duel

from .support import sql
from .test_commands import onebot_event
from .test_duel import NOW, stub


def test_onebot_observe_choose_review_growth_chain(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))

    async def run():
        for index, command in enumerate(("!灵宠领养 青鸾", "!灵宠斗法 详情 松风道人", "!灵宠斗法 松风道人",
                                         "!灵宠斗法 稳守", "!灵宠斗法 回顾", "!我的灵宠")):
            event = onebot_event(command, index+1)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(run())
    replies = [call.args[1] for call in bot.send.call_args_list]
    assert len(replies) == 6 and "UID：10000" in replies[0]
    assert "挑战（!灵宠斗法 松风道人）" in replies[1]
    assert "护法将出：抢攻" in replies[2]
    assert "破招" in replies[3] and "本回合精力 -3" in replies[3]
    assert "查看回合（!灵宠斗法 回顾 查看" in replies[4]
    assert "修为：" in replies[5]
    assert sql(game[1], "SELECT energy FROM pets") == [{"energy": 97}]


@pytest.mark.parametrize("prefix", ["", "!", "/"])
def test_new_views_qq_native_and_text_actions_are_complete_and_unique(game, play, monkeypatch, prefix):
    play("adopt", "青鸾")
    pages = [play("duel"), play("duel", "详情 松风道人"), play("duel", "松风道人")]
    play("team_create")
    play("team_ready")
    before = sql(game[1], "SELECT * FROM team_members")
    pages.append(play("duel"))
    assert sql(game[1], "SELECT * FROM team_members") == before
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    pages.append(play("duel", "稳守"))
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None
    pages.extend((play("duel", "回顾"), play("duel", "回顾 查看 2")))
    for page in pages:
        for link in page.inline_commands:
            assert 0 <= link.line < len(page.lines)
            assert handlers._parse(link.command) is not None
        config = Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix)
        _, native = _qq_segments(page, config)
        markdown = "\n".join(segment.data["markdown"].content for segment in native["markdown"])
        commands = [parse_qs(urlparse(url).query)["command"][0]
                    for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        assert set(commands) == {prefix+link.command for link in page.inline_commands}
        buttons = [button.action.data for segment in native["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert len(buttons) <= 4 and not set(buttons) & set(commands)
        _, plain = _qq_segments(page, Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix=prefix))
        assert "mqqapi://" not in str(plain)
        for link in page.inline_commands:
            assert prefix+link.command in str(plain)
