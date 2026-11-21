from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, Store
from nonebot_plugin_spirit_pet.storage.registration import migrate_family_tutelage, validate_schema37

from .test_family_trial_migration import snapshot
from .test_family_tutelage_migration import schema36_store


def schema37_store(tmp_path):
    store = schema36_store(tmp_path)
    with closing(store.connect()) as conn:
        migrate_family_tutelage(conn)
        conn.execute("PRAGMA user_version=37")
        conn.execute("INSERT INTO quest_progress VALUES ('legacy','bond_exp_1',49,0)")
        conn.execute("INSERT INTO quest_progress VALUES ('legacy','outing_value_1',35,0)")
    return store


def test_verified_schema37_backup_and_migration_preserve_all_old_data(tmp_path):
    store = schema37_store(tmp_path)
    before = snapshot(store)
    with closing(store.connect()) as conn:
        validate_schema37(conn, SCHEMA_PATH.read_text(encoding="utf-8"))
    store.initialize()
    after = snapshot(store)
    for table in ("runs", "steps", "rewards"):
        assert after.pop("family_outing_" + table) == []
    assert after.pop("family_duel_runs") == []
    assert after.pop("family_duel_rewards") == []
    assert after == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("*.schema37-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    assert snapshot(Store(backups[0])) == before
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    store.initialize()
    assert list(tmp_path.glob("*.schema37-backup-*.db")) == backups


@pytest.mark.parametrize("boundary", ["backup_schema37", "migrate_family_outings", "validate_schema38"])
def test_schema37_migration_failure_preserves_original_and_verified_backup(tmp_path, monkeypatch, boundary):
    store = schema37_store(tmp_path)
    before = snapshot(store)
    original = getattr(database, boundary)

    def fail(*args):
        if boundary != "backup_schema37":
            original(*args)
        raise RuntimeError("injected family outing migration")

    monkeypatch.setattr(database, boundary, fail)
    with pytest.raises(RuntimeError, match="injected family outing"):
        store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("*.schema37-backup-*.db"))
    assert len(backups) == (0 if boundary == "backup_schema37" else 1)
    if backups:
        assert snapshot(Store(backups[0])) == before


def test_schema37_structure_mismatch_rejected_before_backup(tmp_path):
    store = schema37_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("DROP INDEX family_tutelage_one_active")
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="schema"):
        store.initialize()
    assert snapshot(store) == before
    assert not list(tmp_path.glob("*.schema37-backup-*.db"))
