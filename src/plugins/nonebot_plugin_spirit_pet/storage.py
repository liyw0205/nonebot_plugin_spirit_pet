import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from .models import Reply

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY,
    pet_name TEXT NOT NULL,
    species TEXT NOT NULL,
    realm INTEGER NOT NULL DEFAULT 0 CHECK (realm BETWEEN 0 AND 6),
    exp INTEGER NOT NULL DEFAULT 0 CHECK (exp >= 0),
    stones INTEGER NOT NULL DEFAULT 100 CHECK (stones >= 0),
    food INTEGER NOT NULL DEFAULT 3 CHECK (food >= 0),
    affinity INTEGER NOT NULL DEFAULT 0 CHECK (affinity BETWEEN 0 AND 100),
    energy INTEGER NOT NULL DEFAULT 100 CHECK (energy BETWEEN 0 AND 100),
    energy_updated INTEGER NOT NULL,
    sign_day TEXT NOT NULL DEFAULT '',
    last_train INTEGER,
    last_explore INTEGER
);
CREATE INDEX IF NOT EXISTS players_rank ON players(realm DESC, exp DESC, user_id);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_age ON operations(created_at);
"""


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
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported spirit pet schema version: {version}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")

    def transact(
        self,
        user_id: str,
        operation_id: str,
        now: int,
        action: Callable[[sqlite3.Connection], Reply],
    ) -> Reply:
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cached = conn.execute(
                    "SELECT user_id, reply FROM operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if cached:
                    if cached["user_id"] != user_id:
                        raise ValueError("operation ID reused by a different user")
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
