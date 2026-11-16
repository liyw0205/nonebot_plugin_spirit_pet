import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

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


def test_quests_claim_links_bind_date_and_only_appear_on_claimable_lines(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)

    listing = play("quests", now=NOW + 1)
    claimable_lines = [
        index for index, line in enumerate(listing.lines) if line.endswith("（可领取）") or "（可领取）" in line
    ]
    claims = [link for link in listing.inline_commands if link.label == "领取奖励"]
    assert {link.line for link in claims} == set(claimable_lines)
    for link in claims:
        quest_name = listing.lines[link.line].split("：", 1)[0]
        assert link.command == f"灵宠领奖 {quest_name} 日 2027-01-15"
        assert link.command not in listing.commands
    assert all(link.line not in {i for i, line in enumerate(listing.lines) if "（已领取）" in line}
               for link in listing.inline_commands)


def test_quests_claim_removes_link_and_replay_stays_consistent(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)

    before = play("quests", now=NOW + 1)
    assert [link.command for link in before.inline_commands if link.label == "领取奖励"] == [
        "灵宠领奖 晨光初至 日 2027-01-15",
    ]
    claimed = play("claim", "晨光初至", now=NOW + 2, op="claim-sign")
    assert claimed.title == "任务领奖"
    assert play("claim", "晨光初至", now=NOW + 2, op="claim-sign") == claimed

    after = play("quests", now=NOW + 3)
    assert not any(link.label == "领取奖励" for link in after.inline_commands)
    assert after.commands == ("灵宠主线", "灵宠周常", "灵宠目标")
    assert "晨光初至：1/1（已领取）" in after.text()


def test_quests_page_projects_new_day_until_an_action_refreshes_daily_rows(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)
    assert play("quests", now=NOW + 1).inline_commands
    play("claim", "晨光初至", now=NOW + 2)

    next_day = play("quests", now=NOW + 86_400 * 2)
    assert not any(link.label == "领取奖励" for link in next_day.inline_commands)
    assert "晨光初至：0/1（进行中）" in next_day.text()
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='sign_once'")
    play("train", now=NOW + 86_400 * 2)
    assert sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id='sign_once'",
    ) == []
    assert sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'signin_day_%'",
    ) == [{"quest_id": "signin_day_2027-01-15"}]


def test_stale_daily_quest_link_cannot_claim_after_refresh_and_keeps_signin_history(game, play):
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)
    listing = play("quests", now=NOW + 1)
    stale_link = next(link.command for link in listing.inline_commands if link.command.startswith("灵宠领奖 晨光初至"))
    stale_action, stale_argument = handlers._parse(stale_link)

    next_day = NOW + 86_400 * 2
    refreshed = play("quests", now=next_day)
    assert not any(link.label == "领取奖励" for link in refreshed.inline_commands)
    with pytest.raises(GameError, match="跨日"):
        game[0].execute("u1", stale_action, stale_argument, "stale-daily-quest-link", next_day + 1)

    assert sql(
        game[1],
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE user_id='u1' AND quest_id='signin_day_2027-01-15'",
    ) == [{"quest_id": "signin_day_2027-01-15", "progress": 1, "claimed": 1}]
    assert stale_link == "灵宠领奖 晨光初至 日 2027-01-15"


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_quests_keep_claims_in_links_and_navigation_in_buttons(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾", now=NOW)
    complete_sign(play)
    reply = play("quests", now=NOW + 1)
    _, message = _qq_segments(reply, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.quests",
    ))
    buttons = {button.action.data for button in keyboard_buttons(message)}
    assert buttons == {"/" + command for command in reply.commands}
    if mode == "native":
        links = markdown_links(message)
        assert ("领取奖励", "/灵宠领奖 晨光初至 日 2027-01-15") in links
        assert not {command for _, command in links} & buttons


def test_onebot_quests_keep_claim_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        await handlers._run(bot, onebot_event("!灵宠签到", 2), "!灵宠签到")
        await handlers._run(bot, onebot_event("!灵宠任务", 3), "!灵宠任务")
        listing = bot.send.call_args.args[1]
        assert "领取奖励（!灵宠领奖 晨光初至 日 2027-01-15）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠领奖 晨光初至", 4), "!灵宠领奖 晨光初至")
        assert "任务领奖" in bot.send.call_args.args[1]

    asyncio.run(run())
