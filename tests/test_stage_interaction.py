import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql
from .test_pve_stages import account

NOW = 1_800_000_000


def seed_clears(game, user, orders):
    for order in orders:
        sql(game[1], "INSERT INTO pve_stage_progress(user_id,stage_id,first_cleared_at,first_operation_id)"
            " VALUES (?,?,?,?)", (user, f"stage_{order:02d}", NOW, f"seed-{user}-{order}"))


def markdown_links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def keyboard_buttons(message):
    return [
        button
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def test_fresh_account_links_only_openable_rows(game, play):
    account(game, play, "u1")
    listing = play("stage_catalog")
    # Only the first stage is openable for a fresh account; the rest stay locked.
    assert [link.command for link in listing.inline_commands] == ["灵宠挑战关卡 1"]
    link = listing.inline_commands[0]
    assert link.label == "前往挑战"
    assert link.line == 0 and "青木试锋" in listing.lines[0]
    assert "月影追猎 · 未解锁" in listing.lines[1]
    # Challenges leave the button set; only pagination remains as a page action.
    assert listing.commands == ("灵宠关卡 2",)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠关卡 2"}
    assert markdown_links(message) == [("前往挑战", "/灵宠挑战关卡 1")]


def test_cleared_and_newly_opened_rows_both_link_replay_runs(game, play):
    account(game, play, "u1")
    play("stage_challenge", "1")
    listing = play("stage_catalog")
    assert "1. 青木试锋 · 已通关" in listing.lines[0]
    assert "2. 月影追猎 · 可挑战" in listing.lines[1]
    # Cleared rows keep a replay entry; the newly opened row gains one; locked rows never do.
    assert [link.command for link in listing.inline_commands] == [
        "灵宠挑战关卡 1", "灵宠挑战关卡 2",
    ]
    for link in listing.inline_commands:
        assert link.label == "前往挑战"
        assert link.command.removeprefix("灵宠挑战关卡 ") in listing.lines[link.line]


def test_unregistered_player_gets_no_executable_stage_links(game, play):
    listing = play("stage_catalog", user="nobody")
    assert "尚未结契" in listing.text()
    # No contract pet means no runnable stage, so no blue link is offered.
    assert not listing.inline_commands
    assert listing.commands == ("灵宠关卡 2",)


def test_second_page_links_only_the_openable_row(game, play):
    account(game, play, "u1")
    seed_clears(game, "u1", range(1, 6))
    second = play("stage_catalog", "2", user="u1")
    # Orders 6-10 on this page: stage_06 just opened, stage_07+ stay locked behind it.
    listing_lines = "幽沼蚀魂 · 可挑战" in second.lines[0]
    assert listing_lines
    assert [link.command for link in second.inline_commands] == ["灵宠挑战关卡 6"]
    assert second.inline_commands[0].line == 0
    assert second.commands == ("灵宠关卡 1", "灵宠关卡 3")


def test_linked_team_stage_command_is_the_registered_team_entry(game, play):
    account(game, play, "u1")
    seed_clears(game, "u1", range(1, 4))
    listing = play("stage_catalog", user="u1")
    team_links = [link for link in listing.inline_commands if link.command.startswith("灵宠组队关卡")]
    assert [link.command for link in team_links] == ["灵宠组队关卡 4"]
    assert team_links[0].line == 3 and "古殿同契" in listing.lines[3]
    # The linked command routes to the team entry; without a ready team it is a clean rejection.
    with pytest.raises(GameError):
        play("team_stage_challenge", "4", user="u1")
