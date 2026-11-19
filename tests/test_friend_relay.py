"""Friend relay consent, real combat, immutable reports and atomic settlement."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import friend_relay
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, player_uid, sql
from .test_cave_coop import buttons, links
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def setup(game, play, now=NOW):
    for user, name in (("u1", "青鸾"), ("u2", "玄狐")):
        play("adopt", name, user=user, now=now)
        sql(game[1], "UPDATE players SET stones=10000 WHERE user_id=?", (user,))
        skill = "风刃术" if user == "u1" else "赤焰术"
        play("buy", skill + "诀", user=user, now=now)
        play("learn", skill, user=user, now=now)
        sql(game[1], "UPDATE players SET stones=100 WHERE user_id=?", (user,))
    uid = player_uid(game[1], "u2")
    play("friends", f"添加 {uid}", now=now)
    play("friends", f"同意 {player_uid(game[1], 'u1')}", user="u2", now=now)
    sql(game[1], "UPDATE pets SET realm=3,layer=5,energy=100,energy_updated=?", (now,))
    pets = {row["user_id"]: row["pet_id"] for row in sql(game[1], "SELECT user_id,pet_id FROM pets")}
    return uid, pets


def state(game):
    return json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='friend_relay' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


def ready(game, play, uid, pets, now=NOW):
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=now, op=f"invite-{now}")
    run_id = state(game)["run_id"]
    play("friend_relay", f"同意 {run_id} {pets['u2']}", user="u2", now=now + 1, op=f"accept-{now}")
    return run_id


def world(game):
    with closing(game[1].connect()) as conn:
        return tuple(conn.iterdump())


def slots(game):
    return sql(game[1], "SELECT user_id,quest_id,progress FROM quest_progress WHERE quest_id LIKE 'friend_relay_week_%' ORDER BY user_id,quest_id")


def test_preview_and_views_do_not_write_and_invite_never_charges_other_player(game, play):
    before = world(game)
    assert "先领养" in play("friend_relay", user="new").text()
    assert world(game) == before
    uid, pets = setup(game, play)
    before = world(game)
    preview = play("friend_relay", f"预览 青岚林 {pets['u1']} {uid}")
    assert "精力 20" in preview.text() and "调息 600 秒" in preview.text()
    assert "邀请不扣精力" in preview.text()
    assert world(game) == before
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    run = state(game)
    assert run["status"] == "pending" and not slots(game)
    assert sql(game[1], "SELECT energy FROM pets") == [{"energy": 100}, {"energy": 100}]
    assert player(game[1], "u2")["last_pve"] is None
    before = world(game)
    play("friend_relay", user="u2")
    play("friend_relay", f"详情 {run['run_id']}")
    play("friend_relay", "记录")
    assert world(game) == before


def test_two_real_legs_settle_only_after_two_wins_for_original_pets(game, play):
    uid, pets = setup(game, play)
    run = ready(game, play, uid, pets)
    before_stones = {user: player(game[1], user)["stones"] for user in pets}
    before_exp = {row["pet_id"]: row["exp"] for row in sql(game[1], "SELECT pet_id,exp FROM pets")}
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    first = play("friend_relay", f"出战 {run} 1", now=NOW + 2, op="leg-one")
    assert "第一棒获胜" in first.text()
    assert state(game)["status"] == "second"
    assert {user: player(game[1], user)["stones"] for user in pets} == before_stones
    assert [row["energy"] for row in sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")] == [80, 100]
    second = play("friend_relay", f"出战 {run} 2", user="u2", now=NOW + 3, op="leg-two")
    assert "两棒全胜" in second.title
    result = state(game)
    assert result["status"] == "completed" and len(result["outcomes"]) == 2
    for user, pet_id in pets.items():
        assert player(game[1], user)["stones"] - before_stones[user] == 40
        assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (pet_id,))[0]["exp"] - before_exp[pet_id] == 35
        assert items(game[1], user)["forge_ore"] == 1
        assert player(game[1], user)["active_pet_id"] is None
        assert player(game[1], user)["last_pve"] == NOW + (2 if user == "u1" else 3)
        assert "两棒全胜" in play("friend_relay", "记录", user=user, now=NOW + 4).text()
        for leg in result["outcomes"]:
            assert "接力·青岚林" in play("battle_reports", f"查看 {leg['report_id']}", user=user, now=NOW + 4).text()
    assert len(slots(game)) == 2
    assert sql(game[1], "SELECT 1 FROM pve_stage_progress") == []
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == 2
    assert all(leg["last_pve_before"] is None and leg["energy"] == 20 for leg in result["outcomes"])
    with pytest.raises(GameError, match="本周接力名额"):
        play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=NOW + 5)


@pytest.mark.parametrize("leg", [1, 2])
def test_real_defeat_or_draw_ends_run_without_final_rewards(game, play, leg):
    uid, pets = setup(game, play)
    sql(game[1], "UPDATE pets SET realm=0,layer=1,affinity=0 WHERE pet_id=?", (pets[f"u{leg}"],))
    enemy = game[0].content.enemies["wood_guard"]
    game[0].content.enemies["wood_guard"] = enemy.model_copy(update={"stats": enemy.stats.model_copy(update={"hp": 1000, "attack": 100, "defense": 100, "speed": 1})})
    run = ready(game, play, uid, pets)
    before = {user: player(game[1], user)["stones"] for user in pets}
    if leg == 2:
        play("friend_relay", f"出战 {run} 1", now=NOW + 2)
    reply = play("friend_relay", f"出战 {run} {leg}", user=f"u{leg}", now=NOW + 3)
    assert "无终章奖励" in reply.text()
    assert state(game)["status"] == "defeated"
    assert state(game)["outcomes"][-1]["winner"] in (-1, 1)
    assert len(state(game)["outcomes"]) == leg
    assert {user: player(game[1], user)["stones"] for user in pets} == before
    assert len(slots(game)) == 2


def test_frozen_combat_and_mastery_survive_loadout_content_and_stats_changes(game, play):
    uid, pets = setup(game, play)
    run = ready(game, play, uid, pets)
    frozen = state(game)
    assert frozen["fighters"][0]["skills"]
    sql(game[1], "UPDATE pets SET realm=0,layer=1,affinity=0")
    sql(game[1], "UPDATE learned_skills SET equipped=0")
    enemy = game[0].content.enemies["wood_guard"]
    game[0].content.enemies["wood_guard"] = enemy.model_copy(update={"stats": enemy.stats.model_copy(update={"hp": 100000, "attack": 100000})})
    dungeon = game[0].content.dungeons["forest"]
    game[0].content.dungeons["forest"] = dungeon.model_copy(update={"energy": 99, "reward": game[0].content.dungeons["moon"].reward})
    game[0].config.spirit_pet_pve_cooldown = 99999
    for leg, user in ((1, "u1"), (2, "u2")):
        play("friend_relay", f"出战 {run} {leg}", user=user, now=NOW + leg + 1)
    assert state(game)["status"] == "completed"
    assert state(game)["fighters"] == frozen["fighters"]
    assert state(game)["outcomes"][0]["mastery"]
    assert all(row["proficiency"] > 0 for row in sql(game[1], "SELECT proficiency FROM learned_skills"))
    for row in sql(game[1], "SELECT snapshot FROM battle_records ORDER BY battle_id"):
        capture = json.loads(row["snapshot"])
        assert capture["teams"][0]["members"][0]["realm"] == 3
        assert capture["teams"][1]["members"][0]["stats"] == frozen["enemies"][0]["stats"]
    assert player(game[1], "u1")["stones"] == 140


def test_roles_old_stage_and_nonparticipant_report_permissions(game, play):
    uid, pets = setup(game, play)
    play("adopt", user="u3")
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    run = state(game)["run_id"]
    for user, action in (("u1", f"同意 {run} {pets['u1']}"), ("u1", f"拒绝 {run}"), ("u3", f"详情 {run}"), ("u3", f"退出 {run}")):
        before = world(game)
        with pytest.raises(GameError):
            play("friend_relay", action, user=user, now=NOW + 1)
        assert world(game) == before
    play("friend_relay", f"同意 {run} {pets['u2']}", user="u2", now=NOW + 2)
    for user, stage in (("u2", 1), ("u1", 2)):
        before = world(game)
        with pytest.raises(GameError):
            play("friend_relay", f"出战 {run} {stage}", user=user, now=NOW + 3)
        assert world(game) == before
    play("friend_relay", f"出战 {run} 1", now=NOW + 4)
    before = world(game)
    with pytest.raises(GameError, match="棒次已过期"):
        play("friend_relay", f"出战 {run} 1", now=NOW + 5)
    with pytest.raises(GameError):
        play("battle_reports", f"查看 {state(game)['outcomes'][0]['report_id']}", user="u3", now=NOW + 5)
    assert world(game) == before


def test_decline_expiry_exit_and_friendship_loss_keep_actual_costs(game, play):
    uid, pets = setup(game, play)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    play("friend_relay", f"拒绝 {state(game)['run_id']}", user="u2", now=NOW + 1)
    assert state(game)["status"] == "rejected" and not slots(game)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=NOW + 2)
    expired = state(game)["run_id"]
    before = world(game)
    assert "邀请到期" in play("friend_relay", now=NOW + 2 + 86400).text()
    assert world(game) == before
    play("friend_relay", f"同意 {expired} {pets['u2']}", user="u2", now=NOW + 2 + 86400)
    assert state(game)["status"] == "expired" and not slots(game)
    run = ready(game, play, uid, pets, now=NOW + 86410)
    play("friend_relay", f"出战 {run} 1", now=NOW + 86412)
    play("friends", f"解除 {uid}", now=NOW + 86413)
    before = world(game)
    with pytest.raises(GameError, match="解除好友"):
        play("friend_relay", f"出战 {run} 2", user="u2", now=NOW + 86414)
    assert world(game) == before
    play("friend_relay", f"退出 {run}", user="u2", now=NOW + 86415)
    assert state(game)["status"] == "cancelled"
    assert len(state(game)["outcomes"]) == 1 and len(slots(game)) == 2
    assert player(game[1], "u1")["last_pve"] == NOW + 86412
    assert player(game[1], "u2")["last_pve"] is None


def test_entry_gates_single_dungeons_realm_friendship_and_active_slot(game, play):
    uid, pets = setup(game, play)
    for dungeon, message in (("上古灵殿", "单人秘境"), ("九霄劫海", "境界不足")):
        before = world(game)
        with pytest.raises(GameError, match=message):
            play("friend_relay", f"邀请 {dungeon} {pets['u1']} {uid}")
        assert world(game) == before
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    with pytest.raises(GameError, match="进行中的接力"):
        play("friend_relay", f"邀请 青岚林 {pets['u2']} {player_uid(game[1], 'u1')}", user="u2")
    play("friends", f"解除 {uid}", now=NOW + 1)
    before = world(game)
    with pytest.raises(GameError, match="解除好友"):
        play("friend_relay", f"同意 {state(game)['run_id']} {pets['u2']}", user="u2", now=NOW + 2)
    assert world(game) == before


@pytest.mark.parametrize("gate", ["archived", "owner", "dispatch", "energy", "cooldown"])
def test_participant_availability_and_shared_pve_costs_are_rechecked(game, play, gate):
    uid, pets = setup(game, play)
    run = ready(game, play, uid, pets)
    if gate == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pets["u1"],))
    elif gate == "owner":
        sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
        sql(game[1], "DELETE FROM active_pet_slots WHERE pet_id=?", (pets["u1"],))
        sql(game[1], "UPDATE pets SET user_id='u2' WHERE pet_id=?", (pets["u1"],))
    elif gate == "dispatch":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) VALUES ('u1',?,'herb_gathering','采灵药','relay-dispatch',?,?,'running','{}')", (pets["u1"], NOW, NOW + 3600))
    elif gate == "energy":
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=?", (NOW, pets["u1"]))
    else:
        play("challenge", "青岚林", now=NOW + 1)
    before = world(game)
    with pytest.raises(GameError):
        play("friend_relay", f"出战 {run} 1", now=NOW + 2)
    assert world(game) == before
    if gate == "archived":
        sql(game[1], "UPDATE pets SET archived=0 WHERE pet_id=?", (pets["u1"],))
        assert "第一棒获胜" in play("friend_relay", f"出战 {run} 1", now=NOW + 3).text()


def test_cross_week_restart_reserves_acceptance_week_and_permanent_receipts(game, play):
    end = beijing_week(NOW)[1]
    uid, pets = setup(game, play, now=end - 30)
    run = ready(game, play, uid, pets, now=end - 20)
    first = play("friend_relay", f"出战 {run} 1", now=end - 10, op="replay-first")
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, rng=game[0].rng, content=game[0].content)
    before = world(game)
    assert restarted.execute("u1", "friend_relay", f"出战 {run} 1", "replay-first", end + 10) == first
    # Durable replay restores the complete reply, including its navigation.
    assert len(first.commands) == 4
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == 1
    with pytest.raises(GameError, match="different user"):
        restarted.execute("u2", "friend_relay", f"出战 {run} 1", "replay-first", end + 10)
    restarted.execute("u2", "friend_relay", f"出战 {run} 2", "second-after-restart", end + 20)
    assert state(game)["status"] == "completed" and state(game)["week"] == end - 7 * 86400
    assert all(row["quest_id"].endswith(str(end - 7 * 86400)) for row in slots(game))
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=end + 30)
    second_run = state(game)["run_id"]
    play("friend_relay", f"同意 {second_run} {pets['u2']}", user="u2", now=end + 31)
    assert len(slots(game)) == 4
    assert before != world(game)


@pytest.mark.parametrize("failure", ["slot", "accept-receipt", "report", "participant", "mastery", "reward", "player", "pet", "receipt"])
def test_write_boundaries_roll_back_entire_transition(game, play, failure):
    uid, pets = setup(game, play)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    run = state(game)["run_id"]
    accept_action = f"同意 {run} {pets['u2']}"
    if failure not in {"slot", "accept-receipt"}:
        play("friend_relay", accept_action, user="u2", now=NOW + 1)
        play("friend_relay", f"出战 {run} 1", now=NOW + 2)
    triggers = {
        "slot": "BEFORE INSERT ON quest_progress WHEN NEW.quest_id LIKE 'friend_relay_week_%' AND NEW.user_id='u2'",
        "accept-receipt": "BEFORE INSERT ON duel_actions WHEN json_extract(NEW.snapshot,'$.kind')='friend_relay' AND json_extract(NEW.snapshot,'$.status')='first'",
        "report": "BEFORE INSERT ON battle_records",
        "participant": "BEFORE INSERT ON battle_participants WHEN NEW.user_id='u2'",
        "mastery": f"BEFORE UPDATE ON learned_skills WHEN NEW.pet_id={pets['u2']}",
        "reward": "BEFORE INSERT ON inventory WHEN NEW.user_id='u2' AND NEW.item_id='forge_ore'",
        "player": "BEFORE UPDATE ON players WHEN NEW.user_id='u2'",
        "pet": f"BEFORE UPDATE ON pets WHEN NEW.pet_id={pets['u2']}",
        "receipt": "BEFORE INSERT ON duel_actions WHEN json_extract(NEW.snapshot,'$.kind')='friend_relay' AND json_extract(NEW.snapshot,'$.status')='completed'",
    }
    sql(game[1], f"CREATE TRIGGER fail_relay {triggers[failure]} BEGIN SELECT RAISE(ABORT,'injected relay failure'); END")
    before = world(game)
    with pytest.raises(Exception, match="injected relay failure"):
        play("friend_relay", accept_action if failure in {"slot", "accept-receipt"} else f"出战 {run} 2", user="u2", now=NOW + 3)
    assert world(game) == before


def test_duplicate_second_leg_race_grants_and_records_once(game, play):
    uid, pets = setup(game, play)
    run = ready(game, play, uid, pets)
    play("friend_relay", f"出战 {run} 1", now=NOW + 2)
    barrier = Barrier(2)

    def execute(op):
        barrier.wait(timeout=10)
        try:
            return game[0].execute("u2", "friend_relay", f"出战 {run} 2", op, NOW + 3)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(execute, "race-a"), pool.submit(execute, "race-b")
        results = a.result(), b.result()
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert state(game)["status"] == "completed"
    assert player(game[1], "u1")["stones"] == player(game[1], "u2")["stones"] == 140
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == 2


def test_accept_exit_race_never_leaves_half_a_weekly_reservation(game, play):
    uid, pets = setup(game, play)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    run = state(game)["run_id"]
    barrier = Barrier(2)

    def execute(user, action, op):
        barrier.wait(timeout=10)
        try:
            return game[0].execute(user, "friend_relay", action, op, NOW + 1)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(execute, "u2", f"同意 {run} {pets['u2']}", "race-accept")
        b = pool.submit(execute, "u1", f"退出 {run}", "race-exit")
        results = a.result(), b.result()
    assert sum(isinstance(result, GameError) for result in results) <= 1
    result = state(game)
    assert result["status"] == "cancelled"
    assert len(slots(game)) == (2 if result["accepted_at"] is not None else 0)
    assert sql(game[1], "SELECT energy FROM pets") == [{"energy": 100}, {"energy": 100}]
    assert sql(game[1], "SELECT 1 FROM battle_records") == []


def test_invitation_accepted_after_week_change_uses_new_week_and_corrupt_capture_fails_closed(game, play):
    end = beijing_week(NOW)[1]
    uid, pets = setup(game, play, now=end - 20)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=end - 10)
    run = state(game)["run_id"]
    play("friend_relay", f"同意 {run} {pets['u2']}", user="u2", now=end + 1)
    assert state(game)["week"] == end
    assert all(row["quest_id"].endswith(str(end)) for row in slots(game))
    snapshot = state(game)
    snapshot["captures"][0]["teams"][0]["members"][0]["stats"]["attack"] += 1
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE action_id=(SELECT MAX(action_id) FROM duel_actions)", (json.dumps(snapshot),))
    before = world(game)
    with pytest.raises(GameError, match="损坏"):
        play("friend_relay", f"出战 {run} 1", now=end + 2)
    assert world(game) == before


def test_rollback_clock_corrupt_snapshot_and_paged_bilateral_history(game, play):
    uid, pets = setup(game, play)
    for index in range(6):
        play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=NOW + index * 2)
        play("friend_relay", f"拒绝 {state(game)['run_id']}", user="u2", now=NOW + index * 2 + 1)
    assert "第 1/2 页" in play("friend_relay", "记录", now=NOW + 12).text()
    assert "第 2/2 页" in play("friend_relay", "记录 2", user="u2", now=NOW + 12).text()
    before = world(game)
    with pytest.raises(GameError, match="时间早于"):
        play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}", now=NOW)
    assert world(game) == before
    run = state(game)
    del run["reward"]
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE action_id=(SELECT MAX(action_id) FROM duel_actions)", (json.dumps(run),))
    before = world(game)
    with pytest.raises(GameError, match="损坏"):
        play("friend_relay", "记录", now=NOW + 13)
    assert world(game) == before


def test_qq_buttons_blue_links_and_objectives_are_role_scoped(game, play):
    uid, pets = setup(game, play)
    play("friend_relay", f"邀请 青岚林 {pets['u1']} {uid}")
    run = state(game)["run_id"]
    page = play("friend_relay", user="u2")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    commands = [button.action.data.removeprefix("/") for button in buttons(message)]
    blue = [data["command"][0].removeprefix("/") for _, data in links(message)]
    assert f"灵宠接力 同意 {run} " in blue and f"灵宠接力 拒绝 {run}" in commands
    assert len(commands) <= 4 and len(commands + blue) == len(set(commands + blue))
    play("friend_relay", f"同意 {run} {pets['u2']}", user="u2", now=NOW + 1)
    mine = play("friend_relay", now=NOW + 2)
    assert f"灵宠接力 出战 {run} 1" in mine.commands
    assert all("出战" not in command for command in play("friend_relay", user="u2", now=NOW + 2).commands)
    assert "轮到你本人出战" in play("objectives", now=NOW + 2).text()
    assert "等待好友本人接棒" in play("today", user="u2", now=NOW + 2).text()
    assert "与好友接力" in play("friends", now=NOW + 2).text()
    assert "灵宠接力" in play("help", "秘境与关卡").text()
    assert "灵宠接力" in play("dungeons").commands


def test_onebot_and_qq_handlers_execute_same_real_two_leg_flow(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def send(bot, text, seq):
        event = onebot_event(text, seq) if bot is onebot else qq_event("helper", group=False, text=text, message_id=str(seq))
        await handlers.handle_command(bot, event, text)

    async def execute():
        await send(onebot, "灵宠领养 青鸾", 1)
        await send(qq, "灵宠领养 玄狐", 2)
        await send(onebot, "灵宠好友 添加 10001", 3)
        await send(qq, "灵宠好友 同意 10000", 4)
        sql(store, "UPDATE pets SET realm=3,layer=5")
        ids = {row["user_id"]: row["pet_id"] for row in sql(store, "SELECT user_id,pet_id FROM pets")}
        await send(onebot, f"灵宠接力 邀请 青岚林 {ids['12345']} 10001", 5)
        run = state(game)["run_id"]
        await send(qq, f"灵宠接力 同意 {run} {ids['helper']}", 6)
        await send(onebot, f"灵宠接力 出战 {run} 1", 7)
        await send(qq, f"灵宠接力 出战 {run} 2", 8)

    asyncio.run(execute())
    assert state(game)["status"] == "completed"
    assert onebot.send.await_count == qq.send.await_count == 4
    assert "两棒全胜" in str(qq.send.call_args.args[1])
