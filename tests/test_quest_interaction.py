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
from .test_commands import onebot_event

NOW = 1_800_000_000


def keyboard_buttons(message):
    return [
        button
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def markdown_links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def complete_sign(play):
    play("sign", now=NOW)


def test_quests_links_only_claimable_quests_on_their_own_lines(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)

    listing = play("quests", now=NOW + 1)
    claimable_lines = [
        index for index, line in enumerate(listing.lines) if line.endswith("（可领取）") or "（可领取）" in line
    ]
    assert {link.line for link in listing.inline_commands} == set(claimable_lines)
    assert {link.label for link in listing.inline_commands} == {"领取奖励"}
    for link in listing.inline_commands:
        quest_name = listing.lines[link.line].split("：", 1)[0]
        assert link.command == f"灵宠领奖 {quest_name}"
        assert link.command in listing.commands
    assert all("（进行中）" not in listing.lines[link.line] for link in listing.inline_commands)
    # Claimed or in-progress quests never receive a link.
    assert all(link.line not in {i for i, line in enumerate(listing.lines) if "（已领取）" in line}
               for link in listing.inline_commands)


def test_quests_claim_removes_link_and_replay_stays_consistent(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)

    before = play("quests", now=NOW + 1)
    assert [link.command for link in before.inline_commands] == ["灵宠领奖 晨光初至"]
    claimed = play("claim", "晨光初至", now=NOW + 2, op="claim-sign")
    assert claimed.title == "任务领奖"
    assert play("claim", "晨光初至", now=NOW + 2, op="claim-sign") == claimed

    after = play("quests", now=NOW + 3)
    assert after.inline_commands == ()
    assert after.commands == ()
    assert "晨光初至：1/1（已领取）" in after.text()


def test_quests_day_refresh_clears_links(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)
    assert play("quests", now=NOW + 1).inline_commands
    play("claim", "晨光初至", now=NOW + 2)

    next_day = play("quests", now=NOW + 86_400 * 2)
    assert next_day.inline_commands == ()
    assert not sql(game[1], "SELECT * FROM quest_progress")


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_quests_native_links_claimable_only_without_buttons(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)
    reply = play("quests", now=NOW + 1)
    _, message = _qq_segments(reply, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.quests",
    ))
    assert keyboard_buttons(message) == []
    if mode == "native":
        assert markdown_links(message) == [("领取奖励", "/灵宠领奖 晨光初至")]


def test_onebot_quests_keep_claim_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        await handlers._run(bot, onebot_event("!灵宠签到", 2), "!灵宠签到")
        await handlers._run(bot, onebot_event("!灵宠任务", 3), "!灵宠任务")
        listing = bot.send.call_args.args[1]
        assert "领取奖励（!灵宠领奖 晨光初至）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠领奖 晨光初至", 4), "!灵宠领奖 晨光初至")
        assert "任务领奖" in bot.send.call_args.args[1]

    asyncio.run(run())
