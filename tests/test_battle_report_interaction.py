import asyncio
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .support import sql
from .test_arena_matching import NOW, register, uid
from .test_commands import onebot_event


def seed_reports(game, user, count, *, played_at=NOW):
    """Insert minimal participant-visible reports directly (reads are plain SELECTs)."""
    snapshot = json.dumps({"teams": [
        {"side": 0, "members": [{"pet_name": "青鸾"}]},
        {"side": 1, "members": [{"pet_name": "敌方灵宠"}]},
    ]})
    ids = []
    with game[1].connect() as conn:
        for index in range(count):
            cursor = conn.execute(
                "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds,"
                " played_at, reply, snapshot, battle_log) VALUES (?, ?, 'pve', ?, 0, 3, ?, '{}', ?, '[]')",
                (f"seed-report-{user}-{index}", user, f"试炼 {index}", played_at + index, snapshot),
            )
            battle_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
                " VALUES (?, ?, 0, 'participant')", (battle_id, user),
            )
            ids.append(battle_id)
    return ids


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


def test_report_list_links_detail_on_every_row(game, play):
    register(game, play)
    battle_ids = seed_reports(game, "private-0", 3)

    listing = play("battle_reports", user="private-0", now=NOW + 10)
    assert len(listing.inline_commands) == 3
    assert {link.label for link in listing.inline_commands} == {"查看详情"}
    for link in listing.inline_commands:
        assert link.command in listing.commands
        battle_id = link.command.rsplit(" ", 1)[1]
        assert listing.lines[link.line].startswith(f"#{battle_id} ")
    # Rows keep their order newest-first; every row is reachable regardless of the button cap.
    assert {link.command for link in listing.inline_commands} == {
        f"灵宠战报 查看 {battle_id}" for battle_id in battle_ids
    }


def test_report_list_pagination_reachable_beyond_button_cap(game, play):
    register(game, play)
    seed_reports(game, "private-0", 6)

    first = play("battle_reports", user="private-0", now=NOW + 10)
    assert first.title == "灵宠战报 1/2"
    assert len(first.inline_commands) == 5
    assert "灵宠战报 分页 2" in first.commands
    second = play("battle_reports", "分页 2", user="private-0", now=NOW + 10)
    assert second.title == "灵宠战报 2/2"
    assert len(second.inline_commands) == 1
    assert "灵宠战报 分页 1" in second.commands

    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert len(buttons := keyboard_buttons(message)) <= 4
    assert not button_commands & {link.command for link in first.inline_commands}
    assert "灵宠战报 分页 2" in button_commands


def test_empty_report_list_offers_roster_entry(game, play):
    register(game, play)
    empty = play("battle_reports", user="private-0", now=NOW + 1)
    assert "尚无参与过的战斗。" in empty.text()
    assert empty.inline_commands[0].label == "查看灵宠名册"
    assert empty.inline_commands[0].command == "灵宠列表"


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_report_detail_roundtrip_keeps_participant_rules(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    register(game, play)
    seed_reports(game, "private-0", 2)
    listing = play("battle_reports", user="private-0", now=NOW + 10)
    _, message = _qq_segments(listing, Config(
        spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.reports",
    ))
    if mode == "native":
        assert [command for _, command in markdown_links(message)] == [
            "/" + link.command for link in listing.inline_commands
        ]

    battle_id = listing.inline_commands[0].command.rsplit(" ", 1)[1]
    detail = play("battle_reports", f"查看 {battle_id}", user="private-0", now=NOW + 10)
    assert detail.title.startswith("战报") or "战报" in detail.title
    with pytest.raises(Exception, match="参与者"):
        play("battle_reports", f"查看 {battle_id}", user="private-1", now=NOW + 10)


def test_onebot_report_list_keeps_detail_links_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )
    battle_ids = []

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 6), "!灵宠领养 青鸾")
        battle_ids.append(seed_reports(game, "12345", 1)[0])
        await handlers._run(bot, onebot_event("!灵宠战报", 7), "!灵宠战报")
        listing = bot.send.call_args.args[1]
        assert f"查看详情（!灵宠战报 查看 {battle_ids[0]}）" in listing
        assert "mqqapi://" not in listing

    asyncio.run(run())
