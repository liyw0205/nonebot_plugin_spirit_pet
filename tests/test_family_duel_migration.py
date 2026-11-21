from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.registration import _without_family_duels


def schema38_store(tmp_path):
    path = tmp_path / "schema38.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_without_family_duels(database.SCHEMA_PATH.read_text(encoding="utf-8")))
        database.initialize_race_league(conn, 1_800_000_000)
        conn.execute("INSERT INTO players(user_id,stones) VALUES ('u1',1234)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('u1')")
        conn.execute("INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','pve_once',1,0)")
        conn.execute("PRAGMA user_version=38")
        conn.commit()
    return database.Store(path)


def _old_data(conn):
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')] for name in names}


def test_schema38_backup_and_upgrade_add_only_isolated_duel_tables(tmp_path):
    store = schema38_store(tmp_path)
    with closing(store.connect()) as conn:
        before = _old_data(conn)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 39
        after = _old_data(conn)
        assert {key: after[key] for key in before} == before
        assert conn.execute("SELECT COUNT(*) FROM family_duel_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM family_duel_rewards").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema38.db.schema38-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 38
        assert "family_duel_runs" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


@pytest.mark.parametrize("boundary", ["backup_schema38", "migrate_family_duels", "validate_schema39"])
def test_schema38_upgrade_failure_keeps_original_and_verified_backup(tmp_path, monkeypatch, boundary):
    store = schema38_store(tmp_path)
    with closing(store.connect()) as conn:
        before = _old_data(conn)

    def fail(*args, **kwargs):
        raise RuntimeError("injected family duel migration failure")

    monkeypatch.setattr(database, boundary, fail)
    with pytest.raises(RuntimeError, match="injected family duel"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 38
        assert _old_data(conn) == before
        assert "family_duel_runs" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    backups = list(tmp_path.glob("schema38.db.schema38-backup-*.db"))
    assert len(backups) == (0 if boundary == "backup_schema38" else 1)


def test_schema38_structure_mismatch_is_rejected_before_backup(tmp_path):
    store = schema38_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("ALTER TABLE family_trial_runs ADD COLUMN unexpected TEXT")
    with pytest.raises(RuntimeError, match="structure mismatch"):
        store.initialize()
    assert not list(tmp_path.glob("schema38.db.schema38-backup-*.db"))
