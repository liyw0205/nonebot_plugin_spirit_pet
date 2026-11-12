import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
import re

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.gameplay import training
from nonebot_plugin_spirit_pet.storage.repository import Repository
from .test_commands import onebot_event, qq_event

from .support import items, pet, sql

NOW = 1_800_000_000


def snapshot(store):
    return {
        table: sql(store, f"SELECT * FROM {table} ORDER BY rowid")
        for table in ("players", "pets", "inventory", "quest_progress", "learned_skills", "duel_actions")
    }


def prepare(play):
    play("adopt", "青鸾")
    play("sign")
    play("buy", "风刃术诀")
    play("learn", "风刃术")


def start(play, trial="观势破阵", op="start"):
    return play("training", "开始 " + trial, op=op)


def test_catalog_preview_and_public_source_are_read_only(game, play):
    before = snapshot(game[1])
    reply = play("training")
    assert "观势破阵" in reply.text() and "灵粮" in reply.text()
    assert snapshot(game[1]) == before
    prepare(play)
    before = snapshot(game[1])
    reply = play("training", "预览 观势破阵")
    assert "灵靶动作" in reply.text() and "风刃术" in reply.text()
    assert snapshot(game[1]) == before


def test_catalog_requires_three_trials_and_real_shop_food(game):
    content = game[0].content
    with pytest.raises(ValueError, match="exactly three"):
        replace(content, training_trials={key: value for key, value in content.training_trials.items()
                                         if key != "opening"}).validate()
    items_by_id = dict(content.items)
    items_by_id["spirit_food"] = items_by_id["spirit_food"].model_copy(update={"price": None})
    with pytest.raises(ValueError, match="public shop source"):
        replace(content, items=items_by_id).validate()


def test_start_pays_real_resources_and_persists_five_step_choices(game, play):
    prepare(play)
    reply = start(play)
    assert "精力-12" in reply.text() and "灵粮-1" in reply.text()
    assert pet(game[1])["energy"] == 88
    assert items(game[1])["spirit_food"] == 5
    saved = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='training'")[0]["snapshot"])
    assert saved["status"] == "active" and saved["trial"]["moves"] == ["probe", "charge", "burst", "brace", "strike"]
    for index, action in enumerate(("风刃术", "普攻", "护持", "普攻", "普攻"), 1):
        reply = play("training", "出手 " + action, op=f"step-{index}", now=NOW + index)
        if index < 5:
            assert f"第{index + 1}/5回合" in reply.text()
    assert "结算" in reply.title
    assert "羁绊经验+" in reply.text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='training_day_2027-01-15'")


def test_skill_casts_feed_mastery_and_bond_consumers(game, play):
    prepare(play)
    start(play, trial="观势破阵")
    for index, action in enumerate(("普攻", "普攻", "风刃术", "普攻", "普攻"), 1):
        reply = play("training", "出手 " + action, op=f"cast-{index}", now=NOW + index)
        if index == 5:
            assert "结算" in reply.title
    assert "熟练度+" in reply.text()
    row = sql(game[1], "SELECT level, proficiency FROM learned_skills WHERE pet_id=1 AND skill_id='wind_slash'")[0]
    assert row["proficiency"] > 0
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'")[0]["progress"] == 4
    assert "灵宠技能 伙伴 1" in [link.command for link in reply.inline_commands]


def test_same_skill_is_rejected_without_a_business_write(game, play):
    prepare(play)
    reply = start(play)
    assert any("施展风刃术" in link.label for link in reply.inline_commands)
    play("training", "出手 风刃术", op="first")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="不能连续"):
        play("training", "出手 风刃术", op="same")
    assert snapshot(game[1]) == before


def test_replay_resume_and_old_step_guards_are_permanent(game, play):
    prepare(play)
    first = start(play, op="opening")
    old = next(command for command in first.commands if "出手 普攻" in command)
    advanced = play("training", "出手 普攻 局 " + old.split(" 局 ")[1], op="advance", now=NOW + 100)
    assert "第2/5回合" in advanced.text()
    assert play("training", "出手 普攻 局 " + old.split(" 局 ")[1], op="advance") == advanced
    before = snapshot(game[1])
    assert "时间早于" in play("training", now=NOW).text()
    with pytest.raises(GameError, match="时间早于"):
        play("training", "出手 普攻", op="clock-rollback", now=NOW)
    with pytest.raises(GameError, match="数量须"):
        play("training", "出手 普攻 局 " + old.split(" 局 ")[1].split(" 步 ")[0] +
             " 步 " + "9" * 5000, op="huge-step", now=NOW + 100)
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="已经执行"):
        play("training", "出手 护持 局 " + old.split(" 局 ")[1], op="stale", now=NOW + 100)
    resumed = Game(game[1], Config())
    reply = resumed.execute("u1", "training", "", "view-after-restart", NOW + 86400)
    assert "第2/5回合" in reply.text()
    with pytest.raises(GameError, match="different user"):
        resumed.execute("u2", "training", "", "opening", NOW + 86400)


def test_quit_has_no_growth_and_daily_slot_remains_spent(game, play):
    prepare(play)
    start(play)
    before = snapshot(game[1])
    reply = play("training", "退出", op="quit")
    assert "不退" in reply.text()
    after = snapshot(game[1])
    assert after["pets"] == before["pets"] and after["inventory"] == before["inventory"]
    with pytest.raises(GameError, match="名额已用尽"):
        start(play, op="second")


def test_specific_refusals_keep_business_state_unchanged(game, play):
    prepare(play)
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='spirit_food'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵粮不足"):
        play("training", "开始 观势破阵", op="no-food")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ["sealed", "trip", "released", "missing", "forgotten"])
def test_original_partner_pause_restore_and_exit(game, play, blocked):
    prepare(play)
    start(play)
    if blocked == "sealed":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=1")
    elif blocked == "trip":
        play("expedition_start", "采灵药")
    elif blocked == "released":
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1','released_1',1,1)")
    elif blocked == "forgotten":
        sql(game[1], "DELETE FROM learned_skills WHERE pet_id=1")
    else:
        play("adopt", "青鸾", user="other")
        sql(game[1], "DELETE FROM active_pet_slots WHERE pet_id=1")
        sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=1")
    reason = {"sealed": "已封存", "trip": "外出派遣", "released": "已归灵",
              "missing": "不存在", "forgotten": "已遗忘"}[blocked]
    before = snapshot(game[1])
    assert reason in play("training").text()
    with pytest.raises(GameError, match=reason):
        play("training", "出手 普攻")
    assert snapshot(game[1]) == before
    if blocked == "sealed":
        play("pet_restore", "1")
    elif blocked == "trip":
        job = sql(game[1], "SELECT job_id FROM expeditions WHERE user_id='u1'")[0]["job_id"]
        play("expedition_cancel", str(job))
    else:
        assert "不退" in play("training", "退出").text()
        return
    assert "第2/5回合" in play("training", "出手 普攻").text()


def test_frozen_content_and_original_partner_survive_restart(game, play):
    prepare(play)
    reply = start(play)
    expected = next(line for line in reply.lines if line.startswith("普攻后："))
    play("summon")
    second = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>1")[0]["pet_id"]
    play("switch", str(second))
    content = replace(game[0].content, training_trials={},
                      training_rule=game[0].content.training_rule.model_copy(update={"win_bond": 1}))
    resumed = Game(game[1], Config(), content=content)
    reply = resumed.execute("u1", "training", "", "restart-view", NOW + 86400)
    assert expected in reply.lines
    for index, action in enumerate(("普攻", "普攻", "风刃术", "普攻", "普攻"), 1):
        reply = resumed.execute("u1", "training", "出手 " + action, f"restart-{index}", NOW + 86400 + index)
    assert "通过演练" in reply.text() and "羁绊经验+4" in reply.text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 4}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (f"bond_exp_{second}",))


def test_all_trials_have_a_publicly_playable_winning_route(game, play):
    for trial_index, trial in enumerate(game[0].content.training_trials.values()):
        now = NOW + trial_index * 86400
        if trial_index == 0:
            prepare(play)
        reply = play("training", "开始 " + trial.name, op=f"start-{trial_index}", now=now)
        saved = json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='training' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])
        plan = []

        def search(run, path):
            if run["status"] != "active" or len(path) == 5:
                if run["player"]["hp"] > 0 and run["enemy"]["hp"] <= 0:
                    plan.append(path)
                return
            for _, action in training._choices(run):
                next_run = json.loads(json.dumps(run))
                player, enemy, _ = training._exchange(next_run, action)
                next_run["history"].append({"action": action})
                next_run["player"] = training._pack(player)
                next_run["enemy"] = training._pack(enemy)
                if player.hp <= 0 or enemy.hp <= 0:
                    next_run["status"] = "over"
                search(next_run, path + (action,))

        search(saved, ())
        assert plan, trial.name
        for index, action in enumerate(plan[0], 1):
            reply = play("training", "出手 " + action, op=f"trial-{trial_index}-{index}", now=now + index)
            if reply.title == "连携演练结算":
                break
        assert "通过演练" in reply.text(), trial.name


@pytest.mark.parametrize("phase,source,method", [
    ("start", Repository, "record_training_action"),
    ("start", Repository, "consume_item"),
    ("start", Repository, "invalidate_pet_ready"),
    ("step", Repository, "record_training_action"),
    ("quit", Repository, "record_training_action"),
    ("finish", Repository, "record_training_action"),
    ("finish", training.mastery, "study"),
    ("finish", training.bond_levels, "add_exp"),
])
def test_write_fault_rolls_back_cost_growth_and_retry(game, play, monkeypatch, phase, source, method):
    prepare(play)
    if phase in ("step", "quit"):
        start(play)
    if phase == "finish":
        start(play)
        for index, action in enumerate(("普攻", "普攻", "普攻", "普攻"), 1):
            play("training", "出手 " + action, op=f"before-fault-{index}", now=NOW + index)
    before = snapshot(game[1])
    original = getattr(source, method)

    def broken(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("training persistence failure")

    monkeypatch.setattr(source, method, broken)
    argument = {"start": "开始 观势破阵", "quit": "退出"}.get(phase, "出手 风刃术")
    operation = "retry-training-" + phase
    with pytest.raises(RuntimeError, match="training persistence"):
        play("training", argument, op=operation, now=NOW + 5)
    assert snapshot(game[1]) == before
    monkeypatch.setattr(source, method, original)
    result = play("training", argument, op=operation, now=NOW + 5)
    assert result == play("training", argument, op=operation, now=NOW + 5)


def test_partner_without_skills_can_play_and_failed_run_only_grows_bond(game, play):
    play("adopt", "青鸾")
    reply = start(play)
    assert all(any(command.startswith(f"灵宠连携演练 出手 {action} ") for command in reply.commands)
               for action in ("普攻", "护持"))
    assert not any("施展" in link.label for link in reply.inline_commands)
    for index in range(1, 6):
        reply = play("training", "出手 护持", op=f"brace-{index}", now=NOW + index)
    assert "未通过演练" in reply.text()
    assert "羁绊经验+1" in reply.text()
    assert not sql(game[1], "SELECT * FROM learned_skills")


def test_same_operation_is_serialized_and_durable_replay_survives_cache_expiry(game, play):
    prepare(play)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: play("training", "开始 观势破阵", op="same-training-start"), range(2)))
    assert replies[0] == replies[1]
    assert pet(game[1])["energy"] == 88 and items(game[1])["spirit_food"] == 5
    with closing(game[1].connect()) as conn:
        conn.execute("DELETE FROM operations WHERE operation_id='same-training-start'")
    assert play("training", "开始 观势破阵", op="same-training-start") == replies[0]


def test_competing_distinct_openings_use_the_daily_slot_once(game, play):
    prepare(play)

    def attempt(operation):
        try:
            return play("training", "开始 观势破阵", op=operation)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("opening-a", "opening-b")))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    rejected = next(result for result in results if isinstance(result, GameError))
    assert "已有连携演练" in str(rejected) or "名额已用尽" in str(rejected)
    assert pet(game[1])["energy"] == 88 and items(game[1])["spirit_food"] == 5


def test_qq_and_onebot_keep_skill_links_separate_from_short_main_actions(game, play, monkeypatch):
    prepare(play)
    reply = start(play)
    commands = {command for _, command in _action_items(reply)}
    assert len(reply.commands) <= 4
    assert all("施展" not in label for label, _ in _action_items(reply))
    _, parts = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    body = parts["markdown"][0].data["markdown"].content
    links = {parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
    buttons = {button.action.data for segment in parts["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons}
    assert buttons == {"!" + command for command in commands}
    assert links == {"!" + link.command for link in reply.inline_commands}
    assert not links & buttons
    event = qq_event(user_id="training-qq", text="!灵宠连携演练 预览 观势破阵", message_id="training-entry")
    from nonebot_plugin_spirit_pet.adapters import handlers
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    assert handlers._parse(event.get_plaintext()) == ("training", "预览 观势破阵")
    monkeypatch.setattr(handlers, "game", game[0])
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    message = onebot_event("!灵宠连携演练 预览 观势破阵", 81)
    asyncio.run(handlers.handle_command(bot, message, message.get_message()))
    assert bot.send.await_count == 1
