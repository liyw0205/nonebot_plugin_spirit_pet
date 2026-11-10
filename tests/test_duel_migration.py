"""Schema 27 compatibility, private backup and migration rollback."""

import sqlite3
from hashlib import sha256
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema27
from nonebot_plugin_spirit_pet.application.game import Game

from .test_duel_tactics import snapshot


def test_frozen_schema27_matches_released_definition():
    frozen = legacy_schema27(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert sha256(frozen.encode()).hexdigest() == "7859127f044fac51ce232de98c985f3165a272ca9c37b1e293cdb6197d11bfcd"


def old_store(tmp_path):
    store = Store(tmp_path / "old27.db")
    with closing(sqlite3.connect(store.path)) as conn:
        conn.executescript(legacy_schema27(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=27")
        for index, user in ((8, "z-first"), (21, "a-next")):
            conn.execute("INSERT INTO players(user_id,stones,registered_at) VALUES (?,123,?)", (user, index))
            conn.execute("INSERT INTO player_identity(id,user_id) VALUES (?,?)", (index, user))
            conn.execute("INSERT INTO pets(pet_id,user_id,species_id,name,energy_updated) VALUES (?,?,'qingluan','青鸾',1800000000)", (index, user))
            conn.execute("UPDATE players SET active_pet_id=? WHERE user_id=?", (index, user))
            for key, value in (("duel_target", 1), ("duel_round", 4), ("duel_hp", 80), ("duel_enemy_hp", 75)):
                conn.execute("INSERT INTO quest_progress VALUES (?,?,?,0)", (user, key, value))
            conn.execute("INSERT INTO quest_progress VALUES (?,'duel_week_1799769600_songfeng',0,1)", (user,))
            conn.execute("INSERT INTO fishing_casts(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,0,'{}','{}')", (user, user))
        conn.commit()
    return store


def test_migrate_preserves_all_rows_uid_order_and_private_backup(tmp_path):
    store = old_store(tmp_path)
    before = snapshot(store)
    store.initialize()
    after = snapshot(store)
    assert after.pop("duel_actions") == []
    assert after == before
    backups = list(tmp_path.glob("*.schema27-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    assert snapshot(Store(backups[0])) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 28
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert [tuple(row) for row in conn.execute("SELECT id,user_id FROM player_identity ORDER BY id")] == [(8,"z-first"),(21,"a-next")]
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 27
    store.initialize()
    assert list(tmp_path.glob("*.schema27-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "ddl", "validation"])
def test_failed_migration_restores_entire_schema_and_data(tmp_path, monkeypatch, failure):
    store = old_store(tmp_path)
    before = snapshot(store)
    original = database.migrate_duel_table

    def fail(*args):
        if failure == "ddl":
            original(*args)
        raise RuntimeError("injected duel migration")

    monkeypatch.setattr(database, {"backup": "backup_schema27", "ddl": "migrate_duel_table", "validation": "validate_schema28"}[failure], fail)
    with pytest.raises(RuntimeError, match="injected duel migration"):
        store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 27


def test_foreign_schema_rejected_without_backup(tmp_path):
    store = old_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("CREATE TABLE surprise(value INTEGER)")
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="structure mismatch"):
        store.initialize()
    assert snapshot(store) == before
    assert not list(tmp_path.glob("*.schema27-backup-*.db"))


def test_migrated_active_bout_resumes_from_its_old_health(game, tmp_path):
    store = old_store(tmp_path)
    store.initialize()
    resumed = Game(store, game[0].config, game[0].rng, content=game[0].content)
    page = resumed.execute("z-first", "duel", "", "inspect", 1800000000)
    assert "旧局" in page.text() and "第 4 回合" in page.text()
    result = resumed.execute("z-first", "duel", "稳守", "continue", 1800000000)
    assert "旧局平招" in result.text() and "本回合精力 -3" in result.text()
    with closing(store.connect()) as conn:
        assert conn.execute("SELECT energy FROM pets WHERE pet_id=8").fetchone()[0] == 97
        assert conn.execute("SELECT progress FROM quest_progress WHERE user_id='z-first' AND quest_id='duel_hp'").fetchone()[0] < 80
        assert conn.execute("SELECT COUNT(*) FROM duel_actions").fetchone()[0] == 1
