"""Frozen schema 26 -> 27, private consistent backup and atomic rollback."""

import sqlite3
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema26


def old_store(tmp_path):
    store = Store(tmp_path / "old26.db")
    with closing(sqlite3.connect(store.path)) as conn:
        conn.executescript(legacy_schema26(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=26")
        for index, user in ((7, "z-first"), (19, "a-second")):
            conn.execute("INSERT INTO players(user_id,stones,registered_at) VALUES (?,321,?)", (user, index))
            conn.execute("INSERT INTO player_identity(id,user_id) VALUES (?,?)", (index, user))
            conn.execute("INSERT INTO inventory VALUES (?,'spirit_food',8)", (user,))
            conn.execute("INSERT INTO quest_progress VALUES (?,'fish_creek_spirit_food',1,1)", (user,))
            conn.execute("INSERT INTO quest_progress VALUES (?,'fishing_day_2027-01-15',2,0)", (user,))
            conn.execute("INSERT INTO quest_progress VALUES (?,'fishing_set_creek',1,1)", (user,))
        conn.commit()
    return store


def snapshot(store):
    with closing(store.connect()) as conn:
        return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                for name in ("players", "player_identity", "pets", "inventory", "quest_progress", "operations")}


def test_schema26_backup_migration_and_repeat_preserve_every_old_row(tmp_path):
    store = old_store(tmp_path)
    before = snapshot(store)
    store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert not conn.execute("SELECT * FROM fishing_casts").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("*.schema26-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    assert snapshot(Store(backups[0])) == before
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 26
    store.initialize()
    assert list(tmp_path.glob("*.schema26-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "ddl", "validation"])
def test_schema26_failure_preserves_version_structure_and_rows(tmp_path, monkeypatch, failure):
    store = old_store(tmp_path)
    before = snapshot(store)
    original = database.migrate_fishing_table

    def fail(*args):
        if failure == "ddl":
            original(*args)
        raise RuntimeError("injected fishing migration failure")

    target = {"backup": "backup_schema26", "ddl": "migrate_fishing_table", "validation": "validate_schema27"}[failure]
    monkeypatch.setattr(database, target, fail)
    with pytest.raises(RuntimeError, match="injected fishing migration"):
        store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 26
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='fishing_casts'").fetchone()


def test_schema26_structure_mismatch_is_rejected_without_backup(tmp_path):
    store = old_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("CREATE TABLE unexpected(value TEXT)")
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="structure mismatch"):
        store.initialize()
    assert snapshot(store) == before
    assert not list(tmp_path.glob("*.schema26-backup-*.db"))
