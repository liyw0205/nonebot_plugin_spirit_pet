import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.banquet_reward_content import BanquetReward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql
from .test_banquet import ready_to_banquet
from .test_commands import onebot_event

NOW = 1_800_000_000
WEEK = 7 * 86_400


def seed_banquets(game, count, user="u1"):
    start = beijing_week(NOW)[0]
    for index in range(count):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (user, f"banquet_{start + index * WEEK}", index + 1),
        )


def adopt(game, play):
    play("adopt", "青鸾", now=NOW)


def test_content_defines_strict_cumulative_tiers(game):
    entries = sorted(game[0].content.banquet_rewards.values(), key=lambda entry: entry.threshold)
    assert [entry.threshold for entry in entries] == [2, 4, 8]
    assert all(entry.stones or entry.items for entry in entries)
    assert all(item in game[0].content.items for entry in entries for item in entry.items)
    with pytest.raises(ValidationError):
        BanquetReward.model_validate({"id": "empty", "name": "空", "threshold": 2})
    with pytest.raises(ValidationError):
        BanquetReward.model_validate({"id": "bad", "name": "坏", "threshold": 0, "stones": 1})


def test_catalog_rejects_wrong_tier_set(tmp_path):
    source = Catalog.load()
    assert source.banquet_rewards
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = __import__("pathlib").Path(__file__).resolve().parents[1] / "src/plugins/nonebot_plugin_spirit_pet/data"
    for entry in original.glob("*.json"):
        (data_dir / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = data_dir / "banquet_rewards.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"threshold": 8', '"threshold": 6'), encoding="utf-8")
    with pytest.raises(ValueError, match="2/4/8"):
        Catalog.load(data_dir)


def test_real_weekly_banquets_unlock_and_pay_cumulative_reward(game, play):
    adopt(game, play)
    ready_to_banquet(game)
    play("banquet", "开席", now=NOW, op="banquet-source-1")
    play("banquet", "开席", now=NOW + WEEK, op="banquet-source-2")
    page = play("banquet_rewards", now=NOW + WEEK + 1)
    assert "累计家宴：2 席" in page.lines[0]
    assert "2 席 · 两席相逢" in page.text() and "可领取" in page.text()
    before = player(game[1])["stones"]
    result = play("banquet_rewards", "领奖 2", now=NOW + WEEK + 1, op="banquet-reward-2")
    assert result.title == "灵宠家宴赏"
    assert player(game[1])["stones"] == before + 300
    assert items(game[1])["spirit_food"] == 10 - 8 + 2 + 3
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id='banquet_reward_2'") == [
        {"progress": 2, "claimed": 1}
    ]
    with pytest.raises(GameError, match="已领取"):
        play("banquet_rewards", "领奖 2", now=NOW + WEEK + 2, op="banquet-reward-repeat")


def test_reward_survives_restart_and_expired_operation_replay_is_read_only(game, play):
    adopt(game, play)
    seed_banquets(game, 4)
    first = play("banquet_rewards", "领奖 2", op="banquet-restart-2")
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id"))
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "banquet_rewards", "", "banquet-view-restart", NOW + 8 * WEEK) == play(
        "banquet_rewards", "", now=NOW + 8 * WEEK,
    )
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id")) == before
    with pytest.raises(GameError, match="已领取"):
        reopened.execute("u1", "banquet_rewards", "领奖 2", "banquet-restart-2", NOW + 8 * WEEK)
    assert first.title == "灵宠家宴赏"


def test_invalid_and_unregistered_requests_do_not_write(game, play):
    page = play("banquet_rewards", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    adopt(game, play)
    seed_banquets(game, 2)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id"))
    for argument in ("领奖", "领奖 0", "领奖 3", "领奖 2 extra", "领奖 ８"):
        with pytest.raises(GameError):
            play("banquet_rewards", argument, op=f"banquet-invalid-{argument}")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id")) == before


def test_concurrent_claims_are_serialized(game, play):
    adopt(game, play)
    seed_banquets(game, 2)

    def attempt(index):
        try:
            return play("banquet_rewards", "领奖 2", op=f"banquet-parallel-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id='banquet_reward_2'") == [{"n": 1}]
    assert player(game[1])["stones"] == game[0].content.rules.starter_stones + 300


def test_reward_marker_failure_rolls_back_and_retry_is_clean(game, play):
    adopt(game, play)
    seed_banquets(game, 2)
    before = (player(game[1]), items(game[1]))
    sql(
        game[1],
        "CREATE TRIGGER reject_banquet_reward BEFORE INSERT ON quest_progress "
        "WHEN NEW.quest_id='banquet_reward_2' BEGIN SELECT RAISE(ABORT, 'banquet reward failure'); END",
    )
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="banquet reward failure"):
        play("banquet_rewards", "领奖 2", op="banquet-failure")
    assert (player(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='banquet_reward_2'")
    sql(game[1], "DROP TRIGGER reject_banquet_reward")
    assert "两席相逢已领取" in play("banquet_rewards", "领奖 2", op="banquet-failure-retry").text()


def test_help_objective_and_command_aliases_are_reachable(game, play):
    assert handlers._parse("灵宠家宴赏") == ("banquet_rewards", "")
    assert handlers._parse("灵宠家宴赏 领奖 2") == ("banquet_rewards", "领奖 2")
    assert handlers._parse("灵宠家宴领奖 4") == ("banquet_rewards", "4")
    assert "灵宠家宴领奖 档位" in play("help", "成长").text()
    adopt(game, play)
    seed_banquets(game, 2)
    assert "家宴赏：累计 2 席 · 可领 1 档" in play("objectives").text()


def test_qq_and_onebot_share_the_reward_page(game, play, monkeypatch):
    adopt(game, play)
    seed_banquets(game, 2)
    page = play("banquet_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert "灵宠家宴赏" in str(message)
    assert page.inline_commands[0].command == "灵宠家宴领奖 2"
    assert message["keyboard"]

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠家宴赏", 88), "!灵宠家宴赏")

    play("adopt", "青鸾", user="12345", op="onebot-adopt")
    seed_banquets(game, 2, user="12345")
    asyncio.run(run())
    assert "累计家宴：2 席" in str(bot.send.call_args.args[1])
