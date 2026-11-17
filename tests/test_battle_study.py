"""Relay-qualified per-pet study, costs, timed combat effects and transaction safety."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import battle_study, roster_relay
from nonebot_plugin_spirit_pet.gameplay.effects import attack, absorb_ward, finish_action
from nonebot_plugin_spirit_pet.gameplay.combat import fight as actual_fight
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.gameplay.talents import initialize
from nonebot_plugin_spirit_pet.gameplay.fighter_state import pack, unpack
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql
from .test_commands import onebot_event
from .test_roster_relay import command as relay_command
from .test_roster_relay import prepare as prepare_relay
from .test_roster_relay import state as relay_state
from .test_roster_relay import scripted

NOW = 1_800_000_000


def context(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config,
                   game[0].rng, user, now, "battle-study-context")


def eligible_player(game, play, *, user="u1", ore=20, stones=1000):
    play("adopt", "青鸾", user=user)
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]
    sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
        (user, f"relay_study_qualified_{pet_id}"))
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,'forge_ore',?) "
        "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity", (user, ore))
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (stones, user))
    return pet_id


def forge_ore(game, user="u1"):
    row = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id='forge_ore'", (user,))
    return int(row[0]["quantity"]) if row else 0


def study(game, pet_id, user="u1"):
    return battle_study.for_pet(context(game, user=user), pet_id, user)


def database_dump(game):
    with game[1].connect() as conn:
        return tuple(conn.iterdump())


def test_unregistered_page_is_read_only_and_registered_page_shows_costs(game, play):
    reply = play("battle_study", user="ghost")
    assert "尚未结契" in reply.text()
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []
    pet_id = eligible_player(game, play)
    page = play("battle_study")
    assert f"编号 {pet_id}" in page.text()
    assert "锻灵矿 1、灵石 30" in page.text()
    assert "每级获得气血上限 5%" in page.text()
    assert "每级获得攻击 4%" in page.text()
    assert {link.command for link in page.inline_commands} == {
        f"灵宠战研 升级 {pet_id} 守御", f"灵宠战研 升级 {pet_id} 强袭",
    }


def test_only_winning_relay_participants_gain_permanent_eligibility(game, play, monkeypatch):
    ids = prepare_relay(game, play)
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 1 2 3")
    reply = play("roster_relay", relay_command(game))
    assert "本场获胜" in reply.text()
    assert [battle_study.qualified(context(game), pet_id) for pet_id in ids] == [True, False, False]
    assert relay_state(game)["outcomes"][0]["pets"] == [ids[0]]
    assert len(sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'relay_study_qualified_%'")) == 1


def test_upgrade_cost_cap_branch_lock_and_durable_replay(game, play):
    pet_id = eligible_player(game, play)
    before = player(game[1])["stones"]
    first = play("battle_study", f"升级 {pet_id} 守御", op="study-level-1")
    assert "守御战研 1/3级" in first.text()
    assert study(game, pet_id) == ("guard", 1)
    assert forge_ore(game) == 19
    assert player(game[1])["stones"] == before - 30
    sql(game[1], "DELETE FROM operations")
    replay = play("battle_study", f"升级 {pet_id} 守御", op="study-level-1")
    assert replay == first
    assert forge_ore(game) == 19
    assert player(game[1])["stones"] == before - 30
    play("battle_study", f"升级 {pet_id} 守御", op="study-level-2")
    assert study(game, pet_id) == ("guard", 2)
    with pytest.raises(GameError, match="分支固定"):
        play("battle_study", f"升级 {pet_id} 强袭")
    play("battle_study", f"升级 {pet_id} 守御", op="study-level-3")
    assert study(game, pet_id) == ("guard", 3)
    page = play("battle_study")
    assert "已满级" in page.text()
    with pytest.raises(GameError, match="上限"):
        play("battle_study", f"升级 {pet_id} 守御")
    assert forge_ore(game) == 15
    assert player(game[1])["stones"] == before - 190


@pytest.mark.parametrize("ore,stones,message", [
    (0, 1000, "锻灵矿不足"), (1, 29, "灵石不足"),
])
def test_missing_study_cost_refuses_without_mutation(game, play, ore, stones, message):
    pet_id = eligible_player(game, play, ore=ore, stones=stones)
    before = database_dump(game)
    with pytest.raises(GameError, match=message):
        play("battle_study", f"升级 {pet_id} 守御")
    assert database_dump(game) == before


@pytest.mark.parametrize("branch, expected_event", [
    ("守御", "守御战研获得开场护盾"), ("强袭", "强袭战研获得开场攻击增幅"),
])
def test_branches_apply_distinct_effects_for_two_actions(game, play, branch, expected_event):
    pet_id = eligible_player(game, play)
    for level in range(3):
        play("battle_study", f"升级 {pet_id} {branch}", op=f"{branch}-{level}")
    fighter = combatant(context(game), pet_id=pet_id, recover_energy=False)
    base_attack = attack(fighter)
    assert fighter.study_level == 3
    event = initialize(fighter)
    assert expected_event in event
    if branch == "守御":
        expected = int(fighter.stats.hp * 0.15)
        assert fighter.effects.ward.value == expected
        assert absorb_ward(fighter, expected - 1) == expected - 1
        assert fighter.effects.ward.value == 1
    else:
        assert fighter.effects.empower.value == 0.12
        assert attack(fighter) > base_attack
    fighter.turns = 1
    finish_action(fighter)
    assert (fighter.effects.ward if branch == "守御" else fighter.effects.empower) is not None
    fighter.turns = 2
    finish_action(fighter)
    assert (fighter.effects.ward if branch == "守御" else fighter.effects.empower) is None
    if branch == "强袭":
        assert attack(fighter) == base_attack


def test_study_follows_its_pet_after_lead_changes(game, play):
    pet_id = eligible_player(game, play)
    second = sql(game[1], "INSERT INTO pets(user_id,species_id,name,affinity,energy_updated) "
                         "VALUES ('u1','xuanhu','玄狐二号',0,?) RETURNING pet_id", (NOW,))[0]["pet_id"]
    play("battle_study", f"升级 {pet_id} 强袭")
    play("lineup", str(second))
    ctx = context(game)
    trained = combatant(ctx, pet_id=pet_id, recover_energy=False)
    untrained = combatant(ctx, pet_id=second, recover_energy=False)
    assert (trained.study_branch, trained.study_level) == ("assault", 1)
    assert (untrained.study_branch, untrained.study_level) == (None, 0)
    assert initialize(trained) is not None
    assert initialize(untrained) is None


def test_battle_state_round_trips_new_study_and_reads_legacy_snapshots(game, play):
    pet_id = eligible_player(game, play)
    play("battle_study", f"升级 {pet_id} 守御")
    current = pack(combatant(context(game), pet_id=pet_id, recover_energy=False))
    restored = unpack(current)
    assert (restored.study_branch, restored.study_level) == ("guard", 1)

    legacy = dict(current)
    legacy.pop("study_branch")
    legacy.pop("study_level")
    restored_legacy = unpack(legacy)
    assert (restored_legacy.study_branch, restored_legacy.study_level) == (None, 0)


@pytest.mark.parametrize("problem", ["unknown", "foreign", "archived", "expedition", "unqualified", "active_relay"])
def test_unavailable_or_unqualified_targets_reject_without_writes(game, play, problem):
    if problem == "active_relay":
        ids = prepare_relay(game, play)
        target = ids[0]
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
            ("u1", f"relay_study_qualified_{target}"))
        sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',20)")
        play("roster_relay", "开始 1 2 3")
    else:
        pet_id = eligible_player(game, play)
        target = pet_id
    if problem == "unknown":
        target = 999999
    elif problem == "foreign":
        play("adopt", "玄狐", user="u2")
        target = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
    if problem == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (target,))
    elif problem == "expedition":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,"
                     "started_at,finishes_at,state,reward_snapshot) "
                     "VALUES ('u1',?,'gather_herbs','采灵药','study-test',?,?,'running','{}')",
            (target, NOW, NOW + 3600))
    elif problem == "unqualified":
        sql(game[1], "DELETE FROM quest_progress WHERE user_id='u1' AND quest_id=?",
            (f"relay_study_qualified_{target}",))
    before = database_dump(game)
    with pytest.raises(GameError):
        play("battle_study", f"升级 {target} 守御")
    assert database_dump(game) == before


@pytest.mark.parametrize("failure", ["consume", "progress", "journal", "save"])
def test_write_failures_roll_back_resources_study_and_reply(game, play, monkeypatch, failure):
    pet_id = eligible_player(game, play, ore=4, stones=300)
    if failure == "progress":
        sql(game[1], f"CREATE TRIGGER fail_study BEFORE INSERT ON quest_progress "
                     f"WHEN NEW.quest_id='relay_study_{pet_id}_guard' "
                     "BEGIN SELECT RAISE(ABORT,'injected'); END")
    elif failure in {"consume", "journal", "save"}:
        name = {"consume": "consume_item", "journal": "record_duel_action", "save": "save"}[failure]
        original = getattr(Repository, name)

        def fail_after_write(*args, **kwargs):
            result = original(*args, **kwargs)
            raise RuntimeError("injected")

        monkeypatch.setattr(Repository, name, fail_after_write)
    before = database_dump(game)
    expected = sqlite3.IntegrityError if failure == "progress" else RuntimeError
    with pytest.raises(expected, match="injected"):
        play("battle_study", f"升级 {pet_id} 守御", op=f"fail-{failure}")
    assert database_dump(game) == before
    if failure == "progress":
        sql(game[1], "DROP TRIGGER fail_study")
    elif failure in {"consume", "journal", "save"}:
        monkeypatch.undo()
    reply = play("battle_study", f"升级 {pet_id} 守御", op=f"fail-{failure}")
    assert "完成守御战研 1/3级" in reply.text()
    assert study(game, pet_id) == ("guard", 1)


def test_concurrent_next_level_spends_are_serial_and_conserve_resources(game, play):
    pet_id = eligible_player(game, play, ore=3, stones=90)
    play("battle_study", f"升级 {pet_id} 守御", op="concurrent-initial")

    def upgrade(index):
        try:
            return play("battle_study", f"升级 {pet_id} 守御", op=f"concurrent-{index}")
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(upgrade, range(2)))
    assert sum(isinstance(reply, GameError) for reply in replies) == 1
    assert study(game, pet_id) == ("guard", 2)
    assert forge_ore(game) == 0
    assert player(game[1])["stones"] == 0


def test_restart_preserves_study_and_later_relay_battle_snapshot(game, play, monkeypatch):
    ids = prepare_relay(game, play)
    sql(game[1], "UPDATE pets SET realm=3,layer=5")
    monkeypatch.setattr(roster_relay, "fight", scripted())
    play("roster_relay", "开始 1 2 3", op="relay-one")
    for index in range(3):
        play("roster_relay", relay_command(game), op=f"clear-{index}", now=NOW + index * 600)
    assert [battle_study.qualified(context(game), pet_id) for pet_id in ids] == [True, True, True]
    assert forge_ore(game) == 5
    play("battle_study", f"升级 {ids[0]} 守御", op="study-1", now=NOW + 1800)
    play("battle_study", f"升级 {ids[0]} 守御", op="study-2", now=NOW + 1801)
    play("battle_study", f"升级 {ids[0]} 守御", op="study-3", now=NOW + 1802)
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    page = restarted.execute("u1", "battle_study", "", "study-page-restart", NOW + 1803)
    assert "守御 3/3级" in page.text()

    play("roster_relay", "开始 1 2 3", op="relay-two", now=NOW + 1803)
    seen = []

    def capture_study(allies, enemies, rng, elements, **kwargs):
        seen.extend((fighter.pet_id, fighter.study_branch, fighter.study_level) for fighter in allies)
        return actual_fight(allies, enemies, rng, elements, **kwargs)

    monkeypatch.setattr(roster_relay, "fight", capture_study)
    reply = restarted.execute("u1", "roster_relay", relay_command(game), "relay-two-stage-1", NOW + 2400)
    assert seen == [(ids[0], "guard", 3)]
    assert "守御战研获得开场护盾" in reply.text()
    records = sql(game[1], "SELECT snapshot,battle_log FROM battle_records WHERE battle_key LIKE 'relay_%' "
                           "ORDER BY battle_id DESC LIMIT 1")
    snapshot = json.loads(records[0]["snapshot"])
    assert snapshot["teams"][0]["members"][0]["battle_study"] == {
        "branch": "guard", "name": "守御", "level": 3,
    }
    assert "守御战研" in json.loads(records[0]["battle_log"])[0]


def test_onebot_and_qq_study_contracts_share_the_same_commands(game, play, monkeypatch):
    user = "12345"
    pet_id = eligible_player(game, play, user=user)
    reply = play("battle_study", user=user)
    assert {link.command for link in reply.inline_commands} == {
        f"灵宠战研 升级 {pet_id} 守御", f"灵宠战研 升级 {pet_id} 强袭",
    }
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    assert message
    for link in reply.inline_commands:
        assert handlers._parse(link.command)[0] == "battle_study"

    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event(f"!灵宠战研 升级 {pet_id} 守御", 81),
                            f"!灵宠战研 升级 {pet_id} 守御")

    asyncio.run(run())
    assert "完成守御战研 1/3级" in bot.send.call_args.args[1]
    assert study(game, pet_id, user) == ("guard", 1)
    assert sql(store, "SELECT COUNT(*) AS count FROM duel_actions WHERE user_id='12345' "
                     "AND json_extract(snapshot,'$.kind')='partner_battle_study'") == [{"count": 1}]
