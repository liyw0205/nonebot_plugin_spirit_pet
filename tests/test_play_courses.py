import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.play_course_content import PlayCourse
from nonebot_plugin_spirit_pet.gameplay import bond_levels, help as game_help, loadout, play_courses, play_games
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
GREAT = (0, 1, 0, 0, 1, 0)
PLAIN = (2, 2, 2, 1, 2, 2)
FAIL = (0, 1, 1, 1)


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "player_identity", "pets", "active_pet_slots", "inventory", "quest_progress",
        "duel_actions", "team_members", "battle_records",
    )}


def run(store, user="u1"):
    return json.loads(sql(store, "SELECT snapshot FROM duel_actions WHERE user_id=? "
                         "AND json_extract(snapshot,'$.kind')='play_course' ORDER BY action_id DESC LIMIT 1",
                         (user,))[0]["snapshot"])


def step(play, reply, lane, **kwargs):
    command = next(c for c in reply.commands if "前进 " + play_courses.LANES[lane] in c)
    return play(*handlers._parse(command), **kwargs)


def finish(play, route=GREAT, course="竹影跳径", **kwargs):
    reply = play("play_course", "出发 " + course, **kwargs)
    for lane in route:
        reply = step(play, reply, lane, **kwargs)
    return reply


def winning_route(course):
    paths = [(1, 4, 0, ())]
    for row in course.rows:
        paths = [(lane, min(6, stamina - play_courses.TILE_COST[tile]), fruit + (tile == "fruit"), route + (lane,))
                 for previous, stamina, fruit, route in paths for lane, tile in enumerate(row)
                 if abs(previous - lane) <= 1 and stamina >= play_courses.TILE_COST[tile]]
    return next(route for _, _, fruit, route in paths if fruit >= 2)


@pytest.mark.parametrize("course_id", ["bamboo", "creek", "orchard"])
def test_every_public_course_has_a_real_great_route(game, play, course_id):
    play("adopt", "青鸾")
    course = game[0].content.play_courses[course_id]
    reply = finish(play, winning_route(course), course.name)
    saved = run(game[1])
    assert saved["status"] == "finished" and saved["score"] >= 90
    assert len(saved["history"]) == 6
    assert "精彩" in reply.text()
    assert pet(game[1])["energy"] == 92 and pet(game[1])["affinity"] == 4
    assert items(game[1])["spirit_food"] == 4
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='play_mastery_reaction'") == [{"progress": 1}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 6}]


@pytest.mark.parametrize("bad", ["short", "wide", "unknown", "empty_description", "unreachable", "extra"])
def test_invalid_content_rejected(game, bad):
    values = game[0].content.play_courses["bamboo"].model_dump()
    if bad == "short":
        values["rows"].pop()
    elif bad == "wide":
        values["rows"][0] = ["fruit", "meadow"]
    elif bad == "unknown":
        values["rows"][0] = ["missing", "low", "high"]
    elif bad == "empty_description":
        values["description"] = " "
    elif bad == "unreachable":
        values["rows"] = [["high", "high", "high"] for _ in range(4)] + [["fruit", "low", "meadow"] for _ in range(2)]
    else:
        values["extra"] = 1
    with pytest.raises(ValidationError):
        PlayCourse.model_validate(values)


@pytest.mark.parametrize("bad", ["no_courses", "no_reaction"])
def test_catalog_requires_real_reward_consumer(game, bad):
    content = replace(game[0].content, play_courses={}) if bad == "no_courses" else replace(
        game[0].content, play_games={k: v for k, v in game[0].content.play_games.items() if k != "reaction"})
    with pytest.raises(ValueError, match="play courses"):
        content.validate()


def test_public_preview_and_running_view_are_business_read_only(game, play):
    before = snapshot(game[1])
    for arg in ("", "预览 竹影跳径", "记录"):
        reply = play("play_course", arg)
        assert reply.commands and snapshot(game[1]) == before
    assert "尚未结契" in play("play_course", "预览 竹影跳径").text()
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET energy=1,energy_updated=?", (NOW - 10000,))
    before = snapshot(game[1])
    reply = play("play_course", "预览 竹影跳径")
    assert "可用精力" in reply.text() and "出发" in reply.commands[0]
    assert snapshot(game[1]) == before
    play("play_course", "出发 竹影跳径")
    before = snapshot(game[1])
    play("play_course", now=NOW + 86400)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("route,status,score,affinity,food", [(GREAT, "finished", 120, 4, 4),
                                                          (PLAIN, "finished", 60, 2, 3),
                                                          (FAIL, "failed", 0, 1, 3)])
def test_grades_and_failure_spend_one_budget_and_grow_original_partner(game, play, route, status, score, affinity, food):
    play("adopt", "青鸾")
    reply = finish(play, route)
    saved = run(game[1])
    assert (saved["status"], saved["score"]) == (status, score)
    assert (pet(game[1])["energy"], pet(game[1])["affinity"]) == (92, affinity)
    assert items(game[1])["spirit_food"] == food
    assert "亲密 +" in reply.text()
    assert "本局路线" in play("play_course", "记录").text()
    assert "反应试炼 · 已游玩" in play("play_game").text()
    with pytest.raises(GameError, match="今天已经"):
        play("play_game", "灵息共振")


def test_stamina_costs_recovery_and_preview_match_actual_steps(game, play):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    for lane, expected in ((0, 3), (1, 2), (0, 0), (0, 2), (1, 1)):
        assert f"耐力将为 {expected}" in reply.text()
        reply = step(play, reply, lane)
        assert run(game[1])["stamina"] == expected
    assert "耐力不足，将失手结束" in reply.text()
    reply = step(play, reply, 0)
    assert "120/120" in reply.text()


def test_quit_gives_no_growth_and_no_refund_even_when_original_is_released(game, play):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    step(play, reply, 0)
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','released_1',1,1)")
    before = snapshot(game[1])
    reply = play("play_course", "退出", op="quit")
    assert run(game[1])["status"] == "quit" and "不退" in reply.text()
    assert snapshot(game[1])["pets"] == before["pets"]
    assert snapshot(game[1])["inventory"] == before["inventory"]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id IN ('play_mastery_reaction','bond_exp_1')")
    assert play("play_course", "退出", op="quit") == reply
    with pytest.raises(GameError, match="今天已经"):
        play("play_course", "出发 溪石折道")


@pytest.mark.parametrize("argument,reason", [("出发 不存在", "没有这条"), ("前进 上路", "路线可选"),
                                            ("预览", "格式"), ("退出 局 x", "局步参数"),
                                            ("前进 左路 局 x 步 " + "9" * 5000, "整数")],
                         ids=["unknown_course", "unknown_lane", "format", "guard_format", "huge_guard"])
def test_specific_refusals_are_zero_business_writes(game, play, argument, reason):
    play("adopt", "青鸾")
    play("play_course", "出发 竹影跳径")
    before = snapshot(game[1])
    with pytest.raises(GameError, match=reason):
        play("play_course", argument)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ["energy", "missing_active", "sealed", "trip", "pending"])
def test_start_conditions_and_preview_keep_exact_reasons(game, play, blocked):
    play("adopt", "青鸾")
    timestamp = NOW
    reasons = {"energy": "精力不足", "missing_active": "尚未选择", "sealed": "已封存", "trip": "正在外出派遣", "pending": "奖励待领取"}
    if blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=7")
    elif blocked == "missing_active":
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif blocked == "sealed":
        sql(game[1], "UPDATE pets SET archived=1")
    else:
        play("expedition_start", "采灵药", op="trip")
        if blocked == "pending":
            timestamp = NOW + 1
            sql(game[1], "UPDATE expeditions SET finishes_at=?", (timestamp,))
    before = snapshot(game[1])
    assert reasons[blocked] in play("play_course", "预览 竹影跳径", now=timestamp).text()
    with pytest.raises(GameError, match=reasons[blocked]):
        play("play_course", "出发 竹影跳径", now=timestamp)
    assert snapshot(game[1]) == before


def test_quota_shared_legacy_compatibility_and_clock_high_water(game, play):
    play("adopt", "青鸾")
    play("play_game", "藏食寻宝", now=NOW + 86400)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="今天已经"):
        play("play_course", "出发 竹影跳径", now=NOW + 86400)
    for action, arg in (("play_course", "出发 竹影跳径"), ("play_game", "反应试炼")):
        with pytest.raises(GameError, match="日期早于"):
            play(action, arg, now=NOW)
    assert snapshot(game[1]) == before
    play("play_course", "出发 竹影跳径", now=NOW + 2 * 86400)
    with pytest.raises(GameError, match="跃障未结束"):
        play("play_game", "灵息共振", now=NOW + 3 * 86400)


def test_adjacent_lane_old_step_and_old_run_cannot_operate_new_run(game, play):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    command = reply.commands[0]
    step(play, reply, 0)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经执行"):
        play(*handlers._parse(command))
    with pytest.raises(GameError, match="相邻"):
        play("play_course", "前进 右路")
    assert snapshot(game[1]) == before
    play("play_course", "退出")
    play("play_course", "出发 溪石折道", now=NOW + 86400)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="另一局"):
        play(*handlers._parse(command), now=NOW + 86400)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ["sealed", "trip", "released", "missing"])
def test_original_partner_pauses_and_can_resume_or_quit(game, play, blocked):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    if blocked == "sealed":
        sql(game[1], "UPDATE pets SET archived=1")
    elif blocked == "trip":
        play("expedition_start", "采灵药")
    elif blocked == "released":
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1','released_1',1,1)")
    else:
        play("adopt", "青鸾", user="other")
        sql(game[1], "DELETE FROM active_pet_slots WHERE pet_id=1")
        sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=1")
    reason = {"sealed": "已封存", "trip": "外出派遣", "released": "已归灵", "missing": "不存在"}[blocked]
    before = snapshot(game[1])
    page = play("play_course")
    assert reason in page.text() and not page.commands
    with pytest.raises(GameError, match=reason):
        step(play, reply, 0)
    assert snapshot(game[1]) == before
    if blocked == "sealed":
        play("pet_restore", "1")
        step(play, play("play_course"), 0)
        assert len(run(game[1])["history"]) == 1
    elif blocked == "trip":
        job_id = sql(game[1], "SELECT job_id FROM expeditions WHERE user_id='u1'")[0]["job_id"]
        play("expedition_cancel", str(job_id))
        step(play, play("play_course"), 0)
        assert len(run(game[1])["history"]) == 1
    else:
        play("play_course", "退出")
        assert run(game[1])["status"] == "quit"


def test_switching_active_pet_does_not_redirect_growth(game, play):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    play("summon")
    second = sql(game[1], "SELECT * FROM pets WHERE pet_id<>1")[0]
    play("switch", str(second["pet_id"]))
    for lane in GREAT:
        reply = step(play, reply, lane)
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=1") == [{"affinity": 4}]
    assert pet(game[1])["affinity"] == second["affinity"]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_2'")


def test_cross_day_restart_and_expired_cache_replay_use_frozen_course(game, play):
    play("adopt", "青鸾")
    first = play("play_course", "出发 竹影跳径", op="start")
    advanced = step(play, first, GREAT[0], op="advance")
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    replacement = game[0].content.play_courses["creek"].model_copy(update={"id": "bamboo", "name": "新赛道"})
    content = replace(game[0].content, play_courses={"bamboo": replacement})
    content = replace(content, play_games={**content.play_games, "reaction": content.play_games["reaction"].model_copy(update={"great_items": {"forge_ore": 99}})})
    fresh = Game(game[1], game[0].config, game[0].rng, content)
    game[1].initialize()
    assert fresh.execute("u1", "play_course", "", "start", NOW + 86400) == first
    assert fresh.execute("u1", "play_course", "", "advance", NOW + 86400) == advanced
    assert snapshot(game[1]) == before
    reply = fresh.execute("u1", "play_course", "", "view", NOW + 86400)
    assert "竹影跳径" in reply.text() and "已过 1/6" in reply.text()
    for index, lane in enumerate(GREAT[1:]):
        command = next(c for c in reply.commands if "前进 " + play_courses.LANES[lane] in c)
        reply = fresh.execute("u1", *handlers._parse(command), f"resume-{index}", NOW + 86400)
    assert items(game[1])["spirit_food"] == 4 and "forge_ore" not in items(game[1])
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    assert fresh.execute("u1", "play_course", "", "resume-4", NOW + 86400 * 9) == reply
    with pytest.raises(GameError, match="different user"):
        fresh.execute("u2", "play_course", "", "resume-4", NOW + 86400 * 9)
    assert snapshot(game[1]) == before
    play("play_game", "灵息共振", now=NOW + 86400)
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='play_mastery_reaction'") == [{"progress": 1}]


def test_time_rollback_is_read_only_and_preserves_progress(game, play):
    play("adopt", "青鸾")
    reply = play("play_course", "出发 竹影跳径")
    reply = step(play, reply, 0, now=NOW + 100)
    before = snapshot(game[1])
    assert "时间早于" in play("play_course", now=NOW).text()
    for arg in ("前进 中路", "退出"):
        with pytest.raises(GameError, match="时间早于"):
            play("play_course", arg, now=NOW)
    assert snapshot(game[1]) == before
    step(play, reply, 1, now=NOW + 100)


@pytest.mark.parametrize("phase,method", [("start", "record_play_course_action"), ("step", "record_play_course_action"),
                                         ("finish", "add_item"), ("finish", "record_play_course_action"),
                                         ("quit", "record_play_course_action"), ("start", "invalidate_pet_ready"),
                                         ("finish", "invalidate_pet_ready")])
def test_repository_write_fault_rolls_back_and_retry_is_idempotent(game, play, monkeypatch, phase, method):
    play("adopt", "青鸾")
    reply = None
    if phase != "start":
        reply = play("play_course", "出发 竹影跳径")
    if phase == "finish":
        for lane in GREAT[:-1]:
            reply = step(play, reply, lane)
    arg = {"start": "出发 竹影跳径", "step": "前进 左路", "finish": "前进 左路", "quit": "退出"}[phase]
    original = getattr(Repository, method)
    before = snapshot(game[1])

    def broken(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("injected course write failure")

    monkeypatch.setattr(Repository, method, broken)
    with pytest.raises(RuntimeError, match="course write"):
        play("play_course", arg, op="retry")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(Repository, method, original)
    result = play("play_course", arg, op="retry")
    assert result == play("play_course", arg, op="retry")


@pytest.mark.parametrize("phase", ["reserve", "growth"])
def test_other_write_faults_roll_back_full_uow(game, play, monkeypatch, phase):
    play("adopt", "青鸾")
    if phase == "growth":
        reply = play("play_course", "出发 竹影跳径")
        for lane in GREAT[:-1]:
            reply = step(play, reply, lane)
    module, name = {"reserve": (play_games, "reserve_day"), "growth": (bond_levels, "add_exp")}[phase]
    original = getattr(module, name)
    before = snapshot(game[1])

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected course uow failure")

    monkeypatch.setattr(module, name, broken)
    arg = "前进 左路" if phase == "growth" else "出发 竹影跳径"
    with pytest.raises(RuntimeError, match="course uow"):
        play("play_course", arg, op="retry-uow")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(module, name, original)
    play("play_course", arg, op="retry-uow")


def test_same_operation_start_and_competing_last_step_quit_settle_once(game, play):
    play("adopt", "青鸾")
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: play("play_course", "出发 竹影跳径", op="same-start"), range(2)))
    assert replies[0] == replies[1] and pet(game[1])["energy"] == 92
    reply = replies[0]
    for lane in GREAT[:-1]:
        reply = step(play, reply, lane)
    finish_command = next(c for c in reply.commands if "前进 左路" in c)
    quit_command = next(link.command for link in reply.inline_commands if link.label == "退出本局")

    def execute(command):
        try:
            return play(*handlers._parse(command))
        except GameError as exc:
            assert "已经执行" in str(exc) or "已结束" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, [finish_command, quit_command]))
    assert sum(reply is not None for reply in results) == 1
    finished = run(game[1])["status"] == "finished"
    assert items(game[1])["spirit_food"] == 3 + finished
    assert pet(game[1])["affinity"] == 4 * finished


def test_two_users_and_other_action_kinds_stay_isolated(game, play):
    play("adopt", "青鸾")
    play("adopt", "青鸾", user="u2")
    play("play_course", "出发 竹影跳径", user="u2")
    before_other = run(game[1], "u2")
    finish(play)
    assert run(game[1], "u2") == before_other
    with closing(game[1].connect()) as conn:
        repo = Repository(conn)
        assert repo.latest_duel_action("u1") is None
        assert repo.latest_cooking_action("u1") is None
        assert repo.latest_tracking_action("u1") is None
        assert repo.latest_herbalism_action("u1") is None
        assert repo.latest_nursery_action("u1") is None
    assert "尚无回合记录" in play("duel", "回顾").text()
    action_id = sql(game[1], "SELECT action_id FROM duel_actions WHERE user_id='u1' LIMIT 1")[0]["action_id"]
    with pytest.raises(GameError, match="未找到本人的斗法"):
        play("duel", f"回顾 查看 {action_id}")


def test_qq_native_and_fallback_short_contract(game, play):
    play("adopt", "青鸾")
    first = play("play_course", "出发 竹影跳径")
    replies = [play("play_course", "预览 溪石折道"), first, step(play, first, 0)]
    for reply in replies:
        assert len(reply.commands) <= 4
        assert all(not re.search(r"[0-9a-f]{16}", label) for label, _ in _action_items(reply))
        _, parts = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        body = parts["markdown"][0].data["markdown"].content
        links = {parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        buttons = {button.action.data for segment in parts["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert buttons == {"!" + c for c in reply.commands}
        assert links == {"!" + link.command for link in reply.inline_commands} and not links & buttons
        assert "| 段 | 左路 | 中路 | 右路 |" in body
        _, text = _qq_segments(reply, Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"))
        assert all("!" + link.command in str(text) for link in reply.inline_commands)


def test_real_public_handler_chain_growth_food_and_qq_entry_only(game, monkeypatch):
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    commands = ["!灵宠领养 青鸾", "!灵宠跃障", "!灵宠跃障 预览 竹影跳径", "!灵宠跃障 出发 竹影跳径",
                *("!灵宠跃障 前进 " + play_courses.LANES[lane] for lane in GREAT), "!灵宠使用 灵粮", "!灵宠羁绊"]

    async def execute():
        for index, command in enumerate(commands, 1):
            event = onebot_event(command, index)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(execute())
    assert bot.send.await_count == len(commands)
    assert items(game[1], "12345")["spirit_food"] == 3
    assert pet(game[1], "12345")["affinity"] > 4
    assert pet(game[1], "12345")["exp"] > 0
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='12345' AND quest_id='bond_exp_1'") == [{"progress": 6}]
    event = qq_event(user_id="qq-course", text="!灵宠跃障 预览 竹影跳径", message_id="qq-course-entry")
    assert handlers._parse(event.get_plaintext()) == ("play_course", "预览 竹影跳径")
    qq_bot = Bot(Adapter(nonebot.get_driver()), "test-app", BotInfo(id="test-app", secret="test-only", token="test-only"))
    qq_bot.post_group_messages = AsyncMock(return_value={})
    asyncio.run(handlers.handle_command(qq_bot, event, event.get_message()))
    assert qq_bot.post_group_messages.await_count == 1


def test_mastery_and_bond_growth_are_consumed_by_existing_systems(game, play):
    play("adopt", "青鸾")
    # Public companionship and courses cross the actual bond threshold without injected assets.
    for index in range(5):
        timestamp = NOW + index * 86400
        play("bond", now=timestamp)
        finish(play, now=timestamp)
    assert "可领取「反应试炼 5 局」" in play("play_game", "记录", now=NOW + 4 * 86400).text()
    assert "精通奖励已领取" in play("play_game", "领奖 反应试炼 5", now=NOW + 4 * 86400).text()
    assert "等级 2" in play("bond_levels", now=NOW + 4 * 86400).text()
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW + 4 * 86400, "inspect")
        with_bond = loadout.combatant(ctx, recover_energy=False).stats
        before = bond_levels._bonuses(2)
        conn.execute("BEGIN")
        conn.execute("DELETE FROM quest_progress WHERE quest_id='bond_exp_1'")
        without_bond = loadout.combatant(ctx, recover_energy=False).stats
        assert with_bond.hp == without_bond.hp + before["hp"]
        assert with_bond.attack == without_bond.attack + before["attack"]
        conn.rollback()


@pytest.mark.parametrize("defense,expected", [(29, 4), (30, 5), (60, 6), (300, 6)])
def test_defense_initial_stamina_bonus_is_bounded_and_frozen(game, play, defense, expected):
    play("adopt", "青鸾")
    species = game[0].content.species["qingluan"]
    species = species.model_copy(update={"stats": species.stats.model_copy(update={"defense": defense})})
    game[0].content = replace(game[0].content, species={**game[0].content.species, "qingluan": species})
    assert f"初始耐力 {expected}" in play("play_course", "预览 竹影跳径").text()
    play("play_course", "出发 竹影跳径")
    assert run(game[1])["stamina"] == expected
    sql(game[1], "UPDATE pets SET realm=3,layer=10")
    assert run(game[1])["defense"] == defense


@pytest.mark.parametrize("affinity,gained", [(98, 2), (100, 0)])
def test_affinity_cap_reports_actual_gain(game, play, affinity, gained):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET affinity=?", (affinity,))
    reply = finish(play)
    assert f"亲密 +{gained}（100/100）" in reply.text()
    assert pet(game[1])["affinity"] == 100 and items(game[1])["spirit_food"] == 4


def test_readiness_only_invalidates_the_original_participant(game, play):
    play("adopt", "青鸾")
    play("summon")
    second = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>1")[0]["pet_id"]
    play("team_create")
    play("team_ready")
    reply = play("play_course", "出发 竹影跳径")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}]
    play("switch", str(second))
    play("team_ready")
    for lane in GREAT:
        reply = step(play, reply, lane)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": second}]


def test_concurrent_different_step_buttons_and_legacy_start_cannot_double_spend(game, play):
    play("adopt", "青鸾")

    def execute(pair):
        try:
            return play(*pair)
        except GameError as exc:
            assert "今天已经" in str(exc) or "跃障未结束" in str(exc) or "已经执行" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(execute, [("play_course", "出发 竹影跳径"), ("play_game", "反应试炼")]))
    assert sum(reply is not None for reply in replies) == 1
    if sql(game[1], "SELECT * FROM duel_actions"):
        reply = play("play_course")
        actions = [handlers._parse(command) for command in reply.commands[:2]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(execute, actions))
        assert sum(reply is not None for reply in result) == 1
        assert len(run(game[1])["history"]) == 1 and pet(game[1])["energy"] == 92
    assert len(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'play_game_*'")) == 1


def test_classified_help_and_objectives_reach_current_run_without_duplicate_controls(game, play):
    play("adopt", "青鸾")
    help_reply = play("help", "血脉与道具")
    assert any(game_help.help_link(line) == ("灵宠跃障", "灵宠跃障") for line in help_reply.lines)
    assert not help_reply.commands
    assert "灵宠跃障" in play("play_game").commands
    play("play_course", "出发 竹影跳径")
    assert "跃障进行中" in play("objectives").text()
    page = play("play_game", now=NOW + 86400)
    assert not page.inline_commands and page.commands[0] == "灵宠跃障"


def test_huge_milestone_argument_uses_bounded_common_parser(game, play):
    play("adopt", "青鸾")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="整数"):
        play("play_game", "领奖 反应试炼 " + "9" * 5000)
    assert snapshot(game[1]) == before
