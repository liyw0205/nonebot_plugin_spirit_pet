import asyncio
import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.achievement_content import AchievementReward
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
    status_lines = [index for index, line in enumerate(listing.lines) if " · " in line and "进度：" in line]
    detail_links = [link for link in listing.inline_commands if link.label == "查看详情"]
    claim_links = [link for link in listing.inline_commands if link.label == "领取奖励"]
    claimable_lines = [index for index in status_lines if "· 可领奖 ·" in listing.lines[index]]
    assert {link.line for link in detail_links} == set(status_lines)
    assert {link.line for link in claim_links} == set(claimable_lines)
    assert {link.label for link in listing.inline_commands} == {"查看详情", "领取奖励"}
    assert all("奖励预览：" in listing.lines[index + 2] for index in status_lines)
    for link in listing.inline_commands:
        name = listing.lines[link.line].split(" · ", 1)[0]
        action = "详情" if link.label == "查看详情" else "领奖"
        assert link.command == f"灵宠成就{action} {name}"
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
    assert [link.command for link in listing.inline_commands if link.label == "领取奖励"] == [
        "灵宠成就领奖 初结灵契", "灵宠成就领奖 同族双灵",
    ]

    claimed = play("achievement_claim", "同族双灵", now=NOW, op="claim-dup")
    assert claimed.title == "成就奖励已领取"
    assert play("achievement_claim", "同族双灵", now=NOW, op="claim-dup") == claimed
    play("achievement_claim", "初结灵契", now=NOW, op="claim-first")

    after = play("achievements", now=NOW)
    assert all(link.label == "查看详情" for link in after.inline_commands)
    assert not any(link.label == "领取奖励" for link in after.inline_commands)
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
            (action.label, f"/{action.command}") for action in listing.inline_commands
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
        assert "查看详情（!灵宠成就详情 同族双灵）" in listing
        assert "领取奖励（!灵宠成就领奖 同族双灵）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠成就领奖 同族双灵", 3), "!灵宠成就领奖 同族双灵")
        assert "成就奖励已领取" in bot.send.call_args.args[1]

    asyncio.run(run())


def test_all_achievements_are_discoverable_with_preview_and_read_only_details(game, play):
    seen = set()
    for page in range(1, 16):
        listing = play("achievements", str(page), now=NOW)
        status_lines = [line for line in listing.lines if " · " in line and "进度：" in line]
        assert 1 <= len(status_lines) <= 5
        assert len(listing.inline_commands) == len(status_lines)
        for line in status_lines:
            name = line.split(" · ", 1)[0]
            seen.add(name)
            assert f"灵宠成就详情 {name}" in listing.commands
            assert f"奖励预览：" in listing.lines[listing.lines.index(line) + 2]
            detail = play("achievement_detail", name, now=NOW)
            assert detail.title == f"成就详情 · {name}"
            assert any(value.startswith("条件：") for value in detail.lines)
            assert any(value.startswith("当前进度：") for value in detail.lines)
            assert any(value.startswith("奖励预览：") for value in detail.lines)
            assert "领取状态：未结契" in detail.lines
    assert len(seen) == 74
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="灵宠成就共 15 页"):
        play("achievements", "16", now=NOW)


def test_claimed_achievement_detail_uses_saved_reward_snapshot(game, play):
    play("adopt", "青鸾", now=NOW)
    play("achievement_claim", "初结灵契", now=NOW, op="ledger-first-contract")

    current = game[0].content
    achievements = dict(current.achievements)
    first = achievements["first_contract"]
    achievements["first_contract"] = first.model_copy(update={
        "reward": AchievementReward(stones=999, items={"spirit_food": 8}),
    })
    items = dict(current.items)
    items["spirit_food"] = items["spirit_food"].model_copy(update={"name": "新灵粮"})
    game[0].content = replace(current, achievements=achievements, items=items)

    detail = play("achievement_detail", "初结灵契", now=NOW + 1)
    assert detail.title == "成就回顾 · 初结灵契"
    assert "领取状态：已领取 · 领取时进度：1/1" in detail.lines
    assert "实际发放：灵石 +100、灵粮 +2" in detail.lines
    assert any(line.startswith("领取时间：") for line in detail.lines)
    assert "领取凭证：已永久保存" in detail.lines
    assert "奖励预览：灵石 +999" not in "\n".join(detail.lines)

    with game[1].connect() as conn:
        conn.execute(
            "UPDATE achievement_claims SET reward_snapshot='not-json' WHERE user_id='u1' AND achievement_id='first_contract'"
        )
    with pytest.raises(GameError, match="领取记录暂不可回顾"):
        play("achievement_detail", "初结灵契", now=NOW + 2)


def test_achievement_detail_error_and_claimable_paths(game, play):
    with pytest.raises(GameError, match="未找到该内容"):
        play("achievement_detail", "不存在的成就", now=NOW)
    assert not sql(game[1], "SELECT * FROM players")

    play("adopt", "青鸾", now=NOW)
    detail = play("achievement_detail", "初结灵契", now=NOW)
    assert "领取状态：可领奖" in detail.lines
    assert detail.inline_commands[0].command == "灵宠成就领奖 初结灵契"
    assert detail.inline_commands[0].line == 3
    _, message = _qq_segments(detail, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert not button_commands & {action.command for action in detail.inline_commands}
    assert markdown_links(message) == [("领取奖励", "/灵宠成就领奖 初结灵契")]
