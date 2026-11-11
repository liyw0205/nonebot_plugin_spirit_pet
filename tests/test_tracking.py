import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.tracking_content import TrackingMap
from nonebot_plugin_spirit_pet.gameplay import tracking
from nonebot_plugin_spirit_pet.gameplay.help import help_link
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .conftest import FixedRandom
from .support import items, pet, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
DAY = 86400


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "player_identity", "pets", "active_pet_slots", "inventory",
        "quest_progress", "duel_actions", "team_members", "battle_records",
    )}


def last_run(store):
    rows = sql(store, "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='tracking' ORDER BY action_id DESC LIMIT 1")
    return json.loads(rows[0]["snapshot"])


def survey(play, **kwargs):
    reply = play("tracking", "勘察 1", **kwargs)
    if reply.title.endswith("勘察"):
        reply = play("tracking", "勘察 4", **kwargs)
    assert reply.title.endswith("挖掘")
    return reply


class TargetRandom(FixedRandom):
    def __init__(self, target):
        self.target = target

    def randint(self, start, stop):
        return self.target if (start, stop) == (1, 16) else start


@pytest.mark.parametrize("map_id", ["bamboo", "ruins", "orchard"])
@pytest.mark.parametrize("target", range(1, 17))
def test_every_map_and_target_can_be_deduced_and_grows_original_pet(game, play, map_id, target):
    play("adopt", "青鸾")
    game[0].rng = TargetRandom(target)
    original = pet(game[1])
    before_items, before_stones = items(game[1]), player(game[1])["stones"]
    start = play("tracking", f"出发 {map_id}")
    assert "候选地点" in start.text() and len(tracking.candidates(last_run(game[1]))) == 8
    assert pet(game[1])["energy"] == original["energy"] - 8
    survey(play)
    assert tracking.candidates(last_run(game[1])) == [target]
    final = play("tracking", f"挖掘 {target}", op="found")
    assert "寻获藏物！" in final.text()
    assert items(game[1])["spirit_food"] == before_items.get("spirit_food", 0) + 1
    assert player(game[1])["stones"] == before_stones
    after = pet(game[1])
    assert after["affinity"] == min(100, original["affinity"] + 2)
    assert after["energy"] == original["energy"] - 8
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 8}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?", (f"tracking_found_{map_id}",)) == [{"progress": 1}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='tracking_pet_completed_1'") == [{"progress": 1}]
    assert not sql(game[1], "SELECT * FROM battle_records")
    before = snapshot(game[1])
    assert play("tracking", "记录").lines == final.lines
    assert not play("tracking", "记录").inline_commands
    assert play("tracking", f"挖掘 {target}", op="found") == final
    assert snapshot(game[1]) == before


def test_unregistered_entry_record_and_start_preserve_uid_adoption(game, play):
    before = snapshot(game[1])
    entry = play("tracking")
    assert entry.inline_commands[0].command == "灵宠领养 "
    assert "还没有" in play("tracking", "记录").text()
    with pytest.raises(GameError) as error:
        play("tracking", "出发 竹溪旧径")
    assert error.value.reply.inline_commands[0].command == "灵宠领养 "
    assert snapshot(game[1]) == before
    adopted = play("adopt", "青鸾")
    assert "10000" in adopted.text()


def test_entry_help_objectives_and_paged_actions_are_read_only(game, play):
    play("adopt", "青鸾")
    assert handlers._parse("灵宠寻踪 勘察 3") == ("tracking", "勘察 3")
    assert any(link.command == "灵宠寻踪" for link in play("objectives").inline_commands)
    guide = play("help", "血脉与道具")
    assert any(help_link(line) == ("灵宠寻踪", "灵宠寻踪") for line in guide.lines)
    before = snapshot(game[1])
    assert len(play("tracking").commands) == 3
    assert snapshot(game[1]) == before
    play("tracking", "出发 bamboo")
    before = snapshot(game[1])
    commands = []
    for page in range(1, 5):
        reply = play("tracking", f"地图 {page}", now=NOW + DAY)
        commands.extend(reply.commands)
        assert len(reply.commands) == 4
        assert "第" in reply.text()
    assert {int(command.split()[2]) for command in commands} == set(range(1, 17))
    assert snapshot(game[1]) == before


def test_poor_surveys_leave_real_choice_and_failure_only_gives_small_bond_growth(game, play):
    play("adopt", "青鸾")
    original = pet(game[1])
    before_items = items(game[1])
    play("tracking", "出发 bamboo")
    play("tracking", "勘察 4")
    play("tracking", "勘察 13")
    assert tracking.candidates(last_run(game[1])) == [1, 16]
    reply = play("tracking", "挖掘 16")
    assert "未寻获藏物" in reply.text() and "藏物在 1 号" in reply.text()
    assert items(game[1]) == before_items
    assert pet(game[1])["affinity"] == original["affinity"]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 2}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'tracking_found_*'")


@pytest.mark.parametrize("argument", ["出发", "出发 不存在", "地图 0", "地图 5", "勘察 0", "勘察 17", "勘察 -1", "勘察 １", "挖掘 x", "挖掘 99999999999999999999", "勘察 1 2 3", "记录 1", "放弃 x", "未知"])
def test_bad_arguments_refuse_without_writes(game, play, argument):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("tracking", argument)
    assert snapshot(game[1]) == before


def test_early_dig_repeated_survey_excluded_dig_and_excess_surveys_refuse(game, play):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="先勘察"):
        play("tracking", "挖掘 1")
    assert snapshot(game[1]) == before
    play("tracking", "勘察 4")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经勘察"):
        play("tracking", "勘察 4")
    assert snapshot(game[1]) == before
    play("tracking", "勘察 13")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="勘察已结束"):
        play("tracking", "勘察 2")
    with pytest.raises(GameError, match="已被线索排除"):
        play("tracking", "挖掘 2")
    assert snapshot(game[1]) == before


def test_start_daily_limit_abandon_clock_rollback_and_cross_day_continuation(game, play):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已有一局"):
        play("tracking", "出发 ruins")
    with pytest.raises(GameError, match="时间早于"):
        play("tracking", "放弃", now=NOW - 1)
    assert snapshot(game[1]) == before
    abandoned = play("tracking", "放弃")
    assert "不退还" in abandoned.text()
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="今天已出发"):
        play("tracking", "出发 ruins")
    assert snapshot(game[1]) == before
    play("tracking", "出发 ruins", now=NOW + DAY)
    before_energy = pet(game[1])["energy"]
    survey(play, now=NOW + DAY * 2)
    play("tracking", "挖掘 1", now=NOW + DAY * 2)
    assert pet(game[1])["energy"] == before_energy
    play("tracking", "出发 orchard", now=NOW + DAY * 2)
    assert last_run(game[1])["map"]["id"] == "orchard"


def test_old_buttons_cannot_act_on_next_day_run(game, play):
    play("adopt", "青鸾")
    first = play("tracking", "出发 bamboo")
    old_command = first.commands[0]
    old_abandon = next(link.command for link in first.inline_commands if link.label == "放弃本局")
    play("tracking", "放弃")
    play("tracking", "出发 ruins", now=NOW + DAY)
    before = snapshot(game[1])
    for command in (old_command, old_abandon):
        action, arg = handlers._parse(command)
        with pytest.raises(GameError, match="旧局"):
            play(action, arg, now=NOW + DAY)
    assert snapshot(game[1]) == before


def test_frozen_map_and_target_survive_content_changes_and_record_skips_active_run(game, play):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    original = last_run(game[1])["map"]
    game[0].content = replace(game[0].content, tracking_maps={})
    survey(play)
    result = play("tracking", "挖掘 1")
    assert "新笋" in result.text() and last_run(game[1])["map"] == original
    game[0].content = replace(game[0].content, tracking_maps={"bamboo": TrackingMap.model_validate(original)})
    play("tracking", "出发 bamboo", now=NOW + DAY)
    before = snapshot(game[1])
    assert play("tracking", "记录").lines == result.lines
    assert snapshot(game[1]) == before


def test_original_partner_grows_after_switch_and_food_can_be_used(game, play):
    play("adopt", "青鸾")
    play("summon", "1")
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','bond_exp_1',45,0)")
    play("tracking", "出发 bamboo")
    play("switch", "2")
    other = pet(game[1])
    survey(play)
    reply = play("tracking", "挖掘 1")
    assert "等级 1 → 2" in reply.text()
    assert pet(game[1])["affinity"] == other["affinity"]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 53}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_2'")
    play("switch", "1")
    original = pet(game[1])
    play("use", "灵粮 1")
    assert pet(game[1])["energy"] >= original["energy"]
    assert pet(game[1])["affinity"] > original["affinity"]


@pytest.mark.parametrize("blocked", ["archived", "expedition"])
def test_original_partner_blocking_is_recoverable_without_losing_run(game, play, blocked):
    play("adopt", "青鸾")
    play("summon", "1")
    play("tracking", "出发 bamboo")
    if blocked == "archived":
        play("switch", "2")
        play("pet_archive", "1")
    else:
        play("expedition_start", "采灵药")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="封存|派遣"):
        play("tracking", "勘察 1")
    assert not play("tracking").commands
    assert snapshot(game[1]) == before
    if blocked == "archived":
        play("pet_restore", "1")
    else:
        expedition = sql(game[1], "SELECT job_id FROM expeditions WHERE state='running'")[0]
        play("expedition_cancel", str(expedition["job_id"]))
    survey(play)
    assert "寻获藏物" in play("tracking", "挖掘 1").text()


@pytest.mark.parametrize("blocked", ["energy", "archived", "no_pet", "expedition"])
def test_start_refusals_preserve_resources_quota_and_readiness(game, play, blocked):
    play("adopt", "青鸾")
    if blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0")
    elif blocked == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    elif blocked == "no_pet":
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
        sql(game[1], "DELETE FROM active_pet_slots")
    else:
        play("expedition_start", "采灵药")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("tracking", "出发 bamboo")
    assert not play("tracking").commands
    assert snapshot(game[1]) == before


def test_expired_cache_and_restart_replay_every_step_and_check_operation_owner(game, play):
    play("adopt", "青鸾")
    receipts = [("出发 bamboo", "start-replay", play("tracking", "出发 bamboo", op="start-replay"))]
    receipts.append(("勘察 1", "survey-replay", play("tracking", "勘察 1", op="survey-replay")))
    receipts.append(("挖掘 1", "dig-replay", play("tracking", "挖掘 1", op="dig-replay")))
    sql(game[1], "DELETE FROM operations")
    restarted_store = Store(game[1].path)
    restarted_store.initialize()
    restarted = Game(restarted_store, Config(), FixedRandom())
    before = snapshot(game[1])
    for arg, op, saved in receipts:
        assert restarted.execute("u1", "tracking", arg, op, NOW + DAY * 10) == saved
        assert restarted.execute("u1", "help", "", op, NOW + DAY * 10) == saved
        with pytest.raises(GameError, match="different user"):
            restarted.execute("other", "tracking", arg, op, NOW + DAY * 10)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("phase", ["start", "survey", "finish", "abandon"])
def test_receipt_failure_rolls_back_entire_action_and_can_retry(game, play, monkeypatch, phase):
    play("adopt", "青鸾")
    arg = "出发 bamboo"
    if phase != "start":
        play("tracking", arg)
        arg = "勘察 1" if phase == "survey" else "放弃"
        if phase == "finish":
            survey(play)
            arg = "挖掘 1"
    before = snapshot(game[1])
    original = Repository.record_tracking_action

    def fail(*args, **kwargs):
        raise RuntimeError("tracking receipt write failed")

    monkeypatch.setattr(Repository, "record_tracking_action", fail)
    with pytest.raises(RuntimeError, match="tracking receipt write failed"):
        play("tracking", arg, op="retry-tracking")
    assert snapshot(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='retry-tracking'")
    monkeypatch.setattr(Repository, "record_tracking_action", original)
    play("tracking", arg, op="retry-tracking")


def test_missing_reward_preserves_excavation_for_retry(game, play):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    survey(play)
    original = game[0].content
    game[0].content = replace(original, items={key: value for key, value in original.items.items() if key != "spirit_food"})
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵粮暂不可用"):
        play("tracking", "挖掘 1", op="missing-food")
    assert snapshot(game[1]) == before
    game[0].content = original
    assert "寻获藏物" in play("tracking", "挖掘 1", op="missing-food").text()


def test_item_write_failure_rolls_back_bond_and_preserves_final_action(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("tracking", "出发 bamboo")
    survey(play)
    before = snapshot(game[1])
    original = Repository.add_item

    def fail(*args, **kwargs):
        raise RuntimeError("tracking inventory write failed")

    monkeypatch.setattr(Repository, "add_item", fail)
    with pytest.raises(RuntimeError, match="tracking inventory write failed"):
        play("tracking", "挖掘 1", op="retry-item")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(Repository, "add_item", original)
    assert "寻获藏物" in play("tracking", "挖掘 1", op="retry-item").text()


def test_affinity_cap_reply_reports_only_actual_growth(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET affinity=99")
    play("tracking", "出发 bamboo")
    survey(play)
    reply = play("tracking", "挖掘 1")
    assert "亲密 +1（100/100）" in reply.text()
    assert pet(game[1])["affinity"] == 100


def test_concurrent_start_and_final_settlement_each_succeed_once(game, play):
    play("adopt", "青鸾")

    def parallel(arg):
        def run(index):
            try:
                return Game(game[1], Config(), FixedRandom()).execute("u1", "tracking", arg, f"parallel-{arg}-{index}", NOW).title
            except GameError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    assert parallel("出发 bamboo").count("灵宠寻踪 · 勘察") == 1
    survey(play)
    before = items(game[1]).get("spirit_food", 0)
    assert parallel("挖掘 1").count("寻踪结算") == 1
    assert items(game[1])["spirit_food"] == before + 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='tracking_pet_completed_1'") == [{"progress": 1}]


def test_active_run_restart_and_old_receipts_cannot_change_a_new_run(game, play):
    play("adopt", "青鸾")
    first = play("tracking", "出发 bamboo", op="old-start")
    play("tracking", "勘察 4", op="old-survey")
    store = Store(game[1].path)
    store.initialize()
    service = Game(store, Config(), FixedRandom())
    assert "已勘察 1/2" in service.execute("u1", "tracking", "", "resumed", NOW + DAY).text()
    service.execute("u1", "tracking", "勘察 13", "resumed-survey", NOW + DAY)
    service.execute("u1", "tracking", "挖掘 1", "resumed-dig", NOW + DAY)
    service.execute("u1", "tracking", "出发 ruins", "next-run", NOW + DAY)
    sql(store, "DELETE FROM operations")
    before = snapshot(store)
    assert service.execute("u1", "tracking", "出发 bamboo", "old-start", NOW + DAY * 10) == first
    assert snapshot(store) == before
    assert "残垣石庭" in service.execute("u1", "tracking", "", "current-run", NOW + DAY).text()


def test_cooking_and_stage_snapshots_stay_independent_of_tracking(game, play):
    play("adopt", "青鸾")
    play("stage_tactics", "开始 1", op="stage-before-tracking")
    sql(game[1], "INSERT INTO inventory VALUES ('u1','spirit_food',5) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=5")
    play("cooking", "开锅 灵米粥", op="pot-before-tracking")
    stage, pot = play("stage_tactics"), play("cooking")
    play("tracking", "出发 bamboo")
    survey(play)
    play("tracking", "挖掘 1")
    assert play("stage_tactics").lines == stage.lines
    assert play("cooking").lines == pot.lines
    sql(game[1], "DELETE FROM operations")
    assert play("cooking", "ignored", op="pot-before-tracking").title == "灵宠掌勺 · 锅中"
    assert play("stage_tactics", "ignored", op="stage-before-tracking").title == "战术关卡开局"


def test_retired_original_pet_has_explicit_reason_and_can_abandon(game, play):
    play("adopt", "青鸾")
    play("summon", "1")
    play("tracking", "出发 bamboo")
    play("switch", "2")
    play("pet_release", "确认 1")
    before = snapshot(game[1])
    reply = play("tracking")
    assert "已归灵" in reply.text() and not reply.commands
    with pytest.raises(GameError, match="已归灵"):
        play("tracking", "勘察 1")
    assert snapshot(game[1]) == before
    assert "已放弃" in play("tracking", "放弃").text()


def test_only_the_actual_team_partner_growth_invalidates_readiness(game, play):
    play("adopt", "青鸾")
    play("summon", "1")
    play("team_create")
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id IS NOT NULL AS ready FROM team_members") == [{"ready": 1}]
    play("tracking", "出发 bamboo")
    assert sql(game[1], "SELECT ready_pet_id IS NOT NULL AS ready FROM team_members") == [{"ready": 0}]
    play("switch", "2")
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id IS NOT NULL AS ready FROM team_members") == [{"ready": 1}]
    survey(play)
    play("tracking", "挖掘 1")
    assert sql(game[1], "SELECT ready_pet_id IS NOT NULL AS ready FROM team_members") == [{"ready": 1}]


def test_users_and_old_action_ledger_consumers_are_isolated(game, play):
    play("adopt", "青鸾")
    play("adopt", "青鸾", user="u2")
    play("duel", "松风道人")
    duel = play("duel")
    play("tracking", "出发 bamboo", op="private-tracking")
    play("tracking", "出发 ruins", user="u2")
    play("tracking", "勘察 4", user="u2")
    assert last_run(game[1])["map"]["id"] == "ruins"
    assert play("duel").lines == duel.lines
    assert "已勘察 0/2" in play("tracking").text()
    action_id = sql(game[1], "SELECT action_id FROM duel_actions WHERE operation_id='private-tracking'")[0]["action_id"]
    with pytest.raises(GameError, match="未找到本人的"):
        play("duel", f"回顾 查看 {action_id}")
    assert "竹溪旧径" not in play("duel", "回顾").text()
    with game[1].connect() as conn:
        repo = Repository(conn)
        assert repo.duel_operation("private-tracking", "u1") is None
        assert repo.cooking_operation("private-tracking", "u1") is None
        assert repo.stage_tactic_operation("private-tracking", "u1") is None
        assert repo.latest_cooking_action("u1") is None
    play("duel", "认输")
    assert "已勘察 0/2" in play("tracking").text()


@pytest.mark.parametrize("change", ["sites", "terrains", "terrain_names", "duplicate", "balance", "runtime"])
def test_maps_reject_malformed_or_runtime_content(game, change):
    data = game[0].content.tracking_maps["bamboo"].model_dump()
    if change in ("sites", "terrains", "terrain_names"):
        data[change].pop()
    elif change == "duplicate":
        data["sites"][1] = data["sites"][0]
    elif change == "balance":
        data["terrains"][0] = 1
    else:
        data["target"] = 1
    with pytest.raises(ValidationError):
        TrackingMap.model_validate(data)


def test_native_text_and_disabled_keyboard_keep_main_actions_and_auxiliary_links_distinct(game, play):
    play("adopt", "青鸾")
    pages = [play("tracking"), play("tracking", "出发 bamboo"), play("tracking", "地图 4"), survey(play)]
    pages.append(play("tracking", "挖掘 1"))
    for reply in pages:
        labels = [label for label, _ in _action_items(reply)]
        assert all("/" not in label and not re.search(r"20\d{6}", label) for label in labels)
        _, messages = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        body = messages["markdown"][0].data["markdown"].content
        linked = {parse_qs(urlparse(url).query)["command"][0]
                  for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        buttons = {button.action.data for segment in messages["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 4 and buttons == {"!" + command for command in reply.commands}
        assert linked == {"!" + link.command for link in reply.inline_commands}
        assert not linked & buttons
        for config in (Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"),
                       Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!", spirit_pet_qq_keyboard=False)):
            _, fallback = _qq_segments(reply, config)
            rendered = str(fallback)
            commands = {"!" + command for command in (*reply.commands, *(link.command for link in reply.inline_commands))}
            if config.spirit_pet_qq_mode == "text":
                assert all(command in rendered for command in commands)
            else:
                body = fallback["markdown"][0].data["markdown"].content
                linked = {parse_qs(urlparse(url).query)["command"][0]
                          for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
                assert commands <= linked


def test_onebot_entry_to_settlement_and_qq_entry_use_shared_registered_handler(game, monkeypatch):
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        for index, command in enumerate(("!灵宠领养 青鸾", "!灵宠寻踪", "!灵宠寻踪 出发 竹溪旧径",
                                         "!灵宠寻踪 勘察 1", "!灵宠寻踪 挖掘 1", "!灵宠羁绊")):
            event = onebot_event(command, index + 1)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(run())
    replies = [call.args[1] for call in bot.send.call_args_list]
    assert len(replies) == 6 and "10000" in replies[0]
    assert "寻获藏物" in replies[4] and "经验 8/50" in replies[5]
    # QQ only verifies its event/identity/message boundary, not a second business chain.
    event = qq_event(user_id="qq-tracking-user", text="!灵宠寻踪", message_id="qq-tracking-entry")
    assert handlers._parse(event.get_plaintext()) == ("tracking", "")
    qq_bot = Bot(Adapter(nonebot.get_driver()), "test-app", BotInfo(id="test-app", secret="test-only", token="test-only"))
    qq_bot.post_group_messages = AsyncMock(return_value={})
    asyncio.run(handlers.handle_command(qq_bot, event, event.get_message()))
    assert qq_bot.post_group_messages.await_count == 1
    payload = qq_bot.post_group_messages.call_args.kwargs
    assert payload["msg_type"] == 2
    assert "灵宠寻踪" in payload["markdown"].content
    assert "[开始领养](mqqapi://" in payload["markdown"].content
    assert not sql(game[1], "SELECT * FROM players WHERE user_id='qq-tracking-user'")
