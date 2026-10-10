"""The single supported preservation migration: deployed schema 18 to 19."""

import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing

REGISTRATION_COLUMN = "    registered_at INTEGER CHECK (registered_at >= 0),\n"


def validate_schema18(conn: sqlite3.Connection, current_schema: str) -> None:
    def definitions(database):
        return {
            (row[0], row[1]): re.sub(r"\s+", " ", row[2].strip())
            for row in database.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }

    with closing(sqlite3.connect(":memory:")) as expected:
        expected.executescript(current_schema.replace(REGISTRATION_COLUMN, ""))
        if definitions(conn) != definitions(expected):
            raise RuntimeError("Unsupported spirit pet schema version: 18 (structure mismatch)")
    if conn.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("Schema 18 integrity/foreign key check failed; database preserved")


def backup_schema18(path: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".schema18-backup-", suffix=".db", dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    try:
        # The caller holds BEGIN IMMEDIATE, before any writes. A separate reader sees that exact state.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(backup)) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA user_version").fetchone()[0] != 18:
                    raise RuntimeError("Schema 18 backup version mismatch")
                if writer.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or writer.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Schema 18 backup verification failed")
        return backup
    except BaseException:
        backup.unlink(missing_ok=True)
        raise


def add_registration_times(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE players ADD COLUMN registered_at INTEGER CHECK (registered_at >= 0)")
    candidates: dict[str, list[int]] = {}
    for user_id, created_at, payload in conn.execute("SELECT user_id, created_at, reply FROM operations"):
        try:
            reply = json.loads(payload)
            lines = reply["lines"]
            if reply["title"] != "灵契初成" or not isinstance(lines, list) or len(lines) < 2:
                continue
            if not re.fullmatch(r"你的道号：[\u4e00-\u9fffA-Za-z0-9]{2,12}。", lines[0]):
                continue
            adoption = re.fullmatch(r"你与.+缔结了灵契，编号 ([0-9]+)。", lines[1])
            if adoption is None or type(created_at) is not int or created_at < 0:
                continue
            pet = conn.execute("SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (user_id, int(adoption[1]))).fetchone()
            if pet:
                candidates.setdefault(user_id, []).append(created_at)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    # Multiple adoption-shaped records are ambiguous; ordinary queries are never evidence.
    for user_id, times in candidates.items():
        if len(times) == 1:
            conn.execute("UPDATE players SET registered_at=? WHERE user_id=?", (times[0], user_id))
