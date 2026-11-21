import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import wild_capture

from .support import items, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def prepare(game, play, *, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id=?", (user,))
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,'spirit_snare',20)", (user,))


def start_encounter(game, play, route, choice_roll, *, now, op, user="u1"):
    rolls = iter([choice_roll, *([0.0] * 100)])
    game[0].rng.random = lambda: next(rolls, 0.0)
    game[0].rng.randint = lambda low, high: high
    return play("explore", f"{route} 野外", user=user, now=now, op=op)


def close_if_pending(game, play, run_id, *, now, op):
    row = sql(game[1], "SELECT state FROM wild_capture_runs WHERE run_id=?", (run_id,))[0]
    if row["state"] == "pending":
        play("wild_capture", f"放归 {run_id} 0", now=now, op=op)


def test_survey_progress_uses_real_encounters_and_fixed_idempotent_rewards(game, play):
    prepare(game, play)
    before_runs = sql(game[1], "SELECT COUNT(*) AS count FROM wild_capture_runs")[0]["count"]
    before_operations = sql(game[1], "SELECT COUNT(*) AS count FROM operations")[0]["count"]
    overview = play("wild_capture", "调查", op="survey-view")
    route_page = play("wild_capture", "调查 灵泉修行", op="survey-route-view")
    next_page = play("wild_capture", "调查 2", op="survey-page-view")
    assert "灵泉栖地" in overview.text()
    assert "[未见] 三灵鹿" in route_page.text()
    assert next_page.title.endswith("2/2")
    assert sql(game[1], "SELECT COUNT(*) AS count FROM wild_capture_runs")[0]["count"] == before_runs
    assert sql(game[1], "SELECT COUNT(*) AS count FROM operations")[0]["count"] == before_operations

    start_encounter(game, play, "灵泉修行", 0.0, now=NOW, op="survey-common")
    close_if_pending(game, play, 1, now=NOW + 1, op="survey-release-common")
    after_common = play("wild_capture", "调查 灵泉修行", op="survey-common-view")
    assert "[已见] 三灵鹿 · 常见" in after_common.text()
    assert "[未见] 灵汐獭" in after_common.text()
    assert "可领取" in after_common.text()

    stones_before = player(game[1])["stones"]
    food_before = items(game[1]).get("spirit_food", 0)
    first = play("wild_capture", "调查领奖 灵泉修行 first_trace", op="survey-first-claim")
    assert "已领取" in first.text()
    assert player(game[1])["stones"] == stones_before + 20
    assert items(game[1])["spirit_food"] == food_before + 1
    receipt = sql(game[1], "SELECT reward_snapshot,reply FROM wild_survey_claims WHERE tier_id='first_trace'")[0]
    assert json.loads(receipt["reward_snapshot"]) == {"stones": 20, "items": {"spirit_food": 1}}
    assert play("wild_capture", "调查领奖 灵泉修行 first_trace", op="survey-first-claim") == first
    assert player(game[1])["stones"] == stones_before + 20
    with pytest.raises(GameError, match="已经领取"):
        play("wild_capture", "调查领奖 灵泉修行 first_trace", op="survey-first-claim-again")

    start_encounter(game, play, "灵泉修行", 0.6, now=NOW + 901, op="survey-uncommon")
    close_if_pending(game, play, 2, now=NOW + 902, op="survey-release-uncommon")
    start_encounter(game, play, "灵泉修行", 0.9, now=NOW + 86_400, op="survey-rare")
    close_if_pending(game, play, 3, now=NOW + 86_401, op="survey-release-rare")
    detail = play("wild_capture", "调查 灵泉修行", op="survey-detail-complete")
    assert "已观察 3/3 种" in detail.text()
    assert "稀有发现：常见、少见、稀有" in detail.text()
    assert all(label in detail.text() for label in ("[已见] 三灵鹿", "[已见] 灵汐獭", "[已见] 雪影狐"))
    assert "rare_trace" in detail.text()

    stones_before = player(game[1])["stones"]
    play("wild_capture", "调查领奖 灵泉修行 mixed_tracks", op="survey-mixed-claim")
    play("wild_capture", "调查领奖 灵泉修行 rare_trace", op="survey-rare-claim")
    assert player(game[1])["stones"] == stones_before + 95
    assert len(sql(game[1], "SELECT * FROM wild_survey_claims WHERE route_id='spirit_spring'")) == 3


def test_repeated_species_counts_once_and_routes_cannot_borrow_evidence(game, play):
    prepare(game, play)
    start_encounter(game, play, "灵泉修行", 0.0, now=NOW, op="survey-repeat-one")
    close_if_pending(game, play, 1, now=NOW + 1, op="survey-repeat-release-one")
    start_encounter(game, play, "灵泉修行", 0.0, now=NOW + 901, op="survey-repeat-two")
    close_if_pending(game, play, 2, now=NOW + 902, op="survey-repeat-release-two")

    detail = play("wild_capture", "调查 灵泉修行", op="survey-repeat-view")
    assert "已观察 1/3 种" in detail.text()
    assert detail.text().count("[已见] 三灵鹿") == 1
    assert "[未见] 灵汐獭" in detail.text()
    with pytest.raises(GameError, match="尚未达到"):
        play("wild_capture", "调查领奖 灵泉修行 mixed_tracks", op="survey-repeat-unearned")

    with pytest.raises(GameError, match="尚未达到"):
        play("wild_capture", "调查领奖 星谷采集 first_trace", op="survey-cross-route-denied")
    sql(game[1], "UPDATE pets SET realm=1 WHERE user_id='u1'")
    start_encounter(game, play, "星谷采集", 0.0, now=NOW + 86_400 + 1_802, op="survey-other-route")
    close_if_pending(game, play, 3, now=NOW + 86_400 + 1_803, op="survey-other-route-release")
    route_detail = play("wild_capture", "调查 星谷采集", op="survey-other-route-view")
    assert "已观察 1/3 种" in route_detail.text()
    assert "[已见] 寒翎鹰" in route_detail.text()
    assert "[未见] 三灵鹿" not in route_detail.text()

    reward_before = player(game[1])["stones"]
    play("wild_capture", "调查领奖 星谷采集 first_trace", op="survey-other-route-claim")
    assert player(game[1])["stones"] == reward_before + 20
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='survey-cross-route-denied'")


def test_lost_battle_observation_is_private_to_player_and_route(game, play, monkeypatch):
    from nonebot_plugin_spirit_pet.gameplay.combat import Battle

    prepare(game, play, user="u1")
    prepare(game, play, user="u2")
    sql(game[1], "UPDATE pets SET realm=1 WHERE user_id IN ('u1','u2')")
    monkeypatch.setattr(
        wild_capture, "fight", lambda *_args, **_kwargs: Battle(1, 1, ("遭遇战败。",), ({}, {})),
    )
    start_encounter(game, play, "星谷采集", 0.0, now=NOW, op="survey-u1-lost")
    start_encounter(game, play, "星谷采集", 0.9, now=NOW + 900, op="survey-u2-lost", user="u2")
    assert sql(game[1], "SELECT state FROM wild_capture_runs WHERE user_id='u1'")[0]["state"] == "escaped"
    assert sql(game[1], "SELECT state FROM wild_capture_runs WHERE user_id='u2'")[0]["state"] == "escaped"

    u1 = play("wild_capture", "调查 星谷采集", user="u1", op="survey-u1-private")
    u2 = play("wild_capture", "调查 星谷采集", user="u2", op="survey-u2-private")
    assert "[已见] 寒翎鹰 · 常见" in u1.text()
    assert "[未见] 金羽隼" in u1.text()
    assert "[已见] 金羽隼 · 稀有" in u2.text()
    assert "[未见] 寒翎鹰" in u2.text()
    assert not sql(game[1], "SELECT * FROM wild_capture_runs WHERE user_id='u1' AND route_id='starfall_valley' AND species_id='jinyu'")


def test_claim_failure_rolls_back_reward_receipt_and_can_be_retried(game, play):
    import sqlite3

    prepare(game, play)
    start_encounter(game, play, "灵泉修行", 0.0, now=NOW, op="survey-rollback-source")
    stones_before = player(game[1])["stones"]
    food_before = items(game[1]).get("spirit_food", 0)
    sql(game[1], "CREATE TRIGGER fail_survey_claim BEFORE INSERT ON wild_survey_claims "
                 "BEGIN SELECT RAISE(ABORT,'injected survey claim failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected survey claim failure"):
        play("wild_capture", "调查领奖 灵泉修行 first_trace", op="survey-rollback-claim")
    assert player(game[1])["stones"] == stones_before
    assert items(game[1]).get("spirit_food", 0) == food_before
    assert not sql(game[1], "SELECT * FROM wild_survey_claims")
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='survey-rollback-claim'")
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='survey-rollback-claim'")

    sql(game[1], "DROP TRIGGER fail_survey_claim")
    reply = play("wild_capture", "调查领奖 灵泉修行 first_trace", op="survey-rollback-claim")
    assert "已领取" in reply.text()
    assert player(game[1])["stones"] == stones_before + 20


def test_same_tier_concurrent_claims_award_once(game, play):
    prepare(game, play)
    start_encounter(game, play, "灵泉修行", 0.0, now=NOW, op="survey-concurrent-source")

    def claim(operation):
        try:
            return play("wild_capture", "调查领奖 灵泉修行 first_trace", op=operation)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("survey-parallel-a", "survey-parallel-b")))
    assert sum(result is not None for result in results) == 1
    assert player(game[1])["stones"] == 1020
    assert len(sql(game[1], "SELECT * FROM wild_survey_claims WHERE route_id='spirit_spring' AND tier_id='first_trace'")) == 1


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_survey_command_uses_shared_adapter_handler(game, play, monkeypatch, adapter):
    prepare(game, play, user="12345")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    text = "!灵宠野外 调查"
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())

    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    message = bot.send.call_args.args[1]
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert bot.send.call_args.args[1] == message
    assert "灵泉栖地" in str(message)
    assert not sql(game[1], "SELECT * FROM wild_capture_runs WHERE user_id='12345'")


def test_survey_routes_and_details_have_distinct_bounded_qq_actions(game, play):
    prepare(game, play)
    replies = [play("explore"), play("wild_capture", "调查"), play("wild_capture", "调查 灵泉修行")]
    replies.append(play("today"))
    replies.append(play("objectives"))
    config = Config(spirit_pet_qq_mode="native")
    for reply in replies:
        _, message = _qq_segments(reply, config)
        keyboards = [segment for segment in message if segment.type == "keyboard"]
        buttons = [button.action.data.removeprefix("/")
                   for segment in keyboards
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        if reply.title.startswith("灵宠野外") or reply.title.startswith("灵泉栖地"):
            assert len(reply.commands) <= 4
        assert len(reply.commands) == len(set(reply.commands))
        assert len(buttons) <= 4
        assert len(buttons) == len(set(buttons))
        assert not set(buttons) & {link.command for link in reply.inline_commands}
        assert all(len(link.label) <= 12 for link in reply.inline_commands)
        assert all(handlers._parse(command) is not None for command in (*reply.commands, *(link.command for link in reply.inline_commands)))
