"""Frozen disjoint plans, finite rewards and transactional relay recovery."""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import roster_relay
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql
from .test_commands import onebot_event
from .test_lineup_presets import add_pet, seed_tactical_plan, switch_to_ungeared_configuration

NOW = 1_800_000_000


def prepare(game, play, user="u1"):
    play("adopt", "青鸾", user=user)
    ids = [sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"],
           add_pet(game, "xuanhu", "玄狐", user), add_pet(game, "baize", "白泽", user)]
    for slot, pet_id in enumerate(ids, 1):
        play("lineup", str(pet_id), user=user)
        play("lineup_presets", f"保存 {slot}", user=user)
    return ids


def state(game, user="u1"):
    return json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE user_id=? "
                          "AND json_extract(snapshot,'$.kind')='roster_relay' ORDER BY action_id DESC LIMIT 1",
                          (user,))[0]["snapshot"])


def command(game, verb="出战"):
    current = state(game)
    return f"{verb} {current['run']} {current['stage'] + 1}"


def scripted(winner=0, seen=None):
    def run(allies, enemies, rng, elements, **kwargs):
        if seen is not None:
            seen.append(([unit.pet_id for unit in allies], [unit.stats for unit in enemies], kwargs))
        return Battle(winner, 2, ("scripted battle",), ({}, {}))
    return run


def dump(game):
    with game[1].connect() as conn:
        return tuple(conn.iterdump())


def test_page_and_registration_are_read_only(game, play):
    reply = play("roster_relay", user="ghost")
    assert "尚未结契" in reply.text()
    assert sql(game[1], "SELECT * FROM players") == []
    assert handlers._parse("灵宠轮战 开始 3 1 2") == ("roster_relay", "开始 3 1 2")
    assert "灵宠轮战" in play("help", "秘境与关卡").text()
    assert not re.search(r"/灵宠", reply.text())


def test_page_opens_only_after_three_valid_disjoint_presets(game, play):
    prepare(game, play)
    page = play("roster_relay")
    assert [link.command for link in page.inline_commands] == ["灵宠轮战 开始 1 2 3"]
    play("lineup_presets", "保存 1")
    page = play("roster_relay")
    assert not page.inline_commands
    assert "重复伙伴" in page.text()


def test_three_real_encounters_use_frozen_order_and_persist_rewards(game, play, monkeypatch):
    ids = prepare(game, play)
    sql(game[1], "UPDATE pets SET realm=3,layer=5")
    before = player(game[1])["stones"]
    ore = items(game[1]).get("forge_ore", 0)
    play("roster_relay", "开始 3 1 2")
    for index, pet_id in enumerate([ids[2], ids[0], ids[1]]):
        reply = play("roster_relay", command(game), now=NOW + index * 600)
        assert f"已胜 {index + 1}/3" in reply.text()
        row = sql(game[1], "SELECT active_pet_id FROM players")[0]
        assert row["active_pet_id"] == pet_id
    assert state(game)["status"] == "completed"
    assert player(game[1])["stones"] - before == 280
    assert items(game[1])["forge_ore"] - ore == 5
    assert [row["exp"] for row in sql(game[1], "SELECT exp FROM pets ORDER BY pet_id")] == [40, 80, 40]
    records = sql(game[1], "SELECT snapshot FROM battle_records WHERE battle_key LIKE 'relay_%' ORDER BY battle_id")
    assert len(records) == 3
    snapshots = [json.loads(row["snapshot"]) for row in records]
    assert [len(snapshot["teams"][1]["members"]) for snapshot in snapshots] == [3, 1, 1]
    assert [snapshot["teams"][0]["members"][0]["species_id"] for snapshot in snapshots] == [
        "baize", "qingluan", "xuanhu",
    ]
    assert [snapshot["scenario"]["name"] for snapshot in snapshots] == [
        "轮战·群敌", "轮战·重甲", "轮战·速攻",
    ]
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []
    # Rewards cannot be farmed by starting another run in the same week.
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 1 2 3", now=NOW + 1800)
    for index in range(3):
        reply = play("roster_relay", command(game), now=NOW + 1800 + index * 600)
        assert "本周该项奖励已领取" in reply.text()
    assert player(game[1])["stones"] - before == 280
    assert items(game[1])["forge_ore"] - ore == 5


def test_presets_and_content_overwrites_do_not_change_a_run(game, play, monkeypatch):
    ids = prepare(game, play)
    seen = []
    play("roster_relay", "开始 1 2 3")
    original = state(game)
    play("lineup_presets", "保存 1")
    game[0].content.enemies["wood_guard"] = game[0].content.enemies["moon_wolf"]
    monkeypatch.setattr(roster_relay, "ENERGY", 99)
    monkeypatch.setattr(roster_relay, "fight", scripted(seen=seen))
    reply = play("roster_relay", command(game))
    assert seen[0][0] == [ids[0]]
    assert len(seen[0][1]) == 3
    assert seen[0][1][0].hp == original["stages"][0]["enemies"][0]["stats"]["hp"]
    assert "精力 -10" in reply.text()
    assert state(game)["stages"] == original["stages"]


@pytest.mark.parametrize("winner", [1, -1])
def test_defeat_and_draw_charge_once_keep_prior_rewards(game, play, monkeypatch, winner):
    ids = prepare(game, play)
    play("roster_relay", "开始 1 2 3")
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", command(game))
    before = player(game[1])["stones"]
    monkeypatch.setattr(roster_relay, "fight", scripted(winner))
    reply = play("roster_relay", command(game), now=NOW + 600)
    assert "本场未通过" in reply.text()
    assert state(game)["status"] == "defeated"
    assert player(game[1])["stones"] == before
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (ids[1],))[0]["energy"] == 90


def test_restart_cache_expiry_old_buttons_and_clock(game, play, monkeypatch):
    prepare(game, play)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    first = play("roster_relay", "开始 1 2 3", op="start")
    cmd = command(game)
    won = play("roster_relay", cmd, op="won")
    before = state(game)
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    assert restarted.execute("u1", "roster_relay", "开始 1 2 3", "start", NOW + 1) == first
    assert restarted.execute("u1", "roster_relay", cmd, "won", NOW + 1) == won
    assert state(game) == before
    with pytest.raises(GameError, match="过期"):
        play("roster_relay", cmd, op="stale")
    with pytest.raises(GameError, match="时间早于"):
        play("roster_relay", command(game), now=NOW - 1)
    abandoned = play("roster_relay", command(game, "放弃"), op="abandon")
    play("roster_relay", "开始 1 2 3", now=NOW + 1)
    sql(game[1], "DELETE FROM operations")
    assert play("roster_relay", "ignored", op="abandon") == abandoned
    with pytest.raises(GameError, match="过期"):
        play("roster_relay", cmd)
    with pytest.raises(GameError, match="different user"):
        play("roster_relay", cmd, user="other", op="won")


def test_restart_can_continue_at_the_next_frozen_stage(game, play, monkeypatch):
    prepare(game, play)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 2 3 1", op="start")
    play("roster_relay", command(game), op="stage-one")
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    reply = restarted.execute("u1", "roster_relay", command(game), "stage-two", NOW + 600)
    assert "第 2 场 · 重甲" in reply.text()
    assert state(game)["stage"] == 2
    assert state(game)["stages"][2]["plan"]["slot"] == 1


def test_concurrent_stage_commands_settle_only_once(game, play, monkeypatch):
    prepare(game, play)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 1 2 3")
    cmd = command(game)
    before = player(game[1])["stones"]
    def run(index):
        try:
            return play("roster_relay", cmd, op=f"race-{index}")
        except GameError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(isinstance(value, str) for value in results) == 1
    assert any("过期" in value for value in results if isinstance(value, str))
    assert state(game)["stage"] == 1
    assert player(game[1])["stones"] - before == 60


def test_active_run_blocks_a_second_start_and_round_limit_is_decisive(game, play, monkeypatch):
    prepare(game, play)
    play("roster_relay", "开始 1 2 3")
    before = dump(game)
    with pytest.raises(GameError, match="已有轮战"):
        play("roster_relay", "开始 3 2 1")
    assert dump(game) == before
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", command(game))
    play("roster_relay", command(game), now=NOW + 600)
    seen = []
    def over_limit(allies, enemies, rng, elements, **kwargs):
        seen.append(kwargs["max_rounds"])
        return Battle(0, 9, ("over limit",), ({}, {}))
    monkeypatch.setattr(roster_relay, "fight", over_limit)
    reply = play("roster_relay", command(game), now=NOW + 1200)
    assert seen == [8]
    assert "本场未通过" in reply.text()
    assert state(game)["status"] == "defeated"


@pytest.mark.parametrize("problem", ["archived", "owner", "energy", "expedition", "cooldown", "skill"])
def test_unavailable_plan_rejects_without_writes_and_can_abandon(game, play, problem):
    ids = prepare(game, play)
    play("roster_relay", "开始 1 2 3")
    if problem == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids[0],))
    elif problem == "owner":
        play("adopt", "青鸾", user="u2")
        sql(game[1], "UPDATE pets SET user_id='u2' WHERE pet_id=?", (ids[0],))
    elif problem == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (ids[0],))
    elif problem == "cooldown":
        sql(game[1], "UPDATE players SET last_pve=?", (NOW,))
    elif problem == "skill":
        # The opening plan originally contains this real learned skill.
        sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)", (ids[0],))
        play("roster_relay", command(game, "放弃"))
        play("lineup", str(ids[0]))
        play("lineup_presets", "保存 1")
        play("roster_relay", "开始 1 2 3")
        sql(game[1], "DELETE FROM learned_skills WHERE pet_id=?", (ids[0],))
    else:
        # Existing expedition contract through its actual gameplay entry.
        play("lineup", str(ids[0]))
        play("expedition_start", next(iter(game[0].content.expeditions)))
    before = dump(game)
    with pytest.raises(GameError):
        play("roster_relay", command(game))
    assert dump(game) == before
    reply = play("roster_relay", command(game, "放弃"))
    assert "已放弃" in reply.text()
    assert state(game)["status"] == "abandoned"


@pytest.mark.parametrize("point", ["gear", "reward", "report", "journal", "save"])
def test_failure_rolls_back_configuration_resources_state_and_reply(game, play, monkeypatch, point):
    first, second, third, slot, gear, skill = seed_tactical_plan(game, play)
    play("lineup", str(third))
    play("lineup_presets", "保存 2")
    fourth = add_pet(game, "qilin", "麒麟")
    play("lineup", str(fourth))
    play("lineup_presets", "保存 3")
    play("roster_relay", "开始 1 2 3")
    play("lineup", str(first))
    switch_to_ungeared_configuration(game, play, first, third, slot, gear, skill)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    if point == "gear":
        from nonebot_plugin_spirit_pet.gameplay import lineup_presets
        target, name = lineup_presets, "take"
    elif point == "reward":
        target, name = roster_relay, "grant"
    else:
        target, name = Repository, {"report": "record_battle", "journal": "record_duel_action", "save": "save"}[point]
    original = getattr(target, name)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected")
    monkeypatch.setattr(target, name, fail)
    before = dump(game)
    with pytest.raises(RuntimeError, match="injected"):
        play("roster_relay", command(game), op="failure")
    assert dump(game) == before
    monkeypatch.setattr(target, name, original)
    reply = play("roster_relay", command(game), op="failure")
    assert "已胜 1/3" in reply.text()
    assert state(game)["stage"] == 1


def test_start_validates_legacy_overlap_bad_arguments_and_replays(game, play):
    prepare(game, play)
    for arg in ("开始", "开始 1 1 2", "出战", "放弃 x 9", "其他"):
        with pytest.raises(GameError):
            play("roster_relay", arg)
    play("lineup_presets", "保存 1")
    with pytest.raises(GameError, match="重复"):
        play("roster_relay", "开始 1 2 3")
    sql(game[1], "DELETE FROM quest_progress WHERE quest_id LIKE 'lineup_tactic_%'")
    with pytest.raises(GameError, match="旧版"):
        play("roster_relay", "开始 1 2 3")


def test_cross_week_continuation_keeps_entry_week_rewards(game, play, monkeypatch):
    prepare(game, play)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 1 2 3")
    week = state(game)["week"]
    play("roster_relay", command(game), now=NOW + 7 * 86400)
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'relay_reward_%'") == [
        {"quest_id": f"relay_reward_{week}_1"}]


def test_qq_links_and_buttons_have_no_duplicate_actions(game, play):
    prepare(game, play)
    reply = play("roster_relay", "开始 1 2 3")
    assert len(reply.commands) == len(set(reply.commands))
    assert not set(reply.commands) & {link.command for link in reply.inline_commands}
    segments = _qq_segments(reply, Config(spirit_pet_markdown=True))
    assert segments
    for link in reply.inline_commands:
        action, arg = handlers._parse(link.command)
        assert action == "roster_relay" and arg


def test_onebot_dispatch_uses_the_same_started_relay_state(game, play, monkeypatch):
    prepare(game, play, user="12345")
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠轮战 开始 1 2 3", 70), "!灵宠轮战 开始 1 2 3")

    asyncio.run(run())
    message = bot.send.call_args.args[1]
    assert "轮战已开启" in message
    assert state(game, "12345")["status"] == "active"
    assert sql(store, "SELECT COUNT(*) AS count FROM duel_actions WHERE user_id='12345' "
                     "AND json_extract(snapshot,'$.kind')='roster_relay'") == [{"count": 1}]
