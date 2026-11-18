import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql

NOW = 1_800_000_000


def _prepare(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','spirit_food',10) "
        "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity")


def _run(game):
    row = sql(game[1], "SELECT snapshot FROM duel_actions WHERE user_id='u1' "
        "AND json_extract(snapshot,'$.kind')='ruin_expedition' ORDER BY action_id DESC LIMIT 1")[0]
    return json.loads(row["snapshot"])


def test_catalog_and_three_hall_risk_completion(game, play):
    _prepare(game, play)
    before = pet(game[1])["energy"]
    page = play("ruin_expedition", now=NOW)
    assert "月门遗迹" in page.text() and "三厅" in page.text()
    preview = play("ruin_expedition", "预览 月门遗迹", now=NOW)
    assert "基础宝藏" in preview.text() and "富集宝藏" in preview.text()
    opened = play("ruin_expedition", "开启 月门遗迹 伙伴 1", now=NOW, op="ruin-open")
    run_id = _run(game)["run_id"]
    assert f"第 {run_id} 局" in opened.text()
    play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW, op="ruin-a")
    play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW + 1, op="ruin-b")
    final = play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW + 2, op="ruin-c")
    assert final.title.endswith("完成") and "富集宝藏" in final.text()
    assert _run(game)["status"] == "finished" and _run(game)["risk"] == 6
    assert pet(game[1])["energy"] == before - 27
    assert play("ruin_expedition", "记录", now=NOW + 3).title.startswith("灵宠遗迹记录")


def test_safe_choice_and_restart_preserve_frozen_state(game, play):
    _prepare(game, play)
    play("ruin_expedition", "开启 月门遗迹 伙伴 1", now=NOW, op="safe-open")
    run_id = _run(game)["run_id"]
    play("ruin_expedition", f"前进 {run_id} 稳行", now=NOW, op="safe-step")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    page = restarted.execute("u1", "ruin_expedition", "", "safe-page", NOW + 86400)
    assert "进度 1/3" in page.text() and "月门遗迹" in page.text()
    with pytest.raises(GameError, match="旧局号"):
        restarted.execute("u1", "ruin_expedition", f"前进 {run_id + 1} 取宝", "safe-old", NOW + 86400)
    with pytest.raises(GameError, match="时间早于"):
        restarted.execute("u1", "ruin_expedition", f"前进 {run_id} 取宝", "safe-clock", NOW - 1)


def test_abandon_keeps_hall_treasure_without_final_reward(game, play):
    _prepare(game, play)
    play("ruin_expedition", "开启 月门遗迹 伙伴 1", now=NOW, op="abandon-open")
    run_id = _run(game)["run_id"]
    play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW, op="abandon-step")
    before = items(game[1]).get("forge_ore", 0)
    reply = play("ruin_expedition", f"放弃 {run_id}", now=NOW + 1, op="abandon")
    assert "不退" in reply.text() and items(game[1])["forge_ore"] == before
    assert _run(game)["status"] == "abandoned" and "final_reward" not in _run(game)


def test_operation_replay_and_receipt_failure_roll_back(game, play, monkeypatch):
    _prepare(game, play)
    play("ruin_expedition", "开启 月门遗迹 伙伴 1", now=NOW, op="replay-open")
    run_id = _run(game)["run_id"]
    first = play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW, op="same-ruin-step")
    before = (pet(game[1])["energy"], items(game[1]))
    sql(game[1], "DELETE FROM operations")
    replay = play("ruin_expedition", f"前进 {run_id} 取宝", now=NOW, op="same-ruin-step")
    assert replay == first and (pet(game[1])["energy"], items(game[1])) == before

    original = Repository.record_ruin_expedition_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    monkeypatch.setattr(Repository, "record_ruin_expedition_action", fail)
    before = (pet(game[1])["energy"], items(game[1]), sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions"))
    with pytest.raises(RuntimeError, match="receipt failure"):
        play("ruin_expedition", f"前进 {run_id} 稳行", now=NOW + 1, op="ruin-rollback")
    assert (pet(game[1])["energy"], items(game[1]), sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions")) == before


def test_shared_entry_points_and_surfaces(game, play):
    _prepare(game, play)
    page = play("ruin_expedition", now=NOW)
    segments, message = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    assert segments and handlers._parse("灵宠遗迹 开启 月门遗迹 伙伴 1") == (
        "ruin_expedition", "开启 月门遗迹 伙伴 1",
    )
    buttons = {button.action.data for segment in message["keyboard"] for row in segment.data["keyboard"].content.rows for button in row.buttons}
    assert len(buttons) <= 4 and not buttons & {"!" + link.command for link in page.inline_commands}
    assert "遗迹探秘" in play("objectives", now=NOW).text()
    assert "灵宠遗迹" in play("help", "秘境与关卡", now=NOW).text()
