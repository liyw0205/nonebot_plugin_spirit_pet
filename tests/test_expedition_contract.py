import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import Range, Reward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql


NOW = 1_800_000_000
OWNER = "private-expedition-owner"
OTHER = "private-expedition-other"
TASKS = (("采灵药", "herb_gathering", 25, 0), ("寻锻矿", "ore_survey", 30, 1), ("探血髓", "essence_search", 40, 2))


def register(play, other=False):
    play("adopt", "青鸾", user=OWNER)
    play("dao_name", "云行", user=OWNER)
    if other:
        play("adopt", "玄狐", user=OTHER)
        play("dao_name", "月明", user=OTHER)


def journeys(store, user=OWNER):
    return sql(store, "SELECT * FROM expeditions WHERE user_id=? ORDER BY job_id", (user,))


def world(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY 1") for table in (
        "players", "pets", "inventory", "expeditions", "team_members", "duels", "quest_progress",
    )}


def reward_state(store, job):
    original_pet = sql(store, "SELECT * FROM pets WHERE pet_id=?", (job["pet_id"],))[0]
    return original_pet["exp"], player(store, job["user_id"])["stones"], items(store, job["user_id"])


def assert_reward(store, job, before, multiplier=1):
    snapshot = json.loads(job["reward_snapshot"])
    exp, stones, inventory = reward_state(store, job)
    assert exp == before[0] + multiplier * snapshot["exp"]
    assert stones == before[1] + multiplier * snapshot["stones"]
    for key in set(inventory) | set(before[2]) | set(snapshot["items"]):
        assert inventory.get(key, 0) == before[2].get(key, 0) + multiplier * snapshot["items"].get(key, 0)


def race(game, commands):
    barrier = Barrier(len(commands))

    def execute(command):
        barrier.wait(timeout=10)
        try:
            return game.execute(*command)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        return list(pool.map(execute, commands))


@pytest.mark.parametrize("task,task_id,cost,realm", TASKS)
def test_start_persists_reward_and_schedule_and_charges_exact_task_cost(game, play, task, task_id, cost, realm):
    register(play)
    sql(game[1], "UPDATE pets SET realm=?", (realm,))
    before = player(game[1], OWNER), items(game[1], OWNER)
    result = play("expedition_start", task, user=OWNER, op="departure")
    job = journeys(game[1])[0]
    assert job["task_id"] == task_id and job["task_name"] == task
    assert job["pet_id"] == pet(game[1], OWNER)["pet_id"]
    assert job["source_operation_id"] == "departure"
    assert job["started_at"] == NOW
    assert job["finishes_at"] == NOW + game[0].config.spirit_pet_expedition_duration == NOW + 3600
    assert job["state"] == "running" and job["settled_at"] is None
    snapshot = json.loads(job["reward_snapshot"])
    definition = game[0].content.expeditions[task_id].reward
    assert set(snapshot) == {"exp", "stones", "items"}
    assert snapshot["exp"] == definition.exp.minimum
    assert snapshot["stones"] == definition.stones.minimum
    assert snapshot["items"] == {key: bounds.minimum for key, bounds in definition.items.items()}
    assert pet(game[1], OWNER)["energy"] == 100 - cost
    assert (player(game[1], OWNER), items(game[1], OWNER)) == before
    assert OWNER not in result.text() + " ".join(result.commands)


@pytest.mark.parametrize("action,arg", [
    ("expedition_start", "采灵药"), ("expedition_claim", "1"),
    ("expedition_cancel", "1"), ("expedition_status", ""),
])
def test_unregistered_users_cannot_mutate_or_view_personal_journeys(game, play, action, arg):
    with pytest.raises(GameError):
        play(action, arg, user=OWNER)
    assert not journeys(game[1])
    assert not sql(game[1], "SELECT * FROM players")


@pytest.mark.parametrize("action", ["expedition_status", "expedition_claim", "expedition_cancel"])
def test_job_id_does_not_authorize_another_player(game, play, action):
    register(play, other=True)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = world(game[1])
    with pytest.raises(GameError):
        play(action, str(job["job_id"]), user=OTHER, now=job["finishes_at"])
    assert world(game[1]) == before


@pytest.mark.parametrize("task,task_id,cost,realm", TASKS)
def test_energy_gate_rolls_back_start_without_creating_a_job(game, play, task, task_id, cost, realm):
    register(play)
    sql(game[1], "UPDATE pets SET realm=?, energy=?", (realm, cost - 1))
    before = world(game[1])
    with pytest.raises(GameError):
        play("expedition_start", task, user=OWNER)
    assert world(game[1]) == before


@pytest.mark.parametrize("task,task_id,cost,realm", TASKS[1:])
def test_realm_gate_rolls_back_start(game, play, task, task_id, cost, realm):
    register(play)
    sql(game[1], "UPDATE pets SET realm=?", (realm - 1,))
    before = world(game[1])
    with pytest.raises(GameError):
        play("expedition_start", task, user=OWNER)
    assert world(game[1]) == before


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_claim_boundary_credits_exactly_the_persisted_reward(game, play, offset):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    if offset < 0:
        original = world(game[1])
        with pytest.raises(GameError):
            play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"] + offset)
        assert world(game[1]) == original
    else:
        play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"] + offset)
        settled = journeys(game[1])[0]
        assert settled["state"] == "claimed"
        assert settled["settled_at"] == job["finishes_at"] + offset
        assert_reward(game[1], job, before)
        with pytest.raises(GameError):
            play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"] + offset)
        assert_reward(game[1], job, before)


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_cancel_boundary_never_refunds_energy_or_grants_reward(game, play, offset):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = world(game[1])
    if offset >= 0:
        with pytest.raises(GameError):
            play("expedition_cancel", str(job["job_id"]), user=OWNER, now=job["finishes_at"] + offset)
        assert world(game[1]) == before
    else:
        play("expedition_cancel", str(job["job_id"]), user=OWNER, now=job["finishes_at"] + offset)
        assert journeys(game[1])[0]["state"] == "cancelled"
        assert pet(game[1], OWNER)["energy"] == 75
        assert world(game[1])["pets"] == before["pets"]
        assert world(game[1])["players"] == before["players"]
        assert world(game[1])["inventory"] == before["inventory"]


@pytest.mark.parametrize("action", ["expedition_claim", "expedition_cancel"])
@pytest.mark.parametrize("offset", [0, 3600])
def test_argumentless_terminal_commands_are_queries_only(game, play, action, offset):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    before = world(game[1])
    reply = play(action, user=OWNER, now=NOW + offset)
    assert world(game[1]) == before
    assert OWNER not in reply.text() + " ".join(reply.commands)


def test_clock_rollback_cannot_cancel_before_departure_or_restart_before_settlement(game, play):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = world(game[1])
    for action in ("expedition_cancel", "expedition_claim"):
        with pytest.raises(GameError):
            play(action, str(job["job_id"]), user=OWNER, now=NOW - 1)
        assert world(game[1]) == before
    play("expedition_cancel", str(job["job_id"]), user=OWNER, now=NOW + 10)
    settled = world(game[1])
    with pytest.raises(GameError):
        play("expedition_start", "采灵药", user=OWNER, now=NOW + 9)
    assert world(game[1]) == settled


def test_completed_unclaimed_job_still_blocks_a_second_departure(game, play):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    before = world(game[1])
    with pytest.raises(GameError):
        play("expedition_start", "采灵药", user=OWNER, now=NOW + 3601)
    assert world(game[1]) == before


def test_restart_preserves_snapshot_deadline_and_settlement(game, play):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng)
    assert journeys(reopened) == [job]
    restarted.execute(OWNER, "expedition_claim", str(job["job_id"]), "restarted-claim", job["finishes_at"])
    assert journeys(reopened)[0]["state"] == "claimed"
    assert_reward(reopened, job, before)


def test_claim_uses_snapshot_without_drawing_randomness_again(game, play):
    class NoFurtherDraws:
        def randint(self, start, stop):
            raise AssertionError("claim must not draw rewards again")

        def random(self):
            raise AssertionError("claim must not use new randomness")

    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    game[0].rng = NoFurtherDraws()
    play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"])
    assert_reward(game[1], job, before)


def test_reward_goes_to_original_pet_after_switching_and_other_pet_remains_usable(game, play):
    register(play)
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", user=OWNER)
    owned = sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (OWNER,))
    second_id = owned[1]["pet_id"]
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    play("switch", str(second_id), user=OWNER)
    play("train", user=OWNER)
    second_exp = pet(game[1], OWNER)["exp"]
    play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"])
    assert pet(game[1], OWNER)["pet_id"] == second_id
    assert pet(game[1], OWNER)["exp"] == second_exp
    assert_reward(game[1], job, before)


@pytest.mark.parametrize("remove_task", [False, True])
def test_in_flight_reward_name_and_duration_survive_catalog_changes(game, play, remove_task):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    original = game[0].content
    if remove_task:
        definitions = {key: value for key, value in original.expeditions.items() if key != job["task_id"]}
    else:
        new_reward = Reward(exp=Range(minimum=999, maximum=999), stones=Range(minimum=888, maximum=888))
        task = original.expeditions[job["task_id"]].model_copy(update={"reward": new_reward, "name": "新委托"})
        definitions = {**original.expeditions, job["task_id"]: task}
    game[0].content = replace(original, expeditions=definitions)
    game[0].config = Config(spirit_pet_expedition_duration=7200)
    reply = play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"])
    assert job["task_name"] in reply.text()
    assert journeys(game[1])[0]["finishes_at"] == job["finishes_at"]
    assert_reward(game[1], job, before)


def test_missing_reward_definition_preserves_claim_for_retry(game, play):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    original = game[0].content
    reward_items = json.loads(job["reward_snapshot"])["items"]
    assert reward_items
    removed = next(iter(reward_items))
    game[0].content = replace(original, items={key: item for key, item in original.items.items() if key != removed})
    before = world(game[1])
    with pytest.raises(GameError):
        play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"], op="recoverable-claim")
    assert world(game[1]) == before
    game[0].content = original
    reward_before = reward_state(game[1], job)
    play("expedition_claim", str(job["job_id"]), user=OWNER, now=job["finishes_at"], op="recoverable-claim")
    assert_reward(game[1], job, reward_before)


@pytest.mark.parametrize("terminal", ["expedition_claim", "expedition_cancel"])
def test_permanent_departure_deduplication_and_old_terminal_events_cannot_touch_new_jobs(game, play, terminal):
    register(play)
    play("expedition_start", "采灵药", user=OWNER, op="retained-start")
    first = journeys(game[1])[0]
    settled_at = first["finishes_at"] if terminal == "expedition_claim" else NOW + 1
    play(terminal, str(first["job_id"]), user=OWNER, now=settled_at, op="retained-terminal")
    future = NOW + 8 * 86400
    play("expedition_start", "采灵药", user=OWNER, now=future, op="new-start")
    second = journeys(game[1])[-1]
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id IN ('retained-start', 'retained-terminal')")
    before = world(game[1])
    old_reply = play("expedition_start", "采灵药", user=OWNER, now=future, op="retained-start")
    assert str(first["job_id"]) in old_reply.text()
    assert world(game[1]) == before
    with pytest.raises(GameError):
        play(terminal, str(first["job_id"]), user=OWNER, now=future, op="retained-terminal")
    assert world(game[1]) == before
    play("expedition_cancel", str(second["job_id"]), user=OWNER, now=future + 1)
    sql(game[1], "DELETE FROM operations WHERE operation_id='retained-start'")
    settled = world(game[1])
    play("expedition_start", "采灵药", user=OWNER, now=future + 2, op="retained-start")
    assert world(game[1]) == settled
    assert len(journeys(game[1])) == 2


def test_retained_departure_identity_cannot_be_reused_by_a_different_player(game, play):
    register(play, other=True)
    play("expedition_start", "采灵药", user=OWNER, op="historical-departure")
    job = journeys(game[1])[0]
    play("expedition_cancel", str(job["job_id"]), user=OWNER, now=NOW + 1)
    future = NOW + 8 * 86400
    play("identity", user=OTHER, now=future)
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='historical-departure'")
    before = world(game[1])
    with pytest.raises(GameError) as caught:
        play("expedition_start", "采灵药", user=OTHER, now=future, op="historical-departure")
    assert OWNER not in str(caught.value) and OTHER not in str(caught.value)
    assert world(game[1]) == before
    assert not journeys(game[1], OTHER)


@pytest.mark.parametrize("action", ["expedition_start", "expedition_claim", "expedition_cancel"])
def test_late_transaction_failure_rolls_back_energy_rewards_job_and_retry(game, play, action):
    register(play)
    if action == "expedition_start":
        argument, now = "采灵药", NOW
    else:
        play("expedition_start", "采灵药", user=OWNER)
        job = journeys(game[1])[0]
        argument = str(job["job_id"])
        now = job["finishes_at"] if action == "expedition_claim" else NOW + 1
    before = world(game[1])
    sql(game[1], "CREATE TRIGGER reject_expedition_commit BEFORE INSERT ON operations "
        "WHEN NEW.operation_id='fail-at-commit' BEGIN SELECT RAISE(ABORT, 'forced transaction failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="forced transaction failure"):
        play(action, argument, user=OWNER, now=now, op="fail-at-commit")
    assert world(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='fail-at-commit'")
    sql(game[1], "DROP TRIGGER reject_expedition_commit")
    first = play(action, argument, user=OWNER, now=now, op="fail-at-commit")
    after = world(game[1])
    assert play(action, argument, user=OWNER, now=now, op="fail-at-commit") == first
    assert world(game[1]) == after


@pytest.mark.parametrize("same_event", [False, True])
def test_concurrent_departures_charge_only_once(game, play, same_event):
    register(play)
    results = race(game[0], [
        (OWNER, "expedition_start", "采灵药", "same-start" if same_event else f"start-{index}", NOW)
        for index in range(4)
    ])
    successful = [result for result in results if not isinstance(result, GameError)]
    assert len(successful) == (4 if same_event else 1)
    assert all(result == successful[0] for result in successful)
    assert len(journeys(game[1])) == 1
    assert pet(game[1], OWNER)["energy"] == 75


@pytest.mark.parametrize("same_event", [False, True])
@pytest.mark.parametrize("terminal", ["expedition_claim", "expedition_cancel"])
def test_concurrent_settlements_apply_once(game, play, same_event, terminal):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    now = job["finishes_at"] if terminal == "expedition_claim" else NOW + 1
    results = race(game[0], [
        (OWNER, terminal, str(job["job_id"]), "same-terminal" if same_event else f"terminal-{index}", now)
        for index in range(4)
    ])
    successful = [result for result in results if not isinstance(result, GameError)]
    assert len(successful) == (4 if same_event else 1)
    assert all(result == successful[0] for result in successful)
    assert_reward(game[1], job, before, multiplier=int(terminal == "expedition_claim"))
    assert pet(game[1], OWNER)["energy"] == 75


@pytest.mark.parametrize("offset", [-1, 0])
def test_concurrent_claim_and_cancel_obey_one_shared_boundary(game, play, offset):
    register(play)
    play("expedition_start", "采灵药", user=OWNER)
    job = journeys(game[1])[0]
    before = reward_state(game[1], job)
    results = race(game[0], [
        (OWNER, action, str(job["job_id"]), action, job["finishes_at"] + offset)
        for action in ("expedition_claim", "expedition_cancel")
    ])
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert isinstance(results[0 if offset < 0 else 1], GameError)
    assert journeys(game[1])[0]["state"] == ("cancelled" if offset < 0 else "claimed")
    assert_reward(game[1], job, before, multiplier=int(offset == 0))


@pytest.mark.parametrize("battle", ["solo", "pvp", "team"])
def test_departure_racing_battle_never_overspends_or_partially_charges(game, play, battle):
    register(play, other=True)
    sql(game[1], "UPDATE pets SET layer=5")
    if battle == "pvp":
        play("pvp", "月明", user=OWNER)
        command = (OTHER, "accept", "", "racing-battle", NOW)
        cost, initial = 20, 40
    elif battle == "team":
        play("team_create", user=OWNER)
        play("team_join", "云行", user=OTHER)
        play("team_accept", "月明", user=OWNER)
        play("team_ready", user=OWNER)
        play("team_ready", user=OTHER)
        command = (OWNER, "team_challenge", "上古灵殿", "racing-battle", NOW)
        cost, initial = 30, 50
    else:
        command = (OWNER, "challenge", "青岚林", "racing-battle", NOW)
        cost, initial = 20, 40
    sql(game[1], "UPDATE pets SET energy=? WHERE user_id=?", (initial, OWNER))
    before_other = player(game[1], OTHER), pet(game[1], OTHER), items(game[1], OTHER)
    results = race(game[0], [(OWNER, "expedition_start", "采灵药", "racing-start", NOW), command])
    assert sum(not isinstance(result, GameError) for result in results) == 1
    if isinstance(results[0], GameError):
        assert not journeys(game[1])
        assert pet(game[1], OWNER)["energy"] == initial - cost
        if battle != "solo":
            assert pet(game[1], OTHER)["energy"] == 100 - cost
    else:
        assert len(journeys(game[1])) == 1
        assert pet(game[1], OWNER)["energy"] == initial - 25
        assert (player(game[1], OTHER), pet(game[1], OTHER), items(game[1], OTHER)) == before_other
        assert player(game[1], OWNER)["last_pve"] is None
        assert player(game[1], OWNER)["last_pvp"] is None
