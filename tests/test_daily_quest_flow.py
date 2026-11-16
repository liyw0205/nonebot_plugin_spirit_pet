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
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, sql
from .test_targeted_care import snapshot
from .test_targeted_training import add_pet
from .test_commands import onebot_event


def row_action(reply, name):
    index = next(i for i, line in enumerate(reply.lines) if line.startswith(name + "："))
    return next(link.command for link in reply.inline_commands if link.line == index)


def test_daily_board_runs_numbered_care_and_settles_each_reward(game, play):
    play("adopt", "青鸾")
    before = player(game[1])["stones"]
    page = play("quests")
    command = row_action(page, "吐纳一周天")
    assert command == "灵宠修炼 1"
    trained = play(*handlers._parse(command), op="daily-train")
    assert trained.commands == ("灵宠任务", "灵宠主线")
    assert [link.command for link in trained.inline_commands] == ["灵宠整备 1"]
    assert pet(game[1])["energy"] == 85 and pet(game[1])["exp"] > 0
    assert play(*handlers._parse(command), op="daily-train") == trained
    for name in ("温养灵契", "灵契相伴"):
        page = play("quests")
        action = row_action(page, name)
        assert action in {"灵宠喂养 1", "灵宠互动 1"}
        play(*handlers._parse(action))
    for name in ("吐纳一周天", "温养灵契", "灵契相伴"):
        command = row_action(play("quests"), name)
        assert command == f"灵宠领奖 {name} 日 2027-01-15"
        reply = play(*handlers._parse(command), op=f"claim-{name}")
        assert reply.commands == ("灵宠任务", "灵宠周常 4", "灵宠目标")
        assert play(*handlers._parse(command), op=f"claim-{name}") == reply
        before_repeat = snapshot(game[1])
        with pytest.raises(GameError, match="已领取"):
            play(*handlers._parse(command))
        assert snapshot(game[1]) == before_repeat
    assert player(game[1])["stones"] == before + 110
    assert pet(game[1])["affinity"] == 7
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_food'") == [{"quantity": 3}]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='energy_pill'") == [{"quantity": 1}]


@pytest.mark.parametrize("arg", ["2", "wrong", "1 2"])
def test_daily_board_rejects_parameters_without_resetting_state(game, play, arg):
    play("adopt")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="不接受参数"):
        play("quests", arg)
    assert snapshot(game[1]) == before


def test_daily_board_unregistered_user_is_not_created(game, play):
    before = snapshot(game[1])
    reply = play("quests")
    assert reply.inline_commands[0].command == "灵宠领养 "
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("state,reason,step", [
    ("inactive", "尚未出战", "灵宠列表"),
    ("archived", "已封存", "灵宠复原 1"),
    ("trip", "正在派遣", "灵宠行程"),
    ("tired", "精力不足", "灵宠整备 1"),
    ("stock", "灵粮不足", "灵宠商店 灵粮"),
])
def test_daily_board_shows_specific_prerequisites_without_cost(game, play, state, reason, step):
    play("adopt")
    if state == "inactive":
        sql(game[1], "DELETE FROM active_pet_slots")
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif state == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    elif state == "trip":
        play("expedition_start", "采灵药")
    elif state == "tired":
        sql(game[1], "UPDATE pets SET energy=0")
    else:
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    play("quests")
    before = snapshot(game[1])
    reply = play("quests")
    assert reason in reply.text()
    assert step in [link.command for link in reply.inline_commands]
    assert len(reply.inline_commands) == len({link.command for link in reply.inline_commands})
    if state in {"inactive", "archived", "trip", "tired"}:
        assert "灵宠修炼 1" not in [link.command for link in reply.inline_commands]
    assert snapshot(game[1]) == before


def test_daily_board_numbered_action_survives_roster_change_and_rechecks_cooldown(game, play):
    play("adopt")
    command = row_action(play("quests"), "吐纳一周天")
    target_id = add_pet(game[1])
    play("switch", str(target_id))
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    reply = play(*handlers._parse(command))
    assert reply.inline_commands[0].command == "灵宠整备 1"
    assert sql(game[1], "SELECT energy FROM pets ORDER BY pet_id") == [{"energy": 85}, {"energy": 100}]
    before = snapshot(game[1])
    with pytest.raises(GameError, match="调息"):
        play(*handlers._parse(command))
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("action,arg", [("train", "1"), ("claim", "吐纳一周天")])
def test_daily_action_and_reward_rollback_after_sqlite_writes(game, play, monkeypatch, action, arg):
    play("adopt")
    if action == "claim":
        play("train", "1")
    before = snapshot(game[1])
    original = Repository.save

    def fail_after_save(repo):
        original(repo)
        raise RuntimeError("injected settlement failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "save", fail_after_save)
        with pytest.raises(RuntimeError, match="injected settlement failure"):
            play(action, arg, op="retry-after-rollback")
    assert snapshot(game[1]) == before
    reply = play(action, arg, op="retry-after-rollback")
    assert reply.title in {"吐纳修炼", "任务领奖"}
    assert play(action, arg, op="retry-after-rollback") == reply


@pytest.mark.parametrize("prefix", ["", "/", "!"])
def test_daily_board_qq_links_and_navigation_are_unique(game, play, prefix):
    play("adopt")
    reply = play("quests")
    plain, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))
    markdown = native["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    payloads = [button.action.data for segment in native["keyboard"]
                for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert set(links) == {prefix + link.command for link in reply.inline_commands}
    assert set(payloads) == {prefix + command for command in reply.commands}
    assert len(payloads) <= 4
    assert len(links + payloads) == len(set(links + payloads))
    assert "mqqapi://" not in plain
    assert f"开始修炼（{prefix}灵宠修炼 1）" in plain


def test_daily_board_onebot_transport_preserves_numbered_command(game, play, monkeypatch):
    play("adopt", user="12345")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: 1_800_000_000)
    event = onebot_event("!灵宠任务")
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    text = bot.send.call_args.args[1]
    assert "开始修炼（!灵宠修炼 1）" in text
    assert "mqqapi://" not in text
    assert pet(game[1], "12345")["energy"] == 100
