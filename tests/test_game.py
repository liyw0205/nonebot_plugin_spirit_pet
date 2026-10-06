from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.catalog import REALMS, breakthrough_cost
from nonebot_plugin_spirit_pet.config import Config
from nonebot_plugin_spirit_pet.models import GameError
from nonebot_plugin_spirit_pet.service import Game
from nonebot_plugin_spirit_pet.storage import Store


class FixedRandom:
    def choice(self, values):
        return values[0]

    def randint(self, start, stop):
        return start

    def random(self):
        return 0.0


@pytest.fixture
def game(tmp_path):
    store = Store(tmp_path / "shared" / "spirit_pet.db")
    store.initialize()
    return Game(store, Config(), FixedRandom()), store


def play(game, user_id, action, argument="", operation_id=None, now=1_800_000_000):
    return game.execute(user_id, action, argument, operation_id or f"{action}-{now}", now)


def get_player(store, user_id):
    with closing(sqlite3.connect(store.path)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone())


def test_different_adapter_entry_points_share_exact_same_user_id(game):
    service, store = game
    play(service, "same-id", "adopt", "青鸾")

    same_player = play(service, "same-id", "status")
    different_player = play(service, "another-id", "identity")

    assert "青鸾" in same_player.title
    assert "another-id" in different_player.text()
    assert get_player(store, "same-id")["user_id"] == "same-id"
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 1


def test_adoption_requires_supported_species_and_rejects_second_pet(game):
    service, store = game
    with pytest.raises(GameError):
        play(service, "u1", "adopt", "天外灵兽")
    with closing(store.connect()) as conn:
        assert not conn.execute("SELECT 1 FROM players").fetchone()
    play(service, "u1", "adopt", "青鸾", "first-pet-valid")
    with pytest.raises(GameError):
        play(service, "u1", "adopt", "玄狐", "second-pet")
    assert get_player(store, "u1")["species"] == "青鸾"


def test_commands_replay_identically_without_duplicating_rewards(game):
    service, store = game
    play(service, "u1", "adopt", "玄狐", "adopt")
    first = play(service, "u1", "sign", operation_id="retry-safe-sign")
    repeated = play(service, "u1", "sign", operation_id="retry-safe-sign")
    assert repeated == first
    assert get_player(store, "u1")["stones"] == 300

    with pytest.raises(GameError, match="今日已领取"):
        play(service, "u1", "sign", operation_id="second-daily-sign")


def test_game_error_rolls_back_energy_restoration_and_state(game):
    service, store = game
    play(service, "u1", "adopt", "白泽", "adopt")
    play(service, "u1", "train", operation_id="first-train", now=1_800_000_000)
    initial = get_player(store, "u1")

    with pytest.raises(GameError, match="调息"):
        play(service, "u1", "train", operation_id="cooldown-rejected", now=1_800_000_030)
    current = get_player(store, "u1")
    assert current["energy"] == initial["energy"]
    assert current["energy_updated"] == initial["energy_updated"]


def test_feed_purchase_rename_inventory_and_leaderboard(game):
    service, store = game
    play(service, "u1", "adopt", "白泽", "adopt-u1")
    assert "小白" in play(service, "u1", "rename", "小白", "rename-u1").text()
    play(service, "u1", "buy", "灵粮 2", "buy-u1")
    assert "灵粮：5" in play(service, "u1", "bag", operation_id="bag-u1").text()
    play(service, "u1", "feed", operation_id="feed-u1")
    assert "小白" in play(service, "u1", "status", operation_id="status-u1").title
    play(service, "u2", "adopt", "青鸾", "adopt-u2")
    assert "小白" in play(service, "u1", "rank", operation_id="rank-u1").text()


def test_breakthrough_spends_resources_and_advances_realm(game):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    _, stone_cost = breakthrough_cost(0)
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("UPDATE players SET exp=100, stones=? WHERE user_id='u1'", (stone_cost,))
        conn.commit()

    result = play(service, "u1", "breakthrough", operation_id="breakthrough-success")
    pet = get_player(store, "u1")
    assert REALMS[pet["realm"]] == "凝气"
    assert pet["exp"] == 0
    assert pet["stones"] == 0
    assert "破境成功" in result.title


def test_purchase_quantity_and_nickname_are_validated(game):
    service, _ = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    with pytest.raises(GameError):
        play(service, "u1", "buy", "灵粮 999", "invalid-purchase")
    with pytest.raises(GameError):
        play(service, "u1", "rename", "不合法的超长灵宠名字123", "invalid-name")


def test_concurrent_adoptions_are_atomic(game):
    service, store = game

    def adopt(index):
        try:
            return play(service, "same-id", "adopt", "青鸾", f"concurrent-{index}")
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(adopt, range(8)))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    with closing(store.connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 1


def test_concurrent_redelivery_pays_only_once(game):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: play(service, "u1", "sign", operation_id="same-message"), range(8)
        ))
    assert all(result == results[0] for result in results)
    assert get_player(store, "u1")["stones"] == 300


def test_persistence_across_store_instances(game):
    service, store = game
    play(service, "u1", "adopt", "蛟龙", "adopt")
    fresh = Store(store.path)
    fresh.initialize()
    other_entry = Game(fresh, Config(), FixedRandom())
    assert play(other_entry, "u1", "status").title == "蛟龙"
    play(other_entry, "another-id", "adopt", "白泽", "other-adopt")
    rank = play(other_entry, "another-id", "rank", operation_id="shared-rank").text()
    assert "蛟龙" in rank and "白泽" in rank


def test_daily_reward_resets_at_beijing_midnight(game):
    from datetime import datetime, timezone

    service, store = game
    midnight = int(datetime(2026, 10, 7, 16, tzinfo=timezone.utc).timestamp())
    play(service, "u1", "adopt", "青鸾", "adopt", midnight - 10)
    play(service, "u1", "sign", operation_id="day-1", now=midnight - 1)
    play(service, "u1", "sign", operation_id="day-2", now=midnight)
    assert get_player(store, "u1")["stones"] == 500
    with pytest.raises(GameError):
        play(service, "u1", "sign", operation_id="same-day", now=midnight + 1)


def test_energy_retains_fractional_interval_and_never_exceeds_cap(game):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt", now=1000)
    play(service, "u1", "train", operation_id="train", now=1000)
    play(service, "u1", "status", operation_id="before", now=1299)
    assert get_player(store, "u1")["energy"] == 85
    play(service, "u1", "status", operation_id="after", now=1301)
    assert get_player(store, "u1")["energy"] == 86
    assert get_player(store, "u1")["energy_updated"] == 1300
    play(service, "u1", "status", operation_id="cap", now=100000)
    assert get_player(store, "u1")["energy"] == 100


def test_explore_has_its_own_cooldown(game):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    play(service, "u1", "train", operation_id="train")
    play(service, "u1", "explore", operation_id="explore")
    assert get_player(store, "u1")["energy"] == 60
    assert get_player(store, "u1")["stones"] == 130
    with pytest.raises(GameError):
        play(service, "u1", "explore", operation_id="explore-again")


def test_failed_breakthrough_and_max_realm(game):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    with closing(store.connect()) as conn:
        conn.execute("UPDATE players SET exp=1000, stones=1000")
    service.rng.random = lambda: 1.0
    assert play(service, "u1", "breakthrough", operation_id="failure").title == "破境未成"
    pet = get_player(store, "u1")
    assert (pet["realm"], pet["exp"], pet["stones"]) == (0, 975, 950)
    with closing(store.connect()) as conn:
        conn.execute("UPDATE players SET realm=6")
    with pytest.raises(GameError, match="最高境界"):
        play(service, "u1", "breakthrough", operation_id="cap")


@pytest.mark.parametrize("action", ["feed", "train", "explore", "breakthrough"])
def test_insufficient_resources_never_commit(game, action):
    service, store = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    with closing(store.connect()) as conn:
        conn.execute("UPDATE players SET energy=0, food=0, stones=0, exp=0")
    before = get_player(store, "u1")
    with pytest.raises(GameError):
        play(service, "u1", action, operation_id="insufficient")
    assert get_player(store, "u1") == before


@pytest.mark.parametrize("amount", ["0", "-1", "100", "1.5", "1; DROP TABLE players", ""])
def test_invalid_purchase_quantities(game, amount):
    service, _ = game
    play(service, "u1", "adopt", "青鸾", "adopt")
    with pytest.raises(GameError):
        play(service, "u1", "buy", f"灵粮 {amount}", "bad-buy")


def test_newer_schema_is_not_downgraded(tmp_path):
    store = Store(tmp_path / "future.db")
    with closing(store.connect()) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="99"):
        store.initialize()
