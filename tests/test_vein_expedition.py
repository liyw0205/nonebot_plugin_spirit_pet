import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql

NOW = 1_800_000_000


def _prepare(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','spirit_food',10) "
        "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity")


def _run(game):
    row = sql(
        game[1],
        "SELECT snapshot FROM duel_actions WHERE user_id='u1' "
        "AND json_extract(snapshot,'$.kind')='vein_expedition' ORDER BY action_id DESC LIMIT 1",
    )[0]
    return json.loads(row["snapshot"])


def test_catalog_preview_and_three_stage_completion(game, play):
    _prepare(game, play)
    before = {
        "pet": pet(game[1])["energy"],
        "items": items(game[1]),
        "actions": sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions"),
    }
    preview = play("vein_expedition", "预览 青木灵脉", now=NOW)
    assert "三段节点" in preview.text() and "青木灵脉" in preview.text()
    assert pet(game[1])["energy"] == before["pet"] and items(game[1]) == before["items"]
    opened = play("vein_expedition", "开启 青木灵脉 伙伴 1", now=NOW, op="vein-start")
    run_id = _run(game)["run_id"]
    assert f"第 {run_id} 局" in opened.text()
    assert pet(game[1])["energy"] == before["pet"] - 10
    assert items(game[1])["spirit_food"] == 9
    play("vein_expedition", f"前进 {run_id} 采集", now=NOW, op="vein-1")
    play("vein_expedition", f"前进 {run_id} 护脉", now=NOW + 1, op="vein-2")
    final = play("vein_expedition", f"前进 {run_id} 绕行", now=NOW + 2, op="vein-3")
    assert final.title.endswith("完成")
    assert "护脉奖励" in final.text()
    assert _run(game)["status"] == "finished"
    assert items(game[1])["forge_ore"] >= 1
    assert pet(game[1])["energy"] == before["pet"] - 25
    assert play("vein_expedition", "记录", now=NOW + 3).title.startswith("灵宠灵脉记录")


def test_qq_native_and_onebot_share_the_same_vein_commands(game, play):
    _prepare(game, play)
    page = play("vein_expedition", now=NOW)
    segments, message = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    assert segments and handlers._parse("灵宠灵脉 开启 青木灵脉 伙伴 1") == (
        "vein_expedition", "开启 青木灵脉 伙伴 1",
    )
    buttons = {
        button.action.data
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert len(buttons) <= 4
    assert not buttons & {"!" + link.command for link in page.inline_commands}


def test_restart_old_step_and_abandon_keep_frozen_state(game, play):
    _prepare(game, play)
    opened = play("vein_expedition", "开启 青木灵脉 伙伴 1", now=NOW, op="restart-start")
    run_id = _run(game)["run_id"]
    step = play("vein_expedition", f"前进 {run_id} 绕行", now=NOW, op="restart-step")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    page = restarted.execute("u1", "vein_expedition", "", "restart-page", NOW + 86400)
    assert f"进度 1/3" in page.text() and "青木灵脉" in page.text()
    with pytest.raises(GameError, match="旧局号"):
        restarted.execute("u1", "vein_expedition", f"前进 {run_id + 1} 采集", "old-run", NOW + 86400)
    with pytest.raises(GameError, match="时间早于"):
        restarted.execute("u1", "vein_expedition", f"前进 {run_id} 采集", "clock-back", NOW - 1)
    abandoned = restarted.execute("u1", "vein_expedition", f"放弃 {run_id}", "restart-abandon", NOW + 86400)
    assert "不退" in abandoned.text()
    assert _run(game)["status"] == "abandoned"


def test_missing_frozen_reward_refuses_without_spending_or_finishing(game, play):
    _prepare(game, play)
    play("vein_expedition", "开启 青木灵脉 伙伴 1", now=NOW, op="bad-reward-open")
    run_id = _run(game)["run_id"]
    play("vein_expedition", f"前进 {run_id} 绕行", now=NOW, op="bad-reward-a")
    play("vein_expedition", f"前进 {run_id} 绕行", now=NOW, op="bad-reward-b")
    run = _run(game)
    run["reward"]["items"]["missing_material"] = {"minimum": 1, "maximum": 1}
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE action_id=("
        "SELECT MAX(action_id) FROM duel_actions WHERE user_id='u1' "
        "AND json_extract(snapshot,'$.kind')='vein_expedition')", (json.dumps(run, ensure_ascii=False),))
    before = (pet(game[1])["energy"], items(game[1]))
    with pytest.raises(GameError, match="不可用"):
        play("vein_expedition", f"前进 {run_id} 绕行", now=NOW, op="bad-reward-finish")
    assert (pet(game[1])["energy"], items(game[1])) == before
    assert _run(game)["status"] == "active"


def test_concurrent_open_only_one_and_operation_replay_is_idempotent(game, play):
    _prepare(game, play)

    def attempt(index):
        try:
            return play("vein_expedition", "开启 青木灵脉 伙伴 1", now=NOW, op=f"open-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    run_id = _run(game)["run_id"]
    first = play("vein_expedition", f"前进 {run_id} 采集", now=NOW, op="same-step")
    before = {"energy": pet(game[1])["energy"], "material": items(game[1]).get("forge_ore", 0)}
    sql(game[1], "DELETE FROM operations")
    replay = play("vein_expedition", f"前进 {run_id} 采集", now=NOW, op="same-step")
    assert replay == first
    assert pet(game[1])["energy"] == before["energy"]
    assert items(game[1]).get("forge_ore", 0) == before["material"]


@pytest.mark.parametrize("phase", ["start", "advance", "finish"])
def test_receipt_failure_rolls_back_entire_operation(game, play, monkeypatch, phase):
    _prepare(game, play)
    if phase == "start":
        argument, operation = "开启 青木灵脉 伙伴 1", "rollback-start"
    else:
        play("vein_expedition", "开启 青木灵脉 伙伴 1", now=NOW, op="rollback-open")
        run_id = _run(game)["run_id"]
        if phase == "advance":
            argument, operation = f"前进 {run_id} 采集", "rollback-advance"
        else:
            play("vein_expedition", f"前进 {run_id} 采集", now=NOW, op="rollback-a")
            play("vein_expedition", f"前进 {run_id} 绕行", now=NOW, op="rollback-b")
            argument, operation = f"前进 {run_id} 采集", "rollback-finish"
    original = Repository.record_vein_expedition_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    before = (pet(game[1])["energy"], items(game[1]), sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions"))
    monkeypatch.setattr(Repository, "record_vein_expedition_action", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        play("vein_expedition", argument, now=NOW, op=operation)
    assert (pet(game[1])["energy"], items(game[1]), sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions")) == before
