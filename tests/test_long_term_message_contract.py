import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .support import sql
from .test_commands import onebot_event, qq_event
from .test_targeted_training import NOW, add_pet


@pytest.mark.parametrize("prefix", ["", "/", "!"])
def test_numbered_and_period_bound_links_render_without_duplicate_buttons(game, play, prefix):
    play("adopt", "青鸾")
    play("sign")
    replies = [play("quests"), play("free_summon"), play("weekly_quests", "4"),
               play("summon"), play("codex_trials", "2")]
    for reply in replies:
        plain, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))
        markdown = native["markdown"][0].data["markdown"].content
        links = [parse_qs(urlparse(url).query)["command"][0]
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        buttons = [button.action.data for segment in native["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert set(links) == {prefix + link.command for link in reply.inline_commands}
        assert len(buttons) <= 4
        assert not set(links) & set(buttons)
        assert "mqqapi://" not in plain
        assert all(handlers._parse(link.command) is not None for link in reply.inline_commands)


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_public_numbered_exploration_uses_shared_settlement_and_replay(game, play, monkeypatch, adapter):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    play("adopt", "青鸾", user="12345")
    target = add_pet(game[1], user_id="12345")
    sql(game[1], "UPDATE pets SET realm=6 WHERE pet_id=?", (target,))
    text = f"!灵宠历练 灵泉修行 伙伴 {target}"
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    first = bot.send.call_args.args[1]
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert bot.send.call_args.args[1] == first
    assert sql(game[1], "SELECT energy,exp FROM pets ORDER BY pet_id") == [
        {"energy": 100, "exp": 0}, {"energy": 75, "exp": 25},
    ]
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1
