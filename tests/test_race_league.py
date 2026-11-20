"""Contracts for the four-week, per-track race league."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import race_league
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day, beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86_400


def first_week(now=NOW):
    return beijing_week(now)[0]


def anchor(game, start=None):
    start = first_week() if start is None else start
    sql(
        game[1],
        "UPDATE race_league_config SET enabled_at=?, first_week_start=? WHERE singleton=1",
        (start - 1, start),
    )
    return start


def seed(game, user, week_start, track_id, tenths):
    sql(
        game[1],
        "INSERT INTO race_track_bests(user_id,week_start,track_id,best_tenths) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id,week_start,track_id) DO UPDATE SET best_tenths=excluded.best_tenths",
        (user, week_start, track_id, tenths),
    )


def context(game, user="u1", now=NOW):
    service, store = game
    return race_league.Context(
        Repository(store.connect()), service.content, service.config, service.rng,
        user, now, "read-race-league",
    )


def adopt(play, users):
    for user in users:
        play("adopt", "青鸾", user=user, op=f"adopt-{user}")


def test_activation_anchor_excludes_legacy_best_and_starts_at_full_week(game, play):
    adopt(play, ["u1"])
    assert sorted(game[0].content.race_league_prizes) == [1, 2, 3]
    start = anchor(game)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,?,1)",
        (f"race_best_{start - WEEK}", 50),
    )

    assert race_league.current_season_start(context(game)) == start
    assert race_league.standings(context(game), start) == []
    page = play("race_league", now=NOW)
    assert "本赛季尚无联赛成绩" in page.text()
    assert "启用前" not in page.text()
    assert sql(game[1], "SELECT * FROM race_track_bests") == []


def test_season_boundaries_are_four_complete_weeks_across_year_end():
    start = int(datetime(2026, 12, 28, tzinfo=BEIJING).timestamp())
    assert beijing_week(start)[0] == start
    assert race_league.season_start_for_week(start, start + 3 * WEEK) == start
    assert race_league.season_start_for_week(start, start + 4 * WEEK) == start + 4 * WEEK
    assert race_league.season_start_for_week(start, start - WEEK) is None


def test_scores_are_derived_per_week_and_track_with_uid_tiebreak(game, play):
    adopt(play, ["u1", "u2", "u3", "u4"])
    start = anchor(game)
    seed(game, "u1", start, "climb", 100)
    seed(game, "u2", start, "climb", 110)
    seed(game, "u3", start, "climb", 120)
    seed(game, "u4", start, "climb", 130)
    seed(game, "u2", start, "ridge", 100)
    seed(game, "u1", start, "ridge", 110)

    rows = race_league.standings(context(game), start)

    assert [(row["user_id"], row["points"], row["champions"], row["podiums"]) for row in rows] == [
        ("u1", 20, 1, 2), ("u2", 20, 1, 2), ("u3", 5, 0, 1), ("u4", 1, 0, 0),
    ]
    page = play("race_league", now=NOW)
    assert "第 1 周：20 分" in page.text()
    assert "第 4 周：0 分 · 未参赛" in page.text()
    assert page.commands == ("灵宠竞速", "灵宠竞速榜", "灵宠竞速奖励", "灵宠帮助")


def test_track_points_cover_places_one_through_ten_and_zero_after_ten(game, play):
    users = [f"p{index:02}" for index in range(11)]
    adopt(play, users)
    start = anchor(game)
    for place, user in enumerate(users, 1):
        seed(game, user, start, "climb", place * 100)

    rows = race_league.standings(context(game), start)
    by_user = {row["user_id"]: row for row in rows}

    assert [by_user[user]["results"][(start, "climb")]["points"] for user in users] == [
        12, 8, 5, 1, 1, 1, 1, 1, 1, 1, 0,
    ]
    page = play("race_league", "榜单 2", now=NOW)
    assert "第 2/2 页" in page.lines[0]
    assert f"11. UID" in page.text()
    assert page.inline_commands[0].command == "灵宠竞速联赛 榜单 1"


def test_championship_count_breaks_equal_points_before_podium_count(game, play):
    users = ["a", "b", "c", "d"]
    adopt(play, users)
    start = anchor(game)
    event = 0

    def race_event(entries):
        nonlocal event
        track_id = f"track-{event}"
        week_start = start + (event % 4) * WEEK
        for rank, user in enumerate(entries, 1):
            seed(game, user, week_start, track_id, rank * 100)
        event += 1

    race_event(["a", "c", "d"])
    race_event(["c", "a", "d"])
    for _ in range(4):
        race_event(["c", "d", "b"])

    rows = race_league.standings(context(game), start)
    by_user = {row["user_id"]: row for row in rows}
    assert (by_user["a"]["points"], by_user["a"]["champions"], by_user["a"]["podiums"]) == (20, 1, 2)
    assert (by_user["b"]["points"], by_user["b"]["champions"], by_user["b"]["podiums"]) == (20, 0, 4)
    assert by_user["a"]["rank"] < by_user["b"]["rank"]


def test_podium_count_breaks_equal_points_and_championships_before_uid(game, play):
    users = ["a", "b", "c", "d", "e"]
    adopt(play, users)
    start = anchor(game)

    def add_event(index, entries):
        for rank, user in enumerate(entries, 1):
            seed(game, user, start + (index % 4) * WEEK, f"track-{index}", rank * 100)

    add_event(0, ["a", "b", "c", "d"])
    add_event(1, ["b", "c", "d", "a"])
    for index in range(2, 9):
        add_event(index, ["c", "d", "e", "a"])

    rows = race_league.standings(context(game), start)
    by_user = {row["user_id"]: row for row in rows}
    assert (by_user["a"]["points"], by_user["a"]["champions"], by_user["a"]["podiums"]) == (20, 1, 1)
    assert (by_user["b"]["points"], by_user["b"]["champions"], by_user["b"]["podiums"]) == (20, 1, 2)
    assert by_user["b"]["rank"] < by_user["a"]["rank"]


def test_signup_upserts_track_pb_and_replay_does_not_charge_or_change_it(game, play):
    adopt(play, ["u1"])
    anchor(game)
    first = play("race", "报名 1", op="race-league-replay", now=NOW)
    after = sql(game[1], "SELECT week_start,track_id,best_tenths FROM race_track_bests WHERE user_id='u1'")
    energy = player(game[1])["stones"], sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")
    replay = play("race", "报名 1", op="race-league-replay", now=NOW)

    assert replay == first
    assert sql(game[1], "SELECT week_start,track_id,best_tenths FROM race_track_bests WHERE user_id='u1'") == after
    assert len(after) == 1
    assert energy == (player(game[1])["stones"], sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'"))
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'race_day_%'") == [
        {"progress": 1},
    ]


def test_league_pb_failure_rolls_back_signup_resources_and_legacy_best(game, play):
    adopt(play, ["u1"])
    anchor(game)
    before_energy = sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")[0]["energy"]
    with closing(game[1].connect()) as conn:
        conn.execute(
            "CREATE TRIGGER reject_race_track_best BEFORE INSERT ON race_track_bests "
            "BEGIN SELECT RAISE(ABORT, 'injected league ledger failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected league ledger failure"):
        play("race", "报名 1", op="race-league-rollback", now=NOW)

    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")[0]["energy"] == before_energy
    assert sql(game[1], "SELECT * FROM race_track_bests") == []
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'race_%'") == []
    assert sql(game[1], "SELECT * FROM operations WHERE operation_id='race-league-rollback'") == []
    assert sql(game[1], "SELECT latest_week_start FROM race_league_config") == [
        {"latest_week_start": None},
    ]


def test_clock_rollback_cannot_reopen_an_earlier_league_week(game, play):
    adopt(play, ["u1"])
    start = anchor(game)
    play("race", "报名 1", op="league-week-one", now=NOW)
    before = sql(
        game[1], "SELECT best_tenths FROM race_track_bests WHERE user_id='u1' AND week_start=?",
        (start,),
    )
    play("race", "报名 1", op="league-week-two", now=NOW + WEEK)

    with pytest.raises(GameError, match="不能回写已结算成绩"):
        play("race", "报名 1", op="league-clock-rollback", now=NOW + 60)

    assert sql(
        game[1], "SELECT best_tenths FROM race_track_bests WHERE user_id='u1' AND week_start=?",
        (start,),
    ) == before
    assert len(sql(game[1], "SELECT * FROM race_track_bests WHERE user_id='u1'")) == 2
    assert sql(game[1], "SELECT latest_week_start FROM race_league_config") == [
        {"latest_week_start": start + WEEK},
    ]


def test_first_place_can_claim_once_and_fourth_place_is_refused(game, play):
    adopt(play, ["u1", "u2", "u3", "u4"])
    start = anchor(game)
    for rank, user in enumerate(["u1", "u2", "u3", "u4"], 1):
        seed(game, user, start, "climb", rank * 100)
    claim_time = start + 4 * WEEK + 3600
    before = player(game[1])["stones"]
    claim_page = play("race_league", f"{beijing_day(start)}", now=claim_time)
    assert any(
        link.command == f"灵宠联赛领奖 {beijing_day(start)}"
        for link in claim_page.inline_commands
    )

    reply = play("race_league_claim", op="league-prize", now=claim_time)

    assert "第 1 名" in reply.text()
    assert player(game[1])["stones"] == before + 800
    assert items(game[1])["forge_ore"] >= 4
    claim = sql(game[1], "SELECT rank,claimed_at,reward_snapshot FROM race_league_claims")
    assert len(claim) == 1 and claim[0]["rank"] == 1
    assert play("race_league_claim", op="league-prize", now=claim_time) == reply
    with pytest.raises(GameError, match="已经领取"):
        play("race_league_claim", op="league-prize-again", now=claim_time)
    with pytest.raises(GameError, match="未进入前三"):
        play("race_league_claim", user="u4", op="league-fourth", now=claim_time)
    with pytest.raises(GameError, match="领奖期"):
        play("race_league_claim", op="league-late", now=claim_time + WEEK)


def test_claim_receipt_failure_rolls_back_reward_and_concurrent_claims_pay_once(game, play):
    adopt(play, ["u1"])
    start = anchor(game)
    seed(game, "u1", start, "climb", 100)
    claim_time = start + 4 * WEEK + 3600
    before = (player(game[1]), items(game[1]))
    sql(
        game[1],
        "CREATE TRIGGER reject_league_claim BEFORE INSERT ON race_league_claims "
        "BEGIN SELECT RAISE(ABORT, 'injected league claim failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected league claim failure"):
        play("race_league_claim", op="league-claim-rollback", now=claim_time)

    assert (player(game[1]), items(game[1])) == before
    assert sql(game[1], "SELECT * FROM race_league_claims") == []
    assert sql(game[1], "SELECT * FROM operations WHERE operation_id='league-claim-rollback'") == []
    sql(game[1], "DROP TRIGGER reject_league_claim")

    def claim(index):
        try:
            return play("race_league_claim", op=f"league-claim-parallel-{index}", now=claim_time)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))

    assert sum(isinstance(result, GameError) for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM race_league_claims")) == 1
    assert player(game[1])["stones"] == before[0]["stones"] + 800
    assert items(game[1])["forge_ore"] == before[1].get("forge_ore", 0) + 4


def test_invalid_season_and_missing_prize_definition_do_not_mutate_claim_state(game, play):
    adopt(play, ["u1"])
    start = anchor(game)
    seed(game, "u1", start, "climb", 100)
    claim_time = start + 4 * WEEK + 3600
    before = (player(game[1]), items(game[1]))

    with pytest.raises(GameError, match="只能领取最近结束赛季"):
        play("race_league_claim", beijing_day(start + 4 * WEEK), op="league-wrong-season", now=claim_time)

    prize = game[0].content.race_league_prizes.pop(1)
    try:
        with pytest.raises(GameError, match="奖励定义缺失"):
            play("race_league_claim", op="league-missing-prize", now=claim_time)
    finally:
        game[0].content.race_league_prizes[1] = prize

    assert (player(game[1]), items(game[1])) == before
    assert sql(game[1], "SELECT * FROM race_league_claims") == []
    assert sql(game[1], "SELECT * FROM operations WHERE operation_id LIKE 'league-%'") == []


def test_season_archive_and_native_links_are_read_only_and_reachable(game, play):
    adopt(play, ["u1", "u2"])
    start = anchor(game)
    seed(game, "u1", start, "climb", 100)
    seed(game, "u2", start, "climb", 110)
    page = play("race_league", "往期", now=start + 4 * WEEK)

    assert "往期竞速联赛" in page.lines[0]
    assert page.inline_commands[0].command == f"灵宠竞速联赛 {beijing_day(start)}"
    assert handlers._parse("灵宠竞速联赛") == ("race_league", "")
    assert handlers._parse("灵宠竞速联赛 往期") == ("race_league", "往期")
    assert handlers._parse(f"灵宠竞速联赛 {beijing_day(start)} 榜单 2") == (
        "race_league", f"{beijing_day(start)} 榜单 2",
    )
    assert handlers._parse("灵宠联赛领奖") == ("race_league_claim", "")
    historical_ranking = play(
        "race_league", f"{beijing_day(start)} 榜单", now=start + 4 * WEEK,
    )
    assert "竞速联赛总榜" in historical_ranking.title
    assert "已结算" in historical_ranking.text()
    native_page = play("race_league", now=NOW)
    _, message = _qq_segments(native_page, Config(spirit_pet_qq_mode="native"))
    assert message is not None
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert buttons == set(native_page.commands)
    assert linked == {f"/{link.command}" for link in native_page.inline_commands}
    assert not buttons & {link.command for link in native_page.inline_commands}
    assert "灵宠联赛领奖" in play("help", "对战与赛季").text()
    with closing(game[1].connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM race_league_claims").fetchone()[0] == 0
