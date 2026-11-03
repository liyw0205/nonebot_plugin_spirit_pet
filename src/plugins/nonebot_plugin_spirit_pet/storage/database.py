import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ..domain.models import GameError, Reply
from .registration import (
    add_registration_times, backup_schema18, backup_schema19, backup_schema20, backup_schema21,
    backup_schema22, backup_schema23, migrate_expedition_slots, migrate_friend_tables,
    migrate_mail_tables, migrate_market_tables,
    migrate_player_identity, validate_schema18, validate_schema19, validate_schema20,
    validate_schema21, validate_schema22, validate_schema23, validate_schema24,
)

SCHEMA_VERSION = 24
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
                    conn.execute("PRAGMA user_version=20")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                conn.execute("PRAGMA foreign_keys=ON")
                version = 20
            if version == 20:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version != 20:
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    schema = SCHEMA_PATH.read_text(encoding="utf-8")
                    validate_schema20(conn, schema)
                    backup_schema20(self.path)
                    migrate_expedition_slots(conn)
                    validate_schema21(conn, schema)
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Expedition slot migration integrity check failed; database preserved")
                    if conn.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("Expedition slot migration foreign key check failed; database preserved")
                    conn.execute("PRAGMA user_version=21")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                conn.execute("PRAGMA foreign_keys=ON")
                version = 21
            if version == 21:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version != 21:
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    schema = SCHEMA_PATH.read_text(encoding="utf-8")
                    validate_schema21(conn, schema)
                    backup_schema21(self.path)
                    migrate_market_tables(conn)
                    validate_schema22(conn, schema)
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Market migration integrity check failed; database preserved")
                    if conn.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("Market migration foreign key check failed; database preserved")
                    conn.execute("PRAGMA user_version=22")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                conn.execute("PRAGMA foreign_keys=ON")
                version = 22
            if version == 22:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version != 22:
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    schema = SCHEMA_PATH.read_text(encoding="utf-8")
                    validate_schema22(conn, schema)
                    backup_schema22(self.path)
                    migrate_mail_tables(conn)
                    validate_schema23(conn, schema)
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Mailbox migration integrity check failed; database preserved")
                    if conn.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("Mailbox migration foreign key check failed; database preserved")
                    conn.execute("PRAGMA user_version=23")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute("PRAGMA foreign_keys=ON")
                    raise
                conn.execute("PRAGMA foreign_keys=ON")
                version = 23
            if version == 23:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == SCHEMA_VERSION:
                        conn.commit()
                        conn.execute("PRAGMA foreign_keys=ON")
                        return
                    if version != 23:
                        raise RuntimeError(f"Database changed during migration (schema {version})")
                    schema = SCHEMA_PATH.read_text(encoding="utf-8")
                    validate_schema23(conn, schema)
                    backup_schema23(self.path)
                    migrate_friend_tables(conn)
                    validate_schema24(conn, schema)
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Friend migration integrity check failed; database preserved")
                    if conn.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("Friend migration foreign key check failed; database preserved")
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
