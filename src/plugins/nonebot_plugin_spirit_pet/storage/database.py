import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ..domain.models import GameError, Reply

SCHEMA_VERSION = 12
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
                    raise RuntimeError(
                        f"Unsupported spirit pet schema version: {version}. "
                        "Unreleased schema changed; back up the old database and use a new SPIRIT_PET_DB path."
                    )
                # Execute individual complete SQL statements without executescript's implicit COMMIT.
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
                    result = Reply(data["title"], tuple(data["lines"]), tuple(data["commands"]))
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
