import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, player_uid, sql
from .test_cave_coop import buttons, links
from .test_commands import onebot_event, qq_event
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day

NOW = 1_800_000_000
DAY = 86_400


def _setup(game, play):
    play("adopt", "青鸾", user="u1", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    sql(game[1], "UPDATE players SET stones=500 WHERE user_id IN ('u1','u2')")
    play("buy", "灵粮 10", user="u1", now=NOW)
    play("buy", "灵粮 10", user="u2", now=NOW)
    uid2, uid1 = player_uid(game[1], "u2"), player_uid(game[1], "u1")
    play("friends", f"添加 {uid2}", user="u1", now=NOW)
    play("friends", f"同意 {uid1}", user="u2", now=NOW)
    ids = {row["user_id"]: row["pet_id"] for row in sql(game[1], "SELECT user_id,pet_id FROM pets")}
    for user_id, pet_id in ids.items():
        sql(game[1], "UPDATE pets SET energy=40,energy_updated=?,exp=100,affinity=10 WHERE pet_id=?",
            (NOW, pet_id))
    return uid2, ids


def _run(game):
    row = sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cuisine_coop' ORDER BY action_id DESC LIMIT 1")[0]
    return json.loads(row["snapshot"])


def _start(game, play, uid, ids, *, now=NOW, op="cuisine-start"):
    reply = play("cuisine_coop", f"发起 灵米粥 {ids['u1']} {uid}", user="u1", now=now, op=op)
    return _run(game)["project_id"], reply


def _ready(game, play, uid, ids, *, now=NOW, op="cuisine-start"):
    project_id, started = _start(game, play, uid, ids, now=now, op=op)
    accepted = play("cuisine_coop", f"同意 {project_id} {ids['u2']}", user="u2", now=now + 1, op=op + "-accept")
    return project_id, started, accepted


def _world(store):
    with closing(store.connect()) as conn:
        return tuple(conn.iterdump())


def test_preview_is_read_only_then_both_partners_pay_and_eat_real_single_meals(game, play):
    uid, ids = _setup(game, play)
    before = _world(game[1])
    preview = play("cuisine_coop", f"预览 灵米粥 {ids['u1']} {uid}", user="u1")
    assert "双方各投入一份" in preview.text() and "精力 +45" in preview.text()
    assert _world(game[1]) == before

    owner_stones, helper_stones = player(game[1], "u1")["stones"], player(game[1], "u2")["stones"]
    owner_food, helper_food = items(game[1], "u1")["spirit_food"], items(game[1], "u2")["spirit_food"]
    project, started = _start(game, play, uid, ids)
    assert "项目号" in started.text()
    assert player(game[1], "u1")["stones"] == owner_stones - 10
    assert player(game[1], "u2")["stones"] == helper_stones
    assert items(game[1], "u1")["spirit_food"] == owner_food - 2
    assert items(game[1], "u2")["spirit_food"] == helper_food
    assert _run(game)["status"] == "pending"

    play("cuisine_coop", f"同意 {project} {ids['u2']}", user="u2", now=NOW + 1)
    assert player(game[1], "u2")["stones"] == helper_stones - 10
    assert items(game[1], "u2")["spirit_food"] == helper_food - 2
    finished = play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 2)
    assert "灵米粥 ×2" in finished.text()
    assert _run(game)["status"] == "finished"
    assert sql(game[1], "SELECT energy,exp,affinity FROM pets WHERE pet_id=?", (ids["u1"],)) == [
        {"energy": 85, "exp": 120, "affinity": 20},
    ]
    assert sql(game[1], "SELECT energy,exp,affinity FROM pets WHERE pet_id=?", (ids["u2"],)) == [
        {"energy": 85, "exp": 120, "affinity": 20},
    ]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id IN ('u1','u2') AND quest_id='cuisine_dish_rice_porridge' ORDER BY user_id") == [
        {"progress": 1}, {"progress": 1},
    ]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id IN ('u1','u2') AND quest_id LIKE 'cuisine_heat_%' ORDER BY user_id") == [
        {"progress": 1}, {"progress": 1},
    ]
    assert "meal_rice" not in items(game[1], "u1") and "meal_rice" not in items(game[1], "u2")


def test_reject_cancel_and_expiry_refund_only_paid_costs_and_never_heat(game, play):
    uid, ids = _setup(game, play)
    owner_before = player(game[1], "u1")["stones"], items(game[1], "u1")["spirit_food"]
    project, _ = _start(game, play, uid, ids, op="reject-start")
    play("cuisine_coop", f"拒绝 {project}", user="u2", now=NOW + 1)
    assert (player(game[1], "u1")["stones"], items(game[1], "u1")["spirit_food"]) == owner_before
    assert sql(game[1], "SELECT 1 FROM quest_progress WHERE quest_id LIKE 'cuisine_heat_%'") == []

    project, _, _ = _ready(game, play, uid, ids, now=NOW + 2, op="cancel-start")
    before = ((player(game[1], "u1")["stones"], items(game[1], "u1")["spirit_food"]),
              (player(game[1], "u2")["stones"], items(game[1], "u2")["spirit_food"]))
    play("cuisine_coop", f"取消 {project}", user="u1", now=NOW + 4)
    assert ((player(game[1], "u1")["stones"], items(game[1], "u1")["spirit_food"]),
            (player(game[1], "u2")["stones"], items(game[1], "u2")["spirit_food"])) == (
                (before[0][0] + 10, before[0][1] + 2), (before[1][0] + 10, before[1][1] + 2),
            )

    project, _, _ = _ready(game, play, uid, ids, now=NOW + 10, op="expire-start")
    deadline = NOW + 10 + 1 + DAY
    before = _world(game[1])
    assert "待退款" in play("cuisine_coop", user="u2", now=deadline).text()
    assert _world(game[1]) == before
    play("cuisine_coop", f"退款 {project}", user="u2", now=deadline, op="expire-refund")
    assert _run(game)["status"] == "expired"
    assert sql(game[1], "SELECT 1 FROM quest_progress WHERE quest_id LIKE 'cuisine_heat_%'") == []
    assert "已退回" in play("cuisine_coop", f"详情 {project}", user="u1", now=deadline + 1).text()


def test_cross_day_completion_charges_only_completion_day_and_uses_frozen_recipe(game, play):
    uid, ids = _setup(game, play)
    cross_start = datetime.fromtimestamp(NOW, BEIJING).replace(hour=23, minute=59, second=0, microsecond=0)
    if int(cross_start.timestamp()) <= NOW:
        cross_start += timedelta(days=1)
    cross_start = int(cross_start.timestamp())
    project, _, _ = _ready(game, play, uid, ids, now=cross_start)
    game[0].content.cuisine["rice_porridge"] = game[0].content.cuisine["rice_porridge"].model_copy(
        update={"heat": 5, "stones": 99, "ingredients": {"bloodline_essence": 9}},
    )
    next_day = cross_start + 120
    result = play("cuisine_coop", f"完成 {project}", user="u1", now=next_day)
    assert "灵米粥 ×2" in result.text() and "灵石 -99" not in result.text()
    assert sql(game[1], "SELECT quest_id,progress FROM quest_progress WHERE user_id IN ('u1','u2') AND quest_id LIKE 'cuisine_heat_%' ORDER BY quest_id,user_id") == [
        {"quest_id": f"cuisine_heat_{beijing_day(next_day)}", "progress": 1},
        {"quest_id": f"cuisine_heat_{beijing_day(next_day)}", "progress": 1},
    ]


def test_selected_pets_are_not_swapped_and_must_be_available_to_complete(game, play):
    uid, ids = _setup(game, play)
    project, _, _ = _ready(game, play, uid, ids)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id IN ('u1','u2')")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (ids["u2"],))
    before = _world(game[1])
    with pytest.raises(GameError, match="不在该主人名册"):
        play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 3)
    assert _world(game[1]) == before
    sql(game[1], "UPDATE pets SET archived=0 WHERE pet_id=?", (ids["u2"],))
    sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,finishes_at,state,reward_snapshot) "
                 "VALUES ('u2',?,'herb_gathering','采灵药','coop-dispatch',?,?, 'running','{}')",
        (ids["u2"], NOW, NOW + 3600))
    before = _world(game[1])
    with pytest.raises(GameError, match="正在外出派遣"):
        play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 4)
    assert _world(game[1]) == before
    sql(game[1], "UPDATE expeditions SET state='cancelled',settled_at=? WHERE source_operation_id='coop-dispatch'", (NOW + 5,))
    result = play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 6)
    assert "完成" in result.text()
    assert player(game[1], "u1")["active_pet_id"] is None
    assert player(game[1], "u2")["active_pet_id"] is None


def test_friendship_loss_blocks_completion_but_owner_can_refund_both(game, play):
    uid, ids = _setup(game, play)
    project, _, _ = _ready(game, play, uid, ids)
    play("friends", f"解除 {uid}", user="u1", now=NOW + 2)
    before = _world(game[1])
    with pytest.raises(GameError, match="解除好友"):
        play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 3)
    assert _world(game[1]) == before
    play("cuisine_coop", f"取消 {project}", user="u1", now=NOW + 4)
    assert _run(game)["status"] == "cancelled"
    assert player(game[1], "u1")["stones"] == 300
    assert player(game[1], "u2")["stones"] == 300
    assert sql(game[1], "SELECT 1 FROM quest_progress WHERE quest_id LIKE 'cuisine_heat_%'") == []


def test_pending_project_roles_and_one_active_slot_are_enforced(game, play):
    uid, ids = _setup(game, play)
    project, _ = _start(game, play, uid, ids)
    play("adopt", user="u3", now=NOW)
    for user, action in (("u1", "同意"), ("u1", "拒绝"), ("u2", "取消"), ("u3", "详情")):
        before = _world(game[1])
        argument = f"{action} {project}" + (f" {sql(game[1], 'SELECT pet_id FROM pets WHERE user_id=?', (user,))[0]['pet_id']}" if action == "同意" else "")
        with pytest.raises(GameError):
            play("cuisine_coop", argument, user=user, now=NOW + 1)
        assert _world(game[1]) == before
    before = _world(game[1])
    with pytest.raises(GameError, match="进行中的合膳"):
        play("cuisine_coop", f"发起 灵米粥 {ids['u1']} {uid}", user="u1", now=NOW + 2)
    assert _world(game[1]) == before


@pytest.mark.parametrize("failure", ["heat", "dish", "pet", "receipt"])
def test_settlement_failures_roll_back_both_pets_progress_heat_and_receipt(game, play, failure):
    uid, ids = _setup(game, play)
    project, _, _ = _ready(game, play, uid, ids)
    if failure == "heat":
        sql(game[1], "CREATE TRIGGER fail_coop_heat BEFORE INSERT ON quest_progress WHEN NEW.quest_id LIKE 'cuisine_heat_%' AND NEW.user_id='u2' BEGIN SELECT RAISE(ABORT,'injected heat failure'); END")
    elif failure == "dish":
        sql(game[1], "CREATE TRIGGER fail_coop_dish BEFORE INSERT ON quest_progress WHEN NEW.quest_id='cuisine_dish_rice_porridge' AND NEW.user_id='u2' BEGIN SELECT RAISE(ABORT,'injected dish failure'); END")
    elif failure == "pet":
        sql(game[1], f"CREATE TRIGGER fail_coop_pet BEFORE UPDATE ON pets WHEN OLD.pet_id={ids['u2']} BEGIN SELECT RAISE(ABORT,'injected pet failure'); END")
    else:
        sql(game[1], "CREATE TRIGGER fail_coop_receipt BEFORE INSERT ON duel_actions WHEN json_extract(NEW.snapshot,'$.kind')='cuisine_coop' AND json_extract(NEW.snapshot,'$.status')='finished' BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END")
    before = _world(game[1])
    with pytest.raises(Exception, match="injected"):
        play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 2)
    assert _world(game[1]) == before


def test_accept_cancel_race_has_one_terminal_state_and_no_partial_refund(game, play):
    uid, ids = _setup(game, play)
    food_before = {user: items(game[1], user)["spirit_food"] for user in ("u1", "u2")}
    project, _ = _start(game, play, uid, ids)
    barrier = Barrier(2)

    def execute(user, argument, op):
        barrier.wait(timeout=10)
        try:
            return game[0].execute(user, "cuisine_coop", argument, op, NOW + 1)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(execute, "u2", f"同意 {project} {ids['u2']}", "racing-accept")
        cancelled = pool.submit(execute, "u1", f"取消 {project}", "racing-cancel")
        results = accepted.result(), cancelled.result()
    assert sum(isinstance(result, GameError) for result in results) <= 1
    assert _run(game)["status"] == "cancelled"
    assert player(game[1], "u1")["stones"] == 300
    assert player(game[1], "u2")["stones"] == 300
    assert {user: items(game[1], user)["spirit_food"] for user in ("u1", "u2")} == food_before


def test_onebot_and_qq_handlers_share_full_coop_flow(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def send(bot, event, text):
        await handlers.handle_command(bot, event, text)

    async def execute():
        await send(onebot, onebot_event("灵宠领养 青鸾", 1), "灵宠领养 青鸾")
        await send(qq, qq_event("helper", group=False, text="灵宠领养 玄狐", message_id="2"), "灵宠领养 玄狐")
        await send(onebot, onebot_event("灵宠好友 添加 10001", 3), "灵宠好友 添加 10001")
        await send(qq, qq_event("helper", group=False, text="灵宠好友 同意 10000", message_id="4"), "灵宠好友 同意 10000")
        sql(store, "UPDATE players SET stones=500 WHERE user_id IN ('12345','helper')")
        sql(store, "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('12345','spirit_food',10),('helper','spirit_food',10) "
                    "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity")
        owner_pet = sql(store, "SELECT pet_id FROM pets WHERE user_id='12345'")[0]["pet_id"]
        helper_pet = sql(store, "SELECT pet_id FROM pets WHERE user_id='helper'")[0]["pet_id"]
        await send(onebot, onebot_event(f"灵宠合膳 发起 灵米粥 {owner_pet} 10001", 5), f"灵宠合膳 发起 灵米粥 {owner_pet} 10001")
        project = _run(game)["project_id"]
        await send(qq, qq_event("helper", group=False, text=f"灵宠合膳 同意 {project} {helper_pet}", message_id="6"), f"灵宠合膳 同意 {project} {helper_pet}")
        await send(onebot, onebot_event(f"灵宠合膳 完成 {project}", 7), f"灵宠合膳 完成 {project}")

    asyncio.run(execute())
    assert _run(game)["status"] == "finished"
    assert "灵宠合膳" in str(onebot.send.call_args.args[1])
    assert "完成" in str(qq.send.call_args.args[1])
    assert onebot.send.await_count == 4 and qq.send.await_count == 3


def test_permanent_replay_and_bilateral_history_survive_cache_cleanup(game, play):
    uid, ids = _setup(game, play)
    project, _, _ = _ready(game, play, uid, ids, op="replay-start")
    old = play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 2, op="replay-finish")
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, content=game[0].content)
    replay = restarted.execute("u1", "cuisine_coop", f"完成 {project}", "replay-finish", NOW + DAY)
    assert replay == old
    with pytest.raises(GameError, match="different user"):
        restarted.execute("u2", "cuisine_coop", f"完成 {project}", "replay-finish", NOW + DAY)
    assert "已完成" in play("cuisine_coop", "记录", user="u1", now=NOW + DAY).text()
    assert "已完成" in play("cuisine_coop", "记录", user="u2", now=NOW + DAY).text()


def test_corrupt_history_snapshot_fails_without_modifying_state(game, play):
    uid, ids = _setup(game, play)
    project, _, _ = _ready(game, play, uid, ids)
    play("cuisine_coop", f"完成 {project}", user="u1", now=NOW + 2)
    row = sql(game[1], "SELECT action_id,snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cuisine_coop' ORDER BY action_id DESC LIMIT 1")[0]
    snapshot = json.loads(row["snapshot"])
    del snapshot["owner_pet_name"]
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE action_id=?", (json.dumps(snapshot), row["action_id"]))
    before = _world(game[1])
    with pytest.raises(GameError, match="快照损坏"):
        play("cuisine_coop", "记录", user="u1", now=NOW + 3)
    assert _world(game[1]) == before


def test_qq_current_actions_and_history_links_are_role_scoped(game, play):
    uid, ids = _setup(game, play)
    project, _ = _start(game, play, uid, ids)
    helper_page = play("cuisine_coop", user="u2")
    _, message = _qq_segments(helper_page, Config(spirit_pet_qq_mode="native"))
    commands = [button.action.data.removeprefix("/") for button in buttons(message)]
    blue = [data["command"][0].removeprefix("/") for _, data in links(message)]
    assert f"灵宠合膳 同意 {project} " in blue
    assert f"灵宠合膳 拒绝 {project}" in commands
    assert len(commands) <= 4 and len(commands + blue) == len(set(commands + blue))
    assert "好友合膳" in play("cuisine", "").text()
    assert "与好友合膳" in play("friends").text()
    assert "灵宠合膳" in play("help", "成长").text()
    assert "合膳：项目" in play("objectives").text()
    assert "合膳：项目" in play("today").text()
    with pytest.raises(GameError, match="受邀好友"):
        play("cuisine_coop", f"同意 {project} {ids['u2']}", user="u1")
