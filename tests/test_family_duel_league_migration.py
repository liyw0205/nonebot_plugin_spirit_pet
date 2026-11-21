from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.registration import _without_family_duel_league


def schema39_store(tmp_path):
    path = tmp_path / "schema39.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        schema = database.SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(_without_family_duel_league(schema))
        database.initialize_race_league(conn, 1_800_000_000)
        conn.execute("INSERT INTO players(user_id,stones) VALUES ('u1',1234)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('u1')")
        conn.execute("PRAGMA user_version=39")
        conn.commit()
    return database.Store(path)


def all_rows(conn):
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')]
            for name in tables}


def test_schema39_backup_and_upgrade_preserve_all_existing_rows(tmp_path):
    store = schema39_store(tmp_path)
    with closing(store.connect()) as conn:
        before = all_rows(conn)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 40
        after = all_rows(conn)
        assert {name: after[name] for name in before} == before
        assert not conn.execute("SELECT * FROM family_duel_league_seasons").fetchall()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("schema39.db.schema39-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 39
        assert "family_duel_league_seasons" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


@pytest.mark.parametrize("boundary", [
    "validate_schema39", "backup_schema39", "migrate_family_duel_league", "validate_schema40",
])
def test_schema39_upgrade_failure_preserves_original_and_backup(tmp_path, monkeypatch, boundary):
    store = schema39_store(tmp_path)
    with closing(store.connect()) as conn:
        before = all_rows(conn)

    def fail(*args, **kwargs):
        raise RuntimeError("injected family duel league migration failure")

    monkeypatch.setattr(database, boundary, fail)
    with pytest.raises(RuntimeError, match="injected family duel league"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 39
        assert all_rows(conn) == before
    backups = list(tmp_path.glob("schema39.db.schema39-backup-*.db"))
    assert len(backups) == (0 if boundary in {"validate_schema39", "backup_schema39"} else 1)
