import json
import sqlite3
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.domain.models import Reply
from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.registration import _legacy_schema


def schema19_store(tmp_path):
    store = Store(tmp_path / "current.db")
    schema = _legacy_schema(database.SCHEMA_PATH.read_text(encoding="utf-8"), 19)
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=19")
        conn.execute("BEGIN IMMEDIATE")
        for rowid, user, dao_name, pet_name in (
            (7, "old-user-a", "旧道号甲", "青鸾"),
            (40, "old-user-b", "旧道号乙", "玄狐"),
        ):
            conn.execute(
                "INSERT INTO players(rowid,user_id,dao_name,stones,registered_at) VALUES (?,?,?,?,?)",
                (rowid, user, dao_name, 321, 1234567890 + rowid),
            )
            pet_id = conn.execute(
                "INSERT INTO pets(user_id,species_id,name,affinity,energy_updated) "
                "VALUES (?, 'qingluan', ?, 20, 999999)", (user, pet_name),
            ).lastrowid
            conn.execute("UPDATE players SET active_pet_id=? WHERE user_id=?", (pet_id, user))
            conn.execute("INSERT INTO active_pet_slots VALUES (?,1,?)", (user, pet_id))
            conn.execute("INSERT INTO inventory VALUES (?,'spirit_food',7)", (user,))
            conn.execute("INSERT INTO operations VALUES (?,?,?,?)", (
                f"cached-{user}", user, 1234567890,
                json.dumps({"title": "旧缓存", "lines": [dao_name], "commands": ["我的信息"]}, ensure_ascii=False),
            ))
        conn.commit()
    return store


def test_schema19_migration_preserves_players_order_saves_cache_and_backup(tmp_path):
    store = schema19_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        original_players = conn.execute(
            "SELECT rowid,user_id,stones,active_pet_id,registered_at FROM players ORDER BY rowid"
        ).fetchall()
        original_pets = conn.execute("SELECT * FROM pets ORDER BY pet_id").fetchall()
        original_inventory = conn.execute("SELECT * FROM inventory ORDER BY user_id,item_id").fetchall()
        original_operations = conn.execute("SELECT * FROM operations ORDER BY operation_id").fetchall()

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 20
        assert [tuple(row) for row in conn.execute(
            "SELECT rowid,user_id,stones,active_pet_id,registered_at FROM players ORDER BY rowid"
        )] == original_players
        assert [tuple(row) for row in conn.execute("SELECT * FROM pets ORDER BY pet_id")] == original_pets
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory ORDER BY user_id,item_id")] == original_inventory
        assert [tuple(row) for row in conn.execute("SELECT * FROM operations ORDER BY operation_id")] == original_operations
        assert [tuple(row) for row in conn.execute(
            "SELECT id,user_id,legacy_dao_name FROM player_identity ORDER BY id"
        )] == [(1, "old-user-a", "旧道号甲"), (2, "old-user-b", "旧道号乙")]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

        cached = conn.execute("SELECT reply FROM operations WHERE operation_id='cached-old-user-a'").fetchone()[0]
        assert Reply.from_data(json.loads(cached)).lines == ("旧道号甲",)

    backups = list(tmp_path.glob("current.db.schema19-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 19
        assert conn.execute("SELECT rowid,user_id,dao_name FROM players ORDER BY rowid").fetchall() == [
            (7, "old-user-a", "旧道号甲"), (40, "old-user-b", "旧道号乙"),
        ]
    store.initialize()
    assert list(tmp_path.glob("current.db.schema19-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "migration"])
def test_failed_schema19_migration_rolls_back_without_touching_player_data(tmp_path, monkeypatch, failure):
    store = schema19_store(tmp_path)
    original_migration = database.migrate_player_identity
    with closing(sqlite3.connect(store.path)) as conn:
        before_players = conn.execute("SELECT rowid,* FROM players ORDER BY rowid").fetchall()
        before_pets = conn.execute("SELECT * FROM pets ORDER BY pet_id").fetchall()

    def fail(*args):
        if failure == "migration":
            original_migration(*args)
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        database, "backup_schema19" if failure == "backup" else "migrate_player_identity", fail,
    )
    with pytest.raises(RuntimeError, match="injected"):
        store.initialize()
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 19
        assert conn.execute("SELECT rowid,* FROM players ORDER BY rowid").fetchall() == before_players
        assert conn.execute("SELECT * FROM pets ORDER BY pet_id").fetchall() == before_pets
        assert "player_identity" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    if failure == "migration":
        assert len(list(tmp_path.glob("*.schema19-backup-*.db"))) == 1
