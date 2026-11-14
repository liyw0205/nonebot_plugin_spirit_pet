import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.visit_reward_content import VisitReward
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, player_uid, sql
from .test_commands import onebot_event
from .test_visits import setup_pair

NOW = 1_800_000_000
DAY = 86_400


def seed_visits(game, count, user="u1", start=NOW):
    for index in range(count):
        day = beijing_day(start + index * DAY)
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
            (user, f"visit_{day}_{10000 + index}"),
        )


def snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(store, "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY user_id, quest_id"),
    )


def adopt(game, play):
    play("adopt", "青鸾", now=NOW, op="visit-reward-adopt")


def test_content_defines_three_strict_tiers(game):
    entries = sorted(game[0].content.visit_rewards.values(), key=lambda entry: entry.threshold)
    assert [entry.threshold for entry in entries] == [3, 10, 30]
    assert all(entry.stones or entry.items for entry in entries)
    assert all(item in game[0].content.items for entry in entries for item in entry.items)
    with pytest.raises(ValidationError):
        VisitReward.model_validate({"id": "empty", "name": "空", "threshold": 3})
    with pytest.raises(ValidationError):
        VisitReward.model_validate({"id": "bad", "name": "坏", "threshold": 0, "stones": 1})


def test_catalog_rejects_wrong_visit_tiers(tmp_path):
    Catalog.load()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = __import__("pathlib").Path(__file__).resolve().parents[1] / "src/plugins/nonebot_plugin_spirit_pet/data"
    for entry in original.glob("*.json"):
        (data_dir / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = data_dir / "visit_rewards.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"threshold": 10', '"threshold": 9'), encoding="utf-8")
    with pytest.raises(ValueError, match="3/10/30"):
        Catalog.load(data_dir)


def test_real_visit_receipts_across_days_unlock_and_pay(game, play):
    uid2 = setup_pair(game, play)
    play("visits", str(uid2), now=NOW, op="visit-source-real")
    seed_visits(game, 2, start=NOW + DAY)
    page = play("visits_rewards", now=NOW + 3 * DAY)
    assert "累计串门：3 次" in page.lines[0]
    assert "3 次 · 初访有礼" in page.text() and "可领取" in page.text()
    before = player(game[1])["stones"]
    result = play("visits_rewards", "领奖 3", now=NOW + 3 * DAY, op="visit-reward-3")
    assert result.title == "灵宠串门礼"
    assert player(game[1])["stones"] == before + 80
    assert items(game[1])["spirit_food"] >= 2
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id='visit_reward_3'") == [
        {"progress": 3, "claimed": 1}
    ]


def test_count_excludes_daily_counters_and_reward_markers(game, play):
    adopt(game, play)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES "
        "('u1', 'visit_day_2026-11-14', 9, 0), ('u1', 'visit_reward_10', 10, 1), "
        "('u1', 'visit_fake_friend', 1, 0)",
    )
    page = play("visits_rewards")
    assert "累计串门：0 次" in page.lines[0]
    assert "还差 3 次" in page.text()


def test_reward_survives_restart_and_rejects_repeat(game, play):
    adopt(game, play)
    seed_visits(game, 10)
    first = play("visits_rewards", "领奖 3", op="visit-restart-3")
    before = snapshot(game[1])
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "visits_rewards", "", "visit-restart-page", NOW + 30 * DAY).title == "灵宠串门礼"
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="已领取"):
        reopened.execute("u1", "visits_rewards", "领奖 3", "visit-restart-repeat", NOW + 30 * DAY)
    assert first.title == "灵宠串门礼"


def test_all_tiers_pay_fixed_rewards_once(game, play):
    adopt(game, play)
    seed_visits(game, 30)
    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    for threshold in (3, 10, 30):
        play("visits_rewards", f"领奖 {threshold}", op=f"visit-tier-{threshold}")
    assert player(game[1])["stones"] == before_stones + 80 + 240 + 800
    inventory = items(game[1])
    assert inventory["spirit_food"] == before_items.get("spirit_food", 0) + 2
    assert inventory["forge_ore"] == before_items.get("forge_ore", 0) + 1
    assert inventory["bloodline_essence"] == before_items.get("bloodline_essence", 0) + 1
    assert sql(
        game[1],
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE quest_id LIKE 'visit_reward_%' ORDER BY quest_id",
    ) == [
        {"quest_id": "visit_reward_10", "progress": 30, "claimed": 1},
        {"quest_id": "visit_reward_3", "progress": 30, "claimed": 1},
        {"quest_id": "visit_reward_30", "progress": 30, "claimed": 1},
    ]


def test_invalid_unmet_and_unregistered_requests_do_not_write(game, play):
    page = play("visits_rewards", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    adopt(game, play)
    before = snapshot(game[1])
    for argument in ("领奖", "领奖 0", "领奖 4", "领奖 3 extra", "领奖 ３"):
        with pytest.raises(GameError):
            play("visits_rewards", argument, op=f"visit-invalid-{argument}")
    with pytest.raises(GameError, match="还未达到"):
        play("visits_rewards", "领奖 3", op="visit-unmet")
    assert snapshot(game[1]) == before


def test_concurrent_claims_are_serialized(game, play):
    adopt(game, play)
    seed_visits(game, 3)

    def attempt(index):
        try:
            return play("visits_rewards", "领奖 3", op=f"visit-parallel-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id='visit_reward_3'") == [{"n": 1}]
    assert player(game[1])["stones"] == game[0].content.rules.starter_stones + 80


def test_reward_marker_failure_rolls_back_and_retry_is_clean(game, play):
    adopt(game, play)
    seed_visits(game, 3)
    before = snapshot(game[1])
    sql(
        game[1],
        "CREATE TRIGGER reject_visit_reward BEFORE INSERT ON quest_progress "
        "WHEN NEW.quest_id='visit_reward_3' BEGIN SELECT RAISE(ABORT, 'visit reward failure'); END",
    )
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="visit reward failure"):
        play("visits_rewards", "领奖 3", op="visit-failure")
    assert snapshot(game[1]) == before
    sql(game[1], "DROP TRIGGER reject_visit_reward")
    assert "初访有礼已领取" in play("visits_rewards", "领奖 3", op="visit-failure-retry").text()


def test_help_objective_alias_and_qq_onebot_share_entry(game, play, monkeypatch):
    assert handlers._parse("灵宠串门礼") == ("visits_rewards", "")
    assert handlers._parse("灵宠串门礼 领奖 3") == ("visits_rewards", "领奖 3")
    assert handlers._parse("灵宠串门领奖 3") == ("visits_rewards", "3")
    assert "灵宠串门领奖 档位" in play("help", "秘境与关卡").text()
    adopt(game, play)
    seed_visits(game, 3)
    page = play("visits_rewards")
    assert "串门礼：累计 3 次 · 可领 1 档" in play("objectives").text()
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert "灵宠串门礼" in str(message)
    assert page.inline_commands[0].command == "灵宠串门领奖 3"
    assert message["keyboard"]

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠串门礼", 88), "!灵宠串门礼")

    play("adopt", "青鸾", user="12345", op="visit-onebot-adopt")
    seed_visits(game, 3, user="12345")
    asyncio.run(run())
    assert "累计串门：3 次" in str(bot.send.call_args.args[1])
