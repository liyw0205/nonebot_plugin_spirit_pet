import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.arena.common import load_season, stats
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, sql
from .test_arena_matching import NOW, register, seed_result


def state(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY 1") for table in (
        "players", "pets", "inventory", "learned_skills", "team_members", "season_entries",
        "pvp_results", "quest_progress",
    )}


def activity(game, user):
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "read-stats")
        return stats(ctx, load_season(ctx, "2028-01"), user)


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


def test_direct_ranked_fight_only_consumes_challenger_resources_and_preparation(game, play):
    register(game, play)
    play("team_create", user="private-0", now=NOW)
    play("team_join", "道友00", user="private-1", now=NOW)
    play("team_accept", "道友01", user="private-0", now=NOW)
    for user in ("private-0", "private-1"):
        play("team_ready", user=user, now=NOW)
        sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)",
            (pet(game[1], user)["pet_id"],))
    defender = player(game[1], "private-1"), pet(game[1], "private-1")
    defender_skills = sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (defender[1]["pet_id"],))
    reply = play("pvp", "道友01", user="private-0", now=NOW)
    assert reply.title == "论剑结算"
    assert pet(game[1], "private-0")["energy"] == 80
    assert player(game[1], "private-0")["last_pvp"] == NOW
    assert (player(game[1], "private-1"), pet(game[1], "private-1")) == defender
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (defender[1]["pet_id"],)) == defender_skills
    assert sql(game[1], "SELECT proficiency FROM learned_skills WHERE pet_id=?", (pet(game[1], "private-0")["pet_id"],))[0]["proficiency"] > 0
    members = {row["user_id"]: row for row in sql(game[1], "SELECT * FROM team_members")}
    assert members["private-0"]["ready_pet_id"] is None
    assert members["private-1"]["ready_pet_id"] == defender[1]["pet_id"]
    result = sql(game[1], "SELECT * FROM pvp_results")[0]
    assert result["challenger_pet_id"] == pet(game[1], "private-0")["pet_id"]
    assert result["target_pet_id"] == defender[1]["pet_id"]
    assert json.loads(result["reply"])["title"] == reply.title
    assert "private-" not in reply.text() + " ".join(reply.commands)
    assert activity(game, "private-0")["today_matches"] == 1
    assert activity(game, "private-1")["today_matches"] == 0
    assert activity(game, "private-1")["qualifying_matches"] == 0
    assert activity(game, "private-1")["opponents"] == 0
    assert activity(game, "private-0")["qualifying_matches"] == int(result["winner_id"] is not None)


def test_spar_is_immediate_and_does_not_even_recover_or_mutate_energy(game, play):
    register(game, play)
    sql(game[1], "UPDATE pets SET energy=0,energy_updated=?,realm=0", (NOW-10000,))
    sql(game[1], "UPDATE players SET last_pvp=?", (NOW,))
    for user in ("private-0", "private-1"):
        sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)",
            (pet(game[1], user)["pet_id"],))
    before = state(game[1])
    reply = play("spar", "道友01", user="private-0", now=NOW)
    assert reply.title == "切磋结算"
    assert state(game[1]) == before
    assert "private-" not in reply.text()


@pytest.mark.parametrize("action", ["pvp", "spar"])
def test_outgoing_pet_cannot_attack_but_can_be_defended_by_mirror(game, play, action):
    register(game, play)
    play("expedition_start", "采灵药", user="private-1", now=NOW)
    defender = pet(game[1], "private-1"), player(game[1], "private-1")
    assert play(action, "道友01", user="private-0", now=NOW).title.endswith("结算")
    assert (pet(game[1], "private-1"), player(game[1], "private-1")) == defender
    before = state(game[1])
    with pytest.raises(GameError, match="外出|派遣"):
        play(action, "道友02", user="private-1", now=NOW)
    assert state(game[1]) == before


@pytest.mark.parametrize("action", ["pvp", "spar"])
@pytest.mark.parametrize("name", ["不存在", "private-1", "道友00"])
def test_interaction_uses_other_dao_name_not_identity_and_rejects_self(game, play, action, name):
    register(game, play)
    before = state(game[1])
    with pytest.raises(GameError):
        play(action, name, user="private-0", now=NOW)
    assert state(game[1]) == before


def test_no_argument_ranked_opens_board_without_challenging_and_spar_requires_name(game, play):
    register(game, play)
    before = state(game[1])
    reply = play("pvp", user="private-0", now=NOW)
    assert "榜" in reply.title
    assert state(game[1]) == before
    with pytest.raises(GameError, match="道号"):
        play("spar", user="private-0", now=NOW)


def test_target_is_resolved_to_current_name_and_current_pet_at_challenge_time(game, play):
    register(game, play)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='private-1'")
    play("summon", user="private-1", now=NOW)
    replacement = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='private-1'")[0]["pet_id"]
    sql(game[1], "UPDATE pets SET realm=1 WHERE pet_id=?", (replacement,))
    play("switch", str(replacement), user="private-1", now=NOW)
    play("dao_name", "新道号", user="private-1", now=NOW)
    reply = play("pvp", "新道号", user="private-0", now=NOW)
    assert "新道号" in reply.text() and "道友01" not in reply.text()
    assert sql(game[1], "SELECT target_pet_id FROM pvp_results")[0]["target_pet_id"] == replacement


@pytest.mark.parametrize("same_event", [False, True])
def test_concurrent_challenges_settle_and_charge_at_most_once(game, play, same_event):
    register(game, play)
    replies = race(game[0], [
        ("private-0", "pvp", "道友01", "same-challenge" if same_event else f"challenge-{index}", NOW)
        for index in range(4)
    ])
    accepted = [reply for reply in replies if not isinstance(reply, GameError)]
    assert len(accepted) == (4 if same_event else 1)
    assert all(reply == accepted[0] for reply in accepted)
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == 1
    assert pet(game[1], "private-0")["energy"] == 80
    assert pet(game[1], "private-1")["energy"] == 100


def test_opposite_simultaneous_challenges_respect_symmetric_pair_quota(game, play):
    register(game, play)
    replies = race(game[0], [
        ("private-0", "pvp", "道友01", "outgoing-zero", NOW),
        ("private-1", "pvp", "道友00", "outgoing-one", NOW),
    ])
    assert sum(not isinstance(reply, GameError) for reply in replies) == 1
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == 1
    assert sorted(pet(game[1], user)["energy"] for user in ("private-0", "private-1")) == [80, 100]


@pytest.mark.parametrize("days", [8, 40])
def test_permanent_result_replay_returns_original_reply_after_cache_expiry_and_rename(game, play, days):
    register(game, play)
    result = play("pvp", "道友01", user="private-0", now=NOW, op="permanent-challenge")
    future = NOW + days * 86400
    play("season", user="private-0", now=future)
    play("dao_name", "后来道号", user="private-1", now=future)
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='permanent-challenge'")
    before = state(game[1])
    with pytest.raises(GameError):
        play("pvp", "道友00", user="private-1", now=future, op="permanent-challenge")
    assert play("pvp", "已经不存在的道号", user="private-0", now=future, op="permanent-challenge") == result
    assert state(game[1]) == before


def test_cached_challenge_operation_cannot_be_reused_by_another_identity(game, play):
    register(game, play)
    play("pvp", "道友01", user="private-0", now=NOW, op="owned-result")
    before = state(game[1])
    with pytest.raises(GameError, match="different user"):
        play("pvp", "道友00", user="private-1", now=NOW, op="owned-result")
    assert state(game[1]) == before


@pytest.mark.parametrize("table", ["pvp_results", "operations"])
def test_failed_result_or_reply_commit_rolls_back_all_resource_and_rating_changes(game, play, table):
    register(game, play)
    sql(game[1], "UPDATE pets SET layer=10,bloodline=4,affinity=100 WHERE user_id='private-0'")
    before = state(game[1])
    sql(game[1], f"CREATE TRIGGER fail_battle BEFORE INSERT ON {table} "
        "WHEN NEW.operation_id='failed-challenge' BEGIN SELECT RAISE(ABORT,'forced battle failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="forced battle failure"):
        play("pvp", "道友01", user="private-0", now=NOW, op="failed-challenge")
    assert state(game[1]) == before
    sql(game[1], "DROP TRIGGER fail_battle")
    first = play("pvp", "道友01", user="private-0", now=NOW, op="failed-challenge")
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='pvp_once'") == [
        {"progress": 1},
    ]
    after = state(game[1])
    assert play("pvp", "道友01", user="private-0", now=NOW, op="failed-challenge") == first
    assert state(game[1]) == after


def test_defensive_and_draw_results_do_not_grant_reward_qualification(game, play):
    register(game, play)
    seed_result(game, "private-1", "private-0", winner="private-0")
    seed_result(game, "private-0", "private-2", winner=None)
    own = activity(game, "private-0")
    assert own["today_matches"] == 1
    assert own["qualifying_matches"] == own["opponents"] == 0
    assert activity(game, "private-1")["qualifying_matches"] == 1


def test_no_legacy_invitation_actions_or_tables_remain(game, play):
    register(game, play)
    assert not sql(game[1], "SELECT name FROM sqlite_master WHERE type='table' AND name='duels'")
    for action in ("accept", "reject", "duels"):
        with pytest.raises(GameError, match="未知指令"):
            play(action, user="private-0", now=NOW)
