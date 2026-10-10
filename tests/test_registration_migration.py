import json
import sqlite3
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.registration import REGISTRATION_COLUMN, add_registration_times


def legacy_store(tmp_path):
    store = Store(tmp_path / "current.db")
    with closing(store.connect()) as conn:
        # Schema 18 differs only by the new column; retain all original constraints/tables.
        conn.executescript(database.SCHEMA_PATH.read_text().replace(REGISTRATION_COLUMN, ""))
        conn.execute("PRAGMA user_version=18")
        conn.execute("BEGIN IMMEDIATE")
        for user in ("proven", "unknown", "ambiguous", "wrong-pet"):
            conn.execute("INSERT INTO players(user_id,dao_name,stones) VALUES (?,?,?)", (user, user, 321))
            pet = conn.execute("INSERT INTO pets(user_id,species_id,name,affinity,energy_updated) VALUES (?,'qingluan','青鸾',20,999999)", (user,)).lastrowid
            conn.execute("UPDATE players SET active_pet_id=? WHERE user_id=?", (pet, user))
            conn.execute("INSERT INTO active_pet_slots VALUES (?,1,?)", (user, pet))
            conn.execute("INSERT INTO inventory VALUES (?,'spirit_food',7)", (user,))
            title = "修士名帖" if user == "unknown" else "灵契初成"
            target = pet if user != "wrong-pet" else 1
            payload = json.dumps({"title": title, "lines": ["你的道号：听雨散人。", f"你与青鸾缔结了灵契，编号 {target}。"], "commands": ["我的灵宠"]}, ensure_ascii=False)
            conn.execute("INSERT INTO operations VALUES (?,?,?,?)", (user, user, 1234567890, payload))
            if user == "ambiguous":
                conn.execute("INSERT INTO operations VALUES ('duplicate',?,?,?)", (user, 1234567891, payload))
        conn.commit()
    return store


def original_data(path):
    with closing(sqlite3.connect(path)) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result = {}
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")') if row[1] != "registered_at"]
            names = ",".join('"' + name + '"' for name in columns)
            result[table] = conn.execute(f'SELECT {names} FROM "{table}" ORDER BY rowid').fetchall()
        return result


def test_schema18_migration_preserves_every_original_field_and_backups(tmp_path):
    store = legacy_store(tmp_path)
    before = original_data(store.path)
    store.initialize()
    assert original_data(store.path) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 19
        dates = dict(conn.execute("SELECT user_id,registered_at FROM players"))
        assert dates == {"proven": 1234567890, "unknown": None, "ambiguous": None, "wrong-pet": None}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("current.db.schema18-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    assert original_data(backups[0]) == before
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 18
    store.initialize()
    assert list(tmp_path.glob("current.db.schema18-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "migration"])
def test_failed_migration_rolls_back_schema_version_and_all_data(tmp_path, monkeypatch, failure):
    store = legacy_store(tmp_path)
    before = original_data(store.path)

    def fail(*args):
        if failure == "migration":
            add_registration_times(*args)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(database, "backup_schema18" if failure == "backup" else "add_registration_times", fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.initialize()
    assert original_data(store.path) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 18
        assert "registered_at" not in [row[1] for row in conn.execute("PRAGMA table_info(players)")]
    if failure == "migration":
        assert len(list(tmp_path.glob("*.schema18-backup-*.db"))) == 1


def test_corrupt_adoption_cache_does_not_invent_historical_registration(tmp_path):
    store = legacy_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("UPDATE operations SET reply='null' WHERE user_id='proven'")
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("SELECT registered_at FROM players WHERE user_id='proven'").fetchone()[0] is None
