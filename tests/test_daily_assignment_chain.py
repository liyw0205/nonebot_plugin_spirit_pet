"""End-to-end tests for the optional seven-day daily-assignment chain."""

from concurrent.futures import ThreadPoolExecutor
import json
import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import daily_assignment, daily_assignment_chain
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, player_uid, sql

NOW = 1_800_000_000
DAY = 86_400


def ctx(game, now=NOW, user="u1"):
    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config,
        game[0].rng, user, now, f"chain-read-{now}-{user}",
    )


def _pet_id(game, user="u1"):
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))[0]["pet_id"]


def _fund(game, amount=5000):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (amount,))


def _seed_metric(game, assignment, now, user="u1"):
    """Seed the same durable records that the metric readers consume."""
    metric = assignment.metric
    target = assignment.target
    if metric == "daily_discovery":
        for index in range(target):
            sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
                (user, f"chain-{now}-{index}", now))
    elif metric == "daily_training":
        sql(game[1], "UPDATE players SET last_train=? WHERE user_id=?", (now, user))
    elif metric == "daily_claim":
        for index in range(target):
            sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, reward_snapshot, reply) "
                "VALUES (?, ?, ?, ?, '{}', '{}')", (user, f"chain-ach-{now}-{index}", f"chain-op-{now}-{index}", now))
    elif metric == "daily_expedition":
        pet_id = _pet_id(game, user)
        for index in range(target):
            start = now - 3600 - index
            sql(game[1], "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, started_at, finishes_at, state, reward_snapshot, settled_at, slot) "
                "VALUES (?, ?, ?, '课题委托', ?, ?, ?, 'claimed', '{}', ?, ?)",
                (user, pet_id, f"chain-task-{now}-{index}", f"chain-exp-{now}-{index}", start, now, now, index % 2))
    elif metric == "daily_pve":
        pet_id = _pet_id(game, user)
        for index in range(target):
            operation = f"chain-pve-{now}-{index}"
            battle_id = sql(game[1], "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side, rounds, played_at, reply, snapshot, battle_log) "
                "VALUES (?, ?, 'pve', 'chain', '课题', 0, 1, ?, '{}', '{}', '[]') RETURNING battle_id",
                (operation, user, now))[0]["battle_id"]
            sql(game[1], "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?, ?, 0, 'participant')",
                (battle_id, user))
    else:
        # The PVP seed needs two real identities and a season row.
        play = game[0].execute
        play("u2", "adopt", "玄狐", f"chain-adopt-{now}", now)
        season = beijing_week(now)[0]
        sql(game[1], "INSERT OR IGNORE INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) VALUES (?, ?, ?, ?, '{}')",
            (season, now - 30 * DAY, now + 30 * DAY, now))
        for index in range(target):
            sql(game[1], "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, winner_id, day, played_at, delta, operation_id, reply) "
                "VALUES (?, ?, 'u2', ?, ?, ?, ?, ?, 1, ?, '{}')",
                (season, user, _pet_id(game, user), _pet_id(game, "u2"), user, beijing_day(now), now, f"chain-pvp-{now}-{index}"))


def _assignment(game, now):
    return daily_assignment.todays(ctx(game, now))[0]


def _make_ready(game, now):
    assignment = _assignment(game, now)
    _seed_metric(game, assignment, now)
    return assignment


def test_preview_and_open_are_persistent_and_read_only_before_adoption(game, play):
    preview = play("daily_assignment_chain", user="ghost")
    assert "尚未结契" in preview.text()
    assert sql(game[1], "SELECT * FROM players") == []
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    before = player(game[1])["stones"]
    opened = play("daily_assignment_chain", "开启", now=NOW, op="chain-open")
    assert opened.title == daily_assignment_chain.TITLE
    assert player(game[1])["stones"] == before - daily_assignment_chain.DEPOSIT
    assert daily_assignment_chain.active(ctx(game)) == {"start": daily_assignment_chain.day_ordinal(NOW), "count": 0, "last": daily_assignment_chain.day_ordinal(NOW) - 1}
    assert "押金 300 灵石已托管" in opened.text()
    with pytest.raises(GameError, match="已有进行中的"):
        play("daily_assignment_chain", "开启", now=NOW, op="chain-open-again")


def test_daily_claim_advances_the_chain_and_replay_is_idempotent(game, play):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    play("daily_assignment_chain", "开启", now=NOW, op="chain-start")
    assignment = _make_ready(game, NOW)
    first = play("daily_assignment_claim", assignment.name, now=NOW, op="chain-day-1")
    assert "课题连章第 1/7 日完成" in first.text()
    assert play("daily_assignment_claim", assignment.name, now=NOW, op="chain-day-1").text() == first.text()
    state = daily_assignment_chain.active(ctx(game))
    assert state["count"] == 1 and state["last"] == daily_assignment_chain.day_ordinal(NOW)
    assert len(sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'assignment_chain_day_%'")) == 1


def test_restart_keeps_the_active_run_and_its_next_day(game, play):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    play("daily_assignment_chain", "开启", now=NOW, op="chain-restart-start")
    first = _make_ready(game, NOW)
    play("daily_assignment_claim", first.name, now=NOW, op="chain-restart-day-1")
    restarted = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    state = restarted.execute("u1", "daily_assignment_chain", "", "chain-restart-page", NOW + DAY)
    assert "进行中：第 1/7 日" in state.text()
    second = _assignment(game, NOW + DAY)
    _seed_metric(game, second, NOW + DAY)
    reply = restarted.execute("u1", "daily_assignment_claim", second.name, "chain-restart-day-2", NOW + DAY)
    assert "课题连章第 2/7 日完成" in reply.text()


def test_seven_real_days_refund_deposit_and_pay_final_reward_once(game, play):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    initial = player(game[1])["stones"]
    daily_stones = 0
    play("daily_assignment_chain", "开启", now=NOW, op="chain-seven-start")
    for index in range(daily_assignment_chain.DAYS):
        stamp = NOW + index * DAY
        assignment = _make_ready(game, stamp)
        daily_stones += assignment.reward.stones.minimum
        reply = play("daily_assignment_claim", assignment.name, now=stamp, op=f"chain-seven-{index}")
        if index < daily_assignment_chain.DAYS - 1:
            assert f"第 {index + 1}/7 日完成" in reply.text()
        else:
            assert "七日连章完成" in reply.text()
    assert daily_assignment_chain.active(ctx(game, NOW + 6 * DAY)) is None
    assert player(game[1])["stones"] == initial - daily_assignment_chain.DEPOSIT + daily_stones + daily_assignment_chain.DEPOSIT + daily_assignment_chain.FINAL_STONES
    result = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id LIKE 'assignment_chain_result_%'")
    assert result == [{"progress": daily_assignment_chain.COMPLETE * 100 + 7}]
    assert items(game[1])["spirit_food"] >= daily_assignment_chain.FINAL_ITEMS["spirit_food"]
    history = play("daily_assignment_chain", "记录", now=NOW + 6 * DAY)
    assert "完成 · 连续 7/7 日 · 押金退回" in history.text()


def test_gap_marks_failure_without_touching_the_new_daily_reward(game, play):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    before = player(game[1])["stones"]
    play("daily_assignment_chain", "开启", now=NOW, op="chain-gap-start")
    first = _make_ready(game, NOW)
    play("daily_assignment_claim", first.name, now=NOW, op="chain-gap-first")
    later = NOW + 2 * DAY
    second = _make_ready(game, later)
    reply = play("daily_assignment_claim", second.name, now=later, op="chain-gap-second")
    assert "因漏过" in reply.text() and "本次课题仍正常领取" in reply.text()
    assert daily_assignment_chain.active(ctx(game, later)) is None
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id LIKE 'assignment_chain_result_%'") == [
        {"progress": daily_assignment_chain.FAILED * 100 + 1}
    ]
    assert player(game[1])["stones"] > before - daily_assignment_chain.DEPOSIT
    assert "断档失败" in play("daily_assignment_chain", "记录", now=later).text()


def test_clock_rollback_and_abandon_are_safe(game, play):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    play("daily_assignment_chain", "开启", now=NOW, op="chain-clock-start")
    _make_ready(game, NOW)
    play("daily_assignment_claim", _assignment(game, NOW).name, now=NOW, op="chain-clock-day")
    snapshot = (
        player(game[1])["stones"],
        sql(game[1], "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id"),
    )
    old_assignment = _make_ready(game, NOW - DAY)
    with pytest.raises(GameError, match="日期早于"):
        play("daily_assignment_claim", old_assignment.name, now=NOW - DAY, op="chain-clock-old")
    assert (player(game[1])["stones"], sql(game[1], "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id")) == snapshot
    abandoned = play("daily_assignment_chain", "放弃", now=NOW + 1, op="chain-abandon")
    assert "押金 300 灵石不退" in abandoned.text()
    assert daily_assignment_chain.active(ctx(game, NOW + 1)) is None


def test_concurrent_open_and_final_reward_failure_roll_back(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    service = game[0]
    def open_once(op):
        try:
            return service.execute("u1", "daily_assignment_chain", "开启", op, NOW)
        except GameError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_once, ("chain-concurrent-a", "chain-concurrent-b")))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    for index in range(daily_assignment_chain.DAYS - 1):
        stamp = NOW + index * DAY
        assignment = _make_ready(game, stamp)
        play("daily_assignment_claim", assignment.name, now=stamp, op=f"chain-pre-final-{index}")
    stamp = NOW + (daily_assignment_chain.DAYS - 1) * DAY
    assignment = _make_ready(game, stamp)
    original = Repository.add_item
    calls = {"count": 0}
    def fail_on_final_item(repo, user_id, item_id, amount):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise RuntimeError("injected final reward failure")
        return original(repo, user_id, item_id, amount)
    monkeypatch.setattr(Repository, "add_item", fail_on_final_item)
    with pytest.raises(RuntimeError, match="injected"):
        play("daily_assignment_claim", assignment.name, now=stamp, op="chain-final-rollback")
    monkeypatch.setattr(Repository, "add_item", original)
    assert daily_assignment_chain.active(ctx(game, stamp))["count"] == 6
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'assignment_chain_result_%'") == []
    retry = play("daily_assignment_claim", assignment.name, now=stamp, op="chain-final-retry")
    assert "七日连章完成" in retry.text()


def test_help_objectives_today_native_and_onebot_share_the_entry(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    _fund(game)
    assert handlers._parse("灵宠课题连章 开启") == ("daily_assignment_chain", "开启")
    guide = play("help", "秘境与关卡", now=NOW)
    assert "灵宠课题连章 开启" in guide.text()
    assert "课题连章：未开启" in play("objectives", now=NOW).text()
    play("daily_assignment_chain", "开启", now=NOW, op="chain-message-start")
    today = play("today", now=NOW)
    assert "课题连章第 1/7 日" in today.text()
    page = play("daily_assignment_chain", now=NOW)
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = native["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    assert handlers._parse("!灵宠课题连章") == ("daily_assignment_chain", "")
