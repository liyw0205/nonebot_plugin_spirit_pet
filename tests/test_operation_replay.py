import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.storage.repository import Repository


NOW = 1_800_000_000


def sql(store, statement, params=()):
    with closing(store.connect()) as conn:
        return conn.execute(statement, params).fetchall()


def test_special_replay_uses_one_indexed_lookup_and_keeps_priority(game, play, monkeypatch):
    play("adopt", "青鸾")
    reply = Reply("持久回放", ("料理记录",), ("灵宠帮助 成长",))
    sql(
        game[1],
        "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
        ("special-priority", "u1", NOW, json.dumps({"kind": "cooking"}), json.dumps(reply.__dict__)),
    )
    sql(
        game[1],
        "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,played_at,reply,snapshot,battle_log) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "special-priority", "u1", "pve", "key", "不应覆盖", 1, 1, NOW,
            json.dumps({"title": "错误", "lines": [], "commands": []}), "{}", "[]",
        ),
    )

    calls = []
    original = Repository.special_operation

    def counted(self, operation_id):
        calls.append(operation_id)
        return original(self, operation_id)

    monkeypatch.setattr(Repository, "special_operation", counted)
    assert game[0].execute("u1", "identity", "", "special-priority", NOW) == reply
    assert calls == ["special-priority"]


def test_special_replay_survives_operation_cache_cleanup_and_rejects_other_user(game, play):
    play("adopt", "青鸾")
    reply = Reply("料理回放", ("只结算一次",), ())
    sql(
        game[1],
        "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
        ("special-restart", "u1", NOW, json.dumps({"kind": "cuisine_order"}), json.dumps(reply.__dict__)),
    )
    sql(game[1], "INSERT INTO operations VALUES (?,?,?,?)", ("special-restart", "u1", NOW, json.dumps(reply.__dict__)))
    sql(game[1], "DELETE FROM operations WHERE operation_id=?", ("special-restart",))

    assert game[0].execute("u1", "cuisine_order_deliver", "warm_meal", "special-restart", NOW + 86400) == reply
    with pytest.raises(GameError, match="different user"):
        game[0].execute("u2", "cuisine_order_deliver", "warm_meal", "special-restart", NOW + 86400)


def test_cached_operation_preflight_skips_a_second_write_transaction(game, play):
    begins = []
    game[1]._transaction_recorder = begins.append

    first = play("identity", op="preflight-operation")
    count_after_first = len(begins)
    replay = play("identity", op="preflight-operation")

    assert replay == first
    assert count_after_first == 1
    assert len(begins) == count_after_first
