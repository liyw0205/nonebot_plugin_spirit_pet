from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day

from .support import pet, player, sql

NOW = int(datetime(2028, 1, 2, 12, tzinfo=BEIJING).timestamp())


def register(game, play, count=3):
    for index in range(count):
        play("adopt", "青鸾", user=f"private-{index}", now=NOW)
        play("dao_name", f"道友{index:02d}", user=f"private-{index}", now=NOW)
    sql(game[1], "UPDATE pets SET realm=1")
    play("season", user="private-0", now=NOW)


def seed_result(game, first="private-0", second="private-1", now=NOW, winner=None):
    store = game[1]
    number = len(sql(store, "SELECT result_id FROM pvp_results"))
    sql(store, "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,target_pet_id,"
        "winner_id,day,played_at,delta,operation_id,reply) VALUES ('2028-01',?,?,?,?,?,?,?,0,?,?)",
        (first, second, pet(store, first)["pet_id"], pet(store, second)["pet_id"], winner,
         beijing_day(now), now, f"seed-{number}", '{"title":"fixture","lines":[],"commands":[]}'))


def test_candidates_paginate_in_sql_and_only_show_names(game, play):
    register(game, play, 13)
    first = play("match", user="private-0", now=NOW)
    second = play("match", "2", user="private-0", now=NOW)
    third = play("match", "3", user="private-0", now=NOW)
    assert first.commands == tuple(f"灵宠论剑 道友{i:02d}" for i in range(1, 6)) + ("灵宠匹配 2",)
    assert len(second.commands) == 7
    assert third.commands == ("灵宠论剑 道友11", "灵宠论剑 道友12", "灵宠匹配 2")
    assert "private-" not in first.text() + second.text() + third.text()
    assert "镜像" in first.text()
    with pytest.raises(GameError, match="暂无"):
        play("match", "4", user="private-0", now=NOW)
    assert not sql(game[1], "SELECT * FROM season_entries")


@pytest.mark.parametrize("change", [
    "UPDATE pets SET realm=0 WHERE user_id='private-1'",
    "UPDATE pets SET realm=2 WHERE user_id='private-1'",
    "UPDATE players SET active_pet_id=NULL WHERE user_id='private-1'",
    "INSERT INTO season_entries VALUES ('2028-01','private-1',1201,0,0,0)",
])
def test_ineligible_mirrors_are_excluded_before_pagination(game, play, change):
    register(game, play)
    sql(game[1], change)
    reply = play("match", user="private-0", now=NOW)
    assert "灵宠论剑 道友01" not in reply.commands
    assert "灵宠论剑 道友02" in reply.commands
    with pytest.raises(GameError):
        play("pvp", "道友01", user="private-0", now=NOW)


@pytest.mark.parametrize("offset,available", [(-1, False), (0, True), (1, True)])
def test_challenger_energy_recovery_matches_battle_boundary(game, play, offset, available):
    register(game, play)
    interval = game[0].config.spirit_pet_energy_interval
    sql(game[1], "UPDATE pets SET energy=19,energy_updated=? WHERE user_id='private-0'", (NOW-interval-offset,))
    if available:
        assert "灵宠论剑 道友01" in play("match", user="private-0", now=NOW).commands
        play("pvp", "道友01", user="private-0", now=NOW)
        assert pet(game[1], "private-0")["energy"] == 0
    else:
        for action, argument in (("match", ""), ("pvp", "道友01")):
            with pytest.raises(GameError, match="精力"):
                play(action, argument, user="private-0", now=NOW)


def test_defender_energy_cooldown_and_daily_quota_do_not_hide_or_mutate_mirror(game, play):
    register(game, play)
    sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE user_id='private-1'", (NOW-10000,))
    sql(game[1], "UPDATE players SET last_pvp=? WHERE user_id='private-1'", (NOW,))
    for _ in range(game[0].content.arena.daily_matches):
        seed_result(game, "private-1", "private-2")
    before = pet(game[1], "private-1"), player(game[1], "private-1")
    assert "灵宠论剑 道友01" in play("match", user="private-0", now=NOW).commands
    play("pvp", "道友01", user="private-0", now=NOW)
    assert (pet(game[1], "private-1"), player(game[1], "private-1")) == before


@pytest.mark.parametrize("finished", [False, True])
def test_running_or_unclaimed_expedition_only_blocks_challenger(game, play, finished):
    register(game, play)
    play("expedition_start", "采灵药", user="private-1", now=NOW)
    now = sql(game[1], "SELECT finishes_at FROM expeditions")[0]["finishes_at"] if finished else NOW
    before = pet(game[1], "private-1")
    assert "灵宠论剑 道友01" in play("match", user="private-0", now=now).commands
    play("pvp", "道友01", user="private-0", now=now)
    assert pet(game[1], "private-1") == before
    for action, argument in (("match", ""), ("pvp", "道友02")):
        with pytest.raises(GameError, match="外出|派遣|待领取"):
            play(action, argument, user="private-1", now=now)


def test_daily_total_includes_active_draws_but_not_defensive_results(game, play):
    register(game, play)
    for _ in range(game[0].content.arena.daily_matches):
        seed_result(game, "private-2", "private-0")
    assert "灵宠论剑 道友01" in play("match", user="private-0", now=NOW).commands
    for _ in range(game[0].content.arena.daily_matches):
        seed_result(game, "private-0", "private-2")
    for action, argument in (("match", ""), ("pvp", "道友01")):
        with pytest.raises(GameError, match="今日论剑次数"):
            play(action, argument, user="private-0", now=NOW)


@pytest.mark.parametrize("reverse", [False, True])
def test_pair_limits_are_symmetric_include_draws_and_filter_matching(game, play, reverse):
    register(game, play)
    first, second = ("private-1", "private-0") if reverse else ("private-0", "private-1")
    seed_result(game, first, second)
    assert "灵宠论剑 道友01" not in play("match", user="private-0", now=NOW).commands
    with pytest.raises(GameError, match="今日已结算"):
        play("pvp", "道友01", user="private-0", now=NOW)
    for days in (1, 2):
        seed_result(game, first, second, NOW + days*86400)
    now = NOW+3*86400
    assert "灵宠论剑 道友01" not in play("match", user="private-0", now=now).commands
    with pytest.raises(GameError, match="本赛季"):
        play("pvp", "道友01", user="private-0", now=now)


def test_new_day_reopens_allowance_but_new_month_does_not_reset_challenger_cooldown(game, play):
    register(game, play)
    play("pvp", "道友01", user="private-0", now=NOW)
    assert "灵宠论剑 道友01" in play("match", user="private-0", now=NOW+86400).commands
    feb = int(datetime(2028, 2, 1, tzinfo=BEIJING).timestamp())
    play("pvp", "道友01", user="private-0", now=feb-1)
    with pytest.raises(GameError, match="调息"):
        play("pvp", "道友01", user="private-0", now=feb)
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == 2


def test_competing_last_daily_slot_is_not_overspent(game, play):
    register(game, play, 4)
    for _ in range(game[0].content.arena.daily_matches-1):
        seed_result(game, "private-0", "private-3")

    def attempt(index):
        try:
            return game[0].execute("private-0", "pvp", f"道友{index:02d}", f"battle-{index}", NOW)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(reply is not None for reply in pool.map(attempt, (1, 2))) == 1
    assert len(sql(game[1], "SELECT * FROM pvp_results")) == 5
    assert pet(game[1], "private-0")["energy"] == 80


def test_open_season_uses_snapshot_not_mutated_catalog(game, play):
    register(game, play)
    game[0].content = replace(game[0].content, arena=game[0].content.arena.model_copy(
        update={"max_rating_gap": 1, "energy": 100},
    ))
    sql(game[1], "INSERT INTO season_entries VALUES ('2028-01','private-1',1200,0,0,0)")
    sql(game[1], "UPDATE pets SET energy=20")
    assert "灵宠论剑 道友01" in play("match", user="private-0", now=NOW).commands
    play("pvp", "道友01", user="private-0", now=NOW)
    assert pet(game[1], "private-0")["energy"] == 0
    assert pet(game[1], "private-1")["energy"] == 20


def test_missing_snapshot_realm_definition_fails_closed(game, play):
    register(game, play)
    game[0].content = replace(game[0].content, realms=tuple(
        realm.model_copy(update={"id": "changed"}) if realm.id == "ningqi" else realm
        for realm in game[0].content.realms
    ))
    for action, argument in (("match", ""), ("pvp", "道友01")):
        with pytest.raises(GameError, match="境界定义缺失"):
            play(action, argument, user="private-0", now=NOW)
    assert not sql(game[1], "SELECT * FROM pvp_results")
