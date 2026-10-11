from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import pet, player, sql


def test_daily_bond_replay_and_quest_claim(game, play):
    now = 1_800_000_000
    play("adopt", now=now)
    starting_stones = player(game[1])["stones"]

    reply = play("bond", now=now, op="bond-once")
    assert reply.title == "灵宠相伴"
    assert "亲密 +2（2/100）" in reply.text()
    assert "连续陪伴：当前 1 天 · 最佳 1 天" in reply.text()
    assert pet(game[1])["affinity"] == 2
    assert player(game[1])["last_bond_day"] == beijing_day(now)
    assert player(game[1])["current_bond_streak"] == 1
    assert player(game[1])["best_bond_streak"] == 1
    assert play("bond", now=now, op="bond-once") == reply
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond", now=now)

    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_once'") == [
        {"progress": 1},
    ]
    play("claim", "灵契相伴", now=now)
    assert player(game[1])["stones"] == starting_stones + 30


def test_daily_bond_uses_beijing_midnight_and_rejects_clock_rollback(play, game):
    midnight = int(datetime(2026, 6, 1, 16, tzinfo=timezone.utc).timestamp())
    play("adopt", now=midnight - 1)
    play("bond", now=midnight - 1)
    assert player(game[1])["last_bond_day"] == "2026-06-01"
    assert player(game[1])["current_bond_streak"] == 1

    play("bond", now=midnight)
    assert player(game[1])["last_bond_day"] == "2026-06-02"
    assert player(game[1])["current_bond_streak"] == 2
    assert player(game[1])["best_bond_streak"] == 2
    assert pet(game[1])["affinity"] == 4
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond", now=midnight - 1)
    assert player(game[1])["best_bond_streak"] == 2


def test_bond_streak_resets_after_gap_and_status_expires_it_immediately(play, game):
    first_day = int(datetime(2026, 6, 1, 16, tzinfo=timezone.utc).timestamp())
    play("adopt", now=first_day)
    play("bond", now=first_day)
    play("bond", now=first_day + 86400)

    after_gap = first_day + 3 * 86400
    status = play("status", now=after_gap)
    assert "连续陪伴：当前 0 天 · 最佳 2 天" in status.text()

    reply = play("bond", now=after_gap)
    assert "连续陪伴：当前 1 天 · 最佳 2 天" in reply.text()
    assert player(game[1])["current_bond_streak"] == 1
    assert player(game[1])["best_bond_streak"] == 2


def test_status_keeps_yesterdays_streak_active_until_today_is_missed(play):
    yesterday = int(datetime(2026, 6, 1, 16, tzinfo=timezone.utc).timestamp())
    play("adopt", now=yesterday)
    play("bond", now=yesterday)

    status = play("status", now=yesterday + 86400)
    assert "连续陪伴：当前 1 天 · 最佳 1 天" in status.text()


def test_full_affinity_bond_advances_streak_and_quest_without_affinity(play, game):
    now = 1_800_000_000
    play("adopt", now=now)
    sql(game[1], "UPDATE pets SET affinity=100")
    reply = play("bond", now=now)
    assert "亲密已满，本次陪伴不再增加" in reply.text()
    assert "连续陪伴：当前 1 天 · 最佳 1 天" in reply.text()
    assert pet(game[1])["affinity"] == 100
    assert player(game[1])["last_bond_day"] == beijing_day(now)
    assert player(game[1])["current_bond_streak"] == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_once'") == [
        {"progress": 1},
    ]
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond", now=now)

    next_day = now + 86400
    sql(game[1], "UPDATE pets SET affinity=99")
    play("bond", now=next_day)
    assert pet(game[1])["affinity"] == 100
    assert player(game[1])["last_bond_day"] == beijing_day(next_day)
    assert player(game[1])["current_bond_streak"] == 2


def test_bond_requires_idle_pet_and_invalidates_team_readiness(play, game):
    now = 1_800_000_000
    play("adopt", now=now)
    play("team_create", now=now)
    play("team_ready", now=now)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is not None

    play("bond", now=now)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None

    active_pet_id = pet(game[1])["pet_id"]
    next_day = now + 86400
    sql(game[1], (
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, "
        "started_at, finishes_at, state, reward_snapshot) "
        "VALUES ('u1', ?, 'herb_gathering', '采灵药', 'bond-expedition', ?, ?, 'running', '{}')"
    ), (active_pet_id, next_day, next_day + 3600))
    with pytest.raises(GameError, match="当前不能行动"):
        play("bond", now=next_day + 1)
    assert player(game[1])["last_bond_day"] == beijing_day(now)


def test_concurrent_daily_bond_only_increases_affinity_once(game, play):
    now = 1_800_000_000
    play("adopt", now=now)

    def interact(index):
        try:
            return play("bond", now=now, op=f"parallel-bond-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(interact, range(8)))
    assert sum(isinstance(result, Reply) for result in results) == 1
    assert sum(isinstance(result, GameError) for result in results) == 7
    assert pet(game[1])["affinity"] == 2
    assert player(game[1])["current_bond_streak"] == 1
    assert player(game[1])["best_bond_streak"] == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_once'") == [
        {"progress": 1},
    ]
