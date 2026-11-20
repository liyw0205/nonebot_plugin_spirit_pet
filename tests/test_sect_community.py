"""Shared weekly sect progress follows only successful contribution awards."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import sect_community, sects
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400


def context(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context

    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config,
        game[0].rng, user, now, "sect-community-read",
    )


def join(play, user="u1", sect="剑阁"):
    play("adopt", "青鸾", user=user, now=NOW)
    play("sect", f"拜入 {sect}", user=user, now=NOW)


def small_milestones(game):
    current = game[0].content
    adjusted = [
        tier.model_copy(update={
            "total_contribution": total,
            "member_contribution": member,
        })
        for tier, total, member in zip(
            current.rules.sect.community_tiers, (20, 40, 60), (10, 20, 30),
        )
    ]
    sect_rule = current.rules.sect.model_copy(update={"community_tiers": adjusted})
    rules = current.rules.model_copy(update={"sect": sect_rule})
    game[0].content = replace(current, rules=rules)


def contribute(ctx, amount):
    sect_community.record_contribution(ctx, sects.current(ctx), amount)


def test_practice_and_mission_awards_update_shared_and_member_ledger(game, play):
    join(play, "u1")
    join(play, "u2")
    sect = game[0].content.sects["jian_ge"]

    play("sect", "修行", user="u1", now=NOW, op="practice-u1")
    play("sect", "修行", user="u1", now=NOW + 1, op="practice-u1")
    play("sect", "修行", user="u2", now=NOW, op="practice-u2")
    assert sect_community.total_contribution(context(game), sect) == 20
    assert sect_community.member_contribution(context(game, "u1"), sect) == 10
    assert sect_community.member_contribution(context(game, "u2"), sect) == 10

    for user in ("u1", "u2"):
        offered = sects.todays_missions(context(game, user), sect)
        mission = next(entry for entry in offered if entry.period == "day")
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
            "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
            (user, f"stat_{mission.metric}_day_{beijing_day(NOW)}", mission.target),
        )
        operation = f"mission-{user}"
        play("sect", f"交差 {mission.name}", user=user, now=NOW + 1, op=operation)
        replay = play("sect", f"交差 {mission.name}", user=user, now=NOW + 1, op=operation)
        assert "已交差" in replay.text()

    values = sql(
        game[1],
        "SELECT user_id, contribution FROM sect_week_contributions "
        "WHERE week_start=? AND sect_id=? ORDER BY user_id",
        (beijing_week(NOW)[0], sect.id),
    )
    assert [row["user_id"] for row in values] == ["u1", "u2"]
    assert sum(row["contribution"] for row in values) == sect_community.total_contribution(
        context(game), sect,
    )
    assert all(row["contribution"] > 10 for row in values)


def test_failed_trial_does_not_add_shared_progress(game, play):
    from dataclasses import replace

    from nonebot_plugin_spirit_pet.domain.content import Stats
    from nonebot_plugin_spirit_pet.gameplay import sect_trial

    join(play)
    sect = sects.current(context(game))
    trial = sect_trial.trial_for(context(game), sect)
    enemy = game[0].content.enemies[trial.enemy]
    stats = Stats(hp=1_000_000, attack=1_000_000, defense=1_000_000, speed=1)
    enemies = dict(game[0].content.enemies)
    enemies[trial.enemy] = enemy.model_copy(update={"stats": stats})
    game[0].content = replace(game[0].content, enemies=enemies)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','sect_contrib_jian_ge',60,1)",
    )
    sql(game[1], "UPDATE pets SET realm=6, layer=10 WHERE user_id='u1'")

    reply = play("sect", "试炼 挑战", now=NOW, op="trial-loss")

    assert reply.title == "师门试炼 · 未过"
    assert sect_community.total_contribution(context(game), sect) == 0
    assert sect_community.member_contribution(context(game), sect) == 0


def test_uncompleted_mission_does_not_add_shared_progress(game, play):
    join(play)
    sect = sects.current(context(game))
    mission = sects.todays_missions(context(game), sect)[0]

    with pytest.raises(GameError, match="尚未完成"):
        play("sect", f"交差 {mission.name}", now=NOW, op="mission-not-ready")

    assert sect_community.total_contribution(context(game), sect) == 0
    assert sect_community.member_contribution(context(game), sect) == 0


def test_trial_win_contributes_and_shared_tiers_require_personal_participation(game, play):
    small_milestones(game)
    join(play, "u1")
    join(play, "u2")
    join(play, "u3")
    sect = game[0].content.sects["jian_ge"]

    for user in ("u1", "u2"):
        play("sect", "修行", user=user, now=NOW, op=f"practice-{user}")
    for user in ("u1", "u2"):
        offered = sects.todays_missions(context(game, user), sect)
        mission = next(entry for entry in offered if entry.period == "day")
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,0) "
            "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
            (user, f"stat_{mission.metric}_day_{beijing_day(NOW)}", mission.target),
        )
        play("sect", f"交差 {mission.name}", user=user, now=NOW + 1, op=f"mission-{user}")

    # Personal rank progress unlocks the existing trial; it is not backfilled into this ledger.
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','sect_contrib_jian_ge',60,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=60",
    )
    sql(game[1], "UPDATE pets SET realm=6, layer=10 WHERE user_id='u1'")
    reply = play("sect", "试炼 挑战", user="u1", now=NOW + 2, op="trial-u1")
    assert reply.title == "师门试炼 · 通过"
    replay = play("sect", "试炼 挑战", user="u1", now=NOW + 2, op="trial-u1")
    assert replay.title == reply.title
    assert sect_community.member_contribution(context(game, "u1"), sect) == 45
    assert sect_community.member_contribution(context(game, "u2"), sect) > 10
    assert sect_community.total_contribution(context(game), sect) >= 60

    u1_stones = player(game[1], "u1")["stones"]
    u1_items = items(game[1], "u1")
    claimed = play("sect", "共修 领奖 全部", user="u1", now=NOW + 3, op="claim-u1")
    assert "1 阶" in claimed.text() and "2 阶" in claimed.text() and "3 阶" in claimed.text()
    assert player(game[1], "u1")["stones"] == u1_stones + 660
    u1_items_after = items(game[1], "u1")
    assert u1_items_after.get("spirit_food", 0) == u1_items.get("spirit_food", 0) + 1
    assert u1_items_after.get("forge_ore", 0) == u1_items.get("forge_ore", 0) + 1
    assert u1_items_after.get("bloodline_essence", 0) == u1_items.get("bloodline_essence", 0) + 1
    with pytest.raises(GameError, match="已经领取"):
        play("sect", "共修 领奖 1", user="u1", now=NOW + 4, op="claim-u1-again")

    play("sect", "共修 领奖 全部", user="u2", now=NOW + 3, op="claim-u2")
    assert sect_community.claimed(context(game, "u2"), sect, 1)
    assert sect_community.claimed(context(game, "u2"), sect, 2)
    assert not sect_community.claimed(context(game, "u2"), sect, 3)
    with pytest.raises(GameError, match="本人共修贡献不足"):
        play("sect", "共修 领奖 3", user="u2", now=NOW + 4, op="claim-u2-third")
    with pytest.raises(GameError, match="本人达到参与门槛"):
        play("sect", "共修 领奖 全部", user="u3", now=NOW + 4, op="claim-u3")


def test_community_progress_is_isolated_by_sect_and_beijing_week(game, play):
    small_milestones(game)
    join(play)
    jian_ge = game[0].content.sects["jian_ge"]
    dan_ding = game[0].content.sects["dan_ding"]
    next_monday = beijing_week(NOW)[0] + 7 * DAY
    last_sunday = next_monday - 1
    contribute(context(game, now=last_sunday), 7)
    contribute(context(game, now=next_monday), 25)
    assert sect_community.member_contribution(context(game, now=last_sunday), jian_ge) == 7
    assert sect_community.member_contribution(context(game, now=next_monday), jian_ge) == 25
    assert sect_community.total_contribution(context(game, now=next_monday), dan_ding) == 0

    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    play("sect", "拜入 丹鼎门", now=next_monday, op="switch-sect")
    assert sect_community.member_contribution(context(game, now=next_monday), dan_ding) == 0
    assert sect_community.member_contribution(context(game, now=last_sunday), jian_ge) == 7
    with pytest.raises(GameError, match="同门共修进度不足"):
        play("sect", "共修 领奖 1", now=next_monday, op="wrong-sect-claim")

    play("sect", "拜入 剑阁", now=next_monday + 1, op="return-to-sect")
    assert sect_community.member_contribution(context(game, now=next_monday + 1), jian_ge) == 25
    play("sect", "共修 领奖 1", now=next_monday + 2, op="claim-after-return")
    assert sect_community.claimed(context(game, now=next_monday + 2), jian_ge, 1)


def test_week_rollover_hides_unclaimed_old_milestone_rewards(game, play):
    small_milestones(game)
    join(play)
    sect = game[0].content.sects["jian_ge"]
    last_sunday = beijing_week(NOW)[0] + 7 * DAY - 1
    next_monday = last_sunday + 1
    contribute(context(game, now=last_sunday), 20)

    sunday_page = play("sect", "共修", now=last_sunday)
    assert "1 阶" in sunday_page.text() and "可领取" in sunday_page.text()
    monday_page = play("sect", "共修", now=next_monday)
    assert "本周同门进度：0 · 我的贡献：0" in monday_page.text()
    with pytest.raises(GameError, match="同门共修进度不足"):
        play("sect", "共修 领奖 1", now=next_monday, op="claim-previous-week")
    assert sect_community.member_contribution(context(game, now=last_sunday), sect) == 20
    assert not sect_community.claimed(context(game, now=next_monday), sect, 1)


def test_contribution_ledger_is_atomic_with_practice(game, play, monkeypatch):
    join(play)
    original = Repository.add_sect_week_contribution

    def fail_after_ledger(self, **values):
        original(self, **values)
        raise RuntimeError("injected ledger failure")

    monkeypatch.setattr(Repository, "add_sect_week_contribution", fail_after_ledger)
    before = player(game[1])
    with pytest.raises(RuntimeError, match="injected ledger failure"):
        play("sect", "修行", now=NOW, op="practice-rollback")
    assert player(game[1])["stones"] == before["stones"]
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'sect_day_%'") == []
    assert sql(game[1], "SELECT * FROM sect_week_contributions") == []
    assert sql(game[1], "SELECT energy,exp FROM pets WHERE user_id='u1'")[0] == {
        "energy": 100, "exp": 0,
    }


def test_atomic_upsert_keeps_parallel_member_updates_and_source_totals(game, play):
    join(play, "u1")
    join(play, "u2")
    sect = game[0].content.sects["jian_ge"]

    def add(user, amount, operation):
        def action(conn):
            Repository(conn).add_sect_week_contribution(
                week_start=beijing_week(NOW)[0], sect_id=sect.id,
                user_id=user, amount=amount,
            )
            return Reply("ok", ())

        return game[1].transact(user, operation, NOW, action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda row: add(*row),
            (("u1", 10, "parallel-1"), ("u1", 15, "parallel-2"), ("u2", 20, "parallel-3")),
        ))
    assert sect_community.total_contribution(context(game), sect) == 45
    assert sect_community.member_contribution(context(game, "u1"), sect) == 25
    assert sect_community.member_contribution(context(game, "u2"), sect) == 20


def test_community_page_buttons_and_command_route_are_exact(game, play):
    small_milestones(game)
    join(play)
    ctx = context(game)
    sect = sects.current(ctx)
    for amount in (20, 20):
        contribute(ctx, amount)
    page = play("sect", "共修", now=NOW)
    assert page.title == "师门共修"
    assert "百家同修" in page.text()
    assert "本人 20" in page.text()
    assert "共修 40/60" in play("objectives", now=NOW).text()
    main_page = play("sect", now=NOW + 1)
    assert "本周共修" in main_page.text()
    assert "灵宠师门 共修" in {link.command for link in main_page.inline_commands}
    assert handlers._parse("灵宠师门 共修") == ("sect", "共修")
    assert handlers._parse("灵宠师门 共修 领奖 1") == ("sect", "共修 领奖 1")

    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    markdown = message["markdown"][0].data["markdown"]
    markdown_text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    qq_links = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown_text)
    }
    linked = {
        link.command.removeprefix("/") for link in page.inline_commands
    }
    assert buttons == set(page.commands)
    assert qq_links == {f"/{command}" for command in linked}
    assert "灵宠师门 共修 领奖 1" in linked
    assert len(linked) == len(page.inline_commands)
    assert not (buttons & {command.removeprefix("/") for command in qq_links})


def test_concurrent_claims_grant_one_reward_and_record_one_receipt(game, play):
    small_milestones(game)
    join(play)
    sect = game[0].content.sects["jian_ge"]
    contribute(context(game), 20)
    before_stones = player(game[1])["stones"]
    before_items = items(game[1]).get("spirit_food", 0)

    def claim(operation):
        try:
            return game[0].execute("u1", "sect", "共修 领奖 1", operation, NOW)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("claim-race-a", "claim-race-b")))

    assert sum(isinstance(result, Reply) and "1 阶" in result.text() for result in results) == 1
    assert sum(isinstance(result, GameError) and "已经领取" in str(result) for result in results) == 1
    assert player(game[1])["stones"] == before_stones + 60
    assert items(game[1]).get("spirit_food", 0) == before_items + 1
    assert sect_community.claimed(context(game), sect, 1)


def test_claim_receipt_failure_rolls_back_reward_and_can_retry(game, play, monkeypatch):
    small_milestones(game)
    join(play)
    sect = game[0].content.sects["jian_ge"]
    contribute(context(game), 20)
    before_stones = player(game[1])["stones"]
    before_items = items(game[1]).get("spirit_food", 0)
    original_grant = sect_community.grant

    def fail_after_reward(ctx, reward):
        original_grant(ctx, reward)
        raise RuntimeError("injected community claim failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(sect_community, "grant", fail_after_reward)
        with pytest.raises(RuntimeError, match="injected community claim failure"):
            play("sect", "共修 领奖 1", now=NOW, op="claim-rollback")

    assert player(game[1])["stones"] == before_stones
    assert items(game[1]).get("spirit_food", 0) == before_items
    assert not sect_community.claimed(context(game), sect, 1)

    sql(
        game[1],
        "CREATE TRIGGER fail_sect_community_receipt BEFORE INSERT ON quest_progress "
        "WHEN NEW.quest_id LIKE 'sect_community_claim_%' "
        "BEGIN SELECT RAISE(ABORT, 'injected community receipt failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected community receipt failure"):
        play("sect", "共修 领奖 1", now=NOW, op="claim-receipt-rollback")

    assert player(game[1])["stones"] == before_stones
    assert items(game[1]).get("spirit_food", 0) == before_items
    assert not sect_community.claimed(context(game), sect, 1)
    sql(game[1], "DROP TRIGGER fail_sect_community_receipt")

    reply = play("sect", "共修 领奖 1", now=NOW + 1, op="claim-retry")
    assert "1 阶" in reply.text()
    assert player(game[1])["stones"] == before_stones + 60
    assert items(game[1]).get("spirit_food", 0) == before_items + 1
