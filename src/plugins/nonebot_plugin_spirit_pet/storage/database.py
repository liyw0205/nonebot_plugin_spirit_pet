import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ..domain.models import GameError, Reply
from .registration import (
    add_registration_times, backup_schema18, backup_schema19, migrate_player_identity,
    validate_schema18, validate_schema19, validate_schema20,
)

SCHEMA_VERSION = 20
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if version == SCHEMA_VERSION:
                return
            if version == 0 and not tables:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    tables = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        return
                    if version != 0 or tables:
                        raise RuntimeError(f"Database changed during initialization (schema {version})")
                    statement = ""
                    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ""
                    if statement.strip():
                        raise RuntimeError("Incomplete schema SQL")
                    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
                return
            if version == 18:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version not in (18, 19):
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    if version == 18:
                        schema = SCHEMA_PATH.read_text(encoding="utf-8")
                        validate_schema18(conn, schema)
                        backup_schema18(self.path)
                        add_registration_times(conn)
                        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("Registration migration integrity check failed; database preserved")
                        if conn.execute("PRAGMA foreign_key_check").fetchone():
                            raise RuntimeError("Registration migration foreign key check failed; database preserved")
                        conn.execute("PRAGMA user_version=19")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                version = 19
            if version == 19:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version != 19:
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    schema = SCHEMA_PATH.read_text(encoding="utf-8")
                    validate_schema19(conn, schema)
                    backup_schema19(self.path)
                    migrate_player_identity(conn)
                    validate_schema20(conn, schema)
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("UID migration integrity check failed; database preserved")
                    if conn.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("UID migration foreign key check failed; database preserved")
                    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                conn.execute("PRAGMA foreign_keys=ON")
                return
            raise RuntimeError(
                f"Unsupported spirit pet schema version: {version}. "
                "Unreleased schema changed; back up the old database and use a new SPIRIT_PET_DB path."
            )

    def transact(
        self, user_id: str, operation_id: str, now: int,
        action: Callable[[sqlite3.Connection], Reply],
    ) -> Reply:
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cached = conn.execute(
                    "SELECT user_id, reply FROM operations WHERE operation_id=?", (operation_id,),
                ).fetchone()
                if cached:
                    if cached["user_id"] != user_id:
                        raise GameError("operation ID reused by a different user")
                    data = json.loads(cached["reply"])
                    result = Reply.from_data(data)
                else:
                    result = action(conn)
                    conn.execute(
                        "INSERT INTO operations VALUES (?, ?, ?, ?)",
                        (operation_id, user_id, now, json.dumps(asdict(result), ensure_ascii=False)),
                    )
                    conn.execute("DELETE FROM operations WHERE created_at < ?", (now - 604800,))
                conn.commit()
                return result
            except BaseException:
                conn.rollback()
                raise
