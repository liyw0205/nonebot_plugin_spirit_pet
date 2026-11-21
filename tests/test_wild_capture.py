import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import wild_capture

from .support import items, pet, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def prepare(game, play, *, user="u1", now=NOW, stones=1000):
    play("adopt", "青鸾", user=user, now=now)
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (stones, user))
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,'spirit_snare',10)", (user,))


def start(game, play, *, route="灵泉修行", now=NOW, op="wild-start"):
    game[0].rng.random = lambda: 0.0
    game[0].rng.randint = lambda low, high: high
    return play("explore", f"{route} 野外", now=now, op=op)


def run_row(game):
    return sql(game[1], "SELECT * FROM wild_capture_runs WHERE user_id='u1'")[0]


def test_route_catalog_exposes_wild_encounter_without_changing_normal_exploration(game, play):
    prepare(game, play)
    catalog = play("explore")
    assert any(link.command == "灵宠历练 灵泉修行 野外 伙伴 1" for link in catalog.inline_commands)
    assert play("explore", "灵泉修行", op="normal-explore").title == "山海历练 · 灵泉修行"
    assert not sql(game[1], "SELECT * FROM wild_capture_runs")


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_wild_route_command_uses_shared_qq_and_onebot_handler(game, play, monkeypatch, adapter):
    prepare(game, play, user="12345")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    text = "!灵宠历练 灵泉修行 野外"
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())

    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    first = bot.send.call_args.args[1]
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))

    assert bot.send.call_args.args[1] == first
    assert len(sql(game[1], "SELECT * FROM wild_capture_runs WHERE user_id='12345'")) == 1
    assert len(sql(game[1], "SELECT * FROM battle_records WHERE battle_key='wild_spirit_spring'")) == 1
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='12345'")[0]["energy"] == 75


@pytest.mark.parametrize("mode", ["native", "template"])
def test_wild_route_and_pending_views_have_resolvable_nonduplicated_actions(game, play, mode):
    prepare(game, play)
    replies = [play("explore")]
    start(game, play)
    replies.extend((play("wild_capture"), play("wild_capture", "图鉴"), play("wild_capture", "战历")))
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_template_id="test.wild")

    for reply in replies:
        _, message = _qq_segments(reply, config)
        keyboards = [segment for segment in message if segment.type == "keyboard"]
        buttons = [button.action.data.removeprefix("/")
                   for segment in keyboards
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert len(buttons) <= 4
        assert len(buttons) == len(set(buttons))
        assert all(handlers._parse(command) is not None for command in buttons)
        assert not {button for button in buttons} & {link.command for link in reply.inline_commands}
        for link in reply.inline_commands:
            assert handlers._parse(link.command) is not None
        if mode == "native":
            markdown = message["markdown"][0].data["markdown"].content
            urls = re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)
            commands = {parse_qs(urlparse(url).query)["command"][0].removeprefix("/") for url in urls}
            assert commands == {link.command for link in reply.inline_commands}


def test_real_route_battle_persists_pending_capture_snapshot_and_read_only_pages(game, play):
    prepare(game, play)
    reply = start(game, play)
    run = run_row(game)

    assert reply.title == "野外遭遇战胜"
    assert run["state"] == "pending"
    assert run["species_id"] == "sanlinglu"
    assert run["rarity"] == "common"
    assert run["enemy_id"] == "wood_guard"
    assert run["expires_at"] == NOW + game[0].content.wild_capture.capture_window_seconds
    assert run["attempt_count"] == 0
    assert pet(game[1])["energy"] == 75
    assert player(game[1])["last_explore"] == NOW
    assert sql(game[1], "SELECT kind,battle_key,winner_side FROM battle_records") == [
        {"kind": "pve", "battle_key": "wild_spirit_spring", "winner_side": 0},
    ]
    snapshot = sql(game[1], "SELECT enemy_snapshot FROM wild_capture_runs")[0]["enemy_snapshot"]
    assert '"enemy_stats":{"hp":85,"attack":17,"defense":5,"speed":12}' in snapshot

    before_operations = sql(game[1], "SELECT COUNT(*) AS count FROM operations")[0]["count"]
    codex = play("wild_capture", "图鉴", op="codex-read")
    history = play("wild_capture", "战历", op="history-read")
    assert "未收服" in codex.text()
    assert "待收服" in history.text()
    assert sql(game[1], "SELECT COUNT(*) AS count FROM operations")[0]["count"] == before_operations


def test_capture_failures_consume_one_item_and_last_attempt_guarantees_a_real_pet(game, play):
    prepare(game, play)
    start(game, play)
    original_active = sql(game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot")
    game[0].rng.random = lambda: 0.99

    first = play("wild_capture", "尝试 1 1", op="catch-1")
    assert first.title == "野外收服未成"
    assert items(game[1])["spirit_snare"] == 9
    assert run_row(game)["attempt_count"] == 1
    assert play("wild_capture", "尝试 1 1", op="catch-1") == first
    with pytest.raises(GameError, match="次数已变化"):
        play("wild_capture", "尝试 1 1", op="stale-catch-1")
    assert items(game[1])["spirit_snare"] == 9
    assert len(sql(game[1], "SELECT * FROM wild_capture_attempts")) == 1

    play("wild_capture", "尝试 1 2", op="catch-2")
    result = play("wild_capture", "尝试 1 3", op="catch-3")
    assert result.title == "野外收服成功"
    assert "出战阵容未更改" in result.text()
    assert items(game[1])["spirit_snare"] == 7
    assert run_row(game)["state"] == "captured"
    assert run_row(game)["attempt_count"] == 3
    assert sql(game[1], "SELECT succeeded,roll FROM wild_capture_attempts ORDER BY attempt_no") == [
        {"succeeded": 0, "roll": 0.99}, {"succeeded": 0, "roll": 0.99},
        {"succeeded": 1, "roll": 0.99},
    ]
    assert len(sql(game[1], "SELECT * FROM pets WHERE user_id='u1'")) == 2
    assert sql(game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot") == original_active
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='wild_capture_codex'") == [
        {"progress": 1},
    ]
    assert "已收服" in play("wild_capture", "图鉴").text()
    assert "图鉴 1/" in play("objectives").text()

    captured_pet_id = int(sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"])
    play("lineup", str(captured_pet_id), op="lineup-captured-pet")
    play("challenge", "forest", now=NOW + 901, op="captured-pet-pve")
    record = sql(game[1], "SELECT snapshot FROM battle_records WHERE battle_key='forest'")[0]
    snapshot = json.loads(record["snapshot"])
    assert snapshot["teams"][0]["members"][0]["pet_name"] == "三灵鹿"
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (captured_pet_id,))[0]["energy"] == 80


def test_missing_capture_item_keeps_the_pending_encounter_unchanged(game, play):
    prepare(game, play)
    start(game, play)
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1' AND item_id='spirit_snare'")

    with pytest.raises(GameError, match="缺少缚灵索"):
        play("wild_capture", "尝试 1 1", op="missing-snare")

    assert run_row(game)["attempt_count"] == 0
    assert run_row(game)["state"] == "pending"
    assert not sql(game[1], "SELECT * FROM wild_capture_attempts")
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='missing-snare'")


def test_explicit_release_and_expiration_are_terminal_and_never_consume_capture_item(game, play):
    prepare(game, play)
    start(game, play)
    released = play("wild_capture", "放归 1 0", op="release-1")
    assert released.title == "野外灵宠已放归"
    assert run_row(game)["state"] == "released"
    assert items(game[1])["spirit_snare"] == 10

    start(game, play, now=NOW + 900, op="wild-start-2")
    expiry = run_row(game)["expires_at"]
    page = play("wild_capture", now=expiry, op="expire-page")
    assert "今日野外遭遇：2/2" in page.text()
    assert sql(game[1], "SELECT state,terminal_reason,finished_at FROM wild_capture_runs WHERE run_id=2") == [
        {"state": "escaped", "terminal_reason": "expired", "finished_at": expiry},
    ]
    with pytest.raises(GameError, match="时间早于"):
        play("wild_capture", now=NOW + 901, op="clock-rollback-view")
    assert run_row(game)["state"] == "escaped"
    with pytest.raises(GameError, match="已经结束"):
        play("wild_capture", "尝试 2 1", now=NOW + 902)
    assert items(game[1])["spirit_snare"] == 10


def test_daily_limit_resets_on_beijing_day_but_clock_rollback_is_rejected(game, play):
    prepare(game, play)
    start(game, play, op="day-one-1")
    play("wild_capture", "放归 1 0", op="release-day-one")
    start(game, play, now=NOW + 900, op="day-one-2")
    play("wild_capture", "放归 2 0", now=NOW + 901, op="release-day-one-2")
    with pytest.raises(GameError, match="次数已用完"):
        start(game, play, now=NOW + 1800, op="day-one-3")
    with pytest.raises(GameError, match="时间早于"):
        play("wild_capture", now=NOW - 1, op="clock-rollback")

    next_day = NOW + 86_400
    result = start(game, play, now=next_day, op="day-two-1")
    assert result.title == "野外遭遇战胜"
    assert run_row(game)["day_key"] != sql(
        game[1], "SELECT day_key FROM wild_capture_runs WHERE run_id=1",
    )[0]["day_key"]


def test_clock_rollback_after_terminal_release_is_rejected(game, play):
    prepare(game, play)
    start(game, play)
    play("wild_capture", "放归 1 0", now=NOW + 900, op="late-release")

    with pytest.raises(GameError, match="时间早于"):
        play("wild_capture", now=NOW + 899, op="rollback-after-release")


def test_encounter_keeps_capture_rule_and_species_snapshots_after_content_changes(game, play):
    prepare(game, play)
    start(game, play)
    stored = run_row(game)
    original = game[0].content
    updated_rules = original.wild_capture.model_copy(update={
        "capture_item": "bloodline_essence",
        "capture_attempts": 1,
        "same_species_limit": 1,
        "capture_rates": {"common": 0.01, "uncommon": 0.01, "rare": 0.01},
    })
    game[0].content = replace(original, wild_capture=updated_rules)
    old_species = original.species["sanlinglu"]
    game[0].content.species["sanlinglu"] = old_species.model_copy(update={"initial_affinity": 99})
    game[0].rng.random = lambda: 0.99

    first = play("wild_capture", "尝试 1 1", op="frozen-attempt-1")
    assert first.title == "野外收服未成"
    game[0].rng.random = lambda: 0.5
    result = play("wild_capture", "尝试 1 2", op="frozen-attempt-2")

    assert result.title == "野外收服成功"
    assert items(game[1])["spirit_snare"] == 8
    assert items(game[1]).get("bloodline_essence", 0) == 0
    assert pet(game[1])["affinity"] == 0
    assert stored["capture_rate"] == 0.8
    assert stored["max_attempts"] == 3
    assert stored["same_species_limit"] == 3
    assert sql(game[1], "SELECT item_id,catch_rate FROM wild_capture_attempts ORDER BY attempt_no") == [
        {"item_id": "spirit_snare", "catch_rate": 0.8},
        {"item_id": "spirit_snare", "catch_rate": 0.8},
    ]


def test_same_species_limit_releases_when_archiving_and_then_captures(game, play):
    prepare(game, play)
    start(game, play)
    game[0].rng.random = lambda: 0.0
    play("wild_capture", "尝试 1 1", op="first-sanlinglu")
    assert len(sql(game[1], "SELECT * FROM pets WHERE species_id='sanlinglu' AND archived=0")) == 1

    original = game[0].content
    game[0].content = replace(
        original,
        wild_capture=original.wild_capture.model_copy(update={"same_species_limit": 1}),
    )
    start(game, play, now=NOW + 900, op="second-sanlinglu")
    game[0].rng.random = lambda: 0.0
    with pytest.raises(GameError, match="同种上限 1"):
        play("wild_capture", "尝试 2 1", now=NOW + 900, op="same-species-at-cap")
    assert items(game[1])["spirit_snare"] == 9
    assert run_row(game)["attempt_count"] == 0

    play("pet_archive", "2", now=NOW + 900)
    result = play("wild_capture", "尝试 2 1", now=NOW + 900, op="same-species-at-cap")
    assert result.title == "野外收服成功"
    assert len(sql(game[1], "SELECT * FROM pets WHERE species_id='sanlinglu' AND archived=0")) == 1
    assert len(sql(game[1], "SELECT * FROM pets WHERE species_id='sanlinglu' AND archived=1")) == 1


def test_rare_pity_forces_a_rare_entry_after_the_configured_misses(game, play):
    prepare(game, play)
    original = game[0].content
    game[0].content = replace(
        original,
        wild_capture=original.wild_capture.model_copy(update={"rare_pity": 2}),
    )
    start(game, play, op="pity-common")
    assert run_row(game)["rarity"] == "common"
    play("wild_capture", "放归 1 0", op="pity-release")
    start(game, play, now=NOW + 900, op="pity-rare")
    assert run_row(game)["rarity"] == "rare"


@pytest.mark.parametrize(("winner", "reason"), [(1, "battle_lost"), (-1, "battle_draw")])
def test_defeat_and_draw_close_the_encounter_with_distinct_terminal_reasons(
    game, play, monkeypatch, winner, reason,
):
    from nonebot_plugin_spirit_pet.gameplay.combat import Battle

    prepare(game, play)
    monkeypatch.setattr(
        wild_capture, "fight", lambda *_args, **_kwargs: Battle(winner, 1, ("战斗结束。",), ({}, {})),
    )
    result = start(game, play, op=f"failed-battle-{reason}")
    assert result.title == "野外遭遇结束"
    assert run_row(game)["state"] == "escaped"
    assert run_row(game)["terminal_reason"] == reason
    assert items(game[1])["spirit_snare"] == 10


def test_capture_supply_is_repeatable_only_through_the_daily_limited_shop(game, play):
    prepare(game, play, stones=10_000)
    with pytest.raises(GameError, match="未找到"):
        play("shop", "缚灵索")
    with pytest.raises(GameError, match="仅在限量特供"):
        play("buy", "缚灵索 1")

    first_day = None
    for day in range(30):
        timestamp = NOW + day * 86_400
        page = play("daily_shop", now=timestamp)
        if any(line.startswith("缚灵索 ·") for line in page.lines):
            first_day = timestamp
            break
    assert first_day is not None
    first = play("daily_shop", "缚灵索 2", now=first_day)
    assert "缚灵索 +2" in first.text()
    with pytest.raises(GameError, match="已售罄"):
        play("daily_shop", "缚灵索 1", now=first_day)

    second_day = None
    for day in range(1, 15):
        timestamp = first_day + day * 86_400
        page = play("daily_shop", now=timestamp)
        if any(line.startswith("缚灵索 ·") for line in page.lines):
            second_day = timestamp
            break
    assert second_day is not None
    second = play("daily_shop", "缚灵索 1", now=second_day)
    assert "缚灵索 +1" in second.text()
    assert items(game[1])["spirit_snare"] == 13


def test_roster_full_does_not_consume_item_and_can_resume_after_organizing_roster(game, play):
    prepare(game, play)
    game[0].config.spirit_pet_max_pets = 2
    start(game, play)
    game[0].rng.random = lambda: 0.5
    summoned = play("summon", "1", op="second-pet")
    second_pet_id = sql(game[1], "SELECT MAX(pet_id) AS id FROM pets")[0]["id"]
    assert "编号" in summoned.text()
    play("lineup", f"1 {second_pet_id}")
    game[0].config.spirit_pet_max_pets = 2
    game[0].rng.random = lambda: 0.0

    with pytest.raises(GameError, match="在册名额已满"):
        play("wild_capture", "尝试 1 1", op="catch-at-cap")
    assert items(game[1])["spirit_snare"] == 10
    assert run_row(game)["attempt_count"] == 0

    play("lineup", str(second_pet_id))
    play("pet_archive", "1")
    result = play("wild_capture", "尝试 1 1", op="catch-after-archive")
    assert result.title == "野外收服成功"
    assert sql(game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1'") == [
        {"pet_id": second_pet_id},
    ]


def test_attempt_failure_injection_rolls_back_item_pet_journal_and_goal(game, play):
    prepare(game, play)
    start(game, play)
    game[0].rng.random = lambda: 0.0
    sql(game[1], "CREATE TRIGGER fail_wild_attempt BEFORE INSERT ON wild_capture_attempts "
                "BEGIN SELECT RAISE(ABORT,'injected wild attempt failure'); END")

    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="injected wild attempt failure"):
        play("wild_capture", "尝试 1 1", op="wild-attempt-rollback")

    assert items(game[1])["spirit_snare"] == 10
    assert len(sql(game[1], "SELECT * FROM pets WHERE user_id='u1'")) == 1
    assert run_row(game)["state"] == "pending"
    assert run_row(game)["attempt_count"] == 0
    assert not sql(game[1], "SELECT * FROM wild_capture_attempts")
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='wild-attempt-rollback'")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='wild_capture_codex'")


def test_encounter_failure_injection_rolls_back_energy_battle_and_run(game, play):
    prepare(game, play)
    sql(game[1], "CREATE TRIGGER fail_wild_run BEFORE INSERT ON wild_capture_runs "
                "BEGIN SELECT RAISE(ABORT,'injected wild run failure'); END")

    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="injected wild run failure"):
        start(game, play, op="wild-run-rollback")

    assert pet(game[1])["energy"] == 100
    assert player(game[1])["last_explore"] is None
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert not sql(game[1], "SELECT * FROM wild_capture_runs")
    assert not sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='wild-run-rollback'")


def test_concurrent_route_actions_allow_only_one_pending_run_and_idempotent_attempt(game, play):
    prepare(game, play)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda op: _call_wild_start(play, op), ("parallel-wild-a", "parallel-wild-b"),
        ))
    assert sum(result == "started" for result in results) == 1
    assert sum(result == "pending" for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM wild_capture_runs")) == 1
    assert pet(game[1])["energy"] == 75

    run_id = run_row(game)["run_id"]
    game[0].rng.random = lambda: 0.99
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(
            lambda _: play("wild_capture", f"尝试 {run_id} 1", op="parallel-catch"), range(2),
        ))
    assert replies[0] == replies[1]
    assert len(sql(game[1], "SELECT * FROM wild_capture_attempts")) == 1
    assert items(game[1])["spirit_snare"] == 9


def _call_wild_start(play, operation_id):
    try:
        play("explore", "灵泉修行 野外", op=operation_id)
        return "started"
    except GameError as exc:
        assert "待处理" in str(exc)
        return "pending"
