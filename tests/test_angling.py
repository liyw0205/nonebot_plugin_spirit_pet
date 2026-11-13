import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.angling_content import AnglingCourse, MOVES, forecast
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import angling
from nonebot_plugin_spirit_pet.gameplay.help import help_link
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, pet, sql
from .test_commands import onebot_event
from .test_fishing_choices import DAY, NOW, account, snapshot


def _winning_moves(rule, *, step=0, progress=0, tension=None):
    def walk(index, current_progress, current_tension, moves):
        for name in MOVES:
            next_progress, next_tension = forecast(
                current_progress, current_tension, rule["pulls"][index], name,
            )
            if not 0 < next_tension < rule["limit"]:
                continue
            path = (*moves, name)
            if index == len(rule["pulls"]) - 1:
                if next_progress >= rule["goal"]:
                    return path
            else:
                result = walk(index + 1, next_progress, next_tension, path)
                if result:
                    return result
        return ()

    return walk(step, progress, rule["initial"] if tension is None else tension, ())


def _start(play, spot="溪口", bait="素饵", **kwargs):
    arg = f"抛竿 {spot}" + (f" {bait}" if bait else "")
    return play("angling", arg, now=kwargs.get("now", NOW), op=kwargs.get("op"))


def _move(play, label, *, now=NOW, op=None):
    page = play("angling", now=now)
    link = next(link for link in page.inline_commands if link.label == label)
    action, arg = handlers._parse(link.command)
    return play(action, arg, now=now, op=op), link.command


def _run_win(game, play, now=NOW):
    run = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                         "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])
    path = _winning_moves(run["rule"], step=run["step"] - 1,
                          progress=run["progress"], tension=run["tension"])
    assert path, run["rule"]
    result = None
    for index, move in enumerate(path):
        result, _ = _move(play, move, now=now + index, op=f"angling-move-{index}-{now}")
    return result


@pytest.mark.parametrize("change", [
    {"goal": 10}, {"goal": "6"}, {"description": " "}, {"pulls": [1, -1]},
    {"pulls": [0, 0, 0, 0, 0]}, {"pulls": [4, -1, 1, -1, 1]},
    {"goal": 9, "pulls": [3, 3, 3, 3, -1]}, {"created_at": NOW},
])
def test_angling_course_rejects_unplayable_or_invalid_content(game, change):
    data = game[0].content.angling_courses["creek"].model_dump()
    with pytest.raises(ValidationError):
        AnglingCourse.model_validate({**data, **change})


def test_angling_catalog_requires_one_course_per_existing_water(game):
    del game[0].content.angling_courses["creek"]
    with pytest.raises(ValueError, match="cover exactly the fishing spots"):
        game[0].content.validate()


def test_all_three_water_routes_use_real_costs_and_enter_existing_fish_collection(game, play):
    account(game, play)
    sql(game[1], "UPDATE pets SET realm=4")
    cases = (("溪口", "谷香饵"), ("深潭", "晶砂饵"), ("灵渊", "灵光饵"))
    for index, (spot, bait) in enumerate(cases):
        course = next(course for course in game[0].content.angling_courses.values()
                      if course.id == next(s.id for s in game[0].content.fishing_spots.values() if s.name == spot))
        preview = play("angling", f"预览 {spot} {bait}", now=NOW + index * DAY)
        assert "五轮水势" in preview.text() and course.description in preview.text()
        before_items = items(game[1])
        opened = _start(play, spot, bait, now=NOW + index * DAY, op=f"angling-open-{index}")
        assert "鱼获尚未入袋" in opened.text()
        assert pet(game[1])["energy"] == 100 - game[0].content.fishing_spots[course.id].energy
        bait_entry = game[0].content.fishing_baits[next(key for key, value in game[0].content.fishing_baits.items()
                                                        if value.name == bait)]
        assert items(game[1])[bait_entry.cost_item] == before_items[bait_entry.cost_item] - bait_entry.cost_quantity
        result = _run_win(game, play, NOW + index * DAY + 10)
        assert "已入乾坤袋" in result.text()
        saved = json.loads(sql(game[1], "SELECT snapshot FROM fishing_casts ORDER BY cast_id DESC LIMIT 1")[0]["snapshot"])
        assert saved["mode"] == "angling" and saved["status"] == "caught"
        assert sql(game[1], "SELECT claimed FROM quest_progress WHERE quest_id=?",
                   (f"fish_{course.id}_{saved['item_id']}",)) == [{"claimed": 1}]
    assert len(sql(game[1], "SELECT * FROM fishing_casts")) == 3


def test_public_preview_is_read_only_and_onebot_help_reaches_live_actions(game, play):
    before = snapshot(game[1], cache=False)
    for arg in ("", "预览 溪口", "预览 深潭 谷香饵", "记录"):
        play("angling", arg, user="new", now=NOW)
    assert snapshot(game[1], cache=False) == before
    adoption = play("angling", "预览 溪口", user="new", now=NOW)
    assert "灵宠领养 " in {link.command for link in adoption.inline_commands}
    account(game, play)
    help_page = play("help", "血脉与道具")
    assert any(help_link(line) == ("灵宠遛鱼", "灵宠遛鱼") for line in help_page.lines)
    assert handlers._parse("灵宠遛鱼 收线") == ("angling", "收线")
    objective = play("objectives")
    assert any(link.command == "灵宠遛鱼" for link in objective.inline_commands)
    preview = play("angling", "预览 溪口 谷香饵")
    fishing_detail = play("fishing", "详情 溪口 谷香饵")
    assert "灵宠遛鱼 预览 溪口 谷香饵" in {link.command for link in fishing_detail.inline_commands}
    for link in preview.inline_commands:
        assert handlers._parse(link.command) is not None
        assert 0 <= link.line < len(preview.lines)
    _, native = _qq_segments(preview, Config(spirit_pet_qq_mode="native"))
    markdown = "\n".join(segment.data["markdown"].content for segment in native["markdown"])
    urls = re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)
    qq_commands = [parse_qs(urlparse(url).query)["command"][0].lstrip("/") for url in urls]
    assert "灵宠遛鱼 抛竿 溪口 谷香饵" in qq_commands
    assert len(native["keyboard"]) <= 4
    _, plain = _qq_segments(preview, Config(spirit_pet_qq_mode="text"))
    assert "灵宠遛鱼 抛竿 溪口 谷香饵" in str(plain)


def test_onebot_handler_runs_the_full_angling_decision_chain(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    clock = [NOW]
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: clock[0])
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
                          send=AsyncMock())

    async def run_chain():
        async def send_command(command, message_id):
            event = onebot_event(command, message_id)
            await handlers.handle_command(bot, event, event.get_message())

        await send_command("!灵宠领养 青鸾", 1)
        sql(game[1], "UPDATE inventory SET quantity=20 WHERE user_id='12345' AND item_id='spirit_food'")
        sql(game[1], "UPDATE pets SET realm=4 WHERE user_id='12345'")
        await send_command("!灵宠遛鱼 预览 溪口 谷香饵", 2)
        await send_command("!灵宠遛鱼 抛竿 溪口 谷香饵", 3)
        run_state = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                                   "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])
        path = _winning_moves(run_state["rule"])
        assert len(path) == 5
        for index, move in enumerate(path):
            clock[0] = NOW + index + 1
            await send_command(
                f"!灵宠遛鱼 {move} 竿 {run_state['run_id']} 步 {run_state['step']}", 4 + index,
            )
            run_state = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                                       "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])

    asyncio.run(run_chain())
    assert bot.send.await_count == 8
    assert "已入乾坤袋" in str(bot.send.call_args.args[1])
    assert sql(game[1], "SELECT COUNT(*) AS n FROM fishing_casts") == [{"n": 1}]


def test_tension_breaks_before_loot_and_basket_reports_miss_truthfully(game, play):
    account(game, play)
    before = items(game[1])
    _start(play, bait="谷香饵", op="break-open")
    _, old_step = _move(play, "收线", op="break-one")
    state_before = snapshot(game[1])
    action, arg = handlers._parse(old_step)
    with pytest.raises(GameError, match="旧竿或旧步骤"):
        play(action, arg, op="stale-break")
    assert snapshot(game[1]) == state_before
    result, _ = _move(play, "收线", op="break-two")
    assert "鱼线绷断" in result.text()
    expected = dict(before)
    expected["spirit_food"] -= 1
    assert items(game[1]) == expected
    assert pet(game[1])["energy"] == 92
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?",
               (f"fishing_day_{beijing_day(NOW)}",)) == [{"progress": 1}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'fish_creek_%'")
    assert "遛鱼失手" in play("fishing", "鱼篓").text()


def test_abandoning_an_active_rod_keeps_cost_and_records_no_fish(game, play):
    account(game, play)
    before = items(game[1])
    _start(play, bait="谷香饵", op="abandon-open")
    result, _ = _move(play, "撤竿", op="abandon-rod")
    assert "不退" in result.text() and "未发放物品" in result.text()
    expected = dict(before)
    expected["spirit_food"] -= 1
    assert items(game[1]) == expected
    assert pet(game[1])["energy"] == 92
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'fish_creek_%'")
    assert "主动撤竿" in play("fishing", "鱼篓").text()
    assert "主动撤竿" in play("angling", "记录").text()


def test_a_caught_existing_consumable_reaches_the_real_pet_use_path(game, play):
    account(game, play)
    sql(game[1], "UPDATE pets SET energy=8,energy_updated=?", (NOW,))
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='spirit_food'")
    _start(play, bait="", op="consumer-open")
    result = _run_win(game, play)
    assert "灵粮×1已入乾坤袋" in result.text()
    before = pet(game[1])["energy"]
    command = next(link.command for link in result.inline_commands if link.label == "喂养伙伴")
    action, arg = handlers._parse(command)
    play(action, arg)
    assert pet(game[1])["energy"] > before
    assert items(game[1]).get("spirit_food", 0) == 0


def test_new_fish_can_complete_and_pay_the_existing_spot_collection_once(game, play):
    account(game, play)
    for item_id in ("forge_ore", "seed_spirit_rice", "exp_pill"):
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
            (f"fish_creek_{item_id}",))
    before_stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    _start(play, bait="", op="collection-open")
    result = _run_win(game, play)
    assert "鱼获「溪口」集齐" in result.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before_stones + 150
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE user_id='u1' AND quest_id='fishing_set_creek'") == [
        {"claimed": 1},
    ]


def test_parallel_same_open_operation_charges_once(game, play):
    account(game, play)
    before = pet(game[1])["energy"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: game[0].execute(
            "u1", "angling", "抛竿 溪口 谷香饵", "parallel-angling-open", NOW,
        ), range(2)))
    assert replies[0] == replies[1]
    assert pet(game[1])["energy"] == before - 8
    assert sql(game[1], "SELECT COUNT(*) AS n FROM duel_actions WHERE json_extract(snapshot,'$.kind')='angling'") == [
        {"n": 1},
    ]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?",
               (f"fishing_day_{beijing_day(NOW)}",)) == [{"progress": 1}]


def test_opening_write_failure_rolls_back_cost_and_active_state(game, play, monkeypatch):
    account(game, play)
    before = snapshot(game[1], cache=False)
    original = Repository.record_angling_action

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected angling opening failure")

    monkeypatch.setattr(Repository, "record_angling_action", fail_after_write)
    with pytest.raises(RuntimeError, match="injected angling opening"):
        _start(play, bait="谷香饵", op="opening-rollback")
    assert snapshot(game[1], cache=False) == before
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE json_extract(snapshot,'$.kind')='angling'")


def test_step_write_failure_rolls_back_progress_and_receipt(game, play, monkeypatch):
    account(game, play)
    _start(play, op="step-rollback-open")
    before = snapshot(game[1], cache=False)
    original = Repository.record_angling_action

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected angling step failure")

    monkeypatch.setattr(Repository, "record_angling_action", fail_after_write)
    with pytest.raises(RuntimeError, match="injected angling step"):
        _move(play, "稳竿", op="step-rollback")
    assert snapshot(game[1], cache=False) == before
    assert "第1/5轮" in play("angling").text()


@pytest.mark.parametrize("condition,match,spot,bait", [
    ("energy", "精力不足", "溪口", "素饵"),
    ("realm", "需要", "灵渊", "素饵"),
    ("bait", "灵粮不足", "溪口", "谷香饵"),
    ("quota", "竿数已用完", "溪口", "素饵"),
])
def test_blocked_opening_is_hidden_and_changes_nothing(game, play, condition, match, spot, bait):
    account(game, play)
    if condition == "energy":
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=?", (NOW,))
    elif condition == "realm":
        pass
    elif condition == "bait":
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='spirit_food'")
    else:
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,3,0)",
            (f"fishing_day_{beijing_day(NOW)}",))
    preview = play("angling", f"预览 {spot} {bait}", now=NOW)
    assert match in preview.text()
    assert not any(link.label == "抛竿遛鱼" for link in preview.inline_commands)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=match):
        _start(play, spot, bait, now=NOW, op=f"blocked-{condition}")
    assert snapshot(game[1]) == before


def test_competing_distinct_openings_create_one_active_rod(game, play):
    account(game, play)

    def cast(index):
        try:
            return game[0].execute("u1", "angling", "抛竿 溪口", f"competing-open-{index}", NOW).title
        except GameError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(cast, range(2)))
    assert sum(result == "灵宠遛鱼 · 竿中" for result in outcomes) == 1
    assert sum("已有一竿遛鱼" in result for result in outcomes) == 1
    assert pet(game[1])["energy"] == 92
    assert sql(game[1], "SELECT COUNT(*) AS n FROM duel_actions WHERE json_extract(snapshot,'$.kind')='angling'") == [
        {"n": 1},
    ]


def test_durable_steps_and_result_survive_cache_eviction_and_replay_once(game, play):
    account(game, play)
    opened = _start(play, bait="", op="durable-open")
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    assert play("angling", "放线", op="durable-open", now=NOW + 9 * DAY) == opened
    assert snapshot(game[1], cache=False) == before
    step_result, step_command = _move(play, "收线", op="durable-step")
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    action, arg = handlers._parse(step_command)
    assert play(action, arg, op="durable-step", now=NOW + 9 * DAY) == step_result
    assert snapshot(game[1], cache=False) == before
    result = _run_win(game, play, NOW + 9 * DAY + 2)
    row = sql(game[1], "SELECT operation_id FROM fishing_casts ORDER BY cast_id DESC LIMIT 1")[0]
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    action, arg = handlers._parse("灵宠遛鱼 记录")
    assert play(action, arg, now=NOW + 3) is not None
    assert play("angling", "收线 竿 1 步 5", op=row["operation_id"], now=NOW + 8 * DAY) == result
    restarted = Game(game[1], game[0].config, game[0].rng, content=game[0].content)
    assert restarted.execute("u1", "angling", "放线", "durable-open", NOW + 10 * DAY) == opened
    assert restarted.execute("u1", "angling", "稳竿", row["operation_id"], NOW + 10 * DAY) == result
    assert snapshot(game[1], cache=False) == before
    with pytest.raises(GameError, match="different user"):
        play("angling", "", user="other", op=row["operation_id"], now=NOW + 8 * DAY)


def test_midrun_snapshot_survives_content_change_and_partner_switch(game, play):
    account(game, play)
    _start(play, bait="", op="snapshot-open")
    _move(play, "稳竿", op="snapshot-first")
    saved = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                           "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])
    course = game[0].content.angling_courses["creek"]
    game[0].content.angling_courses["creek"] = course.model_copy(update={"goal": 9, "pulls": [0, 0, 0, 0, 0]})
    spot = game[0].content.fishing_spots["creek"]
    game[0].content.fishing_spots["creek"] = spot.model_copy(update={"catches": []})
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    page = play("angling", now=NOW + DAY)
    assert saved["pet_name"] in page.text() and "今日竿数" not in page.text()
    assert "/ " + saved["bait_name"] in page.text()
    result = _run_win(game, play, NOW + DAY + 1)
    assert "已入乾坤袋" in result.text()
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE quest_id=?",
               (f"fish_{saved['spot_id']}_{saved['item_id']}",)) == [{"claimed": 1}]


def test_active_rod_continues_after_midnight_without_charging_or_using_todays_rod(game, play):
    account(game, play)
    before = items(game[1])
    _start(play, bait="谷香饵", now=NOW, op="cross-day-open")
    after_open = items(game[1])
    saved = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                           "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])
    assert after_open["spirit_food"] == before["spirit_food"] - 1
    assert pet(game[1])["energy"] == 92

    next_day = NOW + DAY
    assert beijing_day(next_day) != beijing_day(NOW)
    result = _run_win(game, play, next_day + 10)
    assert "已入乾坤袋" in result.text()
    expected = dict(after_open)
    expected[saved["item_id"]] = expected.get(saved["item_id"], 0) + saved["amount"]
    assert items(game[1]) == expected
    assert pet(game[1])["energy"] == 92
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?",
               (f"fishing_day_{beijing_day(NOW)}",)) == [{"progress": 1}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?",
                   (f"fishing_day_{beijing_day(next_day)}",))


def test_angling_rejects_cast_when_beijing_date_moves_back_past_shared_fishing_quota(game, play):
    account(game, play)
    later = NOW + DAY
    play("fishing", "溪口", now=later, op="later-day-fishing")
    preview = play("angling", "预览 溪口", now=NOW)
    assert "日期早于已有垂钓记录" in preview.text()
    before = snapshot(game[1])
    with pytest.raises(GameError, match="日期早于已有垂钓记录"):
        _start(play, now=NOW, op="rolled-back-date-angling")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("condition,match", [
    ("clock", "时间早于"), ("archived", "封存"), ("expedition", "派遣"), ("released", "归灵"),
])
def test_original_partner_constraints_pause_or_allow_only_safe_exit(game, play, condition, match):
    account(game, play)
    _start(play, bait="", op="partner-open")
    if condition == "clock":
        with pytest.raises(GameError, match=match):
            play("angling", "稳竿", now=NOW - 1)
    elif condition == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet(game[1])["pet_id"],))
        with pytest.raises(GameError, match=match):
            play("angling", "稳竿", now=NOW + 2)
    elif condition == "expedition":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot,slot) "
                     "VALUES ('u1',?,'test','测试派遣','angling-test-expedition',?,?, 'running','{}',1)",
            (pet(game[1])["pet_id"], NOW + 1, NOW + 100))
        with pytest.raises(GameError, match=match):
            play("angling", "稳竿", now=NOW + 2)
    else:
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
            (f"released_{pet(game[1])['pet_id']}",))
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet(game[1])["pet_id"],))
        with pytest.raises(GameError, match=match):
            play("angling", "稳竿", now=NOW + 2)
    result, _ = _move(play, "撤竿", now=NOW + 3, op=f"{condition}-exit")
    assert "不退" in result.text() and "未发放物品" in result.text()


@pytest.mark.parametrize("failure", ["loot", "bonus", "ledger", "action"])
def test_angling_settlement_failure_rolls_back_entire_final_action(game, play, monkeypatch, failure):
    account(game, play)
    for item_id in ("forge_ore", "seed_spirit_rice", "exp_pill"):
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
            (f"fish_creek_{item_id}",))
    _start(play, bait="", op=f"rollback-{failure}-open")
    rule = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                          "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])["rule"]
    path = _winning_moves(rule)
    assert path
    for index, move in enumerate(path[:-1]):
        _move(play, move, now=NOW + index + 1, op=f"rollback-{failure}-step-{index}")
    before = snapshot(game[1], cache=False)

    target = {"loot": (Repository, "add_item"), "bonus": (angling.fishing, "_grant"),
              "ledger": (Repository, "record_fishing_cast"),
              "action": (Repository, "record_angling_action")}[failure]
    original = getattr(target[0], target[1])

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected angling settlement failure")

    monkeypatch.setattr(target[0], target[1], fail_after_write)
    with pytest.raises(RuntimeError, match="injected angling"):
        _move(play, path[-1], now=NOW + 20, op=f"rollback-{failure}-last")
    assert snapshot(game[1], cache=False) == before


@pytest.mark.parametrize("same_operation", [True, False])
def test_competing_final_steps_settle_one_catch(game, play, same_operation):
    account(game, play)
    _start(play, bait="", op="parallel-finish-open")
    rule = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE "
                          "json_extract(snapshot,'$.kind')='angling' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])["rule"]
    path = _winning_moves(rule)
    assert len(path) == 5
    for index, move in enumerate(path[:-1]):
        _move(play, move, now=NOW + index + 1, op=f"parallel-finish-step-{index}")
    page = play("angling", now=NOW + 10)
    command = next(link.command for link in page.inline_commands if link.label == path[-1])
    action, argument = handlers._parse(command)
    before = items(game[1])

    def finish(index):
        op = "parallel-finish" if same_operation else f"parallel-finish-{index}"
        try:
            return game[0].execute("u1", action, argument, op, NOW + 10)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finish, range(2)))
    if same_operation:
        assert outcomes[0] == outcomes[1]
    else:
        assert sum(isinstance(outcome, GameError) for outcome in outcomes) == 1
        assert "当前没有遛鱼中的竿" in str(next(outcome for outcome in outcomes if isinstance(outcome, GameError)))
    assert sql(game[1], "SELECT COUNT(*) AS n FROM fishing_casts") == [{"n": 1}]
    saved = json.loads(sql(game[1], "SELECT snapshot FROM fishing_casts")[0]["snapshot"])
    expected = dict(before)
    expected[saved["item_id"]] = expected.get(saved["item_id"], 0) + saved["amount"]
    assert items(game[1]) == expected


def test_active_rod_is_durable_but_not_a_duel_and_shared_cast_limit_is_strict(game, play):
    account(game, play)
    for index in range(2):
        play("fishing", "溪口", now=NOW, op=f"shared-fish-{index}")
    _start(play, bait="", op="shared-final-cast")
    result = _run_win(game, play, NOW + 1)
    assert "已入乾坤袋" in result.text()
    with pytest.raises(GameError, match="竿数已用完"):
        _start(play, bait="", now=NOW + 10, op="shared-fourth-cast")
    with closing(game[1].connect()) as conn:
        duel = Repository(conn)
        assert duel.latest_duel_action("u1") is None
        angling_row = conn.execute(
            "SELECT action_id,operation_id FROM duel_actions WHERE json_extract(snapshot,'$.kind')='angling' "
            "ORDER BY action_id DESC LIMIT 1",
        ).fetchone()
        assert angling_row is not None
        assert duel.duel_operation(angling_row["operation_id"], "u1") is None
    assert "尚无回合记录" in play("duel", "回顾").text()
    with pytest.raises(GameError, match="未找到本人的斗法回合记录"):
        play("duel", f"回顾 查看 {angling_row['action_id']}")
