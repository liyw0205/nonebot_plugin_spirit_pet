import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

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


def duplicate_two_species(game):
    """Same-species pair unlocks the 同族双灵 achievement (duplicate_species >= 2... target 1)."""
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1','qingluan','青鸾二号',?)",
            (NOW,),
        )


def test_achievements_claim_links_match_claimable_rows(game, play):
    play("adopt", "青鸾", now=NOW)
    duplicate_two_species(game)

    listing = play("achievements", now=NOW)
    claimable_lines = [index for index, line in enumerate(listing.lines) if "· 可领奖 ·" in line]
    assert {link.line for link in listing.inline_commands} == set(claimable_lines)
    assert {link.label for link in listing.inline_commands} == {"领取奖励"}
    for link in listing.inline_commands:
        name = listing.lines[link.line].split(" · ", 1)[0]
        assert link.command == f"灵宠成就领奖 {name}"
        assert link.command in listing.commands
    # Linked claim commands leave the button set; pagination and collection stay reachable.
    assert "灵宠成就 2" in listing.commands
    assert "灵宠收集" in listing.commands
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert not button_commands & {link.command for link in listing.inline_commands}


def test_achievements_claim_then_relist_clears_links(game, play):
    play("adopt", "青鸾", now=NOW)
    duplicate_two_species(game)
    listing = play("achievements", now=NOW)
    assert [link.command for link in listing.inline_commands] == [
        "灵宠成就领奖 初结灵契", "灵宠成就领奖 同族双灵",
    ]

    claimed = play("achievement_claim", "同族双灵", now=NOW, op="claim-dup")
    assert claimed.title == "成就奖励已领取"
    assert play("achievement_claim", "同族双灵", now=NOW, op="claim-dup") == claimed
    play("achievement_claim", "初结灵契", now=NOW, op="claim-first")

    after = play("achievements", now=NOW)
    assert after.inline_commands == ()
    assert "同族双灵 · 已领取" in "\n".join(after.lines)


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_achievements_page_claim_links_without_button_duplication(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾", now=NOW)
    duplicate_two_species(game)
    listing = play("achievements", now=NOW)
    _, message = _qq_segments(listing, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.achievements",
    ))
    buttons = keyboard_buttons(message)
    assert len(buttons) <= 4
    button_commands = {button.action.data.removeprefix("/") for button in buttons}
    assert not button_commands & {link.command for link in listing.inline_commands}
    assert "灵宠成就 2" in button_commands or "灵宠收集" in button_commands
    if mode == "native":
        assert markdown_links(message) == [
            ("领取奖励", "/灵宠成就领奖 初结灵契"),
            ("领取奖励", "/灵宠成就领奖 同族双灵"),
        ]


def test_onebot_achievements_keep_claim_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('12345','qingluan','青鸾二号',1800000000)",
            )
        await handlers._run(bot, onebot_event("!灵宠成就", 2), "!灵宠成就")
        listing = bot.send.call_args.args[1]
        assert "领取奖励（!灵宠成就领奖 同族双灵）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠成就领奖 同族双灵", 3), "!灵宠成就领奖 同族双灵")
        assert "成就奖励已领取" in bot.send.call_args.args[1]

    asyncio.run(run())
