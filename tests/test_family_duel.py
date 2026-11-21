import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import re
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application import game as game_module
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import family_duel
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import player, sql
from .test_commands import onebot_event
from .test_family_trial import prepare as prepare_family

NOW = 1_800_000_000


def prepare(game, play, user="u1"):
    ids = prepare_family(game, play, user)
    duel = family_duel.current_duel(SimpleNamespace(
        content=game[0].content, now=NOW,
    ))
    minimum = next(index for index, realm in enumerate(game[0].content.realms)
                   if realm.id == duel.min_realm)
    sql(game[1], "UPDATE pets SET realm=?,energy=100,energy_updated=? WHERE user_id=?",
        (minimum, NOW, user))
    for target in (ids[0], ids[2]):
        sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)",
            (target,))
    return ids


def scripted(winner=0, rounds=5, *, parent_hp=40, child_hp=35, skill_uses=True, seen=None):
    def battle(left, right, rng, elements, *, max_rounds):
        if seen is not None:
            seen.append((tuple(unit.pet_id for unit in left), max_rounds,
                         tuple(tuple(skill.id for skill in unit.skills) for unit in left)))
        uses = {}
        if skill_uses:
            uses = {left[0].pet_id: {"wind_slash": 1}, left[1].pet_id: {"wind_slash": 1}}
        if winner in (-1, 1):
            return Battle(winner, rounds, ("scripted battle",), (uses, {}),
                          remaining_hp=((0 if winner == 1 else parent_hp, child_hp), (17, 0)))
        return Battle(winner, rounds, ("scripted battle",), (uses, {}),
                      remaining_hp=((parent_hp, child_hp), (0, 0)))
    return battle


def run(game, user="u1", start=None):
    query = "SELECT * FROM family_duel_runs WHERE user_id=?"
    args = [user]
    if start is not None:
        query += " AND week_start=?"
        args.append(start)
    rows = sql(game[1], query, tuple(args))
    return rows[0] if rows else None


def dump(game):
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def test_pages_are_read_only_and_pair_preview_binds_week_and_real_direct_parent(game, play):
    ids = prepare(game, play)
    before = dump(game)
    page = play("family_duel")
    assert "本周" in page.text() and page.inline_commands
    pair_page = play("family_duel", "亲子")
    assert any(str(ids[0]) in line and str(ids[2]) in line for line in pair_page.lines)
    preview = play(*handlers._parse(pair_page.inline_commands[0].command))
    assert "真实已孵化凭证" in preview.text()
    assert "本周只可开始一次" in preview.text()
    assert preview.commands[0] == f"灵宠亲子合战 挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}"
    assert dump(game) == before
    assert handlers._parse("灵宠亲子合战 记录 2") == ("family_duel", "记录 2")
    assert "灵宠亲子合战" in play("help", "成长").text()
    assert "亲子合战" in play("objectives").text()
    assert any("亲子合战" in play("today", str(page)).text() for page in range(1, 5))
    before = dump(game)
    with pytest.raises(GameError, match="跨周"):
        play("family_duel", f"预览 {ids[0]} {ids[2]} {beijing_week(NOW)[0] - 7 * 86400}")
    assert dump(game) == before


def test_real_two_pet_loadouts_are_settled_and_high_rating_is_one_atomic_reward(game, play, monkeypatch):
    ids = prepare(game, play)
    seen = []
    monkeypatch.setattr(family_duel, "fight", scripted(seen=seen))
    start = beijing_week(NOW)[0]
    command = f"挑战 {start} {ids[0]} {ids[2]}"
    reply = play("family_duel", command, op="family-duel-once")
    assert "双契凯旋" in reply.title
    assert seen == [((ids[0], ids[2]), family_duel.current_duel(SimpleNamespace(
        content=game[0].content, now=NOW,
    )).max_rounds, (("wind_slash",), ("wind_slash",)))]
    row = run(game, start=start)
    assert row["outcome"] == "won" and row["rating_id"] == "twin_star"
    assert json.loads(row["remaining_hp"]) == [[40, 35], [0, 0]]
    uses = json.loads(row["skill_uses"])
    assert uses[str(ids[0])] == uses[str(ids[2])] == {"wind_slash": 1}
    assert [item["proficiency"] for item in sql(
        game[1], "SELECT proficiency FROM learned_skills WHERE pet_id IN (?,?) ORDER BY pet_id", (ids[0], ids[2]),
    )] == [game[0].content.rules.skill_proficiency_per_use] * 2
    energy_cost = family_duel.current_duel(SimpleNamespace(
        content=game[0].content, now=NOW,
    )).energy
    assert [item["energy"] for item in sql(
        game[1], "SELECT energy FROM pets WHERE pet_id IN (?,?) ORDER BY pet_id", (ids[0], ids[2]),
    )] == [100 - energy_cost, 100 - energy_cost]
    assert player(game[1])["last_pve"] == NOW
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='pve_once'")[0]["progress"] == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM family_duel_rewards")[0]["n"] == 1
    actual = json.loads(sql(game[1], "SELECT reward_snapshot FROM family_duel_rewards")[0]["reward_snapshot"])["actual"]
    assert actual["exp"] > 0 and actual["stones"] > 0 and actual["items"]
    battle = sql(game[1], "SELECT * FROM battle_records WHERE battle_id=?", (row["battle_id"],))[0]
    assert battle["kind"] == "pve_stage" and "family_duel_" in battle["battle_key"]
    assert "查看本场战报" in reply.inline_commands[0].label
    before = dump(game)
    assert play("family_duel", "not the original arguments", op="family-duel-once") == reply
    assert dump(game) == before
    assert "双契凯旋" in play("family_duel", f"详情 {row['run_id']}").text()
    assert f"灵宠战报 查看 {row['battle_id']}" in play(
        "family_duel", f"详情 {row['run_id']}"
    ).commands
    assert dump(game) == before


def test_two_players_use_their_real_lineage_in_unmocked_double_ally_combat(game, play, monkeypatch):
    duel = game[0].content.family_duels["root_echo"]
    monkeypatch.setattr(family_duel, "current_duel", lambda ctx, start=None: duel)
    real_fight = family_duel.fight
    results = []

    def observe(left, right, rng, elements, *, max_rounds):
        battle = real_fight(left, right, rng, elements, max_rounds=max_rounds)
        results.append((battle.winner, battle.rounds, battle.remaining_hp, battle.skill_uses))
        return battle

    monkeypatch.setattr(family_duel, "fight", observe)
    for user in ("u1", "u2"):
        ids = prepare(game, play, user)
        start = beijing_week(NOW)[0]
        play("family_duel", f"挑战 {start} {ids[0]} {ids[2]}", user=user, op=f"real-duel-{user}")
        row = run(game, user, start)
        assert row is not None
        assert row["rounds"] == results[-1][1]
        assert json.loads(row["remaining_hp"]) == [list(side) for side in results[-1][2]]
        assert set(map(int, json.loads(row["skill_uses"]))) == {ids[0], ids[2]}
        assert [item["energy"] for item in sql(
            game[1], "SELECT energy FROM pets WHERE pet_id IN (?,?) ORDER BY pet_id", (ids[0], ids[2]),
        )] == [100 - duel.energy, 100 - duel.energy]
        battle = sql(game[1], "SELECT * FROM battle_records WHERE battle_id=?", (row["battle_id"],))[0]
        assert battle["winner_side"] == results[-1][0]
        assert battle["rounds"] == row["rounds"]
    own = run(game, "u1", beijing_week(NOW)[0])
    other = run(game, "u2", beijing_week(NOW)[0])
    assert "共 1 场" in play("family_duel", "记录", user="u1").text()
    with pytest.raises(GameError, match="不存在或不属于你"):
        play("family_duel", f"详情 {other['run_id']}", user="u1")
    assert own["run_id"] != other["run_id"]


@pytest.mark.parametrize(("winner", "rounds", "expected"), [
    (1, 4, "lost"), (-1, 4, "draw"), (-1, 30, "timeout"),
])
def test_non_wins_keep_structured_outcome_without_rewards(game, play, monkeypatch, winner, rounds, expected):
    ids = prepare(game, play)
    duel = family_duel.current_duel(SimpleNamespace(content=game[0].content, now=NOW))
    monkeypatch.setattr(family_duel, "fight", scripted(winner=winner, rounds=rounds))
    start = beijing_week(NOW)[0]
    play("family_duel", f"挑战 {start} {ids[0]} {ids[2]}")
    row = run(game, start=start)
    assert row["outcome"] == expected
    assert row["rating_id"] is None
    assert not sql(game[1], "SELECT * FROM family_duel_rewards")


def test_partial_clear_ranks_from_structured_hp_and_no_skill_clear_gets_no_reward(game, play, monkeypatch):
    ids = prepare(game, play)
    monkeypatch.setattr(family_duel, "fight", scripted(parent_hp=0, child_hp=21))
    reply = play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}")
    assert "同心破阵" in reply.title
    row = run(game)
    assert row["rating_id"] == "concord"
    assert sql(game[1], "SELECT COUNT(*) AS n FROM family_duel_rewards")[0]["n"] == 1


def test_win_without_both_actual_skill_uses_keeps_record_but_does_not_award(game, play, monkeypatch):
    ids = prepare(game, play)
    monkeypatch.setattr(family_duel, "fight", scripted(skill_uses=False))
    reply = play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}")
    assert "无额外奖励" in reply.text()
    assert run(game)["outcome"] == "won"
    assert run(game)["rating_id"] is None
    assert not sql(game[1], "SELECT * FROM family_duel_rewards")
    assert len(sql(game[1], "SELECT * FROM battle_records WHERE battle_key LIKE 'family_duel_%'")) == 1


@pytest.mark.parametrize("invalid", ["sibling", "foreign", "archived"])
def test_only_owned_current_direct_parent_and_child_can_enter(game, play, invalid):
    ids = prepare(game, play)
    if invalid == "foreign":
        other = prepare(game, play, "u2")
        parent, child = other[0], other[2]
    elif invalid == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
        parent, child = ids[0], ids[2]
    else:
        parent, child = ids[0], ids[1]
    before = dump(game)
    with pytest.raises(GameError):
        play("family_duel", f"预览 {parent} {child}")
    assert dump(game) == before


def test_weekly_unique_and_clock_gates_do_not_consume_a_failed_attempt(game, play):
    ids = prepare(game, play)
    sql(game[1], "UPDATE players SET last_pve=? WHERE user_id='u1'", (NOW + 60,))
    before = dump(game)
    with pytest.raises(GameError, match="时间"):
        play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}")
    assert dump(game) == before
    sql(game[1], "UPDATE players SET last_pve=NULL WHERE user_id='u1'")
    play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}", op="week-used")
    before = dump(game)
    with pytest.raises(GameError, match="名额"):
        play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}", op="another-op")
    assert dump(game) == before
    assert "已参战" in play("family_duel", user="u1").text()


@pytest.mark.parametrize("target", [
    "family_duel_runs", "family_duel_rewards", "duel_actions", "battle_records",
    "learned_skills", "quest_progress", "pets", "players", "operations",
])
def test_every_major_settlement_boundary_rolls_back_and_can_retry(game, play, monkeypatch, target):
    ids = prepare(game, play)
    monkeypatch.setattr(family_duel, "fight", scripted())
    kind = "UPDATE" if target in {"learned_skills", "pets", "players"} else "INSERT"
    sql(game[1], f"CREATE TRIGGER injected BEFORE {kind} ON {target} BEGIN SELECT RAISE(ABORT,'injected duel failure'); END")
    before = dump(game)
    start = beijing_week(NOW)[0]
    with pytest.raises(sqlite3.IntegrityError, match="injected duel failure"):
        play("family_duel", f"挑战 {start} {ids[0]} {ids[2]}", op="duel-retry")
    assert dump(game) == before
    sql(game[1], "DROP TRIGGER injected")
    reply = play("family_duel", f"挑战 {start} {ids[0]} {ids[2]}", op="duel-retry")
    assert "合战" in reply.title
    assert run(game) is not None


def test_same_user_concurrent_challenges_have_one_battle_and_one_reward(game, play, monkeypatch):
    ids = prepare(game, play)
    monkeypatch.setattr(family_duel, "fight", scripted())
    barrier = threading.Barrier(2)

    def execute(index):
        barrier.wait()
        try:
            return play("family_duel", f"挑战 {beijing_week(NOW)[0]} {ids[0]} {ids[2]}", op=f"concurrent-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sum(not isinstance(value, GameError) for value in results) == 1
    assert len(sql(game[1], "SELECT * FROM family_duel_runs")) == 1
    assert len(sql(game[1], "SELECT * FROM battle_records WHERE battle_key LIKE 'family_duel_%'")) == 1
    assert len(sql(game[1], "SELECT * FROM family_duel_rewards")) == 1


def test_native_actions_are_not_duplicated_and_onebot_uses_the_same_handler(game, play, monkeypatch):
    ids = prepare(game, play, "12345")
    preview = play("family_duel", f"预览 {ids[0]} {ids[2]}", user="12345")
    monkeypatch.setattr(family_duel, "fight", scripted())
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(game_module.time, "time", lambda: NOW)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    command = "!" + preview.commands[0]
    asyncio.run(handlers._run(bot, onebot_event(command, 77), command))
    assert "双契凯旋" in bot.send.call_args.args[1]
    for reply in (preview, play("family_duel", user="12345"), play("family_duel", "记录", user="12345")):
        _, segments = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        markdown = segments["markdown"][0].data["markdown"].content
        links = [parse_qs(urlparse(url).query)["command"][0]
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        buttons = [button.action.data for segment in segments["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert len(buttons) <= 4
        assert not set(links) & set(buttons)
