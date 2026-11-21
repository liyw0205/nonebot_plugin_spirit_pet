"""Shared weekly sect boss: damage accounting, idempotency and rewards."""

import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import sect_boss
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_week

from .support import items, pet, player, player_uid, sql

NOW = 1_800_000_000


def join(play, user="u1", sect="剑阁"):
    play("adopt", "青鸾", user=user, now=NOW)
    play("sect", f"拜入 {sect}", user=user, now=NOW)


def soften_enemy(game, sect_id="jian_ge", *, boss_hp=9000):
    boss = next(boss for boss in game[0].content.sect_bosses.values() if boss.sect == sect_id)
    boss = boss.model_copy(update={"max_hp": boss_hp})
    game[0].content.sect_bosses[boss.id] = boss
    enemy = game[0].content.enemies[boss.enemy]
    game[0].content.enemies[boss.enemy] = enemy.model_copy(update={
        "stats": Stats(hp=boss_hp, attack=1, defense=0, speed=1),
    })
    return boss


def attack_rows(store, sect_id="jian_ge"):
    return sql(
        store,
        "SELECT * FROM sect_boss_attacks WHERE sect_id=? ORDER BY attack_id",
        (sect_id,),
    )


def test_page_and_existing_hubs_expose_read_only_shared_boss_entry(game, play):
    join(play)

    page = play("sect", "共讨", now=NOW)
    assert "裂岳剑魁" in page.text()
    assert "尚未开战" in page.text()
    assert not sql(game[1], "SELECT * FROM sect_boss_weeks")
    assert not sql(game[1], "SELECT * FROM sect_boss_attacks")

    home = play("sect", now=NOW + 1)
    assert "师门共讨" in home.text()
    assert "灵宠师门 共讨" in {link.command for link in home.inline_commands}
    today = play("today", "2", now=NOW + 2)
    assert "师门共讨" in today.text()
    team_trial = play("team_trial", now=NOW + 3)
    assert "灵宠师门 共讨" in {link.command for link in team_trial.inline_commands}
    guide = play("help", "成长", now=NOW + 3)
    assert "灵宠师门 共讨 挑战" in guide.text()
    assert "灵宠师门 共讨 个人战历" in guide.text()
    assert handlers._parse("灵宠师门 共讨 领奖") == ("sect", "共讨 领奖")

    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len({link.command for link in page.inline_commands}) == len(page.inline_commands)
    assert not (buttons & {link.command for link in page.inline_commands})


def test_challenge_link_is_bound_to_the_open_week_and_sect(game, play):
    join(play)
    week_start, week_end = beijing_week(NOW)
    page = play("sect", "共讨", now=NOW)
    challenge_command = next(
        link.command for link in page.inline_commands if link.label == "出战共讨"
    )
    assert challenge_command.endswith(f"挑战 {week_start} jian_ge")
    action, argument = handlers._parse(challenge_command)

    with pytest.raises(GameError, match="入口已过期"):
        play(action, argument, now=week_end, op="stale-boss-week-button")
    assert not sql(game[1], "SELECT * FROM sect_boss_weeks")


def test_concurrent_members_share_exact_damage_and_replays_do_not_count_twice(game, play, monkeypatch):
    join(play)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("sect", "拜入 剑阁", user="u2", now=NOW)
    boss = soften_enemy(game)
    observed_damage = []
    original_fight = sect_boss.fight

    def observed_fight(allies, enemies, *args, **kwargs):
        starting_hp = enemies[0].hp
        result = original_fight(allies, enemies, *args, **kwargs)
        observed_damage.append(starting_hp - result.remaining_hp[1][0])
        return result

    monkeypatch.setattr(sect_boss, "fight", observed_fight)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(
            lambda args: play(
                "sect", "共讨 挑战", user=args[0], now=NOW, op=args[1],
            ),
            (("u1", "boss-u1"), ("u2", "boss-u2")),
        ))

    rows = attack_rows(game[1])
    assert len(rows) == 2
    assert all(row["damage"] > 0 for row in rows)
    assert all(row["damage"] == row["hp_before"] - row["hp_after"] for row in rows)
    assert [row["damage"] for row in rows] == observed_damage
    week_start = beijing_week(NOW)[0]
    week = sql(
        game[1], "SELECT * FROM sect_boss_weeks WHERE week_start=? AND sect_id='jian_ge'",
        (week_start,),
    )[0]
    assert week["current_hp"] == boss.max_hp - sum(row["damage"] for row in rows)
    assert play("sect", "共讨 挑战", now=NOW, user="u1", op="boss-u1") == replies[0]
    assert len(attack_rows(game[1])) == 2
    assert player(game[1])["last_pve"] == NOW
    assert pet(game[1])["energy"] < 100


def test_sect_boss_weeks_are_isolated(game, play):
    join(play, "u1", "剑阁")
    join(play, "u2", "玄门")
    soften_enemy(game, "jian_ge")
    soften_enemy(game, "xuan_men")

    play("sect", "共讨 挑战", user="u1", now=NOW, op="jian-hit")
    play("sect", "共讨 挑战", user="u2", now=NOW, op="xuan-hit")

    rows = sql(game[1], "SELECT sect_id,current_hp,max_hp FROM sect_boss_weeks ORDER BY sect_id")
    assert len(rows) == 2
    assert all(row["current_hp"] < row["max_hp"] for row in rows)
    assert {row["sect_id"] for row in attack_rows(game[1], "jian_ge")} == {"jian_ge"}
    assert {row["sect_id"] for row in attack_rows(game[1], "xuan_men")} == {"xuan_men"}


def test_ranking_uses_uid_tiebreak_and_paginates(game, play):
    users = [f"rank-{index}" for index in range(9)]
    for user in users:
        join(play, user)
    boss = soften_enemy(game, boss_hp=1_000_000)
    for index, user in enumerate(users):
        play("sect", "共讨 挑战", user=user, now=NOW, op=f"rank-hit-{index}")

    with closing(game[1].connect()) as conn:
        conn.execute(
            "UPDATE sect_boss_attacks SET damage=1,hp_after=hp_before-1 WHERE sect_id='jian_ge'",
        )
        conn.execute(
            "UPDATE sect_boss_weeks SET current_hp=max_hp-? WHERE sect_id='jian_ge'",
            (len(users),),
        )
        conn.commit()

    expected = sorted(player_uid(game[1], user) for user in users)
    first = play("sect", "共讨 榜 1", user=users[0], now=NOW)
    second = play("sect", "共讨 榜 2", user=users[0], now=NOW)
    first_uids = [int(line.split("UID ")[1].split(" ·")[0]) for line in first.lines if ". UID " in line]
    second_uids = [int(line.split("UID ")[1].split(" ·")[0]) for line in second.lines if ". UID " in line]
    assert first_uids == expected[:8]
    assert second_uids == expected[8:]
    assert "灵宠师门 共讨 榜 2" in first.commands
    assert f"{len(users)}" in first.lines[0]
    assert boss.max_hp - len(users) == sql(
        game[1], "SELECT current_hp FROM sect_boss_weeks WHERE sect_id='jian_ge'",
    )[0]["current_hp"]


def test_daily_attempt_limit_is_per_member_and_beijing_day(game, play):
    join(play)
    boss = soften_enemy(game)

    play("sect", "共讨 挑战", now=NOW, op="daily-boss-one")
    play(
        "sect", "共讨 挑战", now=NOW + game[0].config.spirit_pet_pve_cooldown,
        op="daily-boss-two",
    )
    with pytest.raises(GameError, match="今日师门共讨已达"):
        play(
            "sect", "共讨 挑战", now=NOW + 2 * game[0].config.spirit_pet_pve_cooldown,
            op="daily-boss-three",
        )
    assert len(attack_rows(game[1])) == boss.daily_attempts


def test_started_week_keeps_its_rules_when_static_content_changes(game, play):
    join(play)
    boss = soften_enemy(game, boss_hp=1_000_000)
    locked_tiers = [
        tier.model_copy(update={"damage": threshold})
        for tier, threshold in zip(boss.personal_tiers, (900_000, 950_000, 999_999))
    ]
    original = boss.model_copy(update={"daily_attempts": 1, "energy": 10, "personal_tiers": locked_tiers})
    game[0].content.sect_bosses[boss.id] = original
    play("sect", "共讨 挑战", now=NOW, op="week-snapshot-hit")

    changed_tiers = [tier.model_copy(update={"damage": tier.tier}) for tier in original.personal_tiers]
    changed = original.model_copy(update={
        "max_hp": 2_000_000, "daily_attempts": 3, "energy": 50, "personal_tiers": changed_tiers,
    })
    game[0].content.sect_bosses[boss.id] = changed
    page = play("sect", "共讨", now=NOW + 1)
    assert f"{original.max_hp}" in page.lines[2]
    assert "今日挑战 1/1" in page.lines[3]
    with pytest.raises(GameError, match="今日师门共讨已达 1 次"):
        play("sect", "共讨 挑战", now=NOW + 600, op="week-snapshot-extra-hit")
    with pytest.raises(GameError, match="没有符合条件"):
        play("sect", "共讨 领奖", now=beijing_week(NOW)[1], op="week-snapshot-claim")


def test_concurrent_daily_attempts_do_not_exceed_the_limit(game, play, monkeypatch):
    join(play)
    boss = soften_enemy(game)
    original_check_action = Context.check_action

    def without_cooldown(ctx, player, pet, action, energy, cooldown):
        return original_check_action(ctx, player, pet, action, energy, 0)

    monkeypatch.setattr(Context, "check_action", without_cooldown)

    def attack(op):
        try:
            return play("sect", "共讨 挑战", now=NOW, op=op)
        except GameError as error:
            return error

    operations = [f"boss-race-{index}" for index in range(boss.daily_attempts + 1)]
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        results = list(pool.map(attack, operations))

    assert sum(not isinstance(result, GameError) for result in results) == boss.daily_attempts
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert len(attack_rows(game[1])) == boss.daily_attempts


def test_battle_failure_rolls_back_week_energy_report_and_attack(game, play, monkeypatch):
    join(play)
    soften_enemy(game)

    def fail_record(*args, **kwargs):
        raise RuntimeError("injected battle persistence failure")

    monkeypatch.setattr(sect_boss, "record_battle", fail_record)
    with pytest.raises(RuntimeError, match="injected"):
        play("sect", "共讨 挑战", now=NOW, op="boss-rollback")

    assert not sql(game[1], "SELECT * FROM sect_boss_weeks")
    assert not sql(game[1], "SELECT * FROM sect_boss_attacks")
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert pet(game[1])["energy"] == 100
    assert player(game[1])["last_pve"] is None
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='boss-rollback'")


def test_zero_damage_attack_uses_attempt_but_cannot_claim_rewards(game, play, monkeypatch):
    join(play)
    soften_enemy(game)
    original_fight = sect_boss.fight

    def unchanged_boss_hp(allies, enemies, *args, **kwargs):
        starting_hp = enemies[0].hp
        result = original_fight(allies, enemies, *args, **kwargs)
        return replace(result, remaining_hp=(result.remaining_hp[0], (starting_hp,)))

    monkeypatch.setattr(sect_boss, "fight", unchanged_boss_hp)
    play("sect", "共讨 挑战", now=NOW, op="boss-no-damage")
    attack = attack_rows(game[1])[0]
    assert attack["damage"] == 0
    assert attack["attempt"] == 1
    with pytest.raises(GameError, match="没有符合条件"):
        play("sect", "共讨 领奖", now=beijing_week(NOW)[1], op="boss-no-damage-claim")


def test_last_hit_closes_week_and_rewards_only_open_for_the_following_week(game, play):
    join(play)
    original = next(
        boss for boss in game[0].content.sect_bosses.values() if boss.sect == "jian_ge"
    )
    milestones = [
        tier.model_copy(update={"total_damage": 1, "member_damage": 1})
        for tier in original.milestones
    ]
    personal_tiers = [
        tier.model_copy(update={"damage": 1 if tier.tier == 1 else 999_999})
        for tier in original.personal_tiers
    ]
    boss = original.model_copy(update={
        "max_hp": 1, "milestones": milestones, "personal_tiers": personal_tiers,
    })
    game[0].content.sect_bosses[boss.id] = boss
    enemy = game[0].content.enemies[boss.enemy]
    game[0].content.enemies[boss.enemy] = enemy.model_copy(update={
        "stats": Stats(hp=1, attack=1, defense=0, speed=1),
    })

    hit = play("sect", "共讨 挑战", now=NOW, op="boss-last-hit")
    week_start, week_end = beijing_week(NOW)
    row = sql(
        game[1], "SELECT * FROM sect_boss_weeks WHERE week_start=? AND sect_id='jian_ge'",
        (week_start,),
    )[0]
    assert "已被击败" in hit.text()
    assert (row["current_hp"], row["state"], row["closed_at"]) == (0, "defeated", NOW)
    with pytest.raises(GameError, match="已击败"):
        play("sect", "共讨 挑战", now=NOW + 86400, op="boss-after-kill")

    stones = player(game[1])["stones"]
    page = play("sect", "共讨", now=week_end, op="boss-claim-page")
    claim_command = next(
        link.command for link in page.inline_commands if link.label == "领取上周奖励"
    )
    assert claim_command.endswith(f"活动 {week_start} jian_ge")
    action, argument = handlers._parse(claim_command)
    stones_before_failure = player(game[1])["stones"]
    inventory_before_failure = items(game[1])
    with closing(game[1].connect()) as conn:
        conn.execute(
            "CREATE TRIGGER reject_sect_boss_claim BEFORE INSERT ON sect_boss_claims "
            "BEGIN SELECT RAISE(ABORT, 'injected claim receipt failure'); END",
        )
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected claim receipt failure"):
        play(action, argument, now=week_end, op="boss-claim-rollback")
    with closing(game[1].connect()) as conn:
        conn.execute("DROP TRIGGER reject_sect_boss_claim")
        conn.commit()
    assert player(game[1])["stones"] == stones_before_failure
    assert items(game[1]) == inventory_before_failure
    assert not sql(game[1], "SELECT * FROM sect_boss_claims WHERE operation_id='boss-claim-rollback'")

    def claim_once(op):
        try:
            return play(action, argument, now=week_end, op=op)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_results = list(pool.map(claim_once, ("boss-claim-a", "boss-claim-b")))
    reward = next(result for result in claim_results if not isinstance(result, GameError))
    winning_operation = "boss-claim-a" if claim_results[0] is reward else "boss-claim-b"
    assert sum(isinstance(result, GameError) for result in claim_results) == 1
    assert "个人伤害档 1 已领取" in reward.text()
    assert "全门里程碑 3 已领取" in reward.text()
    assert player(game[1])["stones"] > stones
    claims = sql(game[1], "SELECT scope,tier FROM sect_boss_claims WHERE user_id='u1'")
    assert {(row["scope"], row["tier"]) for row in claims} >= {
        ("sect", 1), ("sect", 2), ("sect", 3), ("personal", 1),
    }
    assert play(action, argument, now=week_end + 1, op=winning_operation) == reward
    with pytest.raises(GameError, match="没有符合条件"):
        play("sect", "共讨 领奖", now=week_end + 2, op="boss-claim-again")
    with pytest.raises(GameError, match="领取周"):
        play("sect", "共讨 领奖", now=week_end + 7 * 86400, op="boss-claim-expired")


def test_switching_sects_hides_old_personal_history_and_claim_until_return(game, play):
    join(play)
    sql(game[1], "UPDATE players SET stones=2500 WHERE user_id='u1'")
    original = next(boss for boss in game[0].content.sect_bosses.values() if boss.sect == "jian_ge")
    milestones = [tier.model_copy(update={"total_damage": 1, "member_damage": 1}) for tier in original.milestones]
    personal_tiers = [
        tier.model_copy(update={"damage": 1 if tier.tier == 1 else 999_999})
        for tier in original.personal_tiers
    ]
    boss = original.model_copy(update={"max_hp": 1, "milestones": milestones, "personal_tiers": personal_tiers})
    game[0].content.sect_bosses[boss.id] = boss
    enemy = game[0].content.enemies[boss.enemy]
    game[0].content.enemies[boss.enemy] = enemy.model_copy(update={
        "stats": Stats(hp=1, attack=1, defense=0, speed=1),
    })
    play("sect", "共讨 挑战", now=NOW, op="switch-boss-hit")
    week_end = beijing_week(NOW)[1]

    play("sect", "拜入 玄门", now=week_end, op="switch-away")
    assert "尚未拜入师门" not in play("sect", now=week_end).text()
    hidden = play("sect", "共讨 个人战历", now=week_end)
    assert "尚无个人共讨攻击记录" in hidden.text()
    with pytest.raises(GameError, match="当前没有处于领取周"):
        play("sect", "共讨 领奖", now=week_end + 1, op="switch-claim-away")

    play("sect", "拜入 剑阁", now=week_end + 2, op="switch-back")
    visible = play("sect", "共讨 个人战历", now=week_end + 3)
    assert "个人共讨战历 1/1" in visible.text()
    reward = play("sect", "共讨 领奖", now=week_end + 3, op="switch-claim-back")
    assert "全门里程碑" in reward.text() and "个人伤害档 1" in reward.text()


def test_week_boundary_expires_live_activity_and_clock_rollback_cannot_reopen_it(game, play):
    join(play)
    soften_enemy(game)
    week_start, week_end = beijing_week(NOW)
    play("sect", "共讨 挑战", now=NOW, op="boss-before-boundary")
    play("sect", "共讨 挑战", now=week_end, op="boss-next-week")

    old = sql(
        game[1], "SELECT state,closed_at FROM sect_boss_weeks WHERE week_start=? AND sect_id='jian_ge'",
        (week_start,),
    )[0]
    assert old == {"state": "expired", "closed_at": week_end}

    archive_date = datetime.fromtimestamp(week_start, BEIJING).date().isoformat()
    public_archive = play(
        "sect", f"共讨 往期 jian_ge {archive_date}", user="u3", now=week_end,
    )
    assert "公开归档" in public_archive.text()
    assert "UID" in public_archive.text()
    assert "u1" not in public_archive.text()

    play("adopt", "玄狐", user="u3", now=NOW)
    play("sect", "拜入 剑阁", user="u3", now=NOW)
    with pytest.raises(GameError, match="自然周已结束"):
        play("sect", "共讨 挑战", user="u3", now=NOW + 10, op="boss-clock-rollback")
    old = sql(
        game[1], "SELECT state,closed_at FROM sect_boss_weeks WHERE week_start=? AND sect_id='jian_ge'",
        (week_start,),
    )[0]
    assert old == {"state": "expired", "closed_at": week_end}


def test_personal_battle_history_is_private_paged_and_read_only(game, play):
    join(play)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("sect", "拜入 剑阁", user="u2", now=NOW)
    play("adopt", "玄狐", user="u3", now=NOW)
    soften_enemy(game, boss_hp=1_000_000)
    play("sect", "共讨 挑战", user="u2", now=NOW, op="personal-history-other")

    for day in range(7):
        play(
            "sect", "共讨 挑战", user="u1", now=NOW + day * 86400,
            op=f"personal-history-{day}",
        )

    before = len(sql(game[1], "SELECT * FROM sect_boss_attacks"))
    first = play("sect", "共讨 个人战历", user="u1", now=NOW + 7 * 86400)
    second = play("sect", "共讨 个人战历 2", user="u1", now=NOW + 7 * 86400)
    other = play("sect", "共讨 个人战历", user="u2", now=NOW + 7 * 86400)
    assert "个人共讨战历 1/2" in first.text()
    assert "个人共讨战历 2/2" in second.text()
    assert sum("伤害" in line for line in first.lines) == 6
    assert sum("伤害" in line for line in second.lines) == 1
    assert all("u1" not in line and "u2" not in line for line in (*first.lines, *second.lines))
    assert "个人共讨战历 1/1" in other.text()
    assert any(link.command.startswith("灵宠战报 查看 ") for link in first.inline_commands)
    u1_battle_ids = [
        row["battle_id"] for row in sql(
            game[1], "SELECT battle_id FROM sect_boss_attacks WHERE user_id='u1' "
            "ORDER BY created_at DESC,attack_id DESC",
        )
    ]
    u2_battle_ids = {
        row["battle_id"] for row in sql(
            game[1], "SELECT battle_id FROM sect_boss_attacks WHERE user_id='u2'",
        )
    }
    assert {int(link.command.rsplit(" ", 1)[1]) for link in first.inline_commands} == set(u1_battle_ids[:6])
    assert {int(link.command.rsplit(" ", 1)[1]) for link in second.inline_commands} == set(u1_battle_ids[6:])
    assert {int(link.command.rsplit(" ", 1)[1]) for link in other.inline_commands} == u2_battle_ids
    assert "灵宠师门 共讨 个人战历 2" in first.commands
    assert len(sql(game[1], "SELECT * FROM sect_boss_attacks")) == before
    with pytest.raises(GameError, match="尚未拜入师门"):
        play("sect", "共讨 个人战历", user="u3", now=NOW + 7 * 86400)
