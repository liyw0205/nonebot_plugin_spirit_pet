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


def adopt(game, play, count):
    play("adopt", "青鸾", now=NOW, op="adopt-0")
    sql(game[1], "UPDATE players SET stones=99999 WHERE user_id='u1'")
    for index in range(1, count):
        play("summon", now=NOW, op=f"summon-{index}")
    return [row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets ORDER BY pet_id")]


def test_archive_list_links_restore_on_each_line(game, play):
    pet_ids = adopt(game, play, 3)
    play("switch", str(pet_ids[0]), now=NOW)
    for index, pet_id in enumerate(pet_ids[1:]):
        play("pet_archive", str(pet_id), now=NOW, op=f"archive-{index}")

    listing = play("pet_archive_list", now=NOW)
    assert {link.label for link in listing.inline_commands} == {"复原"}
    for link in listing.inline_commands:
        pet_id = listing.lines[link.line].split("：", 1)[0].removeprefix("编号 ").strip()
        assert link.command == f"灵宠复原 {pet_id}"
        assert link.command in listing.commands
    assert listing.inline_commands[0].line == 0
    # Linked restore commands leave the button set; roster stays as the page action.
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert not button_commands & {link.command for link in listing.inline_commands}
    assert "灵宠列表" in button_commands


def test_archive_list_empty_offers_roster_entry(game, play):
    adopt(game, play, 1)
    empty = play("pet_archive_list", now=NOW)
    assert empty.inline_commands[0].label == "查看灵宠名册"
    assert empty.inline_commands[0].command == "灵宠列表"
    assert empty.inline_commands[0].line == 0


def test_archive_list_pagination_stays_reachable_with_links(game, play):
    pet_ids = adopt(game, play, 7)
    play("switch", str(pet_ids[0]), now=NOW)
    for index, pet_id in enumerate(pet_ids[1:]):
        play("pet_archive", str(pet_id), now=NOW, op=f"archive-{index}")

    # Six archived pets need two pages; five row links on page 1 must not crowd out navigation.
    first = play("pet_archive_list", now=NOW)
    assert first.title == "灵宠封存库 1/2"
    assert len(first.inline_commands) == 5
    assert "灵宠封存库 2" in first.commands
    second = play("pet_archive_list", "2", now=NOW)
    assert second.title == "灵宠封存库 2/2"
    assert {link.command for link in second.inline_commands} == {f"灵宠复原 {pet_ids[6]}"}
    assert "灵宠封存库 1" in second.commands
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert not button_commands & {link.command for link in first.inline_commands}
    assert "灵宠封存库 2" in button_commands


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_archive_restore_roundtrip_links_then_replay(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    pet_ids = adopt(game, play, 2)
    play("switch", str(pet_ids[0]), now=NOW)
    play("pet_archive", str(pet_ids[1]), now=NOW, op="archive-one")

    listing = play("pet_archive_list", now=NOW)
    _, message = _qq_segments(listing, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.archive",
    ))
    if mode == "native":
        assert markdown_links(message) == [("复原", f"/灵宠复原 {pet_ids[1]}")]

    restored = play("pet_restore", str(pet_ids[1]), now=NOW, op="restore-one")
    assert restored.title == "灵宠复原"
    after = play("pet_archive_list", now=NOW)
    assert after.inline_commands[0].label == "查看灵宠名册"
    assert play("pet_restore", str(pet_ids[1]), now=NOW, op="restore-one") == restored


def test_onebot_archive_list_keeps_restore_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        sql(store, "UPDATE players SET stones=99999 WHERE user_id='12345'")
        await handlers._run(bot, onebot_event("!灵宠召唤", 2), "!灵宠召唤")
        await handlers._run(bot, onebot_event("!灵宠封存 2", 3), "!灵宠封存 2")
        await handlers._run(bot, onebot_event("!灵宠封存库", 4), "!灵宠封存库")
        listing = bot.send.call_args.args[1]
        assert "复原（!灵宠复原 2）" in listing
        assert "mqqapi://" not in listing
        await handlers._run(bot, onebot_event("!灵宠复原 2", 5), "!灵宠复原 2")
        assert "灵宠复原" in bot.send.call_args.args[1]

    asyncio.run(run())
