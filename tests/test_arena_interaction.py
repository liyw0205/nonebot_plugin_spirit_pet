import asyncio
import itertools
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.utils.time import BEIJING

from .support import sql
from .test_arena_matching import NOW, register
from .test_commands import onebot_event


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


def test_match_rows_link_challenge_on_their_own_line(game, play):
    register(game, play, 13)
    first = play("match", user="private-0", now=NOW)
    assert len(first.inline_commands) == 5
    assert {link.label for link in first.inline_commands} == {"挑战该修士"}
    for link in first.inline_commands:
        assert link.command.removeprefix("灵宠论剑 ") in first.lines[link.line]
    # Challenge commands leave the button set; only pagination stays as a page action.
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠匹配 2"}
    assert not button_commands & {link.command for link in first.inline_commands}


def test_match_second_page_links_reach_challenge(game, play):
    register(game, play, 13)
    second = play("match", "2", user="private-0", now=NOW)
    assert second.inline_commands
    target = second.inline_commands[0].command.removeprefix("灵宠论剑 ")
    before = sql(game[1], "SELECT * FROM pvp_results")
    result = play("pvp", target, user="private-0", now=NOW)
    assert result.title  # The linked command executes the challenge directly.
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == len(before) + 1


def test_board_links_only_current_season_and_never_self(game, play):
    register(game, play, 7)
    season_id = play("pvp_rank", user="private-0", now=NOW).title.split("· ")[1].split()[0]
    for index in range(7):
        user = "private-0" if index == 0 else f"private-{index}"
        sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating) VALUES (?,?,?)",
            (season_id, user, 1000 + index))
    board = play("pvp_rank", user="private-0", now=NOW)
    linked = [link.command for link in board.inline_commands]
    # private-0 owns the lowest identity (UID 10000); their own row never links a challenge.
    assert linked and "灵宠论剑 UID 10000" not in linked
    assert all(command.startswith("灵宠论剑 UID ") for command in linked)
    for link in board.inline_commands:
        assert link.command.removeprefix("灵宠论剑 ") in board.lines[link.line]
    # A later month makes 2028-01 historical: entries stay readable but lose the challenge entry.
    feb = int(datetime(2028, 2, 2, 12, tzinfo=BEIJING).timestamp())
    play("pvp_rank", user="private-0", now=feb)  # Creates the 2028-02 season as current.
    history = play("pvp_rank", "2028-01", user="private-0", now=feb)
    assert "1/2" in history.title and history.lines[0].startswith("1. UID ")
    assert not history.inline_commands
    assert not [command for command in history.commands if command.startswith("灵宠论剑 ")]
    assert history.commands == ("灵宠论剑榜 2028-01 分页 2", "灵宠赛季 2028-01")
    # A season with no stored record is a hard rejection, so it can never render stale links.
    with pytest.raises(Exception, match="未找到该赛季"):
        play("pvp_rank", "2027-12", user="private-0", now=feb)


def test_qq_board_challenge_link_roundtrip_executes_once(game, play):
    pytest.importorskip("nonebot.adapters.qq")
    register(game, play, 3)
    season_id = play("pvp_rank", user="private-0", now=NOW).title.split("· ")[1].split()[0]
    for index in range(3):
        user = "private-0" if index == 0 else f"private-{index}"
        sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating) VALUES (?,?,?)",
            (season_id, user, 1000 + index))
    board = play("pvp_rank", user="private-0", now=NOW)
    _, message = _qq_segments(board, Config(spirit_pet_qq_mode="native"))
    links = markdown_links(message)
    assert links and all(label == "挑战该修士" for label, _ in links)
    target = links[0][1].removeprefix("/灵宠论剑 ")
    play("pvp", target, user="private-0", now=NOW)
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == 1


def test_onebot_arena_lists_keep_challenge_links_readable(game, monkeypatch):
    service, store = game
    counter = itertools.count()

    # handlers._run executes with the real clock, so registration must not stamp 2028 ahead of it.
    def linked_play(action, arg="", user="12345", now=None):
        return service.execute(user, action, arg, f"link-{next(counter)}", now)

    # The OneBot event user is "12345"; opponents stay on platform-style IDs.
    def register_as(event_user):
        for index in range(3):
            user = event_user if index == 0 else f"private-{index}"
            linked_play("adopt", "青鸾", user=user)
        sql(game[1], "UPDATE pets SET realm=1")
        linked_play("season")
        season_id = sql(game[1], "SELECT season_id FROM seasons ORDER BY season_id DESC LIMIT 1")[0]["season_id"]
        for index in range(3):
            user = event_user if index == 0 else f"private-{index}"
            sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating) VALUES (?,?,?)",
                (season_id, user, 1000 + index))

    register_as("12345")
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠匹配", 1), "!灵宠匹配")
        listing = bot.send.call_args.args[1]
        assert "挑战该修士（!灵宠论剑 UID " in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠论剑榜", 2), "!灵宠论剑榜")
        board = bot.send.call_args.args[1]
        assert "挑战该修士（!灵宠论剑 UID " in board

    asyncio.run(run())
