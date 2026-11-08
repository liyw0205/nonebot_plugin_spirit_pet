"""Sect loop: daily mission board, weekly pay and the weekly sect trial."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import counters, sects
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400
WEEK = 7 * DAY


def context(game, now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config,
        game[0].rng, "u1", now, "sect-read",
    )


def join(play, sect="剑阁"):
    play("adopt", "青鸾", now=NOW)
    play("sect", f"拜入 {sect}", now=NOW)


def bump_day(game, metric, amount=1, day=None, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"stat_{metric}_day_{day or beijing_day(NOW)}", amount),
    )


def set_contribution(game, value, sect="jian_ge"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (f"sect_contrib_{sect}", value),
    )


def offers_for(game, sect_id="jian_ge"):
    ctx = context(game)
    return sects.todays_missions(ctx, game[0].content.sects[sect_id])


def test_content_ships_three_missions_per_sect_and_one_trial(game):
    content = game[0].content
    assert len(content.sect_missions) == 12
    for sect_id in content.sects:
        missions = sorted(
            (m for m in content.sect_missions.values() if m.sect == sect_id),
            key=lambda m: m.order,
        )
        assert [m.order for m in missions] == [1, 2, 3]
        assert all(m.reward.items or m.reward.stones.maximum for m in missions)
        assert all(item in content.items for m in missions for item in m.reward.items)
    assert {m.period for m in content.sect_missions.values()} == {"day", "week"}
    assert len(content.sect_trials) == 4
    for trial in content.sect_trials.values():
        assert trial.sect in content.sects and trial.enemy in content.enemies
    tiers = sorted(content.rules.sect.weekly_tiers, key=lambda t: t.tier)
    assert [t.contribution for t in tiers] == [40, 100, 180]


def test_board_is_stable_within_a_day_and_rotates(game):
    sect = game[0].content.sects["jian_ge"]
    first = sects.todays_missions(context(game), sect)
    assert len(first) == game[0].content.rules.sect.mission_offers == 2
    same_day = sects.todays_missions(context(game, now=NOW + 3600), sect)
    assert [m.id for m in same_day] == [m.id for m in first]
    later = [m.id for m in sects.todays_missions(context(game, now=NOW + DAY), sect)]
    assert later != [m.id for m in first]


def test_mission_page_lists_the_board_and_guards_membership(game, play):
    with pytest.raises(GameError, match="尚未结契"):
        play("sect", "任务", user="ghost", now=NOW)
    join(play)
    play("sect", "修行", now=NOW, op="mission-practice")
    page = play("sect", "任务", now=NOW + 1)
    assert page.title == "灵宠师门 · 任务"
    offers = offers_for(game)
    assert f"今日任务：0/{len(offers)} 已交差" in page.text()
    for mission in offers:
        assert mission.name in page.text()
    assert "本周贡献：10" in page.text()


def test_submit_pays_once_and_records_the_voucher(game, play):
    join(play)
    mission = offers_for(game)[0]
    bump_day(game, mission.metric, mission.target)
    stones = player(game[1])["stones"]
    reply = play("sect", f"交差 {mission.name}", now=NOW, op="submit-one")
    assert f"{mission.name}已交差" in reply.text()
    assert player(game[1])["stones"] == stones + mission.reward.stones.maximum
    ctx = context(game)
    assert sects.contribution(ctx, game[0].content.sects["jian_ge"]) == mission.contribution
    rows = sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'sect_mission_%'",
    )
    assert len(rows) == 1
    with pytest.raises(GameError, match="已经交过差"):
        play("sect", f"交差 {mission.name}", now=NOW + 1, op="submit-twice")
    assert player(game[1])["stones"] == stones + mission.reward.stones.maximum


def test_submit_refuses_incomplete_and_off_board_missions(game, play):
    join(play)
    mission = offers_for(game)[0]
    before = (player(game[1])["stones"], len(sql(game[1], "SELECT * FROM quest_progress")))
    with pytest.raises(GameError, match="尚未完成"):
        play("sect", f"交差 {mission.name}", now=NOW, op="submit-early")
    assert before == (player(game[1])["stones"], len(sql(game[1], "SELECT * FROM quest_progress")))

    pool = sects.mission_pool(context(game), game[0].content.sects["jian_ge"])
    benched = next(m for m in pool if m.id not in {o.id for o in offers_for(game)})
    with pytest.raises(GameError, match="今天没有轮到|未找到"):
        play("sect", f"交差 {benched.name}", now=NOW + 1, op="submit-bench")
    with pytest.raises(GameError, match="序号超出范围"):
        play("sect", "交差 9", now=NOW + 2, op="submit-range")


def test_weekly_mission_reads_the_whole_week(game, play):
    join(play, sect="丹鼎门")
    weekly = next(m for m in game[0].content.sect_missions.values() if m.period == "week")
    week_start = beijing_week(NOW)[0]
    for offset in (0, 1, 2):
        bump_day(game, weekly.metric, 1, day=beijing_day(week_start + offset * DAY))
    ctx = context(game)
    assert counters.week_value(context(game), weekly.metric) == 3
    # A row from last week must not count.
    old = beijing_day(week_start - DAY)
    bump_day(game, weekly.metric, 5, day=old)
    assert counters.week_value(context(game), weekly.metric) == 3


def test_weekly_pay_tiers_claim_once(game, play):
    join(play)
    set_contribution(game, 100)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES "
        "('u1', ?, 100, 0)",
        (f"{sects.WEEK_CONTRIB}{beijing_week(NOW)[0]}",),
    )
    page = play("sect", "周俸", now=NOW)
    assert "本周贡献：100" in page.text()
    assert "1 档 · 贡献 40" in page.text() and "可领取" in page.text()
    stones = player(game[1])["stones"]
    reply = play("sect", "领俸", now=NOW + 1, op="weekly-all")
    assert "1 档：" in reply.text() and "2 档：" in reply.text()
    assert player(game[1])["stones"] == stones + 120 + 300
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领俸", now=NOW + 2, op="weekly-again")
    with pytest.raises(GameError, match="已经领取"):
        play("sect", "领俸 1", now=NOW + 3, op="weekly-one-again")
    with pytest.raises(GameError, match="需要本周贡献 180"):
        play("sect", "领俸 3", now=NOW + 4, op="weekly-three-early")


def test_interaction_entry_exists_today(game, play):
    join(play)
    from nonebot_plugin_spirit_pet.gameplay import today as today_module

    claimable, pending = today_module.collect(context(game))
    labels = [entry["label"] for entry in claimable + pending]
    assert any("任务" in label for label in labels), labels
    assert any("试炼" in label for label in labels), labels
    objectives = play("objectives", now=NOW)
    assert "师门：剑阁 1 阶" in objectives.text()
    assert "任务 0/2" in objectives.text()


def test_trial_guards_rank_realm_and_repeat(game, play):
    join(play)
    page = play("sect", "试炼", now=NOW)
    assert "剑心试炼" in page.text() and "1 阶" in page.text()
    assert "阶位不足" in page.text()
    with pytest.raises(GameError, match="需要 2 阶"):
        play("sect", "试炼 挑战", now=NOW + 1, op="trial-rank")

    set_contribution(game, 60)
    with pytest.raises(GameError, match="境界不足"):
        play("sect", "试炼 挑战", now=NOW + 2, op="trial-realm")

    sql(game[1], "UPDATE pets SET realm=6, layer=10")
    reply = play("sect", "试炼 挑战", now=NOW + 3, op="trial-win")
    assert reply.title == "师门试炼 · 通过", reply.text()
    assert "门派贡献 +25" in reply.text()
    assert sql(
        game[1], "SELECT 1 FROM quest_progress WHERE quest_id LIKE 'sect_trial_%'",
    )
    assert sql(
        game[1], "SELECT kind, battle_key FROM battle_records WHERE battle_key='sect_trial'",
    ) == [{"kind": "pve_stage", "battle_key": "sect_trial"}]
    with pytest.raises(GameError, match="已经通过"):
        play("sect", "试炼 挑战", now=NOW + 4, op="trial-twice")


def test_help_parse_and_native_payload(game, play):
    join(play)
    guide = play("help", "成长", now=NOW)
    for command in ("灵宠师门 任务", "灵宠师门 交差", "灵宠师门 周俸", "灵宠师门 试炼"):
        assert command in guide.text()
    assert handlers._parse("灵宠师门 任务") == ("sect", "任务")
    assert handlers._parse("灵宠师门 试炼 挑战") == ("sect", "试炼 挑战")
    assert handlers._parse("灵宠师门 领俸 2") == ("sect", "领俸 2")

    page = play("sect", "任务", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not (buttons & linked)
