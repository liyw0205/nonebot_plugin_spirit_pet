import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import family_trial
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def prepare(game, play, user="u1", suffix=""):
    if not sql(game[1], "SELECT 1 FROM players WHERE user_id=?", (user,)):
        play("adopt", "青鸾", user=user)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id=?", (user,))
    with closing(game[1].connect()) as conn:
        ids = [int(conn.execute(
            "INSERT INTO pets(user_id,species_id,name,affinity,energy_updated) VALUES (?, 'qingluan',?,100,?)",
            (user, name + suffix, NOW),
        ).lastrowid) for name in ("亲本甲", "亲本乙")]
    play("breeding", " ".join(map(str, ids)), user=user)
    play("use", "egg_qingluan", user=user)
    child = sql(game[1], "SELECT child_pet_id FROM pet_lineage_eggs WHERE parent_a_id=?", (ids[0],))[0]
    return [*ids, child["child_pet_id"]]


def run(game, user="u1"):
    result = sql(game[1], "SELECT * FROM family_trial_runs WHERE user_id=? ORDER BY week_start DESC", (user,))[0]
    result["snapshot"] = json.loads(result["snapshot"])
    return result


def next_arg(game, user="u1"):
    current = run(game, user)
    return f"继续 {current['run_id']} {current['current_stage']}"


def dump(game):
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def scripted(winner=0, rounds=2, seen=None):
    def battle(left, right, rng, elements, **kwargs):
        if seen is not None:
            seen.append(([unit.hp for unit in left], [unit.hp for unit in right], kwargs))
        for unit in left:
            unit.hp = max(0, unit.hp - 7) if winner != 1 else 0
        if winner == 0:
            for unit in right:
                unit.hp = 0
        return Battle(winner, rounds, ("scripted battle",), ({}, {}),
                      remaining_hp=(tuple(unit.hp for unit in left), tuple(unit.hp for unit in right)))
    return battle


def test_private_overview_is_read_only_and_registered_in_navigation(game, play):
    before = dump(game)
    assert "尚未结契" in play("family_trial", user="ghost").text()
    assert dump(game) == before
    play("adopt", "青鸾")
    before = dump(game)
    assert "尚无在册人数足够" in play("family_trial").text()
    assert dump(game) == before
    assert handlers._parse("灵宠家族试炼 战历 2") == ("family_trial", "战历 2")
    assert "灵宠家族试炼" in play("help", "成长").text()
    assert "灵宠家族试炼" in play("pedigree").commands
    ids = prepare(game, play)
    before = dump(game)
    page = play("family_trial")
    assert all(str(pet_id) in page.text() for pet_id in ids)
    assert len(page.inline_commands) == 1
    assert dump(game) == before
    assert "家族试炼" in play("objectives").text()
    today = [play("today", str(page)).text() for page in range(1, 4)]
    assert any("家族试炼" in text for text in today)


def test_real_breeding_family_can_clear_real_stages_and_rewards_persist(game, play, monkeypatch):
    ids = prepare(game, play)
    sql(game[1], "UPDATE pets SET realm=6,layer=10 WHERE user_id='u1'")
    before = player(game[1])["stones"]
    before_exp = sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (ids[0],))[0]["exp"]
    first = play(*handlers._parse(play("family_trial").inline_commands[0].command), op="start-real")
    current = run(game)
    trial = current["snapshot"]["trial"]
    assert len(current["snapshot"]["family_edges"]) == 1
    assert first == play("family_trial", "开始 " + " ".join(map(str, ids[:2])), op="start-real")
    assert len(sql(game[1], "SELECT * FROM family_trial_members")) == 2
    real = family_trial.fight
    starting_hp = []

    def observe(left, right, *args, **kwargs):
        starting_hp.append([unit.hp for unit in left])
        return real(left, right, *args, **kwargs)

    monkeypatch.setattr(family_trial, "fight", observe)
    for index in range(len(trial["stages"])):
        reply = play("family_trial", next_arg(game), now=NOW + index * 600, op=f"real-stage-{index}")
        assert "通过" in reply.title
        assert len(sql(game[1], "SELECT * FROM family_trial_stages")) == index + 1
        if index:
            previous = sql(game[1], "SELECT remaining_hp FROM family_trial_stages WHERE stage_no=?", (index,))[0]
            assert starting_hp[index] == json.loads(previous["remaining_hp"])
    assert starting_hp[1][0] < starting_hp[0][0]
    assert run(game)["status"] == "completed"
    assert player(game[1])["stones"] == before + trial["bonus"]["stones"]["minimum"] + sum(
        stage["reward"]["stones"]["minimum"] for stage in trial["stages"]
    )
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (ids[0],))[0]["exp"] == before_exp + sum(
        stage["reward"]["exp"]["minimum"] for stage in trial["stages"]
    ) + trial["bonus"]["exp"]["minimum"]
    assert len(sql(game[1], "SELECT * FROM family_trial_rewards")) == len(trial["stages"]) + 1
    assert len(sql(game[1], "SELECT * FROM battle_records")) == len(trial["stages"])
    assert "已发放" in play("family_trial").text()
    assert "全通奖励已发放" in play("family_trial").text()
    assert play("family_trial", "战历").inline_commands
    review = play("family_trial", f"回顾 {current['run_id']}")
    assert len(review.inline_commands) == len(trial["stages"])
    assert "场景：家族试炼" in play(*handlers._parse(review.inline_commands[0].command)).text()
    sql(game[1], "DELETE FROM operations")
    before = (run(game), player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pets"),
              sql(game[1], "SELECT * FROM family_trial_stages"), sql(game[1], "SELECT * FROM family_trial_rewards"))
    assert play("family_trial", "irrelevant", now=NOW + 9 * 86400, op="real-stage-0").title.endswith("通过")
    assert (run(game), player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pets"),
            sql(game[1], "SELECT * FROM family_trial_stages"), sql(game[1], "SELECT * FROM family_trial_rewards")) == before
    with pytest.raises(GameError, match="本周已开启"):
        play("family_trial", "开始 " + " ".join(map(str, ids[:2])), now=NOW + 2000)
    with closing(game[1].connect()) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_frozen_fighters_enemy_rules_and_hp_survive_restart(game, play, monkeypatch):
    ids = prepare(game, play)
    play("family_trial", "开始 " + " ".join(map(str, ids)))
    initial = run(game)["snapshot"]
    real_fight = family_trial.fight
    seen = []

    def spy(left, right, rng, elements, **kwargs):
        seen.append(([unit.hp for unit in left], [unit.stats for unit in left],
                     [unit.stats for unit in right], elements))
        return scripted()(left, right, rng, elements, **kwargs)

    monkeypatch.setattr(family_trial, "fight", spy)
    play("family_trial", next_arg(game))
    remaining = [unit["hp"] for unit in run(game)["snapshot"]["fighters"]]
    assert remaining == [unit["hp"] - 7 for unit in initial["fighters"]]
    assert json.loads(sql(game[1], "SELECT remaining_hp FROM family_trial_stages")[0]["remaining_hp"]) == remaining
    sql(game[1], "UPDATE pets SET realm=6,layer=10,name='新名'")
    restarted = Game(game[1], game[0].config, game[0].rng)
    restarted.content.enemies.clear()
    restarted.content.skills.clear()
    restarted.content.elements.clear()
    restarted.content.family_trials.clear()
    arg = next_arg(game)
    restarted.execute("u1", "family_trial", arg, "restart-stage", NOW + 600)
    assert seen[1][0] == remaining
    assert [stats.model_dump() for stats in seen[1][1]] == [unit["stats"] for unit in initial["fighters"]]
    assert seen[1][2][0].model_dump() == initial["stages"][1]["enemy"]["stats"]
    assert {key: value.model_dump(mode="json") for key, value in seen[1][3].items()} == initial["elements"]
    assert "亲本甲" in restarted.execute("u1", "family_trial", f"回顾 {run(game)['run_id']}", "history", NOW + 600).text()
    monkeypatch.setattr(family_trial, "fight", real_fight)


@pytest.mark.parametrize("selection", ["unknown", "foreign", "different", "duplicate", "archived", "released", "trip"])
def test_only_own_current_qualified_family_can_start(game, play, selection):
    ids = prepare(game, play)
    other = prepare(game, play, "u2")
    if selection == "unknown":
        ids[1] = player(game[1])["active_pet_id"]
    elif selection == "foreign":
        ids[1] = other[0]
    elif selection == "different":
        ids[1] = prepare(game, play, suffix="另支")[0]
    elif selection == "duplicate":
        ids[1] = ids[0]
    elif selection in {"archived", "released"}:
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
    else:
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'test','test','trip',?,?,'running','{}')", (ids[0], NOW, NOW + 1000))
    before = dump(game)
    with pytest.raises(GameError):
        play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    assert dump(game) == before


def test_two_players_are_isolated_and_cannot_review_or_continue_others(game, play):
    for user in ("u1", "u2"):
        ids = prepare(game, play, user)
        play("family_trial", "开始 " + " ".join(map(str, ids[:2])), user=user)
    before = dump(game)
    for arg in (next_arg(game), f"放弃 {run(game)['run_id']}", f"回顾 {run(game)['run_id']}"):
        with pytest.raises(GameError):
            play("family_trial", arg, user="u2")
    assert dump(game) == before
    assert run(game, "u1")["run_id"] != run(game, "u2")["run_id"]


@pytest.mark.parametrize("winner,rounds,outcome", [(1, 2, "lost"), (-1, 2, "draw"), (-1, 40, "timeout")])
def test_failure_ends_run_and_retains_only_prior_rewards(game, play, monkeypatch, winner, rounds, outcome):
    ids = prepare(game, play)
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    monkeypatch.setattr(family_trial, "fight", scripted())
    play("family_trial", next_arg(game))
    stones = player(game[1])["stones"]
    monkeypatch.setattr(family_trial, "fight", scripted(winner, rounds))
    reply = play("family_trial", next_arg(game), now=NOW + 600)
    assert "止步" in reply.title
    assert run(game)["status"] == "defeated"
    assert player(game[1])["stones"] == stones
    assert sql(game[1], "SELECT outcome FROM family_trial_stages ORDER BY stage_no")[-1]["outcome"] == outcome
    assert len(sql(game[1], "SELECT * FROM family_trial_rewards")) == 1
    with pytest.raises(GameError, match="已经结束"):
        play("family_trial", next_arg(game), now=NOW + 1200)


@pytest.mark.parametrize("block", ["energy", "cooldown", "archived", "trip"])
def test_stage_rechecks_member_availability_without_partial_cost(game, play, block):
    ids = prepare(game, play)
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    if block == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (ids[1],))
    elif block == "cooldown":
        sql(game[1], "UPDATE players SET last_pve=?", (NOW,))
    elif block == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[1],))
    else:
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'test','test','trip',?,?,'running','{}')", (ids[1], NOW, NOW + 1000))
    before = dump(game)
    with pytest.raises(GameError):
        play("family_trial", next_arg(game))
    assert dump(game) == before


def test_week_expiry_clock_rollback_old_buttons_and_abandon(game, play, monkeypatch):
    ids = prepare(game, play)
    old_command = play("family_trial").inline_commands[0].command
    play(*handlers._parse(old_command))
    first = run(game)
    boundary = beijing_week(NOW)[0] + 604800
    with pytest.raises(GameError, match="轮换"):
        play(*handlers._parse(old_command), now=boundary)
    assert "已结束" in play("family_trial", next_arg(game), now=boundary).text()
    assert run(game)["status"] == "expired"
    with pytest.raises(GameError):
        play("family_trial", f"继续 {first['run_id']} 1", now=NOW)
    with pytest.raises(GameError, match="时间"):
        play("family_trial", "开始 " + " ".join(map(str, ids[:2])), now=NOW - 604800)
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])), now=boundary)
    second = run(game)
    assert second["trial_id"] != first["trial_id"]
    monkeypatch.setattr(family_trial, "fight", scripted())
    play("family_trial", next_arg(game), now=boundary)
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="时间"):
        play("family_trial", f"放弃 {second['run_id']}", now=boundary - 1)
    play("family_trial", f"放弃 {second['run_id']}", now=boundary + 1)
    assert run(game)["status"] == "abandoned"
    assert player(game[1])["stones"] == stones
    before = dump(game)
    for arg in ("", "战历", "历史", f"回顾 {first['run_id']}"):
        play("family_trial", arg, now=boundary + 2)
    assert dump(game) == before


@pytest.mark.parametrize("target", ["battle_records", "family_trial_stages", "family_trial_rewards", "duel_actions", "operations", "quest_progress", "pets", "players", "inventory"])
def test_stage_failure_rolls_back_everything_and_retry_succeeds(game, play, monkeypatch, target):
    ids = prepare(game, play)
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    monkeypatch.setattr(family_trial, "fight", scripted())
    # Use the final stage to include the material and full-clear award writes.
    stages = len(run(game)["snapshot"]["stages"])
    for index in range(stages - 1):
        play("family_trial", next_arg(game), now=NOW + index * 600)
    with closing(game[1].connect()) as conn:
        conn.execute(f"CREATE TRIGGER injected BEFORE {'UPDATE' if target in {'pets', 'players', 'quest_progress'} else 'INSERT'} ON {target} BEGIN SELECT RAISE(ABORT,'injected trial failure'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected trial failure"):
        play("family_trial", next_arg(game), now=NOW + stages * 600, op="stage-retry")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    assert "通过" in play("family_trial", next_arg(game), now=NOW + stages * 600, op="stage-retry").title
    assert run(game)["status"] == "completed"


@pytest.mark.parametrize("target", ["duel_actions", "family_trial_runs", "family_trial_members", "operations"])
def test_start_failure_does_not_consume_week_and_can_retry(game, play, target):
    ids = prepare(game, play)
    sql(game[1], f"CREATE TRIGGER injected BEFORE INSERT ON {target} BEGIN SELECT RAISE(ABORT,'injected start failure'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="injected start"):
        play("family_trial", "开始 " + " ".join(map(str, ids[:2])), op="start-retry")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])), op="start-retry")
    assert len(sql(game[1], "SELECT * FROM family_trial_runs")) == 1


def test_concurrent_starts_and_stages_are_unique_and_permanent(game, play, monkeypatch):
    ids = prepare(game, play)
    arg = "开始 " + " ".join(map(str, ids[:2]))

    def execute(index, argument=arg):
        try:
            return game[0].execute("u1", "family_trial", argument, f"parallel-{argument}-{index}", NOW)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, range(4)))
    assert sum(result is not None for result in results) == 1
    monkeypatch.setattr(family_trial, "fight", scripted())
    argument = next_arg(game)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: execute(i, argument), range(4)))
    assert sum(result is not None for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1
    assert len(sql(game[1], "SELECT * FROM family_trial_rewards")) == 1
    assert len(sql(game[1], "SELECT * FROM family_trial_stages")) == 1


def test_skill_mastery_counts_only_new_stage_uses_and_failure_rolls_back(game, play, monkeypatch):
    ids = prepare(game, play)
    sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)", (ids[0],))
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    original = family_trial.award_mastery
    seen = []

    def fight(left, right, *args, **kwargs):
        left[0].skill_uses["wind_slash"] = left[0].skill_uses.get("wind_slash", 0) + 2
        result = scripted()(left, right, *args, **kwargs)
        return Battle(result.winner, result.rounds, result.lines,
                      ({unit.pet_id: dict(unit.skill_uses) for unit in left}, {}),
                      remaining_hp=result.remaining_hp)

    def award(*args, **kwargs):
        seen.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(family_trial, "fight", fight)
    monkeypatch.setattr(family_trial, "award_mastery", award)
    play("family_trial", next_arg(game))
    assert seen[0] == {"wind_slash": 2}
    before = dump(game)

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected mastery failure")

    monkeypatch.setattr(family_trial, "award_mastery", fail)
    with pytest.raises(RuntimeError, match="mastery failure"):
        play("family_trial", next_arg(game), now=NOW + 600, op="mastery-retry")
    assert dump(game) == before
    monkeypatch.setattr(family_trial, "award_mastery", award)
    play("family_trial", next_arg(game), now=NOW + 600, op="mastery-retry")
    assert seen[2] == {"wind_slash": 2}


def test_full_clear_receipt_failure_rolls_back_stage_and_both_awards(game, play, monkeypatch):
    ids = prepare(game, play)
    play("family_trial", "开始 " + " ".join(map(str, ids[:2])))
    monkeypatch.setattr(family_trial, "fight", scripted())
    stages = len(run(game)["snapshot"]["stages"])
    for index in range(stages - 1):
        play("family_trial", next_arg(game), now=NOW + index * 600)
    sql(game[1], "CREATE TRIGGER injected BEFORE INSERT ON family_trial_rewards WHEN NEW.reward_key='full_clear' BEGIN SELECT RAISE(ABORT,'injected full clear'); END")
    before = dump(game)
    with pytest.raises(sqlite3.IntegrityError, match="full clear"):
        play("family_trial", next_arg(game), now=NOW + stages * 600)
    assert dump(game) == before


@pytest.mark.parametrize("argument", ["战历 0", "战历 -1", "战历 999", "回顾 missing", "开始 1", "开始 1 1", "继续 xx 1", "放弃 xx", "missing"])
def test_invalid_commands_do_not_write(game, play, argument):
    prepare(game, play)
    before = dump(game)
    with pytest.raises(GameError):
        play("family_trial", argument)
    assert dump(game) == before


@pytest.mark.parametrize("timestamp", [1798732799, 1798732800, 1804435199, 1804435200])
def test_rotation_uses_beijing_week_even_across_year(game, timestamp):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository
    with closing(game[1].connect()) as conn:
        context = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "ghost", timestamp, "week")
        start = beijing_week(timestamp)[0]
        assert family_trial.current_trial(context).id == game[0].content.family_trial_rotation[
            ((start - 316800) // 604800) % len(game[0].content.family_trial_rotation)
        ]
        current = family_trial.current_trial(context).id
        context.now = start + 604799
        assert family_trial.current_trial(context).id == current
        context.now = start + 604800
        assert family_trial.current_trial(context).id != current


def test_qq_native_has_distinct_bounded_actions_and_onebot_shared_handler(game, play, monkeypatch):
    ids = prepare(game, play, "12345")
    page = play("family_trial", user="12345")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    markdown = message["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    buttons = [button.action.data for segment in message["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert len(buttons) <= 4
    assert not set(links) & set(buttons)
    command = "灵宠家族试炼 开始 " + " ".join(map(str, ids[:2]))
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    asyncio.run(handlers._run(bot, onebot_event("!" + command, 74), "!" + command))
    assert "已开局" in bot.send.call_args.args[1]
    assert len(sql(game[1], "SELECT * FROM family_trial_runs")) == 1
