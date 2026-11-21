import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import json
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application import game as game_module
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import family_outing
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_week

from .support import sql
from .test_commands import onebot_event
from .test_family_trial import prepare as prepare_family

NOW = 1_800_000_000


def prepare(game, play, user="u1"):
    ids = prepare_family(game, play, user)
    sql(game[1], "UPDATE pets SET energy=100,energy_updated=? WHERE user_id=?", (NOW, user))
    sql(game[1], "INSERT INTO inventory VALUES (?,'spirit_food',10) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=10", (user,))
    return ids


def run(game, user="u1"):
    row = sql(game[1], "SELECT * FROM family_outing_runs WHERE user_id=? ORDER BY rowid DESC", (user,))[0]
    row["snapshot"] = json.loads(row["snapshot"])
    return row


def start(game, play, ids, user="u1", route="brook_walk", now=NOW, op=None):
    return play("family_outing", f"出发 {route} {ids[0]} {ids[2]} {beijing_week(now)[0]}", user=user, now=now, op=op)


def choose(game, play, choice="explore", user="u1", now=NOW, op=None):
    current = run(game, user)
    return play("family_outing", f"选择 {current['trip_id']} {current['steps_done'] + 1} {choice}", user=user, now=now, op=op)


def dump(game):
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def exp(game, target, user="u1"):
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (user, f"bond_exp_{target}"))
    return rows[0]["progress"] if rows else 0


def fighter(game, target, user="u1"):
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "inspect")
        return combatant(ctx, pet_id=target, recover_energy=False)


def test_all_private_discovery_pages_are_read_only_and_navigation_is_reachable(game, play):
    before = dump(game)
    assert "尚未结契" in play("family_outing", user="ghost").text()
    assert dump(game) == before
    ids = prepare(game, play)
    before = dump(game)
    page = play("family_outing")
    assert len(page.inline_commands) == 3
    pairs = play(*handlers._parse(page.inline_commands[0].command))
    assert len(pairs.inline_commands) == 2
    preview = play(*handlers._parse(pairs.inline_commands[0].command))
    assert "不预扣" in preview.text()
    assert "各羁绊经验 +16" in preview.text()
    assert dump(game) == before
    assert handlers._parse("灵宠亲子伴游 记录 2") == ("family_outing", "记录 2")
    assert "灵宠亲子伴游" in play("help", "成长").text()
    assert "灵宠亲子伴游" in play("bond_levels").commands
    assert "灵宠亲子伴游" in play("pet_outing", f"路线 {ids[2]}").commands
    assert any(link.command == "灵宠亲子伴游" for link in play("pedigree").inline_commands)
    assert "亲子伴游" in play("objectives").text()


@pytest.mark.parametrize("route,choice,gain,user", [
    ("brook_walk", "rest", 8, "u1"), ("grove_walk", "guide", 12, "u2"), ("ridge_walk", "explore", 16, "u3"),
])
def test_real_breeding_three_choices_original_pets_grow_and_permanent_story_replays(game, play, route, choice, gain, user):
    ids = prepare(game, play, user)
    sql(game[1], "INSERT INTO quest_progress VALUES (?,?,49,0)", (user, f"bond_exp_{ids[0]}"))
    baseline = fighter(game, ids[0], user).stats
    old = sql(game[1], "SELECT last_bond_day,current_bond_streak,last_pve FROM players WHERE user_id=?", (user,))
    inventory = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'", (user,))[0]["quantity"]
    start(game, play, ids, user, route)
    trip = run(game, user)["trip_id"]
    assert len(play("family_outing", user=user).commands) == 4
    assert exp(game, ids[2], user) == 0
    for index in range(3):
        reply = choose(game, play, choice, user, op=f"step-{user}-{index}")
        if index < 2:
            assert not sql(game[1], "SELECT * FROM family_outing_rewards")
    assert "完程" in reply.title
    assert run(game, user)["status"] == "completed"
    assert exp(game, ids[0], user) == 49 + gain
    assert exp(game, ids[2], user) == gain
    assert exp(game, ids[1], user) == 0
    assert fighter(game, ids[0], user).stats.hp == baseline.hp + 30
    assert fighter(game, ids[0], user).stats.attack == baseline.attack + 5
    assert sql(game[1], "SELECT last_bond_day,current_bond_streak,last_pve FROM players WHERE user_id=?", (user,)) == old
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id=? AND quest_id LIKE 'outing_%'", (user,))
    spent = 3 if choice == "rest" else 0
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'", (user,))[0]["quantity"] == inventory - spent
    definition = next(c for c in game[0].content.family_outings.choices if c.id == choice)
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (ids[0],))[0]["energy"] == 100 - 3 * definition.parent_energy
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (ids[2],))[0]["energy"] == 100 - 3 * definition.child_energy
    before = dump(game)
    detail = play("family_outing", f"详情 {trip}", user=user)
    assert "已结算" in detail.text() and "第 3 段" in detail.text()
    assert dump(game) == before
    sql(game[1], "DELETE FROM operations")
    before = dump(game)
    restarted = Game(game[1], game[0].config, game[0].rng)
    assert restarted.execute(user, "family_outing", "invalid", f"step-{user}-2", NOW + 900000) == reply
    sql(game[1], "DELETE FROM operations")
    assert dump(game) == before
    with pytest.raises(GameError, match="结束"):
        play("family_outing", f"选择 {trip} 3 {choice}", user=user)


@pytest.mark.parametrize("violation", ["unrelated", "foreign", "archived", "released", "expedition", "before_hatch"])
def test_start_qualification_failure_consumes_no_quota_or_assets(game, play, violation):
    ids = prepare(game, play)
    now = NOW
    if violation == "unrelated":
        ids[0] = sql(game[1], "SELECT active_pet_id FROM players WHERE user_id='u1'")[0]["active_pet_id"]
    elif violation == "foreign":
        ids[0] = prepare(game, play, "u2")[0]
    elif violation in {"archived", "released"}:
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[2],))
        if violation == "released":
            sql(game[1], "INSERT INTO quest_progress VALUES ('u1',?,1,0)", (f"released_{ids[2]}",))
    elif violation == "expedition":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'forest_patrol','旧行程','old-trip',?,?,'running','{}')", (ids[2], NOW, NOW + 3600))
    else:
        now -= 1
    before = dump(game)
    with pytest.raises(GameError):
        start(game, play, ids, now=now)
    assert dump(game) == before


@pytest.mark.parametrize("block", ["parent_energy", "child_energy", "food", "archived", "expedition", "old_step", "bad_choice", "clock"])
def test_unavailable_step_never_half_pays_or_advances(game, play, block):
    ids = prepare(game, play)
    start(game, play, ids)
    current = run(game)
    if block.endswith("energy"):
        target = ids[0] if block == "parent_energy" else ids[2]
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=?", (NOW, target))
    elif block == "food":
        sql(game[1], "DELETE FROM inventory WHERE item_id='spirit_food'")
    elif block == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
    elif block == "expedition":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'forest_patrol','待领行程','old-trip',?,?,'running','{}')", (ids[0], NOW - 3600, NOW))
    argument = f"选择 {current['trip_id']} {'2' if block == 'old_step' else '1'} {'missing' if block == 'bad_choice' else 'rest'}"
    before = dump(game)
    with pytest.raises(GameError):
        play("family_outing", argument, now=NOW - 1 if block == "clock" else NOW)
    assert dump(game) == before


@pytest.mark.parametrize("target", ["family_outing_runs", "duel_actions", "operations"])
def test_start_write_failure_rolls_back_quota_and_reply(game, play, target):
    ids = prepare(game, play)
    sql(game[1], f"CREATE TRIGGER injected BEFORE INSERT ON {target} BEGIN SELECT RAISE(ABORT,'injected outing'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected outing"):
        start(game, play, ids, op="retry-start")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    start(game, play, ids, op="retry-start")
    assert len(sql(game[1], "SELECT * FROM family_outing_runs")) == 1


@pytest.mark.parametrize("boundary", ["food", "parent", "child", "parent_bond", "child_bond", "step", "run", "reward", "permanent", "operation"])
def test_final_step_each_write_boundary_rolls_back_both_pets_and_can_retry(game, play, boundary):
    ids = prepare(game, play)
    start(game, play, ids)
    choose(game, play, "rest")
    choose(game, play, "rest")
    targets = {
        "food": ("UPDATE", "inventory", ""),
        "parent": ("UPDATE", "pets", f"WHEN OLD.pet_id={ids[0]}"),
        "child": ("UPDATE", "pets", f"WHEN OLD.pet_id={ids[2]}"),
        "parent_bond": ("INSERT", "quest_progress", f"WHEN NEW.quest_id='bond_exp_{ids[0]}'"),
        "child_bond": ("INSERT", "quest_progress", f"WHEN NEW.quest_id='bond_exp_{ids[2]}'"),
        "step": ("INSERT", "family_outing_steps", ""), "run": ("UPDATE", "family_outing_runs", ""),
        "reward": ("INSERT", "family_outing_rewards", ""), "permanent": ("INSERT", "duel_actions", ""),
        "operation": ("INSERT", "operations", ""),
    }
    verb, table, condition = targets[boundary]
    sql(game[1], f"CREATE TRIGGER injected BEFORE {verb} ON {table} {condition} BEGIN SELECT RAISE(ABORT,'injected outing'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected outing"):
        choose(game, play, "rest", op="retry-final")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    assert "完程" in choose(game, play, "rest", op="retry-final").title
    assert exp(game, ids[0]) == exp(game, ids[2]) == 8


def test_frozen_stories_costs_and_rewards_survive_content_rename_leader_changes(game, play):
    ids = prepare(game, play)
    start(game, play, ids)
    current = run(game)
    sql(game[1], "UPDATE pets SET name='新名' WHERE pet_id IN (?,?)", (ids[0], ids[2]))
    sql(game[1], "UPDATE players SET active_pet_id=?", (ids[1],))
    content = game[0].content.family_outings
    changed = content.model_copy(update={"choices": [], "routes": [], "tiers": []})
    game[0].content = replace(game[0].content, family_outings=changed)
    for _ in range(3):
        reply = choose(game, play)
    assert "新名" not in reply.text()
    assert exp(game, ids[0]) == exp(game, ids[2]) == 16
    assert exp(game, ids[1]) == 0
    before = dump(game)
    assert "亲本甲" in play("family_outing", f"详情 {current['trip_id']}").text()
    assert dump(game) == before


def test_week_limits_expiry_terminal_clock_and_new_week_remain_independent(game, play):
    ids = prepare(game, play)
    start(game, play, ids, op="first")
    first = run(game)
    with pytest.raises(GameError, match="进行中"):
        start(game, play, ids)
    before = dump(game)
    assert "已到期" in play("family_outing", now=NOW + 86400).text()
    assert dump(game) == before
    assert "期限" in play("family_outing", f"取消 {first['trip_id']}", now=NOW + 86400).text()
    with pytest.raises(GameError, match="时间"):
        start(game, play, ids)
    start(game, play, ids, now=NOW + 86400, op="second")
    play("family_outing", f"取消 {run(game)['trip_id']}", now=NOW + 86400)
    with pytest.raises(GameError, match="名额"):
        start(game, play, ids, now=NOW + 86400)
    next_week = beijing_week(NOW)[1]
    start(game, play, ids, now=next_week)
    assert run(game)["week_start"] == next_week
    with pytest.raises(GameError, match="结束"):
        play("family_outing", f"选择 {first['trip_id']} 1 rest", now=next_week)
    assert not sql(game[1], "SELECT * FROM family_outing_rewards")


def test_concurrent_start_step_and_final_cancel_have_one_committed_result(game, play):
    ids = prepare(game, play)

    def execute(argument, index):
        try:
            return game[0].execute("u1", "family_outing", argument, f"parallel-{argument}-{index}", NOW)
        except GameError:
            return None

    argument = f"出发 brook_walk {ids[0]} {ids[2]} {beijing_week(NOW)[0]}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: execute(argument, i), range(2)))
    assert sum(reply is not None for reply in results) == 1
    trip = run(game)["trip_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: execute(f"选择 {trip} 1 explore", i), range(2)))
    assert sum(reply is not None for reply in results) == 1
    choose(game, play)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: execute(*pair), [(f"选择 {trip} 3 explore", 0), (f"取消 {trip}", 1)]))
    assert sum(reply is not None for reply in results) == 1
    finished = run(game)["status"] == "completed"
    assert len(sql(game[1], "SELECT * FROM family_outing_rewards")) == int(finished)
    assert exp(game, ids[0]) == exp(game, ids[2]) == (16 if finished else 0)


def test_cross_year_history_pagination_privacy_and_operation_ownership(game, play):
    ids = prepare(game, play)
    at = int(datetime(2027, 12, 27, tzinfo=BEIJING).timestamp())
    trip_ids = []
    for index in range(8):
        now = at + index * 604800
        start(game, play, ids, now=now, op=f"history-{index}")
        trip_ids.append(run(game)["trip_id"])
        play("family_outing", f"取消 {trip_ids[-1]}", now=now)
    before = dump(game)
    page = play("family_outing", "记录", now=now)
    assert len(page.inline_commands) == 6
    assert "灵宠亲子伴游 记录 2" in page.commands
    assert len(play("family_outing", "记录 2", now=now).inline_commands) == 2
    assert dump(game) == before
    play("adopt", "青鸾", user="u2", now=now)
    for action in (f"详情 {trip_ids[0]}", f"取消 {trip_ids[0]}"):
        with pytest.raises(GameError, match="不属于"):
            play("family_outing", action, user="u2", now=now)
    with pytest.raises(GameError, match="different user"):
        play("family_outing", "invalid", user="u2", now=now, op="history-0")
    with pytest.raises(GameError, match="过期"):
        play("family_outing", f"出发 brook_walk {ids[0]} {ids[2]} {beijing_week(at)[0]}", now=now)


def test_qq_native_no_duplicate_actions_and_onebot_calls_the_same_handler(game, play, monkeypatch):
    ids = prepare(game, play, "12345")
    preview = play("family_outing", f"预览 brook_walk {ids[0]} {ids[2]}", user="12345")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(game_module.time, "time", lambda: NOW)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    command = "!" + preview.commands[0]
    asyncio.run(handlers._run(bot, onebot_event(command, 77), command))
    assert "同行中" in bot.send.call_args.args[1]
    for reply in (preview, play("family_outing", user="12345"), choose(game, play, user="12345")):
        _, segments = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        markdown = segments["markdown"][0].data["markdown"].content
        links = [parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        buttons = [button.action.data for segment in segments["keyboard"] for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert len(buttons) <= 4
        assert not set(links) & set(buttons)
    assert "亲子伴游" in play("objectives", user="12345").text()
    assert any("亲子伴游" in play("today", str(page), user="12345").text() for page in range(1, 4))


def test_grandparent_and_sibling_cannot_substitute_for_direct_parent(game, play):
    ids = prepare(game, play)
    sql(game[1], "UPDATE pets SET affinity=100,energy=100 WHERE user_id='u1'")
    at = NOW + 604800
    play("breeding", f"{ids[1]} {ids[2]}", now=at)
    play("use", "egg_qingluan", now=at)
    descendant = sql(game[1], "SELECT MAX(child_pet_id) AS id FROM pet_lineage_eggs")[0]["id"]
    before = dump(game)
    with pytest.raises(GameError, match="直接亲本"):
        start(game, play, [ids[0], ids[1], descendant], now=at)
    assert dump(game) == before


def test_pair_pagination_keeps_every_family_reachable_without_writing(game, play):
    ids = prepare(game, play)
    for index in range(3):
        at = NOW + (index + 1) * 604800
        sql(game[1], "UPDATE pets SET affinity=100,energy=100 WHERE user_id='u1'")
        play("breeding", f"{ids[0]} {ids[1]}", now=at)
        play("use", "egg_qingluan", now=at)
    before = dump(game)
    first = play("family_outing", "亲子 brook_walk", now=at)
    second = play("family_outing", "亲子 brook_walk 2", now=at)
    assert len(first.inline_commands) == 6
    assert len(second.inline_commands) == 2
    assert "灵宠亲子伴游 亲子 brook_walk 2" in first.commands
    assert "灵宠亲子伴游 亲子 brook_walk 1" in second.commands
    assert len({link.command for link in (*first.inline_commands, *second.inline_commands)}) == 8
    assert dump(game) == before


def test_expiring_old_active_trip_and_starting_new_are_one_transaction(game, play):
    ids = prepare(game, play)
    start(game, play, ids)
    old = run(game)["trip_id"]
    sql(game[1], "CREATE TRIGGER injected BEFORE INSERT ON family_outing_runs BEGIN SELECT RAISE(ABORT,'replacement failed'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="replacement failed"):
        start(game, play, ids, now=NOW + 86400, op="replace-expired")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    start(game, play, ids, now=NOW + 86400, op="replace-expired")
    assert sql(game[1], "SELECT status FROM family_outing_runs WHERE trip_id=?", (old,)) == [{"status": "expired"}]


def test_week_limit_freezes_even_when_same_second_content_changes(game, play):
    ids = prepare(game, play)
    for index in range(2):
        if index:
            content = game[0].content.family_outings
            game[0].content = replace(game[0].content, family_outings=content.model_copy(
                update={"rules": content.rules.model_copy(update={"weekly_starts": 3})}))
        start(game, play, ids, op=f"week-start-{index}")
        play("family_outing", f"取消 {run(game)['trip_id']}")
    with pytest.raises(GameError, match="名额"):
        start(game, play, ids)
    assert {json.loads(row["snapshot"])["rules"]["weekly_starts"] for row in sql(game[1], "SELECT snapshot FROM family_outing_runs")} == {2}


def test_partial_trip_restores_after_restart_then_completes_across_week_boundary(game, play):
    ids = prepare(game, play)
    at = beijing_week(NOW)[1] - 10
    start(game, play, ids, now=at)
    choose(game, play, "guide", now=at)
    current = run(game)
    restarted = Game(game[1], game[0].config, game[0].rng)
    before = dump(game)
    assert "已同行" not in restarted.execute("u1", "family_outing", "", "read-restored", at + 20).title
    assert dump(game) == before
    restarted.execute("u1", "family_outing", f"选择 {current['trip_id']} 2 explore", "restored-2", at + 20)
    restarted.execute("u1", "family_outing", f"选择 {current['trip_id']} 3 explore", "restored-3", at + 20)
    assert run(game)["status"] == "completed"
    assert run(game)["week_start"] == beijing_week(at)[0]
    assert exp(game, ids[0]) == exp(game, ids[2]) == 16
    start(game, play, ids, now=at + 20)
    assert run(game)["week_start"] == beijing_week(at + 20)[0]
