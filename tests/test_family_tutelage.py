import asyncio
from dataclasses import replace
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.application import game as game_module
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import family_tutelage
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.utils.time import beijing_week
from nonebot_plugin_spirit_pet.utils.time import BEIJING

from .support import sql
from .test_family_trial import prepare as prepare_family
from .test_commands import onebot_event

NOW = 1_800_000_000


def prepare(game, play, user="u1"):
    ids = prepare_family(game, play, user)
    sql(game[1], "INSERT INTO inventory VALUES (?,'forge_ore',30)", (user,))
    for target in ids:
        for skill in ("wind_slash", "wood_heal"):
            sql(game[1], "INSERT INTO inventory VALUES (?,?,1) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+1", (user, "book_" + skill))
            play("learn", f"{skill} 伙伴 {target}", user=user)
    sql(game[1], "UPDATE learned_skills SET level=2 WHERE pet_id IN (?,?)", ids[:2])
    return ids


def run(game, user="u1"):
    row = sql(game[1], "SELECT * FROM family_tutelage_courses WHERE user_id=? ORDER BY started_at DESC,course_id DESC", (user,))[0]
    row["snapshot"] = json.loads(row["snapshot"])
    return row


def start(game, play, ids, course="wind_lesson", user="u1", now=NOW, op=None):
    return play("family_tutelage", f"开课 {course} {ids[0]} {ids[2]} {beijing_week(now)[0]}", user=user, now=now, op=op)


def ready(game, play, ids, course="wind_lesson", user="u1"):
    start(game, play, ids, course, user)
    course_id = run(game, user)["course_id"]
    play("family_tutelage", f"讲习 {course_id} 1", user=user)
    play("family_tutelage", f"讲习 {course_id} 2", user=user, now=NOW + 600)
    return course_id


def dump(game):
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def scripted(winner=0, rounds=2, use=True):
    def battle(left, right, *args, **kwargs):
        return Battle(winner, rounds, ("scripted exam",), ({left[0].pet_id: {"wind_slash": 1} if use else {}}, {}))
    return battle


def test_read_only_private_selection_preview_and_navigation(game, play):
    before = dump(game)
    assert "尚未结契" in play("family_tutelage", user="ghost").text()
    assert dump(game) == before
    ids = prepare(game, play)
    before = dump(game)
    page = play("family_tutelage")
    assert len(page.inline_commands) == 4
    pairs = play(*handlers._parse(page.inline_commands[0].command))
    assert len(pairs.inline_commands) == 2
    preview = play(*handlers._parse(pairs.inline_commands[0].command))
    assert "未预扣" not in preview.text()
    assert "不预扣" in preview.text()
    assert dump(game) == before
    assert handlers._parse("灵宠家族传习 记录 2") == ("family_tutelage", "记录 2")
    assert "灵宠家族传习" in play("help", "成长").text()
    assert any(link.command == "灵宠家族传习" for link in play("pedigree").inline_commands)
    assert any(link.command == f"灵宠家族传习 伙伴 {ids[2]}" for link in play("skills", f"伙伴 {ids[2]}").inline_commands)
    assert "家族传习" in play("objectives").text()


@pytest.mark.parametrize("course,skill,user", [("wind_lesson", "wind_slash", "u1"), ("wood_lesson", "wood_heal", "u2")])
def test_real_parent_lessons_real_combat_graduation_and_permanent_replay(game, play, monkeypatch, course, skill, user):
    ids = prepare(game, play, user)
    # Use the real engine with a deterministic non-evasion roll.
    class ExamRandom:
        def random(self):
            return 0.99

        def randint(self, low, high):
            return low

    game[0].rng = ExamRandom()
    course_id = ready(game, play, ids, course, user)
    current = run(game, user)
    assert current["lessons_done"] == 2
    assert len(sql(game[1], "SELECT * FROM family_tutelage_lessons")) == 2
    observed = []
    real = family_tutelage.fight

    def observe(left, right, *args, **kwargs):
        result = real(left, right, *args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(family_tutelage, "fight", observe)
    reply = play("family_tutelage", f"考核 {course_id} 1", user=user, now=NOW + 601, op="exam-real")
    assert "结业" in reply.title, reply.text()
    assert observed[0].winner == 0
    assert observed[0].skill_uses[0][ids[2]][skill] > 0
    assert run(game, user)["status"] == "completed"
    assert sql(game[1], "SELECT * FROM family_tutelage_graduations")[0]["proficiency"] == 12
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1
    details = play("family_tutelage", f"详情 {course_id}", user=user, now=NOW + 602)
    assert "实际额外熟练度 +12" in details.text()
    report = next(link for link in details.inline_commands if "战报" in link.command)
    assert "家族传习" in play(*handlers._parse(report.command), user=user).text()
    sql(game[1], "DELETE FROM operations")
    before = dump(game)
    assert play("family_tutelage", "invalid", user=user, now=NOW + 900000, op="exam-real") == reply
    sql(game[1], "DELETE FROM operations")
    assert dump(game) == before
    for parent in ids[:2]:
        with pytest.raises(GameError, match="已.*结业"):
            start(game, play, [parent, ids[1], ids[2]], course, user, NOW + 604800)


@pytest.mark.parametrize("violation", ["unrelated", "foreign", "unlearned", "low_parent", "max_child", "archived", "released", "expedition"])
def test_eligibility_failures_are_private_and_do_not_consume_quota(game, play, violation):
    ids = prepare(game, play)
    if violation == "unrelated":
        ids[0] = sql(game[1], "SELECT active_pet_id FROM players WHERE user_id='u1'")[0]["active_pet_id"]
    elif violation == "foreign":
        ids[0] = prepare(game, play, "u2")[0]
    elif violation == "unlearned":
        sql(game[1], "DELETE FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (ids[2],))
    elif violation == "low_parent":
        sql(game[1], "UPDATE learned_skills SET level=1 WHERE pet_id=?", (ids[0],))
    elif violation == "max_child":
        sql(game[1], "UPDATE learned_skills SET level=5 WHERE pet_id=?", (ids[2],))
    elif violation in {"archived", "released"}:
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
        if violation == "released":
            sql(game[1], "INSERT INTO quest_progress VALUES ('u1',?,1,0)", (f"released_{ids[0]}",))
    else:
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'forest_patrol','旧行程','exp-op',?,?,'running','{}')", (ids[0], NOW, NOW + 3600))
    before = dump(game)
    with pytest.raises(GameError):
        start(game, play, ids)
    assert dump(game) == before
    assert not sql(game[1], "SELECT * FROM family_tutelage_courses")


def test_order_interval_cost_and_free_read_only_pages(game, play):
    ids = prepare(game, play)
    balances = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")
    start(game, play, ids)
    course_id = run(game)["course_id"]
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'") == balances
    before = dump(game)
    for argument in (f"讲习 {course_id} 2", f"考核 {course_id} 1"):
        with pytest.raises(GameError):
            play("family_tutelage", argument)
        assert dump(game) == before
    first = play("family_tutelage", f"讲习 {course_id} 1", op="lesson-original")
    assert "第 1/2" in first.text()
    after = dump(game)
    assert play("family_tutelage", "irrelevant", op="lesson-original") == first
    assert dump(game) == after
    with pytest.raises(GameError, match="间隔"):
        play("family_tutelage", f"讲习 {course_id} 2", now=NOW + 599)
    for argument in ("", f"详情 {course_id}", "记录"):
        play("family_tutelage", argument)
    assert dump(game) == after
    play("family_tutelage", f"讲习 {course_id} 2", now=NOW + 600)
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == balances[0]["stones"] - 120


@pytest.mark.parametrize("resource", ["parent_energy", "child_energy", "stones", "materials"])
def test_insufficient_lesson_resources_roll_back_all_costs(game, play, resource):
    ids = prepare(game, play)
    start(game, play, ids)
    course_id = run(game)["course_id"]
    if resource.endswith("energy"):
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=?", (NOW, ids[0] if resource.startswith("parent") else ids[2]))
    elif resource == "stones":
        sql(game[1], "UPDATE players SET stones=0")
    else:
        sql(game[1], "DELETE FROM inventory WHERE item_id='forge_ore'")
    before = dump(game)
    with pytest.raises(GameError):
        play("family_tutelage", f"讲习 {course_id} 1")
    assert dump(game) == before


@pytest.mark.parametrize("winner,rounds,use,outcome", [(0,2,False,"unused"),(1,2,True,"lost"),(-1,2,True,"draw"),(-1,40,True,"timeout")])
def test_exam_failures_use_limited_attempts_but_never_graduate(game, play, monkeypatch, winner, rounds, use, outcome):
    ids = prepare(game, play)
    course_id = ready(game, play, ids)
    monkeypatch.setattr(family_tutelage, "fight", scripted(winner, rounds, use))
    for attempt in range(1, 4):
        reply = play("family_tutelage", f"考核 {course_id} {attempt}", now=NOW + 600 * attempt)
        assert "未通过" in reply.title
    assert run(game)["status"] == "failed"
    assert [row["outcome"] for row in sql(game[1], "SELECT * FROM family_tutelage_exams")] == [outcome] * 3
    assert not sql(game[1], "SELECT * FROM family_tutelage_graduations")
    with pytest.raises(GameError, match="结束"):
        play("family_tutelage", f"考核 {course_id} 4", now=NOW + 2400)


@pytest.mark.parametrize("target", ["family_tutelage_courses", "duel_actions", "operations"])
def test_start_failure_rolls_back_quota_and_permanent_reply(game, play, target):
    ids = prepare(game, play)
    sql(game[1], f"CREATE TRIGGER injected BEFORE INSERT ON {target} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        start(game, play, ids, op="retry-start")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    start(game, play, ids, op="retry-start")
    assert len(sql(game[1], "SELECT * FROM family_tutelage_courses")) == 1


@pytest.mark.parametrize("target,verb", [("family_tutelage_lessons","INSERT"),("family_tutelage_courses","UPDATE"),("inventory","UPDATE"),("players","UPDATE"),("pets","UPDATE"),("duel_actions","INSERT"),("operations","INSERT")])
def test_every_lesson_write_failure_rolls_back_and_can_retry(game, play, target, verb):
    ids = prepare(game, play)
    start(game, play, ids)
    course_id = run(game)["course_id"]
    sql(game[1], f"CREATE TRIGGER injected BEFORE {verb} ON {target} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        play("family_tutelage", f"讲习 {course_id} 1", op="retry-lesson")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    play("family_tutelage", f"讲习 {course_id} 1", op="retry-lesson")
    assert run(game)["lessons_done"] == 1


@pytest.mark.parametrize("target,verb", [("battle_records","INSERT"),("learned_skills","UPDATE"),("family_tutelage_exams","INSERT"),("family_tutelage_graduations","INSERT"),("family_tutelage_courses","UPDATE"),("players","UPDATE"),("pets","UPDATE"),("duel_actions","INSERT"),("operations","INSERT")])
def test_every_exam_write_failure_rolls_back_and_can_retry(game, play, monkeypatch, target, verb):
    ids = prepare(game, play)
    course_id = ready(game, play, ids)
    monkeypatch.setattr(family_tutelage, "fight", scripted())
    sql(game[1], f"CREATE TRIGGER injected BEFORE {verb} ON {target} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600, op="retry-exam")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600, op="retry-exam")
    assert run(game)["status"] == "completed"


def test_weekly_quota_expiry_clock_rollback_privacy_and_restart(game, play):
    ids = prepare(game, play)
    start(game, play, ids)
    first = run(game)["course_id"]
    with pytest.raises(GameError, match="进行中"):
        start(game, play, ids)
    for argument in (f"详情 {first}", f"取消 {first}", f"讲习 {first} 1", f"考核 {first} 1"):
        with pytest.raises(GameError):
            play("family_tutelage", argument, user="u2")
    play("family_tutelage", f"取消 {first}", now=NOW + 1)
    with pytest.raises(GameError, match="时间"):
        start(game, play, ids, now=NOW)
    start(game, play, ids, now=NOW + 1)
    second = run(game)["course_id"]
    play("family_tutelage", f"取消 {second}", now=NOW + 2)
    with pytest.raises(GameError, match="名额"):
        start(game, play, ids, now=NOW + 3)
    start(game, play, ids, now=NOW + 604800)
    current = run(game)
    restarted = Game(game[1], game[0].config, game[0].rng)
    restarted.content.family_tutelage.clear()
    restarted.content.enemies.clear()
    restarted.content.items.clear()
    assert "风刃传习" in restarted.execute("u1", "family_tutelage", "", "read-restart", NOW + 604801).text()
    before = dump(game)
    assert "已到期" in play("family_tutelage", now=current["expires_at"]).text()
    assert dump(game) == before
    assert "期限已到" in play("family_tutelage", f"讲习 {current['course_id']} 1", now=current["expires_at"]).text()
    assert run(game)["status"] == "expired"


def test_concurrent_start_and_exam_have_one_winner(game, play, monkeypatch):
    ids = prepare(game, play)

    def execute(argument, index, now=NOW):
        try:
            return game[0].execute("u1", "family_tutelage", argument, f"parallel-{argument}-{index}", now)
        except GameError:
            return None

    argument = f"开课 wind_lesson {ids[0]} {ids[2]} {beijing_week(NOW)[0]}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda index: execute(argument, index), range(2)))
    assert sum(result is not None for result in results) == 1
    course_id = run(game)["course_id"]
    play("family_tutelage", f"讲习 {course_id} 1")
    play("family_tutelage", f"讲习 {course_id} 2", now=NOW + 600)
    monkeypatch.setattr(family_tutelage, "fight", scripted())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda index: execute(f"考核 {course_id} 1", index, NOW + 600), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM family_tutelage_graduations")) == 1
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1


@pytest.mark.parametrize("boundary", ["ordinary", "bonus"])
def test_both_mastery_settlement_boundaries_rollback(game, play, monkeypatch, boundary):
    ids = prepare(game, play)
    course_id = ready(game, play, ids)
    monkeypatch.setattr(family_tutelage, "fight", scripted())
    key = "award_mastery" if boundary == "ordinary" else "study"
    original = getattr(family_tutelage.mastery, key)

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected mastery settlement")

    monkeypatch.setattr(family_tutelage.mastery, key, fail)
    before = dump(game)
    with pytest.raises(RuntimeError, match="injected mastery"):
        play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600, op="mastery-retry")
    assert dump(game) == before
    monkeypatch.setattr(family_tutelage.mastery, key, original)
    assert "结业" in play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600, op="mastery-retry").title


@pytest.mark.parametrize("proficiency,expected", [(180,0),(178,0),(170,5)])
def test_bonus_is_capped_at_actual_remaining_mastery_after_normal_combat(game, play, monkeypatch, proficiency, expected):
    ids = prepare(game, play)
    course_id = ready(game, play, ids)
    if proficiency == 180:
        sql(game[1], "UPDATE learned_skills SET level=5,proficiency=0 WHERE pet_id=? AND skill_id='wind_slash'", (ids[2],))
    else:
        sql(game[1], "UPDATE learned_skills SET level=4,proficiency=? WHERE pet_id=? AND skill_id='wind_slash'", (proficiency, ids[2]))
    monkeypatch.setattr(family_tutelage, "fight", scripted())
    reply = play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600)
    assert "结业" in reply.title
    assert sql(game[1], "SELECT proficiency FROM family_tutelage_graduations")[0]["proficiency"] == expected
    assert sql(game[1], "SELECT level,proficiency FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (ids[2],)) == [{"level":5,"proficiency":0}]


@pytest.mark.parametrize("block", ["unequipped", "energy", "cooldown", "archived", "clock"])
def test_not_ready_exam_never_consumes_an_attempt(game, play, block):
    ids = prepare(game, play)
    course_id = ready(game, play, ids)
    now = NOW + 600
    if block == "unequipped":
        sql(game[1], "UPDATE learned_skills SET equipped=0 WHERE pet_id=? AND skill_id='wind_slash'", (ids[2],))
    elif block == "energy":
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=?", (now, ids[2]))
    elif block == "cooldown":
        sql(game[1], "UPDATE players SET last_pve=?", (now,))
    elif block == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[2],))
    else:
        now -= 1
    before = dump(game)
    with pytest.raises(GameError):
        play("family_tutelage", f"考核 {course_id} 1", now=now)
    assert dump(game) == before
    assert run(game)["attempts_used"] == 0


def test_rules_enemy_and_costs_freeze_but_student_uses_current_loadout(game, play, monkeypatch):
    ids = prepare(game, play)
    start(game, play, ids)
    course_id = run(game)["course_id"]
    original_enemy = run(game)["snapshot"]["fighter"]
    game[0].content.family_tutelage.clear()
    game[0].content.enemies.clear()
    play("family_tutelage", f"讲习 {course_id} 1")
    play("family_tutelage", f"讲习 {course_id} 2", now=NOW + 600)
    sql(game[1], "UPDATE pets SET realm=3,name='新名' WHERE pet_id=?", (ids[2],))
    sql(game[1], "UPDATE players SET active_pet_id=?", (ids[1],))
    seen = []

    def inspect(left, right, *args, **kwargs):
        seen.append((left[0], right[0], kwargs))
        return scripted()(left, right, *args, **kwargs)

    monkeypatch.setattr(family_tutelage, "fight", inspect)
    play("family_tutelage", f"考核 {course_id} 1", now=NOW + 600)
    assert seen[0][0].pet_id == ids[2]
    assert "新名" in seen[0][0].name
    assert seen[0][0].stats.hp > 120
    assert seen[0][1].stats.model_dump() == original_enemy["stats"]
    assert seen[0][2]["max_rounds"] == 40
    assert sql(game[1], "SELECT child_id FROM family_tutelage_graduations")[0]["child_id"] == ids[2]


def test_grandparent_and_unrelated_same_species_cannot_replace_direct_parent(game, play):
    ids = prepare(game, play)
    # The child breeds a second real generation; the first grandparent has no direct credential.
    sql(game[1], "UPDATE pets SET affinity=100,energy=100 WHERE user_id='u1'")
    play("breeding", f"{ids[1]} {ids[2]}", now=NOW + 604800)
    play("use", "egg_qingluan", now=NOW + 604800)
    grandchild = sql(game[1], "SELECT MAX(child_pet_id) AS id FROM pet_lineage_eggs")[0]["id"]
    with pytest.raises(GameError, match="直接亲本"):
        start(game, play, [ids[0], ids[1], grandchild], now=NOW + 604800)


def test_qq_buttons_have_no_duplicate_links_and_onebot_uses_same_start_handler(game, play, monkeypatch):
    ids = prepare(game, play, "12345")
    preview = play("family_tutelage", f"预览 wind_lesson {ids[0]} {ids[2]}", user="12345")
    _, segments = _qq_segments(preview, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    markdown = segments["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    buttons = [button.action.data for segment in segments["keyboard"] for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert len(buttons) <= 4
    assert not set(links) & set(buttons)
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(game_module.time, "time", lambda: NOW)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    command = preview.commands[0]
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    asyncio.run(handlers._run(bot, onebot_event("!" + command, 76), "!" + command))
    assert "已开课" in bot.send.call_args.args[1]
    assert len(sql(game[1], "SELECT * FROM family_tutelage_courses")) == 1


def test_week_quota_is_frozen_even_when_courses_share_a_timestamp(game, play):
    ids = prepare(game, play)
    start(game, play, ids, op="quota-first")
    first = run(game)["course_id"]
    play("family_tutelage", f"取消 {first}")
    game[0].content = replace(game[0].content, family_tutelage_rules=game[0].content.family_tutelage_rules.model_copy(update={"weekly_starts":3}))
    start(game, play, ids, op="quota-second")
    second = sql(game[1], "SELECT course_id FROM family_tutelage_courses WHERE status='active'")[0]["course_id"]
    play("family_tutelage", f"取消 {second}")
    with pytest.raises(GameError, match="名额"):
        start(game, play, ids, op="quota-third")
    assert {json.loads(row["snapshot"])["rules"]["weekly_starts"] for row in sql(game[1], "SELECT snapshot FROM family_tutelage_courses")} == {2}


def test_year_boundary_expired_old_buttons_and_paginated_private_history(game, play):
    ids = prepare(game, play)
    now = int(datetime(2027, 12, 27, tzinfo=BEIJING).timestamp())
    course_ids = []
    for index in range(8):
        at = now + index * 604800
        start(game, play, ids, now=at, op=f"history-start-{index}")
        current = run(game)
        course_ids.append(current["course_id"])
        play("family_tutelage", f"取消 {current['course_id']}", now=at)
    before = dump(game)
    page = play("family_tutelage", "记录", now=at)
    assert len(page.inline_commands) == 6
    assert f"{family_tutelage.TITLE} 记录 2" in page.commands
    second = play("family_tutelage", "记录 2", now=at)
    assert len(second.inline_commands) == 2
    assert dump(game) == before
    with pytest.raises(GameError, match="结束"):
        play("family_tutelage", f"讲习 {course_ids[0]} 1", now=at)
    with pytest.raises(GameError, match="过期"):
        play("family_tutelage", f"开课 wind_lesson {ids[0]} {ids[2]} {beijing_week(now)[0]}", now=at)
    play("adopt", "青鸾", user="u2", now=at)
    assert "0 门" in play("family_tutelage", "记录", user="u2", now=at).text()


def test_start_rejects_clock_before_hatching_and_old_course_closure_is_atomic(game, play):
    ids = prepare(game, play)
    with pytest.raises(GameError, match="孵化凭证"):
        start(game, play, ids, now=NOW - 1)
    start(game, play, ids)
    old = run(game)["course_id"]
    sql(game[1], "CREATE TRIGGER injected BEFORE INSERT ON family_tutelage_courses BEGIN SELECT RAISE(ABORT,'injected replacement'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected replacement"):
        start(game, play, ids, now=NOW + 604800, op="new-week-retry")
    assert dump(game) == before
    assert run(game)["status"] == "active"
    sql(game[1], "DROP TRIGGER injected")
    start(game, play, ids, now=NOW + 604800, op="new-week-retry")
    assert sql(game[1], "SELECT status FROM family_tutelage_courses WHERE course_id=?", (old,))[0]["status"] == "expired"


def test_concurrent_lesson_is_paid_once_and_today_only_shows_ready_actions(game, play):
    ids = prepare(game, play)
    start(game, play, ids)
    course_id = run(game)["course_id"]

    def teach(index):
        try:
            return game[0].execute("u1", "family_tutelage", f"讲习 {course_id} 1", f"parallel-lesson-{index}", NOW)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(teach, range(2)))
    assert sum(reply is not None for reply in replies) == 1
    assert len(sql(game[1], "SELECT * FROM family_tutelage_lessons")) == 1
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW + 599, "readonly")
        assert family_tutelage.today_state(ctx, "u1") is None
        ctx.now += 1
        assert "家族传习" in family_tutelage.today_state(ctx, "u1")
