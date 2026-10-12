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


def dispatch(play, job_id, now):
    return play("expedition_status", str(job_id), now=now)


def test_expedition_catalog_links_every_task_and_keeps_navigation_on_buttons(game, play):
    play("adopt", "青鸾")
    first = play("expedition_catalog")
    assert len(first.inline_commands) == 5
    assert {link.line for link in first.inline_commands} == set(range(5))
    assert {link.label for link in first.inline_commands} == {"查看详情"}
    assert all(link.command in first.commands for link in first.inline_commands)
    assert "灵宠委托 采灵药" in first.text() and "灵宠委托 天门寻器" not in first.text()

    second = play("expedition_catalog", "2")
    assert {link.command for link in second.inline_commands} == {
        "灵宠委托 幽庭觅卵", "灵宠委托 天门寻器",
    }


@pytest.mark.parametrize("mode", ["native", "template"])
def test_qq_expedition_catalog_buttons_stay_few_and_never_duplicate_links(game, play, mode):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    for reply in (play("expedition_catalog"), play("expedition_catalog", "2")):
        _, message = _qq_segments(reply, Config(
            spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.expedition",
        ))
        buttons = keyboard_buttons(message)
        assert len(buttons) <= 4
        button_commands = {button.action.data.removeprefix("/") for button in buttons}
        assert not button_commands & {link.command for link in reply.inline_commands}
        assert "灵宠委托 2" in button_commands or "灵宠委托 1" in button_commands
        assert "灵宠行程" in button_commands
        if mode == "native":
            links = markdown_links(message)
            assert [command for _, command in links] == [
                "/" + link.command for link in reply.inline_commands
            ]


def test_expedition_detail_links_departure_without_duplicate_button(game, play):
    play("adopt", "青鸾")
    detail = play("expedition_catalog", "采灵药")
    assert detail.inline_commands == (detail.inline_commands[0],)
    assert detail.inline_commands[0].label == "出发派遣"
    assert detail.inline_commands[0].line == 1
    assert detail.inline_commands[0].command == "灵宠派遣 采灵药"
    _, message = _qq_segments(detail, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert "灵宠派遣 采灵药" not in button_commands
    assert markdown_links(message) == [("出发派遣", "/灵宠派遣 采灵药")]


def test_expedition_status_links_match_state_and_replay_stays_consistent(game, play):
    play("adopt", "青鸾")
    started = play("expedition_start", "采灵药", now=NOW, op="dispatch-herb")
    job = sql(game[1], "SELECT * FROM expeditions")[0]
    key = str(job["job_id"])
    assert started.inline_commands == ()

    running = dispatch(play, key, NOW)
    assert running.inline_commands[0].label == "提前召回"
    assert running.inline_commands[0].line == 1
    assert running.inline_commands[0].command == f"灵宠召回 {key}"

    completed = dispatch(play, key, job["finishes_at"])
    assert completed.inline_commands[0].label == "领取归来奖励"
    assert completed.inline_commands[0].command == f"灵宠归来 {key}"
    # The generic seven-day cache replays the original departure reply unchanged.
    assert play("expedition_start", "采灵药", now=NOW, op="dispatch-herb") == started

    claimed = play("expedition_claim", key, now=job["finishes_at"])
    assert claimed.inline_commands == ()
    after = dispatch(play, key, job["finishes_at"])
    assert after.inline_commands[0].label == "查看委托目录"
    assert after.inline_commands[0].command == "灵宠委托"


def test_expedition_empty_status_offers_catalog_entry(game, play):
    play("adopt", "青鸾")
    empty = play("expedition_status")
    assert empty.inline_commands[0].label == "查看委托目录"
    assert empty.inline_commands[0].command == "灵宠委托"
    assert "灵宠委托" in empty.commands


def test_onebot_expedition_flow_keeps_contextual_commands_readable(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock()
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        await handlers._run(bot, onebot_event("!灵宠委托", 2), "!灵宠委托")
        catalog = bot.send.call_args.args[1]
        assert "查看详情（!灵宠委托 采灵药）" in catalog
        assert "mqqapi://" not in catalog
        await handlers._run(bot, onebot_event("!灵宠委托 采灵药", 3), "!灵宠委托 采灵药")
        detail = bot.send.call_args.args[1]
        assert "出发派遣（!灵宠派遣 采灵药）" in detail
        await handlers._run(bot, onebot_event("!灵宠派遣 采灵药", 4), "!灵宠派遣 采灵药")
        job = sql(store, "SELECT * FROM expeditions")[0]
        await handlers._run(bot, onebot_event(f"!灵宠行程 {job['job_id']}", 5), f"!灵宠行程 {job['job_id']}")
        status = bot.send.call_args.args[1]
        assert "提前召回（!灵宠召回 " in status

    asyncio.run(run())
