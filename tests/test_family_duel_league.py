from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.family_duel_content import LEAGUE_SECONDS, league_start
from nonebot_plugin_spirit_pet.gameplay import family_duel
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_week

from .support import sql
from .test_family_duel import NOW, prepare, scripted

SEASON = 1_800_201_600  # 2027-01-18, the next aligned first registration week in these fixtures.


def _dump(game):
    from contextlib import closing
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def activate_season(game):
    content = game[0].content
    rules = content.family_duel_league.model_copy(update={"first_season_start": SEASON})
    game[0].content = replace(content, family_duel_league=rules)


def test_league_lookups_and_registration_pair_list_are_read_only(game, play):
    activate_season(game)
    ids = prepare(game, play)
    before = _dump(game)
    overview = play("family_duel", "联赛", now=NOW)
    assert "2027-01-18" in overview.text()
    page = play("family_duel", "联赛 报名", now=SEASON + 100)
    assert str(ids[0]) in page.text() and "锁定报名" in page.text()
    signup = page.inline_commands[0].command
    assert signup.startswith(f"灵宠亲子合战 联赛 报名 {SEASON} ")
    assert handlers._parse(signup)[0] == "family_duel"
    _, segments = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    markdown = segments["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0].removeprefix("/")
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    buttons = [button.action.data for segment in segments["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert signup in links or signup in buttons
    assert not set(links) & set(buttons)
    assert _dump(game) == before
    assert handlers._parse("灵宠亲子合战 联赛 榜单 2") == ("family_duel", "联赛 榜单 2")


def test_real_three_week_scores_snapshot_rotation_and_rank_prize(game, play, monkeypatch):
    activate_season(game)
    first_ids = prepare(game, play, "u1")
    second_ids = prepare(game, play, "u2")
    third_ids = prepare(game, play, "u3")
    original_rotation = game[0].content.family_duel_rotation
    for user, ids in (("u1", first_ids), ("u2", second_ids), ("u3", third_ids)):
        reply = play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", user=user,
                     now=SEASON + 100, op=f"league-signup-{user}")
        assert "真实孵化凭证" in reply.text()
        assert play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", user=user,
                    now=SEASON + 100, op=f"league-signup-{user}") == reply

    changed_rotation = tuple(reversed(original_rotation))
    changed_rules = game[0].content.family_duel_league.model_copy(update={
        "first_season_start": SEASON + 3 * 604800,
        "ratings": [{"id": "concord", "name": "同心破阵", "points": 90},
                    {"id": "twin_star", "name": "双契凯旋", "points": 100}],
    })
    game[0].content = replace(game[0].content, family_duel_rotation=changed_rotation,
                              family_duel_league=changed_rules)
    for week_index in range(3):
        at = SEASON + week_index * 604800 + 3_000
        week = beijing_week(at)[0]
        expected = original_rotation[week_index]
        preview = play("family_duel", f"预览 {first_ids[0]} {first_ids[2]} {week}", now=at, user="u1")
        assert game[0].content.family_duels[expected].name in preview.text()
        for user, ids in (("u1", first_ids), ("u2", second_ids), ("u3", third_ids)):
            if user == "u3" and week_index > 0:
                continue
            if week_index == 0 and user == "u1":
                with pytest.raises(GameError, match="锁定"):
                    play("family_duel", f"挑战 {week} {ids[1]} {ids[2]}", user=user,
                         now=at, op="wrong-family-pair")
            def fight(left, right, rng, elements, *, max_rounds):
                rounds = 5 if user == "u1" else 20
                return scripted(rounds=rounds)(left, right, rng, elements, max_rounds=max_rounds)
            monkeypatch.setattr(family_duel, "fight", fight)
            play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", user=user,
                 now=at, op=f"league-battle-{user}-{week_index}")

    links = sql(game[1], "SELECT * FROM family_duel_league_runs ORDER BY user_id,week_start")
    assert len(links) == 7
    assert len({row["run_id"] for row in links}) == 7
    reply = play("family_duel", "联赛 榜单 2027-01-18 1", now=SEASON + 2 * 604800 + 4_000)
    assert "UID 10000 · 15 分 · 3/3 场" in reply.text()
    assert "UID 10001 · 9 分 · 3/3 场" in reply.text()
    assert "UID 10002 · 3 分 · 1/3 场" in reply.text()
    assert "未完赛 · UID 10002" in reply.text()
    personal = play("family_duel", "联赛 战历 2027-01-18", user="u1", now=SEASON + 2 * 604800 + 4_000)
    assert "锁定 #" in personal.text() and "双契凯旋 · +5 分" in personal.text()
    with pytest.raises(GameError, match="尚未报名"):
        play("family_duel", "联赛 战历", user="u4", now=SEASON + 2 * 604800 + 4_000)

    end = SEASON + 3 * 604800
    before_stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    before_pills = sql(game[1], "SELECT COALESCE((SELECT quantity FROM inventory WHERE user_id='u1' "
                                "AND item_id='exp_pill'),0) AS n")[0]["n"]
    with pytest.raises(GameError, match="仅可在赛季结束后"):
        play("family_duel", "联赛 领奖 2027-01-18", now=end - 1, user="u1", op="early-league-claim")
    claim = play("family_duel", f"联赛 领奖 2027-01-18", now=end + 100, user="u1", op="league-claim")
    assert "最终第 1 名" in claim.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before_stones + 600
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='exp_pill'")[0]["quantity"] == before_pills + 2
    assert play("family_duel", "无效参数", now=end + 100, user="u1", op="league-claim") == claim
    rolled_back = play("family_duel", "联赛", now=SEASON + 2 * 604800 + 5_000, user="u1")
    assert "最终榜" in rolled_back.text()
    assert "15 分" in rolled_back.text()
    with pytest.raises(GameError, match="已领取"):
        play("family_duel", "联赛 领奖 2027-01-18", now=end + 101, user="u1", op="league-claim-again")
    with pytest.raises(GameError, match="领取"):
        play("family_duel", "联赛 领奖 2027-01-18", now=end + 3 * 604800, user="u2", op="late-league-claim")


def test_same_week_battle_blocks_late_signup_and_no_old_run_is_backfilled(game, play):
    activate_season(game)
    ids = prepare(game, play)
    start = beijing_week(SEASON + 100)[0]
    play("family_duel", f"挑战 {start} {ids[0]} {ids[2]}", now=SEASON + 100, op="league-too-late")
    with pytest.raises(GameError, match="不能补报名"):
        play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", now=SEASON + 200)
    assert not sql(game[1], "SELECT * FROM family_duel_league_seasons")
    assert not sql(game[1], "SELECT * FROM family_duel_league_runs")


def test_finalized_season_rejects_backdated_challenge_and_signup(game, play, monkeypatch):
    activate_season(game)
    ids_by_user = {user: prepare(game, play, user) for user in ("u1", "u2", "u3")}
    for user in ("u1", "u2"):
        ids = ids_by_user[user]
        play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}",
             now=SEASON + 100, user=user)
    monkeypatch.setattr(family_duel, "fight", scripted())
    for week_index in (0, 1):
        at = SEASON + week_index * 604800 + 1000
        week = beijing_week(at)[0]
        for user in ("u1", "u2"):
            ids = ids_by_user[user]
            play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=at, user=user,
                 op=f"finalized-season-{user}-{week_index}")

    end = SEASON + LEAGUE_SECONDS
    play("family_duel", "联赛 领奖 2027-01-18", now=end + 100, user="u1",
         op="finalize-league-season")

    week_three = beijing_week(SEASON + 2 * 604800 + 1000)[0]
    late_battler = ids_by_user["u2"]
    with pytest.raises(GameError, match="已结算"):
        play("family_duel", f"挑战 {week_three} {late_battler[0]} {late_battler[2]}",
             now=SEASON + 2 * 604800 + 1000, user="u2", op="backdated-league-battle")
    late_signup = ids_by_user["u3"]
    with pytest.raises(GameError, match="已结算"):
        play("family_duel", f"联赛 报名 {SEASON} {late_signup[0]} {late_signup[2]}",
             now=SEASON + 100, user="u3", op="backdated-league-signup")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM family_duel_league_runs")[0]["n"] == 4
    assert not sql(game[1], "SELECT * FROM family_duel_league_entries WHERE user_id='u3'")


def test_three_week_schedule_is_contiguous_across_year_boundary():
    anchor = int(datetime(2026, 12, 7, tzinfo=BEIJING).timestamp())
    start = anchor + LEAGUE_SECONDS
    assert league_start(int(datetime(2026, 12, 31, tzinfo=BEIJING).timestamp())) == start
    assert league_start(start + LEAGUE_SECONDS - 1) == start
    assert league_start(start + LEAGUE_SECONDS) == start + LEAGUE_SECONDS
    assert beijing_week(start + 2 * 604800)[0] == start + 2 * 604800


def test_equal_season_results_use_stable_uid_order(game, play, monkeypatch):
    activate_season(game)
    ids_by_user = {user: prepare(game, play, user) for user in ("u1", "u2")}
    for user, ids in ids_by_user.items():
        play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", now=SEASON + 100, user=user)
    monkeypatch.setattr(family_duel, "fight", scripted(rounds=5))
    for week_index in range(3):
        at = SEASON + week_index * 604800 + 1000
        week = beijing_week(at)[0]
        for user, ids in ids_by_user.items():
            play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=at, user=user,
                 op=f"uid-tie-{user}-{week_index}")
    result = play("family_duel", "联赛 榜单 2027-01-18 1", now=SEASON + 2 * 604800 + 2_000)
    assert result.text().index("UID 10000") < result.text().index("UID 10001")
    assert result.text().count("15 分 · 3/3 场") == 2


def test_claim_write_failure_rolls_back_currency_receipt_and_claim(game, play, monkeypatch):
    activate_season(game)
    ids_by_user = {user: prepare(game, play, user) for user in ("u1", "u2")}
    for user, ids in ids_by_user.items():
        play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", now=SEASON + 100, user=user)
    monkeypatch.setattr(family_duel, "fight", scripted())
    for week_index in range(3):
        at = SEASON + week_index * 604800 + 1000
        week = beijing_week(at)[0]
        for user, ids in ids_by_user.items():
            play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=at, user=user,
                 op=f"claim-failure-battle-{user}-{week_index}")
    end = SEASON + 3 * 604800 + 100
    sql(game[1], "CREATE TRIGGER reject_league_claim BEFORE INSERT ON family_duel_league_claims "
        "BEGIN SELECT RAISE(ABORT,'injected league claim failure'); END")
    before = _dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected league claim failure"):
        play("family_duel", "联赛 领奖 2027-01-18", now=end, user="u1", op="retry-league-claim")
    assert _dump(game) == before
    sql(game[1], "DROP TRIGGER reject_league_claim")
    assert "奖励已到账" in play("family_duel", "联赛 领奖 2027-01-18", now=end,
                               user="u1", op="retry-league-claim").text()


def test_concurrent_claims_for_one_player_issue_one_prize(game, play, monkeypatch):
    activate_season(game)
    ids_by_user = {user: prepare(game, play, user) for user in ("u1", "u2")}
    for user, ids in ids_by_user.items():
        play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", now=SEASON + 100, user=user)
    monkeypatch.setattr(family_duel, "fight", scripted())
    for week_index in range(3):
        at = SEASON + week_index * 604800 + 1000
        week = beijing_week(at)[0]
        for user, ids in ids_by_user.items():
            play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=at, user=user,
                 op=f"concurrent-claim-battle-{user}-{week_index}")
    before_stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    end = SEASON + 3 * 604800

    def claim(index):
        try:
            return play("family_duel", "联赛 领奖 2027-01-18", now=end + 100, user="u1",
                        op=f"concurrent-league-claim-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(not isinstance(value, GameError) for value in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM family_duel_league_claims WHERE user_id='u1'")[0]["n"] == 1
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before_stones + 600


def test_failed_league_run_link_rolls_back_the_entire_existing_duel(game, play, monkeypatch):
    activate_season(game)
    ids = prepare(game, play)
    play("family_duel", f"联赛 报名 {SEASON} {ids[0]} {ids[2]}", now=SEASON + 100)
    monkeypatch.setattr(family_duel, "fight", scripted())
    sql(game[1], "CREATE TRIGGER reject_league_run BEFORE INSERT ON family_duel_league_runs "
        "BEGIN SELECT RAISE(ABORT,'injected league run failure'); END")
    before = _dump(game)
    week = beijing_week(SEASON + 1000)[0]
    with pytest.raises(sqlite3.IntegrityError, match="injected league run failure"):
        play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=SEASON + 1000, op="retry-league-run")
    assert _dump(game) == before
    sql(game[1], "DROP TRIGGER reject_league_run")
    play("family_duel", f"挑战 {week} {ids[0]} {ids[2]}", now=SEASON + 1000, op="retry-league-run")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM family_duel_league_runs")[0]["n"] == 1
