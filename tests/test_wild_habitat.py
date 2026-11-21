import asyncio
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import wild_habitat

from .support import items, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def _prepare(game, play, user):
    play("adopt", "青鸾", user=user, now=NOW)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id=?", (user,))
    sql(game[1], "UPDATE pets SET realm=6 WHERE user_id=?", (user,))


def _encounter(game, play, user, entry_index, day_index, route_id=None):
    week_start = wild_habitat.beijing_week(NOW)[0]
    route_event = wild_habitat._event_for_week(game[0].content, week_start)
    route_id = route_id or route_event.route
    route = game[0].content.exploration_routes[route_id]
    route_rules = next(row for row in game[0].content.wild_capture.routes if row.route == route_id)
    weights = [entry.weight for entry in route_rules.entries]
    roll = (sum(weights[:entry_index]) + weights[entry_index] / 2) / sum(weights)
    rolls = iter([roll, *([0.0] * 100)])
    game[0].rng.random = lambda: next(rolls, 0.0)
    game[0].rng.randint = lambda low, high: high
    now = NOW + day_index * 86_400
    reply = play("explore", f"{route.name} 野外", user=user, now=now,
                 op=f"habitat-run-{user}-{entry_index}-{day_index}")
    run = sql(game[1], "SELECT run_id,state FROM wild_capture_runs WHERE operation_id=?",
              (f"habitat-run-{user}-{entry_index}-{day_index}",))[0]
    if run["state"] == "pending":
        play("wild_capture", f"放归 {run['run_id']} 0", user=user, now=now + 1,
             op=f"habitat-release-{user}-{entry_index}-{day_index}")
    return route_event, reply


def _contribute_all_species(game, play, user):
    _prepare(game, play, user)
    event = wild_habitat._event_for_week(game[0].content, wild_habitat.beijing_week(NOW)[0])
    route = next(row for row in game[0].content.wild_capture.routes if row.route == event.route)
    assert len(route.entries) >= 3
    for index in range(3):
        _encounter(game, play, user, index, index)


def _edit_content(tmp_path, change):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "wild_habitat_events.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return target


def test_real_encounters_create_week_snapshot_and_unique_private_contributions(game, play):
    _prepare(game, play, "u1")
    event = wild_habitat._event_for_week(game[0].content, wild_habitat.beijing_week(NOW)[0])
    before_ops = sql(game[1], "SELECT COUNT(*) AS n FROM operations")[0]["n"]
    page = play("wild_habitat", op="habitat-read-only")
    assert event.name in page.text()
    assert "0/6 组" in page.text()
    assert not sql(game[1], "SELECT * FROM wild_habitat_weeks")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM operations")[0]["n"] == before_ops

    _encounter(game, play, "u1", 0, 0)
    _encounter(game, play, "u1", 0, 1)
    _prepare(game, play, "u2")
    _encounter(game, play, "u2", 0, 0)

    totals = play("wild_habitat", op="habitat-progress")
    assert "2/6 组" in totals.text()
    assert "参与修士 2 人" in totals.text()
    assert "你的首次物种贡献 1 种" in totals.text()
    assert "u1" not in totals.text() and "u2" not in totals.text()
    assert len(sql(game[1], "SELECT * FROM wild_habitat_contributions")) == 2
    assert len(sql(game[1], "SELECT * FROM wild_habitat_weeks")) == 1


def test_event_rules_are_frozen_for_the_week_and_old_activity_is_read_only(game, play):
    _prepare(game, play, "u1")
    week_start = wild_habitat.beijing_week(NOW)[0]
    event = wild_habitat._event_for_week(game[0].content, week_start)
    _encounter(game, play, "u1", 0, 0)
    original_name = event.name
    game[0].content.wild_habitat_events[event.id] = event.model_copy(update={
        "name": "临时栖地", "goal_pairs": 1,
    })
    _encounter(game, play, "u1", 1, 1)

    page = play("wild_habitat", "周 " + str(week_start), op="habitat-frozen-read")
    assert original_name in page.text()
    assert "临时栖地" not in page.text()
    assert "2/6 组" in page.text()
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='habitat-frozen-read'")


def test_non_target_route_freezes_week_without_earning_contribution(game, play):
    _prepare(game, play, "u1")
    start = wild_habitat.beijing_week(NOW)[0]
    event = wild_habitat._event_for_week(game[0].content, start)
    other_route = next(
        route for route in game[0].content.exploration_routes.values() if route.id != event.route
    )

    _encounter(game, play, "u1", 0, 0, route_id=other_route.id)
    week = sql(game[1], "SELECT event_id,route_id FROM wild_habitat_weeks WHERE week_start=?", (start,))
    assert [(row["event_id"], row["route_id"]) for row in week] == [(event.id, event.route)]
    assert not sql(game[1], "SELECT * FROM wild_habitat_contributions")

    _encounter(game, play, "u1", 0, 1, route_id=event.route)
    contributions = sql(game[1], "SELECT user_id,species_id FROM wild_habitat_contributions")
    assert len(contributions) == 1 and contributions[0]["user_id"] == "u1"


def test_nonparticipants_are_not_told_they_can_claim_unlocked_milestones(game, play):
    _prepare(game, play, "u1")
    _encounter(game, play, "u1", 0, 0)
    _prepare(game, play, "u2")

    page = play("today", user="u2", now=NOW)
    habitat_lines = [line for line in page.lines if "栖地共护" in line]
    assert habitat_lines
    assert all("可领" not in line for line in habitat_lines)


def test_participants_can_claim_frozen_milestones_once_in_following_week(game, play):
    _contribute_all_species(game, play, "u1")
    _contribute_all_species(game, play, "u2")
    event = wild_habitat._event_for_week(game[0].content, wild_habitat.beijing_week(NOW)[0])
    start = wild_habitat.beijing_week(NOW)[0]
    assert sql(game[1], "SELECT COUNT(*) AS n FROM wild_habitat_contributions")[0]["n"] == 6

    _prepare(game, play, "u3")
    with pytest.raises(GameError, match="参与者"):
        play("wild_habitat", f"领奖 {start} first_sign", user="u3", now=start + 7 * 86_400 + 10,
             op="habitat-nonparticipant")

    stones = player(game[1], "u1")["stones"]
    for tier in event.tiers:
        reply = play("wild_habitat", f"领奖 {start} {tier.id}", user="u1",
                     now=start + 7 * 86_400 + 10, op=f"habitat-claim-{tier.id}")
        assert "已领取" in reply.text()
    assert player(game[1], "u1")["stones"] == stones + 145
    receipt = sql(game[1], "SELECT reward_snapshot FROM wild_habitat_claims WHERE user_id='u1' ORDER BY tier_id")
    assert len(receipt) == 3
    replay = play("wild_habitat", f"领奖 {start} first_sign", user="u1",
                  now=start + 7 * 86_400 + 11, op="habitat-claim-first_sign")
    assert replay.title == "栖地共护奖励"
    assert player(game[1], "u1")["stones"] == stones + 145
    with pytest.raises(GameError, match="已经领取"):
        play("wild_habitat", f"领奖 {start} first_sign", user="u1",
             now=start + 7 * 86_400 + 12, op="habitat-claim-first-again")


def test_failed_claim_rolls_back_reward_receipt_and_operation_for_retry(game, play):
    _contribute_all_species(game, play, "u1")
    start = wild_habitat.beijing_week(NOW)[0]
    stones = player(game[1])["stones"]
    sql(game[1], "CREATE TRIGGER fail_habitat_claim BEFORE INSERT ON wild_habitat_claims "
       "BEGIN SELECT RAISE(ABORT, 'injected habitat claim failure'); END")
    with pytest.raises(Exception, match="injected habitat claim failure"):
        play("wild_habitat", f"领奖 {start} first_sign", now=start + 7 * 86_400 + 1,
             op="habitat-retry")
    assert player(game[1])["stones"] == stones
    assert not sql(game[1], "SELECT * FROM wild_habitat_claims")
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='habitat-retry'")
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='habitat-retry'")

    sql(game[1], "DROP TRIGGER fail_habitat_claim")
    reply = play("wild_habitat", f"领奖 {start} first_sign", now=start + 7 * 86_400 + 2,
                 op="habitat-retry")
    assert "已领取" in reply.text()
    assert player(game[1])["stones"] == stones + 20


def test_concurrent_claims_only_award_one_milestone(game, play):
    _prepare(game, play, "u1")
    _encounter(game, play, "u1", 0, 0)
    start = wild_habitat.beijing_week(NOW)[0]

    def claim(operation):
        try:
            return play("wild_habitat", f"领奖 {start} first_sign", now=start + 7 * 86_400 + 1,
                        op=operation)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("habitat-parallel-a", "habitat-parallel-b")))
    assert sum(result is not None for result in results) == 1
    assert player(game[1])["stones"] == 1020
    assert len(sql(game[1], "SELECT * FROM wild_habitat_claims")) == 1
    with pytest.raises(GameError, match="活动周及其后一个自然周"):
        play("wild_habitat", f"领奖 {start} first_sign", now=start + wild_habitat.CLAIM_SECONDS,
             op="habitat-expired-claim")


def test_history_page_rejects_oversized_numeric_input(game, play):
    with pytest.raises(GameError, match="历史页码必须是正整数"):
        play("wild_habitat", "历史 " + "9" * 5_000, op="habitat-large-page")


def test_history_is_paginated_and_does_not_write_operations(game, play):
    current = wild_habitat.beijing_week(NOW)[0]
    event = wild_habitat._event_for_week(game[0].content, current)
    snapshot = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    for offset in range(6):
        start = current - offset * wild_habitat.WEEK_SECONDS
        sql(game[1],
            "INSERT INTO wild_habitat_weeks(week_start,event_id,route_id,event_snapshot,opened_at) "
            "VALUES (?,?,?,?,?)",
            (start, event.id, event.route, snapshot, start),
        )
    before = sql(game[1], "SELECT COUNT(*) AS n FROM operations")[0]["n"]

    first = play("wild_habitat", "历史", user="u1", now=NOW, op="habitat-history-one")
    second = play("wild_habitat", "历史 2", user="u1", now=NOW, op="habitat-history-two")

    assert "共 6 周活动记录 · 第 1/2 页" in first.text()
    assert "共 6 周活动记录 · 第 2/2 页" in second.text()
    assert sum(link.label == "查看本周" for link in first.inline_commands) == 5
    assert sum(link.label == "查看本周" for link in second.inline_commands) == 1
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id LIKE 'habitat-history-%'")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM operations")[0]["n"] == before


@pytest.mark.parametrize("change,error", [
    (lambda data: data[0].update(route="missing_route"), "unknown wild route"),
    (lambda data: data[0]["tiers"][1].update(contribution_pairs=1), "milestones must increase"),
    (lambda data: data[0].update(goal_pairs=7), "goal must equal its final milestone"),
    (lambda data: data[0]["tiers"][0].update(reward={"stones": 0, "items": {}}), "empty reward"),
    (lambda data: data[0]["tiers"][0].update(
        reward={"stones": 10, "items": {"egg_qingluan": 1}},
    ), "must be consumable or material"),
])
def test_catalog_rejects_invalid_habitat_rotation(tmp_path, change, error):
    content = _edit_content(tmp_path, change)
    with pytest.raises(ValueError, match=error):
        Catalog.load(content)


def test_catalog_rejects_invalid_habitat_fields(tmp_path):
    content = _edit_content(tmp_path, lambda data: data[0]["tiers"][0].update(contribution_pairs=0))
    with pytest.raises(ValidationError):
        Catalog.load(content)


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_habitat_command_uses_shared_adapter_handler(game, play, monkeypatch, adapter):
    _prepare(game, play, "12345")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    text = "!灵宠栖地共护"
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    message = bot.send.call_args.args[1]
    assert "共护进度 0/6" in str(message)


def test_habitat_navigation_and_native_controls_are_bounded(game, play):
    replies = [play("wild_habitat"), play("explore"), play("wild_capture")]
    config = Config(spirit_pet_qq_mode="native")
    for reply in replies:
        _, message = _qq_segments(reply, config)
        buttons = [button.action.data.removeprefix("/")
                   for segment in message if segment.type == "keyboard"
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        if reply.title.startswith("栖地共护 ·"):
            assert len(reply.commands) <= 4
        assert len(reply.commands) == len(set(reply.commands))
        assert len(buttons) <= 4
        assert len(buttons) == len(set(buttons))
        assert not set(buttons) & {link.command for link in reply.inline_commands}
        assert all(handlers._parse(command) is not None
                   for command in (*reply.commands, *(link.command for link in reply.inline_commands)))
