from contextlib import closing
import sqlite3

import pytest

from scripts.database_admin import backup_database, restore_database, verify_database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_VERSION


def make_database(path, *, version=SCHEMA_VERSION):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN")
        conn.execute("CREATE TABLE values_table(value TEXT NOT NULL)")
        conn.execute("INSERT INTO values_table VALUES ('committed in WAL')")
        conn.execute(f"PRAGMA user_version={version}")
        conn.commit()


def test_online_backup_preserves_committed_wal_data_and_schema(tmp_path):
    source = tmp_path / "live.db"
    destination = tmp_path / "backup.db"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE values_table(value TEXT NOT NULL)")
    writer.execute("INSERT INTO values_table VALUES ('committed in WAL')")
    writer.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    writer.commit()

    try:
        assert backup_database(source, destination) == SCHEMA_VERSION
    finally:
        writer.close()
    assert verify_database(destination, expected_schema=SCHEMA_VERSION) == SCHEMA_VERSION
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM values_table").fetchone() == ("committed in WAL",)


def test_backup_and_restore_never_overwrite_existing_files(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    make_database(source)
    backup_database(source, backup)
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"preserve this file")

    with pytest.raises(FileExistsError):
        restore_database(backup, destination)
    assert destination.read_bytes() == b"preserve this file"


def test_restore_creates_a_verified_copy_without_changing_backup(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    make_database(source, version=8)

    backup_database(source, backup)
    assert restore_database(backup, restored) == 8
    assert verify_database(backup) == 8
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT value FROM values_table").fetchone() == ("committed in WAL",)


def test_verify_is_read_only_and_checks_expected_schema(tmp_path):
    database = tmp_path / "read-only.db"
    make_database(database)
    before = database.read_bytes()

    assert verify_database(database, expected_schema=SCHEMA_VERSION) == SCHEMA_VERSION
    assert database.read_bytes() == before
    with pytest.raises(RuntimeError, match="does not match expected version"):
        verify_database(database, expected_schema=SCHEMA_VERSION - 1)


def test_verify_rejects_foreign_key_violations(tmp_path):
    database = tmp_path / "bad-foreign-key.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child VALUES (99)")
        conn.commit()

    with pytest.raises(RuntimeError, match="foreign key check failed"):
        verify_database(database)


def test_failed_backup_does_not_publish_partial_file(tmp_path):
    source = tmp_path / "not-a-database.db"
    destination = tmp_path / "backup.db"
    source.write_bytes(b"not a SQLite database")

    with pytest.raises(sqlite3.DatabaseError):
        backup_database(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".backup.db.*.tmp"))
