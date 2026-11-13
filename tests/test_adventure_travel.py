import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000


def _command(reply, action):
    return next(command for command in reply.commands if action in command)


def _run(game):
    row = sql(
        game[1],
        "SELECT snapshot FROM duel_actions WHERE user_id='u1' "
        "AND json_extract(snapshot,'$.kind')='adventure_travel' ORDER BY action_id DESC LIMIT 1",
    )[0]
    row["snapshot"] = json.loads(row["snapshot"])
    return row


def _snapshot(game):
    return {
        table: sql(game[1], f"SELECT * FROM {table} ORDER BY rowid")
        for table in ("players", "pets", "inventory", "quest_progress", "adventure_discoveries", "duel_actions")
    }


def test_full_command_chain_survives_restart_and_keeps_original_partner(game, play):
    play("adopt", "青鸾", now=NOW)
    start = play("adventure_travel", "启程 灵泉修行", now=NOW, op="travel-start")
    saved = _run(game)
    assert "支付精力 75" in start.text()
    assert saved["snapshot"]
    assert pet(game[1])["energy"] == 25

    first = _command(start, "选择 局")
    original_exp = pet(game[1])["exp"]
    first_reply = play(*handlers._parse(first), now=NOW, op="travel-step-1")
    assert "已行 1/3 处" in first_reply.text()
    assert pet(game[1])["exp"] > original_exp
    assert sql(game[1], "SELECT encounter_id FROM adventure_discoveries") == [{"encounter_id": "spring"}]

    play("summon", now=NOW + 1, op="summon-second")
    second = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id <> 1")[0]["pet_id"]
    play("switch", str(second), now=NOW + 2, op="switch-second")
    original_exp_after_first = sql(game[1], "SELECT exp FROM pets WHERE pet_id=1")[0]["exp"]
    before_second_pet = pet(game[1])["exp"]

    # Cached operation replay after the ordinary message cache is removed is still read-only.
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    assert restarted.execute("u1", "adventure_travel", "选择 局 " + _run(game)["snapshot"]["run_id"] + " 段 2 取水", "travel-step-1", NOW + 86400) == first_reply
    before_page = _snapshot(game)
    page = restarted.execute("u1", "adventure_travel", "", "travel-view", NOW + 86400)
    assert "已行 1/3 处" in page.text()
    assert _snapshot(game) == before_page
    assert pet(game[1])["exp"] == before_second_pet

    # The next settlement uses the frozen pet, even though the active pet changed.
    second_command = _command(page, "选择 局")
    second_reply = restarted.execute("u1", "adventure_travel", handlers._parse(second_command)[1], "travel-step-2", NOW + 86400)
    assert "已行 2/3 处" in second_reply.text()
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=1")[0]["exp"] > original_exp_after_first
    assert pet(game[1])["exp"] == before_second_pet

    for index, reply in enumerate((second_reply,), 3):
        command = _command(reply, "选择 局")
        restarted.execute("u1", "adventure_travel", handlers._parse(command)[1], f"travel-step-{index}", NOW + 86400)
    final = restarted.execute("u1", "adventure_travel", "记录", "travel-record", NOW + 86400)
    assert "已完成" in final.text()
    assert _run(game)["snapshot"]["status"] == "finished"
    assert sql(game[1], "SELECT COUNT(*) AS count FROM quest_progress WHERE quest_id LIKE 'echo_%'") == [{"count": 3}]


def test_preview_continue_and_echo_page_are_read_only_and_mutually_exclusive(game, play):
    play("adopt", "青鸾", now=NOW)
    before = _snapshot(game)
    preview = play("adventure_travel", "预览 灵泉修行", now=NOW)
    assert "启程需 75" in preview.text()
    assert _snapshot(game) == before

    start = play("adventure_travel", "启程 灵泉修行", now=NOW, op="travel-start")
    running_before_preview = _snapshot(game)
    assert "已有行程进行中" in play("adventure_travel", "预览 灵泉修行", now=NOW + 1).text()
    assert _snapshot(game) == running_before_preview
    first = _command(start, "选择 局")
    chosen_id = handlers._parse(first)[1].rsplit(" ", 1)[-1]
    chosen = next(option.label for option in game[0].content.encounters["spring"].options if option.id == chosen_id)
    play("adventure_travel", handlers._parse(first)[1], now=NOW, op="travel-step-1")
    echoes = play("echoes", now=NOW + 1)
    assert f"灵泉寻踪 · {chosen} · 已回响（{chosen}）" in echoes.text()
    with pytest.raises(GameError, match="已回响"):
        play("echo_choose", "灵泉寻踪 静坐", now=NOW + 1)
    assert _snapshot(game) != before


def test_settlement_failure_rolls_back_and_same_step_is_not_double_paid(game, play):
    play("adopt", "青鸾", now=NOW)
    start = play("adventure_travel", "启程 灵泉修行", now=NOW, op="travel-start")
    command = _command(start, "选择 局")
    before = _snapshot(game)
    with game[1].connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_travel_reward BEFORE INSERT ON inventory "
            "WHEN NEW.item_id='spirit_food' BEGIN SELECT RAISE(ABORT,'injected travel failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected travel failure"):
        play("adventure_travel", handlers._parse(command)[1], now=NOW, op="travel-step-1")
    assert _snapshot(game) == before
    with game[1].connect() as conn:
        conn.execute("DROP TRIGGER fail_travel_reward")
    result = play("adventure_travel", handlers._parse(command)[1], now=NOW, op="travel-step-1")
    assert result == play("adventure_travel", handlers._parse(command)[1], now=NOW, op="travel-step-1")
    assert sql(game[1], "SELECT COUNT(*) AS count FROM adventure_discoveries") == [{"count": 1}]


def test_concurrent_same_step_commits_once(game, play):
    play("adopt", "青鸾", now=NOW)
    start = play("adventure_travel", "启程 灵泉修行", now=NOW, op="travel-start")
    command = _command(start, "选择 局")
    argument = handlers._parse(command)[1]

    def execute(index):
        try:
            return play("adventure_travel", argument, now=NOW, op=f"travel-concurrent-{index}")
        except GameError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (1, 2)))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS count FROM adventure_discoveries") == [{"count": 1}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='echo_spring'") == [{"progress": 1}]


def test_old_step_and_clock_rollback_are_read_only(game, play):
    play("adopt", "青鸾", now=NOW)
    start = play("adventure_travel", "启程 灵泉修行", now=NOW, op="travel-start")
    first = _command(start, "选择 局")
    play("adventure_travel", handlers._parse(first)[1], now=NOW + 100, op="travel-step-1")
    before = _snapshot(game)
    assert "时间早于" in play("adventure_travel", "", now=NOW).text()
    with pytest.raises(GameError, match="已经处理"):
        play("adventure_travel", handlers._parse(first)[1], now=NOW + 100, op="stale-step")
    assert _snapshot(game) == before
