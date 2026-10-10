"""Player registration metadata and stable public UID migrations."""

import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing

REGISTRATION_COLUMN = "    registered_at INTEGER CHECK (registered_at >= 0),\n"


def _legacy_schema(current_schema: str, version: int) -> str:
    schema = re.sub(r"CREATE TABLE player_identity \([\s\S]*?\n\);\n", "", current_schema)
    match = re.search(r"CREATE TABLE players \(([\s\S]*?)\n\);", schema)
    if match is None:
        raise RuntimeError("Current schema is missing players table")
    body = match.group(1)
    body = body.replace(
        "    user_id TEXT PRIMARY KEY,\n",
        "    user_id TEXT PRIMARY KEY,\n    dao_name TEXT NOT NULL UNIQUE COLLATE NOCASE,\n",
        1,
    )
    if version == 18:
        body = body.replace(REGISTRATION_COLUMN, "")
    return schema[:match.start(1)] + body + schema[match.end(1):]


def _validate_schema(conn: sqlite3.Connection, expected_schema: str, version: int) -> None:
    def normalize(sql: str) -> str:
        sql = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", sql.strip())
        return re.sub(r"\s+", " ", sql)

    def definitions(database):
        return {
            (row[0], row[1]): normalize(row[2])
            for row in database.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }

    with closing(sqlite3.connect(":memory:")) as expected:
        expected.executescript(expected_schema)
        if definitions(conn) != definitions(expected):
            raise RuntimeError(f"Unsupported spirit pet schema version: {version} (structure mismatch)")
    if conn.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError(f"Schema {version} integrity/foreign key check failed; database preserved")


def validate_schema18(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, _legacy_schema(current_schema, 18), 18)


def validate_schema19(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, _legacy_schema(current_schema, 19), 19)


def validate_schema20(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, current_schema, 20)


def backup_schema18(path: Path) -> Path:
    return _backup_schema(path, 18)


def backup_schema19(path: Path) -> Path:
    return _backup_schema(path, 19)


def _backup_schema(path: Path, version: int) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=path.name + f".schema{version}-backup-", suffix=".db", dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    os.chmod(backup, 0o600)
    try:
        # The caller holds BEGIN IMMEDIATE, before any writes. A separate reader sees that exact state.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(backup)) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA user_version").fetchone()[0] != version:
                    raise RuntimeError(f"Schema {version} backup version mismatch")
                if writer.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or writer.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError(f"Schema {version} backup verification failed")
        return backup
    except BaseException:
        backup.unlink(missing_ok=True)
        raise


def migrate_player_identity(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    identity_match = re.search(r"CREATE TABLE player_identity \([\s\S]*?\n\);", schema)
    match = re.search(r"CREATE TABLE players \([\s\S]*?\n\);", schema)
    if identity_match is None or match is None:
        raise RuntimeError("Current schema is missing player identity tables")
    conn.execute(identity_match.group(0))
    players_sql = match.group(0)
    conn.execute(
        "INSERT INTO player_identity(user_id, legacy_dao_name) "
        "SELECT user_id, dao_name FROM players ORDER BY rowid"
    )

    new_table = players_sql.replace("CREATE TABLE players (", "CREATE TABLE players_new (", 1)
    conn.execute(new_table)
    columns = (
        "user_id, stones, active_pet_id, registered_at, sign_day, last_bond_day, current_bond_streak, "
        "best_bond_streak, quest_day, last_train, last_explore, last_pve, last_pvp"
    )
    conn.execute(
        f"INSERT INTO players_new(rowid, {columns}) SELECT rowid, {columns} FROM players ORDER BY rowid"
    )
    conn.execute("DROP TABLE players")
    conn.execute("ALTER TABLE players_new RENAME TO players")


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
