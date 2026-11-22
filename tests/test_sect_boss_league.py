from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import json
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import sect_boss_league
from nonebot_plugin_spirit_pet.utils.time import BEIJING, WEEK_SECONDS

from .support import items, player, sql
from .test_sect_boss import NOW, join, soften_enemy

SEASON = sect_boss_league.season_start(NOW, 316800)
SECT = "jian_ge"


def activate(game):
    league = game[0].content.sect_boss_league.model_copy(update={"first_season_start": SEASON})
    game[0].content = replace(game[0].content, sect_boss_league=league)


def enroll(play, user, now=SEASON + 100, operation=None):
    return play(
        "sect", f"共讨 联赛 报名 {SEASON} {SECT}", user=user, now=now,
        op=operation or f"league-enroll-{user}",
    )


def attack(play, game, user, week, hp, op):
    boss = soften_enemy(game, boss_hp=hp)
    enemy = game[0].content.enemies[boss.enemy]
    game[0].content.enemies[boss.enemy] = enemy.model_copy(update={
        "stats": Stats(hp=hp, attack=1, defense=0, speed=1),
    })
    return play("sect", "共讨 挑战", user=user, now=week + 1800, op=op)


def test_overview_is_read_only_signup_locks_sect_and_old_damage_is_not_adopted(game, play):
    activate(game)
    join(play)
    preview = play("sect", "共讨 联赛", now=SEASON + 100)
    assert "首周可锁定剑阁报名" in preview.text()
    command = next(link.command for link in preview.inline_commands if link.label == "锁定门派报名")
    assert handlers._parse(command) == ("sect", f"共讨 联赛 报名 {SEASON} {SECT}")
    _, segments = _qq_segments(preview, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in segments["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    blue = set()
    for segment in segments["markdown"]:
        urls = re.findall(r"\]\((mqqapi://[^)]+)\)", segment.data["markdown"].content)
        blue.update(
            parse_qs(urlparse(url).query)["command"][0].removeprefix("/")
            for url in urls if "command" in parse_qs(urlparse(url).query)
        )
    assert command in buttons or any(command in target for target in blue)
    assert not buttons & {link.command for link in preview.inline_commands}
    assert not sql(game[1], "SELECT * FROM sect_boss_league_seasons")
    assert not sql(game[1], "SELECT * FROM sect_boss_league_entries")
    assert "师门共讨联赛" in play("sect", now=SEASON + 101).text()
    target = play("objectives", now=SEASON + 102)
    assert any("共讨联赛" in line for line in target.lines)
    today = play("today", "3", now=SEASON + 103)
    assert "共讨联赛" in today.text()

    signup = enroll(play, "u1", operation="league-enroll-u1")
    assert "已锁定剑阁" in signup.text()
    assert enroll(play, "u1", operation="league-enroll-u1") == signup
    with pytest.raises(GameError, match="已锁定剑阁"):
        enroll(play, "u1", operation="league-enroll-u1-again")
    snapshot = json.loads(sql(game[1], "SELECT snapshot FROM sect_boss_league_seasons")[0]["snapshot"])
    assert snapshot["minimum_weeks"] == 2 and snapshot["points_per_week"] == 10_000
    assert sql(game[1], "SELECT sect_id,registered_at FROM sect_boss_league_entries")[0]["sect_id"] == SECT

    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    play("sect", "拜入 玄门", now=SEASON + 200, op="league-switch-sect")
    with pytest.raises(GameError, match="当前门派与赛季锁定门派不同"):
        play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=SEASON + 3 * WEEK_SECONDS + 100)


def test_signup_cannot_follow_attack_or_move_outside_registration_week(game, play):
    activate(game)
    join(play)
    soften_enemy(game)
    play("sect", "共讨 挑战", now=SEASON + 100, op="league-before-signup-attack")
    with pytest.raises(GameError, match="不能补报名"):
        enroll(play, "u1", operation="late-league-signup")
    assert not sql(game[1], "SELECT * FROM sect_boss_league_seasons")

    play("adopt", "玄狐", user="u2", now=SEASON + 100)
    play("sect", "拜入 剑阁", user="u2", now=SEASON + 100)
    with pytest.raises(GameError, match="仅可在赛季首周报名"):
        enroll(play, "u2", now=SEASON + WEEK_SECONDS, operation="outside-league-window")


def test_started_season_keeps_its_schedule_and_prize_snapshot_after_content_update(game, play):
    activate(game)
    join(play)
    enroll(play, "u1")
    old_snapshot = json.loads(sql(
        game[1], "SELECT snapshot FROM sect_boss_league_seasons WHERE season_start=?", (SEASON,),
    )[0]["snapshot"])
    updated_rules = game[0].content.sect_boss_league.model_copy(update={
        "first_season_start": SEASON + 3 * WEEK_SECONDS,
    })
    game[0].content = replace(game[0].content, sect_boss_league=updated_rules)
    current = play("sect", "共讨 联赛", now=SEASON + WEEK_SECONDS + 100)
    old_date = datetime.fromtimestamp(SEASON, BEIJING).date().isoformat()
    new_date = datetime.fromtimestamp(SEASON + 3 * WEEK_SECONDS, BEIJING).date().isoformat()
    assert f"赛季 {old_date} 至" in current.text()
    assert f"赛季 {new_date} 至" not in current.text()
    frozen = sql(
        game[1], "SELECT snapshot FROM sect_boss_league_seasons WHERE season_start=?", (SEASON,),
    )[0]["snapshot"]
    assert json.loads(frozen) == old_snapshot
    board = play("sect", f"共讨 联赛 榜 {SEASON}", now=SEASON + WEEK_SECONDS + 101)
    assert "UID 10000 · 0 分" in board.text()


def test_signup_snapshot_and_entry_roll_back_together_on_entry_failure(game, play):
    activate(game)
    join(play)
    with closing(game[1].connect()) as conn:
        conn.execute(
            "CREATE TRIGGER reject_sect_boss_league_entry BEFORE INSERT ON sect_boss_league_entries "
            "BEGIN SELECT RAISE(ABORT,'injected league entry failure'); END",
        )
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected league entry failure"):
        enroll(play, "u1", operation="league-entry-fault")
    with closing(game[1].connect()) as conn:
        conn.execute("DROP TRIGGER reject_sect_boss_league_entry")
        conn.commit()
    assert not sql(game[1], "SELECT * FROM sect_boss_league_seasons")
    assert not sql(game[1], "SELECT * FROM sect_boss_league_entries")
    assert "已锁定剑阁" in enroll(play, "u1", operation="league-entry-fault").text()


def test_attacks_after_transfer_do_not_score_for_the_locked_sect(game, play):
    activate(game)
    join(play)
    enroll(play, "u1")
    sql(game[1], "UPDATE players SET stones=3000 WHERE user_id='u1'")
    play("sect", "拜入 玄门", now=SEASON + 200, op="league-temporary-transfer")
    soften_enemy(game, "xuan_men", boss_hp=500_000)
    play("sect", "共讨 挑战", now=SEASON + 300, op="league-other-sect-attack")
    play("sect", "拜入 剑阁", now=SEASON + 400, op="league-return-to-locked-sect")
    board = play("sect", f"共讨 联赛 榜 {SEASON}", now=SEASON + 500)
    assert "UID 10000 · 0 分 · 0/3 周 · 未完赛 · 实伤 0" in board.text()
    assert sql(
        game[1], "SELECT sect_id FROM sect_boss_attacks WHERE operation_id='league-other-sect-attack'",
    )[0]["sect_id"] == "xuan_men"


def test_real_attacks_derive_normalized_points_rank_and_one_time_prize(game, play):
    activate(game)
    join(play, "u1")
    join(play, "u2")
    enroll(play, "u1")
    enroll(play, "u2")

    hp_by_week = (500_000, 250_000, 800_000)
    for index, hp in enumerate(hp_by_week):
        week = SEASON + index * WEEK_SECONDS
        attack(play, game, "u1", week, hp, f"league-hit-u1-{index}")
        attack(play, game, "u2", week, hp, f"league-hit-u2-{index}")

    attacks = sql(
        game[1],
        "SELECT a.user_id,a.week_start,a.damage,w.max_hp FROM sect_boss_attacks a "
        "JOIN sect_boss_weeks w USING(week_start,sect_id) WHERE a.week_start>=? AND a.week_start<? "
        "ORDER BY a.user_id,a.week_start",
        (SEASON, SEASON + 3 * WEEK_SECONDS),
    )
    assert len(attacks) == 6
    assert all(row["damage"] > 0 for row in attacks)
    expected = {
        user: sum(row["damage"] * 10_000 // row["max_hp"] for row in attacks if row["user_id"] == user)
        for user in ("u1", "u2")
    }
    board = play("sect", f"共讨 联赛 榜 {SEASON}", now=SEASON + 2 * WEEK_SECONDS + 4000)
    assert f"UID 10000 · {expected['u1']} 分 · 3/3 周 · 完赛" in board.text()
    assert f"UID 10001 · {expected['u2']} 分 · 3/3 周 · 完赛" in board.text()
    assert board.text().index("UID 10000") < board.text().index("UID 10001")

    progress = play(
        "sect", f"共讨 联赛 门派榜 {SEASON}",
        now=SEASON + 2 * WEEK_SECONDS + 4000,
    )
    assert "四门派进度榜" in progress.text()
    assert "剑阁" in progress.text() and "/30000 归一分" in progress.text()
    battle_log = play(
        "sect", f"共讨 联赛 战历 {SEASON}",
        now=SEASON + 2 * WEEK_SECONDS + 4001,
    )
    assert "实伤" in battle_log.text() and "合计" in battle_log.text()

    end = SEASON + 3 * WEEK_SECONDS
    before = player(game[1], "u1")["stones"]
    receipt = play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 100, op="league-u1-prize")
    assert "最终第 1 名已领取" in receipt.text()
    assert player(game[1], "u1")["stones"] == before + 600
    assert items(game[1], "u1")["exp_pill"] == 2
    assert play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 100, op="league-u1-prize") == receipt
    assert play(
        "sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 4 * WEEK_SECONDS, op="league-u1-prize",
    ) == receipt
    with pytest.raises(GameError, match="已经领取"):
        play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 101, op="league-u1-prize-again")
    with pytest.raises(GameError, match="参数与结算名次不符"):
        play("sect", f"共讨 联赛 领奖 {SEASON} 1", user="u2", now=end + 100, op="league-u2-wrong-rank")
    before_u2 = player(game[1], "u2")["stones"]

    def claim_u2(operation):
        try:
            return play(
                "sect", f"共讨 联赛 领奖 {SEASON} 2", user="u2", now=end + 100, op=operation,
            )
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim_u2, ("league-u2-claim-a", "league-u2-claim-b")))
    assert sum(not isinstance(result, GameError) for result in claims) == 1
    assert player(game[1], "u2")["stones"] == before_u2 + 400
    assert len(sql(game[1], "SELECT * FROM sect_boss_league_claims WHERE user_id='u2'")) == 1


def test_unfinished_member_prevents_a_two_person_podium(game, play):
    activate(game)
    join(play, "u1")
    join(play, "u2")
    enroll(play, "u1")
    enroll(play, "u2")
    for week_index in range(2):
        week = SEASON + week_index * WEEK_SECONDS
        if week_index == 0:
            attack(play, game, "u1", week, 20_000, "league-finish-u1-0")
            attack(play, game, "u2", week, 20_000, "league-incomplete-u2")
        else:
            attack(play, game, "u1", week, 20_000, "league-finish-u1-1")
    end = SEASON + 3 * WEEK_SECONDS
    with pytest.raises(GameError, match="完赛周数或本门报名人数不足"):
        play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 100, op="league-no-podium")


def test_concurrent_registration_and_claim_receipts_are_unique(game, play):
    activate(game)
    join(play, "u1")
    join(play, "u2")

    def signup(op):
        try:
            return enroll(play, "u1", operation=op)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(signup, ("league-race-signup-a", "league-race-signup-b")))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM sect_boss_league_entries WHERE user_id='u1'")) == 1


def test_claim_receipt_failure_rolls_back_stones_and_clock_finalization(game, play):
    activate(game)
    join(play, "u1")
    join(play, "u2")
    enroll(play, "u1")
    enroll(play, "u2")
    for week_index in range(2):
        week = SEASON + week_index * WEEK_SECONDS
        attack(play, game, "u1", week, 10_000, f"league-rollback-u1-{week_index}")
        attack(play, game, "u2", week, 10_000, f"league-rollback-u2-{week_index}")

    end = SEASON + 3 * WEEK_SECONDS
    before = player(game[1], "u1")["stones"]
    with closing(game[1].connect()) as conn:
        conn.execute(
            "CREATE TRIGGER reject_sect_boss_league_claim BEFORE INSERT ON sect_boss_league_claims "
            "BEGIN SELECT RAISE(ABORT,'injected league receipt failure'); END",
        )
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected league receipt failure"):
        play("sect", f"共讨 联赛 领奖 {SEASON} 1", now=end + 100, op="league-claim-fails")
    with closing(game[1].connect()) as conn:
        conn.execute("DROP TRIGGER reject_sect_boss_league_claim")
        conn.commit()
    assert player(game[1], "u1")["stones"] == before
    assert not sql(game[1], "SELECT * FROM sect_boss_league_claims")
    assert sql(
        game[1], "SELECT finalized_at FROM sect_boss_league_seasons WHERE season_start=?", (SEASON,),
    )[0]["finalized_at"] is None


def test_finalized_league_cannot_accept_backdated_member_attack(game, play):
    activate(game)
    join(play)
    enroll(play, "u1")
    closed_at = SEASON + 3 * WEEK_SECONDS
    play("sect", "共讨 挑战", now=closed_at + 100, op="league-finalize-by-later-action")
    with pytest.raises(GameError, match="赛季已结算"):
        play("sect", "共讨 挑战", now=SEASON + 2 * WEEK_SECONDS + 100, op="league-backdated-hit")


def test_finalized_league_rejects_backdated_attack_from_unregistered_member(game, play):
    activate(game)
    join(play, "u1")
    join(play, "u2")
    enroll(play, "u1")
    close_time = SEASON + 3 * WEEK_SECONDS + 100
    play("sect", "共讨 挑战", user="u2", now=close_time, op="league-finalize-unregistered")
    previous = sql(
        game[1], "SELECT COUNT(*) AS count FROM sect_boss_attacks WHERE user_id='u2'",
    )[0]["count"]
    with pytest.raises(GameError, match="不能追加任何共讨伤害"):
        play(
            "sect", "共讨 挑战", user="u2", now=SEASON + WEEK_SECONDS + 100,
            op="league-backdated-unregistered-hit",
        )
    assert sql(
        game[1], "SELECT COUNT(*) AS count FROM sect_boss_attacks WHERE user_id='u2'",
    )[0]["count"] == previous


def test_three_week_alignment_crosses_year_without_local_timezone_assumptions():
    from datetime import datetime
    from nonebot_plugin_spirit_pet.utils.time import BEIJING

    anchor = int(datetime(2026, 12, 7, tzinfo=BEIJING).timestamp())
    first = sect_boss_league.season_start(anchor, anchor)
    assert first == anchor
    assert sect_boss_league.season_start(anchor + 25 * 86400, anchor) == anchor + 21 * 86400
