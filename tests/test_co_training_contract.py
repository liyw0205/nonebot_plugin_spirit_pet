import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments, send_reply
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def training_state(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY 1") for table in (
        "players", "player_identity", "pets", "active_pet_slots", "inventory", "quest_progress", "team_members",
    )}


def buttons(message):
    return [button for segment in message["keyboard"]
            for row in segment.data["keyboard"].content.rows for button in row.buttons]


def links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [(label, parse_qs(urlparse(url).query))
            for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)]


@pytest.mark.parametrize("argument", ["", "2"])
def test_co_training_prerequisites_keep_adoption_and_roster_guidance(game, play, argument):
    with pytest.raises(GameError) as unregistered:
        play("co_train", argument)
    assert unregistered.value.reply.inline_commands[0].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    with pytest.raises(GameError) as no_active:
        play("co_train", argument)
    assert no_active.value.reply.inline_commands[0].command == "灵宠列表"
    assert "领养" not in no_active.value.reply.text()


def test_partner_pages_are_bounded_and_do_not_change_resources_or_preparation(game, play):
    play("adopt", "青鸾", now=NOW - 86400)
    play("sign", now=NOW - 86400)
    play("sign")
    play("summon", "5")
    play("team_create")
    play("team_ready")
    sql(game[1], "UPDATE pets SET energy=70, energy_updated=?", (NOW,))
    before = training_state(game[1])

    first = play("co_train", now=NOW + 600)
    second = play("co_train", "分页 2", now=NOW + 600)
    third = play("co_train", "分页 3", now=NOW + 600)

    assert first.title == "同族合修 1/3"
    assert first.commands == ("灵宠合修 2", "灵宠合修 3", "灵宠合修 分页 2")
    assert second.commands == ("灵宠合修 4", "灵宠合修 5", "灵宠合修 分页 1", "灵宠合修 分页 3")
    assert third.commands == ("灵宠合修 6", "灵宠合修 分页 2")
    assert "可用精力 72/100" in first.text()
    assert before == training_state(game[1])


@pytest.mark.parametrize("argument", ["分页", "分页 0", "分页 2", "分页 x", "分页 1 2", "-1", "2 3"])
def test_partner_argument_errors_do_not_execute_or_charge(game, play, argument):
    play("adopt", "青鸾")
    play("summon")
    before = training_state(game[1])
    with pytest.raises(GameError):
        play("co_train", argument)
    assert training_state(game[1]) == before


def test_partner_page_explains_expedition_and_energy_and_excludes_archived_or_foreign_pets(game, play):
    play("adopt", "青鸾")
    play("sign")
    play("summon", "3")
    play("switch", "2")
    play("expedition_start", "采灵药")
    play("switch", "1")
    sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=3")
    play("pet_archive", "4")
    play("adopt", "青鸾", user="other-owner")
    before = training_state(game[1])

    reply = play("co_train")

    assert "编号 2" in reply.text() and "外出中" in reply.text()
    assert "编号 3" in reply.text() and "精力不足" in reply.text()
    assert "编号 4" not in reply.text() and "编号 5" not in reply.text()
    assert not any(command in reply.commands for command in ("灵宠合修 2", "灵宠合修 3"))
    assert any(link.command == "灵宠行程" for link in reply.inline_commands)
    with pytest.raises(GameError, match="属于你的"):
        play("co_train", "5")
    assert training_state(game[1]) == before


def test_archived_same_species_guidance_keeps_existing_pets(game, play):
    play("adopt", "青鸾")
    play("summon")
    play("pet_archive", "2")
    reply = play("co_train")
    assert "封存库中还有同族伙伴" in reply.text()
    assert any(link.command == "灵宠封存库" for link in reply.inline_commands)
    assert not any(command.startswith("灵宠合修 ") for command in reply.commands)


@pytest.mark.parametrize("finished", [False, True])
def test_active_expedition_blocks_partner_actions_until_claimed(game, play, finished):
    play("adopt", "青鸾")
    play("summon")
    play("expedition_start", "采灵药")
    now = sql(game[1], "SELECT finishes_at FROM expeditions")[0]["finishes_at"] if finished else NOW
    before = training_state(game[1])

    reply = play("co_train", now=now)

    assert ("行程已完成，先领取奖励" if finished else "外出中，先完成行程") in reply.text()
    assert "灵宠合修 2" not in reply.commands
    assert any(link.command == "灵宠行程" for link in reply.inline_commands)
    with pytest.raises(GameError, match="派遣|领取"):
        play("co_train", "2", now=now)
    assert training_state(game[1]) == before


def test_stale_partner_action_rechecks_conditions_and_shared_cooldown(game, play):
    play("adopt", "青鸾")
    play("summon")
    assert "灵宠合修 2" in play("co_train").commands
    play("train")
    before = training_state(game[1])
    preview = play("co_train", now=NOW + 1)
    assert "调息 299 秒" in preview.text()
    assert "灵宠合修 2" not in preview.commands
    with pytest.raises(GameError, match="调息"):
        play("co_train", "2", now=NOW + 1)
    assert training_state(game[1]) == before


def test_concurrent_co_training_charges_once_and_replays_after_restart(game, play):
    play("adopt", "青鸾")
    play("summon")
    barrier = Barrier(2)

    def attempt(operation):
        barrier.wait(timeout=5)
        try:
            return game[0].execute("u1", "co_train", "2", operation, NOW)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("co-race-a", "co-race-b")))
    accepted = next(result for result in results if not isinstance(result, GameError))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert [row["energy"] for row in sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")] == [85, 85]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='train_once'") == [{"progress": 1}]
    before = training_state(game[1])
    operation = "co-race-a" if results[0] == accepted else "co-race-b"
    Store(game[1].path).initialize()
    assert play("co_train", "2", op=operation, now=NOW + 1) == accepted
    assert training_state(game[1]) == before


def test_onebot_short_co_training_selection_to_growth_uses_registered_commands(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        for index, command in enumerate(("!灵宠领养 青鸾", "!灵宠召唤 1", "!灵宠合修", "!灵宠合修 2", "!我的灵宠")):
            event = onebot_event(command, index + 1)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(run())
    replies = [call.args[1] for call in bot.send.call_args_list]
    assert len(replies) == 5
    assert "UID：10000" in replies[0]
    assert "与编号 2 合修（!灵宠合修 2）" in replies[2]
    assert "编号 1）修为 +" in replies[3] and "编号 2）修为 +" in replies[3]
    assert "修为：" in replies[4]
    assert [row["energy"] for row in sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")] == [85, 85]


@pytest.mark.parametrize("prefix", ["", "!", "/"])
def test_qq_partner_actions_are_bounded_complete_and_unique_and_keep_text_fallback(game, play, prefix):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    play("sign")
    play("summon", "3")
    reply = play("co_train")
    config = Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix)

    plain, message = _qq_segments(reply, config)
    payloads = [button.action.data for button in buttons(message)]
    assert payloads == [prefix + "灵宠合修 2", prefix + "灵宠合修 3", prefix + "灵宠合修 分页 2"]
    assert all(button.action.enter for button in buttons(message))
    assert buttons(message)[0].render_data.label == "与编号 2 合修"
    assert all(not button.render_data.label.startswith("/") for button in buttons(message))
    assert [data["command"][0] for _, data in links(message)] == [prefix + "我的灵宠"]
    assert f"与编号 2 合修（{prefix}灵宠合修 2）" in plain

    _, markdown_only = _qq_segments(reply, config, allow_keyboard=False)
    assert not buttons(markdown_only)
    fallback_payloads = [data["command"][0] for _, data in links(markdown_only)]
    assert fallback_payloads == [prefix + "我的灵宠", *payloads]
    assert len(fallback_payloads) == len(set(fallback_payloads))


def test_qq_no_partner_only_prefills_summon_and_help_has_no_keyboard(game, play):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    _, message = _qq_segments(play("co_train"), Config(spirit_pet_qq_mode="native"))
    summon = next(button for button in buttons(message) if button.action.data == "/灵宠召唤 ")
    assert summon.action.enter is False
    _, help_message = _qq_segments(play("help", "成长"), Config(spirit_pet_qq_mode="native"))
    commands = [data for _, data in links(help_message) if data["command"][0].startswith("/灵宠合修")]
    assert [data["enter"][0] for data in commands] == ["true", "false"]
    assert not buttons(help_message)


@pytest.mark.parametrize("mode,blue_links", [("text", True), ("native", False), ("template", True)])
def test_qq_co_training_degradation_is_readable_without_inline_links(game, play, mode, blue_links):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    play("summon")
    reply = play("co_train")
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_blue_links=blue_links,
                    spirit_pet_qq_keyboard=False, spirit_pet_command_prefix="!",
                    spirit_pet_qq_template_id="test.training")
    bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())
    asyncio.run(send_reply(bot, object(), reply, config))
    output = bot.send.call_args.args[1]
    assert "mqqapi://" not in str(output)
    if mode == "text":
        visible = output
    elif mode == "template":
        visible = output["markdown"][0].data["markdown"].params[0].values[0]
    else:
        visible = output["markdown"][0].data["markdown"].content
    assert "!灵宠合修 2" in visible and "双方各消耗 15 精力" in visible
