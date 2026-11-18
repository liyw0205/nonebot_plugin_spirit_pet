import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import ACTIONS
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, player_uid, sql
from .test_co_training_contract import buttons, links
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000


def _setup(game, play):
    play("adopt", "青鸾", user="u1", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id IN ('u1','u2')")
    uid2 = player_uid(game[1], "u2")
    uid1 = player_uid(game[1], "u1")
    play("friends", f"添加 {uid2}", user="u1", now=NOW)
    play("friends", f"同意 {uid1}", user="u2", now=NOW)
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','spirit_food',10),('u1','forge_ore',10),('u1','bloodline_essence',10),('u2','forge_ore',10),('u2','spirit_food',10),('u2','bloodline_essence',10) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity")
    return uid2


def _run(game):
    row = sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cave_coop' ORDER BY action_id DESC LIMIT 1")[0]
    return json.loads(row["snapshot"])


def test_full_owner_helper_completion_and_shared_rewards(game, play):
    uid2 = _setup(game, play)
    page = play("cave", "共建", user="u1", now=NOW)
    assert "灵泉共建" in page.text() and "主人成本" in page.text()
    before_owner = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    before_food = items(game[1])["spirit_food"]
    started = play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="coop-start")
    project = _run(game)["project_id"]
    assert f"项目号 {project}" in started.text()
    play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op="coop-accept")
    finished = play("cave", f"共建 完工 {project}", user="u1", now=NOW + 2, op="coop-finish")
    assert "提升至 Lv2" in finished.text() and "主人奖励" in finished.text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='cave_spring_level'")[0]["progress"] == 2
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before_owner - 20
    assert items(game[1])["spirit_food"] == before_food - 1
    assert _run(game)["status"] == "finished"
    assert "项目" in play("cave", "共建 记录", user="u2", now=NOW + 3).text()


def test_reject_and_cancel_refund_owner_cost(game, play):
    uid2 = _setup(game, play)
    before = (sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"], items(game[1]).get("spirit_food", 0))
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="reject-start")
    project = _run(game)["project_id"]
    play("cave", f"共建 拒绝 {project}", user="u2", now=NOW + 1, op="reject")
    after = (sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"], items(game[1]).get("spirit_food", 0))
    assert after == before

    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW + 2, op="cancel-start")
    project = _run(game)["project_id"]
    play("cave", f"共建 取消 {project}", user="u1", now=NOW + 3, op="cancel")
    assert (sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"], items(game[1]).get("spirit_food", 0)) == before


def test_expiry_is_read_only_until_a_project_action_and_does_not_consume_helper_items(game, play):
    uid2 = _setup(game, play)
    owner_stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    owner_food = items(game[1])["spirit_food"]
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="expiry-start")
    project = _run(game)["project_id"]
    helper_ore = items(game[1], "u2")["forge_ore"]
    expired_at = NOW + 72 * 3600

    page = play("cave", "共建", user="u1", now=expired_at)
    assert "已过期" in page.text()
    assert _run(game)["status"] == "pending"

    reply = play("cave", f"共建 同意 {project}", user="u2", now=expired_at, op="expiry-accept")
    assert "已过期" in reply.text()
    assert _run(game)["status"] == "expired"
    assert items(game[1], "u2")["forge_ore"] == helper_ore
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == owner_stones
    assert items(game[1])["spirit_food"] == owner_food

    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=expired_at + 1, op="after-expiry-start")
    assert _run(game)["status"] == "pending"


def test_ready_project_expiry_refunds_both_participants(game, play):
    uid2 = _setup(game, play)
    owner_stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    owner_food = items(game[1])["spirit_food"]
    helper_ore = items(game[1], "u2")["forge_ore"]
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="ready-expiry-start")
    project = _run(game)["project_id"]
    play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op="ready-expiry-accept")

    reply = play("cave", f"共建 完工 {project}", user="u1", now=NOW + 72 * 3600, op="ready-expiry-finish")
    assert "已过期" in reply.text()
    assert _run(game)["status"] == "expired"
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == owner_stones
    assert items(game[1])["spirit_food"] == owner_food
    assert items(game[1], "u2")["forge_ore"] == helper_ore


def test_clock_rollback_and_corrupt_snapshot_do_not_consume_resources(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="guard-start")
    project = _run(game)["project_id"]
    helper_ore = items(game[1], "u2")["forge_ore"]

    with pytest.raises(GameError, match="时钟恢复"):
        play("cave", f"共建 同意 {project}", user="u2", now=NOW - 1, op="clock-rollback")
    assert items(game[1], "u2")["forge_ore"] == helper_ore

    action = sql(game[1], "SELECT action_id,snapshot FROM duel_actions WHERE operation_id='guard-start'")[0]
    snapshot = json.loads(action["snapshot"])
    snapshot.pop("owner_id")
    sql(game[1], "UPDATE duel_actions SET snapshot=? WHERE action_id=?", (json.dumps(snapshot), action["action_id"]))
    with pytest.raises(GameError, match="快照损坏"):
        play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op="corrupt-accept")
    assert items(game[1], "u2")["forge_ore"] == helper_ore


def test_real_onebot_and_qq_handlers_share_cross_player_contract(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config())
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    onebot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    qq = SimpleNamespace(self_id="qq-app", adapter=SimpleNamespace(get_name=lambda: "QQ"), send=AsyncMock())

    async def send(bot, event):
        await handlers.handle_command(bot, event, event.get_message())

    async def execute():
        await send(onebot, onebot_event("灵宠领养 青鸾", 1))
        await send(qq, qq_event("helper", group=False, text="灵宠领养 玄狐", message_id="2"))
        await send(onebot, onebot_event("灵宠好友 添加 10001", 3))
        await send(qq, qq_event("helper", group=False, text="灵宠好友 同意 10000", message_id="4"))
        sql(store, "UPDATE players SET stones=1000 WHERE user_id='12345'")
        sql(store, "INSERT INTO inventory VALUES ('helper','forge_ore',1) "
                   "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=1")
        await send(onebot, onebot_event("灵宠洞府 共建 发起 灵泉 UID 10001", 5))
        project = _run(game)["project_id"]
        await send(qq, qq_event("helper", group=False, text=f"灵宠洞府 共建 同意 {project}", message_id="6"))
        await send(onebot, onebot_event(f"灵宠洞府 共建 完工 {project}", 7))

    asyncio.run(execute())
    assert _run(game)["status"] == "finished"
    assert sql(store, "SELECT progress FROM quest_progress WHERE user_id='12345' AND quest_id='cave_spring_level'")[0]["progress"] == 2
    assert onebot.send.await_count == 4
    assert qq.send.await_count == 3
    assert "提升至 Lv2" in str(onebot.send.call_args.args[1])


def test_qq_actions_are_clickable_and_scoped_to_project_and_role(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉 {uid2}", op="qq-start")
    project = _run(game)["project_id"]
    reply = play("cave", "共建", user="u2")
    plain, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    actions = [button.action.data for button in buttons(message)]
    blue = [data["command"][0] for _, data in links(message)]
    accept, reject = (f"!灵宠洞府 共建 {step} {project}" for step in ("同意", "拒绝"))
    assert accept in blue and reject in blue
    assert len(actions) <= 4 and len(actions + blue) == len(set(actions + blue))
    assert accept in plain and reject in plain
    assert f"UID {uid2}" in plain and "UID 10000" in plain
    with pytest.raises(GameError, match="没有找到"):
        play("cave", f"共建 同意 {project}", user="u3")
    assert _run(game)["status"] == "pending"


def test_restart_and_cache_eviction_preserve_frozen_rewards_and_actor(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉 {uid2}", op="restart-start")
    project = _run(game)["project_id"]
    accepted = play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op="restart-accept")
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], Config())
    restarted.content.cave_coop.clear()
    assert restarted.execute("u2", "cave", f"共建 同意 {project}", "restart-accept", NOW + 86400) == accepted
    with pytest.raises(GameError, match="different user"):
        restarted.execute("u1", "cave", f"共建 同意 {project}", "restart-accept", NOW + 86400)
    finished = restarted.execute("u1", "cave", f"共建 完工 {project}", "restart-finish", NOW + 86400)
    assert "提升至 Lv2" in finished.text()
    assert player(game[1], "u2")["stones"] == 1120
    sql(game[1], "DELETE FROM operations")
    assert restarted.execute("u1", "cave", f"共建 完工 {project}", "restart-finish", NOW + 86401) == finished
    assert player(game[1], "u2")["stones"] == 1120


def test_solo_upgrade_invalidates_ready_project_without_second_upgrade(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉 {uid2}")
    project = _run(game)["project_id"]
    play("cave", f"共建 同意 {project}", user="u2")
    play("cave", "升级 灵泉")
    reply = play("cave", f"共建 完工 {project}")
    assert "已退还" in reply.text()
    assert _run(game)["status"] == "invalidated"
    assert player(game[1])["stones"] == 700
    assert player(game[1], "u2")["stones"] == 1000
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cave_spring_level'") == [{"progress": 2}]


def test_start_replaces_expired_project_even_without_previous_expiry_action(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉 {uid2}", op="old-project")
    project = _run(game)["project_id"]
    reply = play("cave", f"共建 发起 灵泉 {uid2}", now=NOW + 72 * 3600, op="new-project")
    assert _run(game)["project_id"] != project
    assert player(game[1])["stones"] == 820
    assert "已过期" in play("cave", "共建 记录", user="u2").text()
    sql(game[1], "DELETE FROM operations")
    assert play("cave", f"共建 发起 灵泉 {uid2}", now=NOW + 72 * 3600, op="new-project") == reply


def test_parallel_accept_and_operation_replay_are_idempotent(game, play):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="parallel-start")
    project = _run(game)["project_id"]

    def attempt(index):
        try:
            return play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op=f"accept-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    before = items(game[1])["forge_ore"]
    sql(game[1], "DELETE FROM operations")
    winner = next((index, result) for index, result in enumerate(results, 1) if not isinstance(result, GameError))
    replay = play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op=f"accept-{winner[0]}")
    assert replay == winner[1]
    assert items(game[1])["forge_ore"] == before


def test_accept_and_cancel_race_cannot_spend_and_refund_the_same_project(game, play):
    uid2 = _setup(game, play)
    ore = items(game[1], "u2")["forge_ore"]
    play("cave", f"共建 发起 灵泉 {uid2}")
    project = _run(game)["project_id"]

    def act(pair):
        step, user = pair
        try:
            play("cave", f"共建 {step} {project}", user=user, op=f"race-{user}")
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted, cancelled = pool.map(act, (("同意", "u2"), ("取消", "u1")))
    assert accepted != cancelled
    assert _run(game)["status"] == ("ready" if accepted else "cancelled")
    assert items(game[1], "u2")["forge_ore"] == ore - int(accepted)
    assert player(game[1])["stones"] == (820 if accepted else 1000)


def test_receipt_failure_rolls_back_cross_player_completion(game, play, monkeypatch):
    uid2 = _setup(game, play)
    play("cave", f"共建 发起 灵泉共建 {uid2}", user="u1", now=NOW, op="rollback-start")
    project = _run(game)["project_id"]
    play("cave", f"共建 同意 {project}", user="u2", now=NOW + 1, op="rollback-accept")
    before = (sql(game[1], "SELECT stones FROM players ORDER BY user_id"), items(game[1]), sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='cave_spring_level'"))
    original = Repository.record_cave_coop_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    monkeypatch.setattr(Repository, "record_cave_coop_action", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        play("cave", f"共建 完工 {project}", user="u1", now=NOW + 2, op="rollback-finish")
    assert (sql(game[1], "SELECT stones FROM players ORDER BY user_id"), items(game[1]), sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='cave_spring_level'")) == before


@pytest.mark.parametrize(("stage", "trigger"), [
    ("start", "BEFORE UPDATE OF quantity ON inventory WHEN NEW.user_id='u1'"),
    ("accept", "BEFORE UPDATE OF quantity ON inventory WHEN NEW.user_id='u2'"),
    ("complete", "BEFORE INSERT ON quest_progress WHEN NEW.quest_id='cave_spring_level'"),
    ("complete", "BEFORE INSERT ON inventory WHEN NEW.user_id='u1'"),
    ("complete", "BEFORE INSERT ON inventory WHEN NEW.user_id='u2'"),
    ("complete", "BEFORE UPDATE OF stones ON players WHEN NEW.user_id='u2'"),
    ("complete", "BEFORE INSERT ON duel_actions"),
    ("complete", "BEFORE INSERT ON operations"),
    ("expire", "BEFORE INSERT ON duel_actions"),
])
def test_every_mutation_boundary_rolls_back_as_one_transaction(game, play, stage, trigger):
    uid2 = _setup(game, play)
    project = 0
    if stage != "start":
        play("cave", f"共建 发起 灵泉 {uid2}", op="atomic-start")
        project = _run(game)["project_id"]
    if stage in {"complete", "expire"}:
        play("cave", f"共建 同意 {project}", user="u2", op="atomic-accept")

    def snapshot():
        return {table: sql(game[1], f"SELECT * FROM {table} ORDER BY 1") for table in (
            "players", "pets", "inventory", "quest_progress", "duel_actions", "operations",
        )}

    before = snapshot()
    sql(game[1], f"CREATE TRIGGER coop_failure {trigger} BEGIN SELECT RAISE(ABORT,'coop injected failure'); END")
    command, user, now = {
        "start": (f"共建 发起 灵泉 {uid2}", "u1", NOW),
        "accept": (f"共建 同意 {project}", "u2", NOW),
        "complete": (f"共建 完工 {project}", "u1", NOW),
        "expire": (f"共建 完工 {project}", "u1", NOW + 72 * 3600),
    }[stage]
    with pytest.raises(sqlite3.IntegrityError, match="coop injected failure"):
        play("cave", command, user=user, now=now, op="atomic-failure")
    assert snapshot() == before
    sql(game[1], "DROP TRIGGER coop_failure")
    assert play("cave", command, user=user, now=now, op="atomic-failure")


def test_help_and_parser_cover_cave_coop(game, play):
    _setup(game, play)
    assert handlers._parse("灵宠洞府 共建 发起 灵泉共建 10001") == ("cave", "共建 发起 灵泉共建 10001")
    assert ACTIONS["cave"].handler.__module__.endswith("gameplay.cave")
    assert handlers._parse("灵宠洞府 共建 同意 123456") == ("cave", "共建 同意 123456")
    assert "灵宠洞府 共建" in play("help", "成长", user="u1", now=NOW).text()
    assert "洞府共建" in play("objectives", user="u1", now=NOW).text()
