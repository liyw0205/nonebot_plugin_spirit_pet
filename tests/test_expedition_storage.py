import json
import sqlite3

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.domain.expedition_state import RewardSnapshot

from .support import pet, sql


NOW = 1_800_000_000
FINISH = NOW + 3600


def snapshot_json(**overrides):
    return json.dumps({"exp": 10, "stones": 20, "items": {"spirit_food": 1}, **overrides})


def record(store, user="u1", **overrides):
    return {
        "user_id": user,
        "pet_id": pet(store, user)["pet_id"],
        "task_id": "herb_gathering",
        "task_name": "采灵药",
        "source_operation_id": "storage-departure",
        "started_at": NOW,
        "finishes_at": FINISH,
        "state": "running",
        "reward_snapshot": snapshot_json(),
        "settled_at": None,
        **overrides,
    }


def insert_record(store, values):
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    sql(store, f"INSERT INTO expeditions ({columns}) VALUES ({placeholders})", tuple(values.values()))


def saved_state(store):
    return {
        table: sql(store, f"SELECT * FROM {table} ORDER BY 1")
        for table in ("players", "pets", "inventory", "expeditions")
    }


@pytest.fixture
def owners(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    return game[1]


def test_expedition_owner_pet_foreign_key_rejects_a_real_pet_belonging_to_someone_else(owners):
    other_pet_id = pet(owners, "u2")["pet_id"]
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_record(owners, record(owners, pet_id=other_pet_id))
    assert not sql(owners, "SELECT * FROM expeditions")
    insert_record(owners, record(owners, user="u2", pet_id=other_pet_id))
    assert len(sql(owners, "SELECT * FROM expeditions")) == 1


@pytest.mark.parametrize("missing", ["player", "pet"])
def test_expedition_rejects_nonexistent_owner_or_pet(owners, missing):
    values = record(owners)
    values["user_id" if missing == "player" else "pet_id"] = "missing-owner" if missing == "player" else 999999
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_record(owners, values)
    assert not sql(owners, "SELECT * FROM expeditions")


def test_expedition_has_both_partial_unique_running_indexes(owners):
    indexes = {row["name"]: row for row in sql(owners, "PRAGMA index_list(expeditions)")}
    for name, field in (
        ("expedition_running_player", "user_id"), ("expedition_running_pet", "pet_id"),
    ):
        assert indexes[name]["unique"] == 1
        assert indexes[name]["partial"] == 1
        assert [row["name"] for row in sql(owners, f"PRAGMA index_info({name})")] == [field]
        definition = sql(owners, "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,))[0]["sql"]
        assert "WHERE state='running'" in definition


def test_one_player_cannot_run_two_pets_but_different_players_can_depart(owners):
    insert_record(owners, record(owners))
    sql(owners, "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        ("u1", "qingluan", "备用灵宠", NOW))
    second_id = sql(owners, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_record(owners, record(owners, pet_id=second_id, source_operation_id="second-pet"))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_record(owners, record(owners, source_operation_id="same-pet"))
    insert_record(owners, record(owners, user="u2", source_operation_id="other-owner"))
    assert len(sql(owners, "SELECT * FROM expeditions WHERE state='running'")) == 2


@pytest.mark.parametrize("terminal,settled", [("claimed", FINISH), ("cancelled", NOW)])
def test_terminal_history_releases_partial_index_but_cannot_reopen_over_running_job(owners, terminal, settled):
    insert_record(owners, record(owners, state=terminal, settled_at=settled))
    insert_record(owners, record(owners, source_operation_id="new-departure"))
    before = sql(owners, "SELECT * FROM expeditions ORDER BY job_id")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        sql(owners, "UPDATE expeditions SET state='running', settled_at=NULL WHERE source_operation_id='storage-departure'")
    assert sql(owners, "SELECT * FROM expeditions ORDER BY job_id") == before


@pytest.mark.parametrize("state,settled,valid", [
    ("running", None, True),
    ("running", NOW, False),
    ("claimed", None, False),
    ("claimed", NOW, False),
    ("claimed", FINISH - 1, False),
    ("claimed", FINISH, True),
    ("claimed", FINISH + 1, True),
    ("cancelled", None, False),
    ("cancelled", NOW - 1, False),
    ("cancelled", NOW, True),
    ("cancelled", FINISH - 1, True),
    ("cancelled", FINISH, False),
    ("cancelled", FINISH + 1, False),
    ("unknown", None, False),
])
def test_expedition_state_and_settlement_time_are_consistent(owners, state, settled, valid):
    values = record(owners, state=state, settled_at=settled)
    if valid:
        insert_record(owners, values)
        stored = sql(owners, "SELECT * FROM expeditions")[0]
        assert stored["state"] == state and stored["settled_at"] == settled
    else:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            insert_record(owners, values)
        assert not sql(owners, "SELECT * FROM expeditions")


@pytest.mark.parametrize("finish", [NOW - 1, NOW])
def test_expedition_deadline_must_be_later_than_departure(owners, finish):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_record(owners, record(owners, finishes_at=finish))
    assert not sql(owners, "SELECT * FROM expeditions")


@pytest.mark.parametrize("terminal,settled", [("claimed", FINISH), ("cancelled", NOW)])
def test_source_operation_id_remains_unique_after_terminal_settlement(owners, terminal, settled):
    insert_record(owners, record(owners, state=terminal, settled_at=settled))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_record(owners, record(owners, user="u2"))
    assert len(sql(owners, "SELECT * FROM expeditions")) == 1


@pytest.mark.parametrize("source_id", ["", None])
def test_departure_source_operation_id_is_required(owners, source_id):
    with pytest.raises(sqlite3.IntegrityError):
        insert_record(owners, record(owners, source_operation_id=source_id))


def invalid_snapshots():
    cases = []
    for field in ("exp", "stones", "items"):
        for label, value in (
            ("negative", -1), ("string", "1"), ("fraction", 1.5), ("boolean", True),
            ("over-cap", 1_000_001), ("sqlite-overflow", 2 ** 63),
        ):
            update = {field: {"spirit_food": value} if field == "items" else value}
            cases.append(pytest.param(snapshot_json(**update), id=f"{field}-{label}"))
    cases.extend((
        pytest.param(snapshot_json(unexpected=1), id="extra-field"),
        pytest.param(snapshot_json(created_at=NOW), id="runtime-timestamp-in-snapshot"),
        pytest.param(snapshot_json(items={"invalid-item-key": 1}), id="invalid-item-id"),
        pytest.param(snapshot_json(items=["spirit_food"]), id="items-not-object"),
        pytest.param(snapshot_json(items={"spirit_food": None}), id="null-item-quantity"),
        pytest.param('{"exp": 1, "stones": 2}', id="missing-items"),
        pytest.param('{"exp": 1e1000, "stones": 2, "items": {}}', id="numeric-overflow"),
        pytest.param('{"exp":', id="malformed-json"),
    ))
    return cases


@pytest.mark.parametrize("payload", invalid_snapshots())
def test_reward_snapshot_json_strictly_rejects_bad_data(payload):
    with pytest.raises(ValidationError):
        RewardSnapshot.model_validate_json(payload)


@pytest.mark.parametrize("amount", [0, 1_000_000])
def test_reward_snapshot_accepts_inclusive_numeric_boundaries(amount):
    snapshot = RewardSnapshot.model_validate_json(snapshot_json(exp=amount, stones=amount, items={"spirit_food": amount}))
    assert snapshot.exp == snapshot.stones == snapshot.items["spirit_food"] == amount
    assert RewardSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize("payload", invalid_snapshots())
def test_bad_persisted_snapshot_keeps_job_running_and_all_resources_unchanged(game, play, payload):
    play("adopt", "青鸾")
    play("expedition_start", "采灵药")
    job = sql(game[1], "SELECT * FROM expeditions")[0]
    sql(game[1], "UPDATE expeditions SET reward_snapshot=? WHERE job_id=?", (payload, job["job_id"]))
    before = saved_state(game[1])
    with pytest.raises(ValidationError):
        play("expedition_claim", str(job["job_id"]), now=job["finishes_at"], op="invalid-snapshot-claim")
    assert saved_state(game[1]) == before
    assert sql(game[1], "SELECT state FROM expeditions")[0]["state"] == "running"
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='invalid-snapshot-claim'")

    sql(game[1], "UPDATE expeditions SET reward_snapshot=? WHERE job_id=?", (job["reward_snapshot"], job["job_id"]))
    play("expedition_claim", str(job["job_id"]), now=job["finishes_at"], op="invalid-snapshot-claim")
    assert sql(game[1], "SELECT state FROM expeditions")[0]["state"] == "claimed"
