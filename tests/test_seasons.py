import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime
from uuid import uuid4

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.arena_content import ArenaTier
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay.arena import common, scoring, seasons
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day

from .support import items, pet, player, sql


def stamp(year, month, day=1, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=BEIJING).timestamp())


JAN = stamp(2028, 1)
FEB = stamp(2028, 2)
MAR = stamp(2028, 3)
OWNER = "private-season-owner"


def register(play, count=5):
    for index in range(count):
        user = OWNER if index == 0 else f"private-opponent-{index}"
        play("adopt", "青鸾", user=user, now=JAN)
        play("dao_name", f"道友{index}", user=user, now=JAN)


def invoke(game, handler, arg="", now=JAN, user=OWNER, operation=None):
    operation = operation or str(uuid4())

    def run(conn):
        repo = Repository(conn)
        ctx = Context(repo, game[0].content, game[0].config, game[0].rng, user, now, operation)
        reply = handler(ctx, arg)
        repo.save()
        return reply

    return game[1].transact(user, operation, now, run)


def observe(game, now=JAN):
    output = []

    def run(ctx, arg):
        output.append(common.current_season(ctx))
        return Reply("season", ())

    invoke(game, run, now=now)
    return output[0]


def record(game, opponent="private-opponent-1", winner=0, now=JAN, operation=None):
    def run(ctx, arg):
        season = common.current_season(ctx)
        first, second = ctx.player(OWNER), ctx.player(opponent)
        delta, lines = scoring.settle_ranked(ctx, season, opponent, Battle(winner, 1, (), ({}, {})))
        reply = Reply("score", lines)
        ctx.repo.conn.execute(
            "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,target_pet_id,"
            "winner_id,day,played_at,delta,operation_id,reply) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (season.season_id, OWNER, opponent, first.active_pet_id, second.active_pet_id,
             None if winner == -1 else (OWNER, opponent)[winner], beijing_day(now), now, delta,
             ctx.operation_id, json.dumps(asdict(reply), ensure_ascii=False)),
        )
        return reply

    return invoke(game, run, now=now, operation=operation)


def qualify(game, matches=10, opponents=4, winner=0):
    for index in range(matches):
        record(game, f"private-opponent-{index % opponents + 1}", winner, JAN + index * 86400)


def stats(game, season_id="2028-01", now=JAN, user=OWNER):
    output = []

    def run(ctx, arg):
        output.append(common.stats(ctx, common.load_season(ctx, season_id), user))
        return Reply("stats", ())

    invoke(game, run, now=now, user=user)
    return output[0]


def world(game):
    return {table: sql(game[1], f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "pets", "inventory", "seasons", "season_entries", "pvp_results", "season_claims",
    )}


def test_month_boundary_and_leap_february_are_beijing_natural_months(game, play):
    register(play)
    january = observe(game, FEB - 1)
    assert (january.season_id, january.starts_at, january.ends_at) == ("2028-01", JAN, FEB)
    february = observe(game, FEB)
    assert (february.season_id, february.starts_at, february.ends_at) == ("2028-02", FEB, MAR)
    assert february.ends_at - february.starts_at == 29 * 86400
    assert sql(game[1], "SELECT closed_at FROM seasons WHERE season_id='2028-01'")[0]["closed_at"] is not None
    assert observe(game, MAR).season_id == "2028-03"


@pytest.mark.parametrize("when", [JAN - 1, JAN + 9])
def test_clock_rollback_rejects_without_reopening_or_creating_seasons(game, play, when):
    register(play)
    observe(game, JAN + 10)
    before = world(game)
    with pytest.raises(GameError, match="时间|时钟"):
        observe(game, when)
    assert world(game) == before


def test_no_unplayed_skipped_seasons_are_synthesized(game, play):
    register(play)
    observe(game, JAN)
    observe(game, MAR)
    before = sql(game[1], "SELECT * FROM seasons")
    with pytest.raises(GameError, match="赛季|记录"):
        invoke(game, seasons.status, "2028-02", now=MAR)
    assert sql(game[1], "SELECT * FROM seasons") == before


def test_season_rules_are_snapshotted_and_new_month_uses_new_rules(game, play):
    register(play)
    old = observe(game)
    changed = game[0].content.arena.model_copy(update={"initial_rating": 1200, "rating_delta": 35})
    game[0].content = replace(game[0].content, arena=changed)
    assert observe(game, JAN + 1).rules.initial_rating == old.rules.initial_rating
    assert observe(game, JAN + 1).rules.rating_delta == old.rules.rating_delta
    assert observe(game, FEB).rules == changed


def test_status_rating_and_stats_do_not_enroll_nonparticipants(game, play):
    register(play)
    season = observe(game)
    reply = invoke(game, seasons.status)
    assert "1000" in reply.text() and OWNER not in reply.text()
    assert stats(game) == {"rating": season.rules.initial_rating, "wins": 0, "losses": 0,
                           "draws": 0, "today_matches": 0, "qualifying_matches": 0, "opponents": 0}
    assert not sql(game[1], "SELECT * FROM season_entries")


@pytest.mark.parametrize("winner", [-1, 0, 1])
def test_ranked_score_transfers_points_and_records_results_once(game, play, winner):
    register(play)
    before_pet = pet(game[1], OWNER)
    before_player = player(game[1], OWNER)
    reply = record(game, winner=winner, operation="rank-once")
    assert record(game, winner=winner, operation="rank-once") == reply
    left = stats(game)
    right = stats(game, user="private-opponent-1")
    assert left["rating"] + right["rating"] == 2000
    assert left["rating"] == 1000 + (0 if winner == -1 else 20 if winner == 0 else -20)
    assert left["wins"] == int(winner == 0)
    assert left["losses"] == int(winner == 1)
    assert left["draws"] == int(winner == -1)
    assert left["qualifying_matches"] == left["opponents"] == int(winner != -1)
    assert left["today_matches"] == 1
    assert right["today_matches"] == right["qualifying_matches"] == right["opponents"] == 0
    assert pet(game[1], OWNER) == before_pet
    assert player(game[1], OWNER) == before_player
    results = sql(game[1], "SELECT * FROM pvp_results")
    assert len(results) == 1 and results[0]["delta"] == (0 if winner == -1 else 20)
    assert results[0]["day"] == beijing_day(JAN)
    assert OWNER not in reply.text() and "private-opponent" not in reply.text()


def test_score_cannot_make_loser_negative(game, play):
    register(play)
    observe(game)
    sql(game[1], "INSERT INTO season_entries(season_id, user_id, rating) VALUES ('2028-01', ?, 7)",
        ("private-opponent-1",))
    record(game)
    assert stats(game)["rating"] == 1007
    assert stats(game, user="private-opponent-1")["rating"] == 0
    assert sql(game[1], "SELECT delta FROM pvp_results") == [{"delta": 7}]


def test_draws_count_daily_quota_but_not_reward_matches_or_opponents(game, play):
    register(play)
    record(game, winner=-1)
    record(game, "private-opponent-2", winner=0, now=JAN + 1)
    record(game, "private-opponent-2", winner=1, now=JAN + 86400)
    state = stats(game, now=JAN + 86400)
    assert state["today_matches"] == 1
    assert state["qualifying_matches"] == 2
    assert state["opponents"] == 1


def test_claim_requires_finished_season(game, play):
    register(play)
    qualify(game)
    before = world(game)
    with pytest.raises(GameError, match="结束|结算"):
        invoke(game, seasons.claim, "2028-01", now=FEB - 1)
    assert world(game) == before


@pytest.mark.parametrize("matches,opponents,winner", [(9, 4, 0), (10, 3, 0), (10, 4, -1)])
def test_reward_requires_decisive_matches_and_distinct_decisive_opponents(game, play, matches, opponents, winner):
    register(play)
    qualify(game, matches, opponents, winner)
    observe(game, FEB)
    before = world(game)
    with pytest.raises(GameError, match="有效|对手|资格|场"):
        invoke(game, seasons.claim, "2028-01", now=FEB)
    assert world(game) == before


def test_highest_final_tier_claim_is_fixed_and_never_touches_pet(game, play):
    register(play)
    qualify(game)
    before_pet = pet(game[1], OWNER)
    before_player = player(game[1], OWNER)
    before_items = items(game[1], OWNER)
    reply = invoke(game, seasons.claim, "2028-01", now=FEB, operation="season-reward")
    assert "天阙" in reply.text() and OWNER not in reply.text()
    assert invoke(game, seasons.claim, "2028-01", now=FEB, operation="season-reward") == reply
    assert pet(game[1], OWNER) == before_pet
    assert player(game[1], OWNER)["stones"] == before_player["stones"] + 1000
    assert items(game[1], OWNER)["forge_ore"] == before_items.get("forge_ore", 0) + 10
    claims = sql(game[1], "SELECT * FROM season_claims")
    assert len(claims) == 1
    snapshot = json.loads(claims[0]["reward_snapshot"])
    assert snapshot["tier_id"] == "tianque"
    assert snapshot["stones"] == 1000 and snapshot["items"]["forge_ore"] == 10
    with pytest.raises(GameError, match="已领取"):
        invoke(game, seasons.claim, "2028-01", now=FEB)


def test_missing_snapshot_item_definition_rejects_then_can_retry(game, play):
    register(play)
    qualify(game)
    original = game[0].content
    game[0].content = replace(original, items={key: value for key, value in original.items.items()
                                            if key != "forge_ore"})
    before = world(game)
    with pytest.raises(GameError, match="定义|物品|恢复"):
        invoke(game, seasons.claim, "2028-01", now=FEB, operation="retry-claim")
    assert world(game) == before
    game[0].content = original
    invoke(game, seasons.claim, "2028-01", now=FEB, operation="retry-claim")
    assert len(sql(game[1], "SELECT * FROM season_claims")) == 1


@pytest.mark.parametrize("same_operation", [True, False])
def test_concurrent_claims_grant_once(game, play, same_operation):
    register(play)
    qualify(game)
    before = player(game[1], OWNER)["stones"]

    def claim(index):
        try:
            return invoke(game, seasons.claim, "2028-01", now=FEB,
                          operation="same-claim" if same_operation else f"claim-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(claim, range(4)))
    assert sum(isinstance(reply, Reply) for reply in replies) == (4 if same_operation else 1)
    assert player(game[1], OWNER)["stones"] == before + 1000
    assert len(sql(game[1], "SELECT * FROM season_claims")) == 1


@pytest.mark.parametrize("argument", ["2028-1", "28-01", "2028-00", "2028-13", "2028-01 extra", ""])
def test_claim_rejects_ambiguous_or_invalid_season_ids(game, play, argument):
    register(play)
    with pytest.raises(GameError):
        invoke(game, seasons.claim, argument)
    assert not sql(game[1], "SELECT * FROM season_claims")


def test_historical_ranking_and_catalog_are_paginated_and_id_free(game, play):
    register(play, count=24)
    for month in range(1, 7):
        season = observe(game, stamp(2028, month))
        for index in range(24):
            user = OWNER if index == 0 else f"private-opponent-{index}"
            sql(game[1], "INSERT INTO season_entries(season_id, user_id, rating) VALUES (?, ?, ?)",
                (season.season_id, user, 1000 + index))
    now = stamp(2028, 7)
    first = invoke(game, seasons.catalog, now=now)
    second = invoke(game, seasons.catalog, "2", now=now)
    assert "1/2" in first.title and "2/2" in second.title
    assert len(first.commands) <= 8 and len(second.commands) <= 8
    board = invoke(game, seasons.rank, "2028-01", now=now)
    next_board = invoke(game, seasons.rank, "2028-01 分页 2", now=now)
    assert "1/5" in board.title and "2/5" in next_board.title
    assert len(board.lines) <= 5 and len(next_board.lines) <= 5
    assert "道友23" in board.text() and "道友23" not in next_board.text()
    for reply in (first, second, board, next_board):
        assert OWNER not in reply.text() and "private-opponent" not in reply.text()
    with pytest.raises(GameError, match="页"):
        invoke(game, seasons.rank, "2028-01 分页 6", now=now)


def test_current_rule_details_are_available_without_any_history(game, play):
    register(play)
    status = invoke(game, seasons.status)
    assert "凝气" in status.text() and "分差不超过 200" in status.text()
    assert "每日最多 1 场" in status.text() and "本季最多 3 场" in status.text()
    assert "灵石 300" in status.text() and "锻灵矿 3" in status.text()
    catalog = invoke(game, seasons.catalog)
    assert all(name in catalog.text() for name in ("青云", "凌霄", "天阙"))
    assert "灵石 1000" in catalog.text() and "血脉精华 4" in catalog.text()
    assert not sql(game[1], "SELECT * FROM season_entries")


def test_current_board_buttons_are_named_challenges_and_fit_qq_keyboard(game, play):
    from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
    from nonebot_plugin_spirit_pet.core.config import Config

    register(play, count=13)
    season = observe(game)
    for index in range(13):
        user = OWNER if index == 0 else f"private-opponent-{index}"
        sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating) VALUES (?,?,?)",
            (season.season_id, user, 1000+index))
    for page in range(1, 4):
        reply = invoke(game, seasons.rank, f"分页 {page}")
        assert len(reply.commands) <= 8
        assert "灵宠论剑 道友0" not in reply.commands
        challenges = [command for command in reply.commands if command.startswith("灵宠论剑 ")]
        assert challenges and all(command.removeprefix("灵宠论剑 ") in reply.text() for command in challenges)
        _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        assert len([button for row in message["keyboard"][0].data["keyboard"].content.rows
                    for button in row.buttons]) == len(reply.commands)


def test_large_reward_tier_catalog_uses_reachable_bounded_pages(game, play):
    register(play)
    tiers = [ArenaTier(id=f"tier{index}", name=f"仙阶{index}", minimum_rating=index * 100,
                       stones=(index + 1) * 100, items={}) for index in range(10)]
    rules = game[0].content.arena.model_copy(update={"tiers": tiers})
    game[0].content = replace(game[0].content, arena=rules)
    first = invoke(game, seasons.catalog)
    assert "1/3" in first.title and len(first.lines) == 5
    assert "灵宠赛季奖励 规则 2028-01 分页 2" in first.commands
    last = invoke(game, seasons.catalog, "规则 2028-01 分页 3")
    assert "3/3" in last.title and "仙阶9" in last.text() and "仙阶0" not in last.text()
    assert len(last.lines) == 3 and len(last.commands) <= 8
    with pytest.raises(GameError, match="页"):
        invoke(game, seasons.catalog, "规则 分页 4")


def test_claim_uses_old_qualification_and_reward_rules_after_content_change(game, play):
    register(play)
    qualify(game)
    old = game[0].content.arena
    changed = old.model_copy(update={"reward_matches": 100, "reward_opponents": 20,
                                     "tiers": [tier.model_copy(update={"stones": tier.stones + 999})
                                               for tier in old.tiers]})
    game[0].content = replace(game[0].content, arena=changed)
    before = player(game[1], OWNER)["stones"]
    invoke(game, seasons.claim, "2028-01", now=FEB)
    assert player(game[1], OWNER)["stones"] == before + 1000
    assert observe(game, FEB).rules.reward_matches == 100


def test_reward_uses_final_rating_not_previous_peak(game, play):
    register(play)
    qualify(game)
    for index in range(4):
        record(game, f"private-opponent-{index + 1}", winner=1, now=JAN + (10 + index) * 86400)
    assert stats(game)["rating"] == 1120
    before = player(game[1], OWNER)["stones"]
    reply = invoke(game, seasons.claim, "2028-01", now=FEB)
    assert "凌霄" in reply.text() and "天阙" not in reply.text()
    assert player(game[1], OWNER)["stones"] == before + 600


def test_new_season_starts_independently_and_never_rolls_old_records_forward(game, play):
    register(play)
    record(game)
    observe(game, FEB)
    state = stats(game, "2028-02", now=FEB)
    assert state["rating"] == 1000 and state["qualifying_matches"] == 0
    assert stats(game, now=FEB)["rating"] == 1020
    assert not sql(game[1], "SELECT * FROM season_entries WHERE season_id='2028-02'")
    before = world(game)
    with pytest.raises(GameError, match="时间|时钟"):
        invoke(game, seasons.status, "2028-01", now=FEB - 1)
    assert world(game) == before


def test_duplicate_scoring_is_rejected_after_generic_cache_cleanup(game, play):
    register(play)
    record(game, operation="scoring-once")
    sql(game[1], "DELETE FROM operations WHERE operation_id='scoring-once'")
    before = world(game)

    def duplicate(ctx, arg):
        season = common.current_season(ctx)
        _, lines = scoring.settle_ranked(ctx, season, "private-opponent-1", Battle(0, 1, (), ({}, {})))
        return Reply("score", lines)

    with pytest.raises(GameError, match="已经计分"):
        invoke(game, duplicate, operation="scoring-once")
    assert world(game) == before


def test_claim_stays_single_after_generic_reply_cache_is_deleted(game, play):
    register(play)
    qualify(game)
    invoke(game, seasons.claim, "2028-01", now=FEB, operation="long-lived-claim")
    sql(game[1], "DELETE FROM operations WHERE operation_id='long-lived-claim'")
    before = world(game)
    with pytest.raises(GameError, match="已领取"):
        invoke(game, seasons.claim, "2028-01", now=MAR, operation="long-lived-claim")
    assert world(game) == before


def test_late_transaction_failure_rolls_back_season_claim_and_all_rewards(game, play):
    register(play)
    qualify(game)
    sql(game[1], "CREATE TRIGGER reject_claim_commit BEFORE INSERT ON operations "
        "WHEN NEW.operation_id='late-failure' BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
    before = world(game)
    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        invoke(game, seasons.claim, "2028-01", now=FEB, operation="late-failure")
    assert world(game) == before
    sql(game[1], "DROP TRIGGER reject_claim_commit")
    invoke(game, seasons.claim, "2028-01", now=FEB, operation="late-failure")
    assert len(sql(game[1], "SELECT * FROM season_claims")) == 1
