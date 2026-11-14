import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.cooking_reward_content import CookingReward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, player, sql
from .test_commands import onebot_event
from .test_cooking import account, finish

NOW = 1_800_000_000


def seed_finished(game, count, user="u1", portions=1):
    for index in range(count):
        sql(
            game[1],
            "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
            (
                f"seed-cooking-{user}-{index}-{count}", user, NOW + index,
                json.dumps({
                    "kind": "cooking", "status": "finished", "event": "finish",
                    "portions": portions, "grade": "成膳", "dish": {"id": "rice_porridge"},
                }, ensure_ascii=False),
                json.dumps({"title": "掌勺成品", "lines": ["已完成"], "commands": []}),
            ),
        )


def test_content_has_strict_cooking_milestones(game):
    entries = sorted(game[0].content.cooking_rewards.values(), key=lambda entry: entry.threshold)
    assert [entry.threshold for entry in entries] == [1, 3, 6]
    assert all(entry.stones or entry.items for entry in entries)
    assert all(item in game[0].content.items for entry in entries for item in entry.items)
    with pytest.raises(ValidationError):
        CookingReward.model_validate({"id": "empty", "name": "空", "threshold": 1})
    with pytest.raises(ValidationError):
        CookingReward.model_validate({"id": "bad", "name": "坏", "threshold": 0, "stones": 1})


def test_catalog_rejects_wrong_cooking_tier_set(tmp_path):
    source = Catalog.load()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = __import__("pathlib").Path(__file__).resolve().parents[1] / "src/plugins/nonebot_plugin_spirit_pet/data"
    for entry in original.glob("*.json"):
        (data_dir / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = data_dir / "cooking_rewards.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"threshold": 6', '"threshold": 5'), encoding="utf-8")
    with pytest.raises(ValueError, match="1/3/6"):
        Catalog.load(data_dir)
    assert source.cooking_rewards


def test_only_real_successful_pots_count(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥", op="burn-start")
    finish(play, ("离火", "离火", "离火"), prefix="burn")
    play("cuisine_cook", "灵米粥", op="instant-cook")
    page = play("cooking_rewards")
    assert "成功成膳：0 锅" in page.text()
    play("cooking", "开锅 灵米粥", op="success-start")
    finish(play, prefix="success")
    assert "成功成膳：1 锅" in play("cooking_rewards").text()
    assert sql(game[1], "SELECT COUNT(*) AS n FROM duel_actions WHERE json_extract(snapshot,'$.status')='finished' AND json_extract(snapshot,'$.portions')>0") == [{"n": 1}]


def test_claim_persists_across_restart_and_rejects_bad_tiers(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥", op="claim-start")
    finish(play, prefix="claim")
    before = player(game[1])["stones"]
    before_food = items(game[1]).get("spirit_food", 0)
    result = play("cooking_rewards", "领奖 1", op="cooking-reward-1")
    assert result.title == "灵宠掌勺成品赏"
    assert player(game[1])["stones"] == before + 100
    assert items(game[1])["spirit_food"] == before_food + 1
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id='cooking_reward_1'") == [{"progress": 1, "claimed": 1}]
    restarted = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    with pytest.raises(GameError, match="已领取"):
        restarted.execute("u1", "cooking_rewards", "领奖 1", "cooking-reward-repeat", NOW + 86400)
    for argument in ("领奖", "领奖 0", "领奖 2", "领奖 1 extra", "领奖 １"):
        with pytest.raises(GameError):
            play("cooking_rewards", argument, op=f"cooking-invalid-{argument}")


def test_unregistered_and_read_only_pages_do_not_write(game, play):
    before = sql(game[1], "SELECT * FROM players")
    page = play("cooking_rewards", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players") == before
    account(game, play)
    seed_finished(game, 3)
    snapshot = sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id")
    assert "可领取" in play("cooking_rewards").text()
    assert sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id") == snapshot


def test_concurrent_claims_are_serialized(game, play):
    account(game, play)
    seed_finished(game, 1)

    def attempt(index):
        try:
            return play("cooking_rewards", "领奖 1", op=f"cooking-parallel-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id='cooking_reward_1'") == [{"n": 1}]
    assert player(game[1])["stones"] == game[0].content.rules.starter_stones + 100


def test_reward_marker_failure_rolls_back_and_retry_is_clean(game, play):
    account(game, play)
    seed_finished(game, 1)
    before = (player(game[1]), items(game[1]))
    sql(
        game[1],
        "CREATE TRIGGER reject_cooking_reward BEFORE INSERT ON quest_progress "
        "WHEN NEW.quest_id='cooking_reward_1' BEGIN SELECT RAISE(ABORT, 'cooking reward failure'); END",
    )
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="cooking reward failure"):
        play("cooking_rewards", "领奖 1", op="cooking-failure")
    assert (player(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='cooking_reward_1'")
    sql(game[1], "DROP TRIGGER reject_cooking_reward")
    assert "初掌灶火已领取" in play("cooking_rewards", "领奖 1", op="cooking-failure-retry").text()


def test_help_objective_and_qq_onebot_share_the_entry(game, play, monkeypatch):
    assert _parse("灵宠掌勺成品赏") == ("cooking_rewards", "")
    assert _parse("灵宠掌勺成品赏 领奖 3") == ("cooking_rewards", "领奖 3")
    assert _parse("灵宠掌勺成品领奖 1") == ("cooking_reward_claim", "1")
    account(game, play)
    seed_finished(game, 1)
    page = play("cooking_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert "灵宠掌勺成品赏" in str(message)
    assert page.inline_commands[0].command == "灵宠掌勺成品领奖 1"
    assert message["keyboard"]
    assert "灵宠掌勺成品领奖 档位" in play("help", "成长").text()
    assert "掌勺成品赏：成功 1 锅 · 可领 1 档" in play("objectives").text()

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠掌勺成品赏", 88), "!灵宠掌勺成品赏")

    play("adopt", "青鸾", user="12345", op="onebot-adopt")
    seed_finished(game, 1, user="12345")
    asyncio.run(run())
    assert "成功成膳：1 锅" in str(bot.send.call_args.args[1])
