from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, Store
from nonebot_plugin_spirit_pet.storage.registration import _without_family_tutelage, validate_schema36

from .test_family_trial_migration import snapshot


def schema36_store(tmp_path):
    store = Store(tmp_path / "schema36.db")
    with closing(store.connect()) as conn:
        conn.executescript(_without_family_tutelage(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=36")
        conn.execute("INSERT INTO players(user_id,stones,registered_at) VALUES ('legacy',3456,100)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('legacy')")
        conn.execute("INSERT INTO pets(pet_id,user_id,species_id,name,energy_updated) VALUES (1,'legacy','qingluan','旧伙伴',100)")
        conn.execute("UPDATE players SET active_pet_id=1 WHERE user_id='legacy'")
        conn.execute("INSERT INTO inventory VALUES ('legacy','forge_ore',7)")
        conn.execute("INSERT INTO learned_skills(pet_id,skill_id,level,proficiency,equipped) VALUES (1,'wind_slash',2,13,1)")
        conn.execute("INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES ('old','legacy',100,'{}','{}')")
        conn.execute("INSERT INTO family_trial_runs VALUES ('old-run','legacy',0,'trial','old','completed',3,100,100,'{}','{}')")
    return store


def test_schema36_verified_backup_and_atomic_migration_preserve_every_old_value(tmp_path):
    store = schema36_store(tmp_path)
    before = snapshot(store)
    with closing(store.connect()) as conn:
        validate_schema36(conn, SCHEMA_PATH.read_text(encoding="utf-8"))
    store.initialize()
    after = snapshot(store)
    for name in ("courses", "lessons", "exams", "graduations"):
        assert after.pop("family_tutelage_" + name) == []
    assert before == after
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema36.db.schema36-backup-*.db"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert snapshot(Store(backups[0])) == before
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 36
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    store.initialize()
    assert list(tmp_path.glob("schema36.db.schema36-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "migration", "validation"])
def test_failed_schema36_migration_restores_old_schema_and_data(tmp_path, monkeypatch, failure):
    store = schema36_store(tmp_path)
    before = snapshot(store)
    migrate = database.migrate_family_tutelage
    validate = database.validate_schema37

    def fail(*args):
        if failure == "migration":
            migrate(*args)
        elif failure == "validation":
            validate(*args)
        raise RuntimeError("injected tutelage migration")

    monkeypatch.setattr(database, {"backup":"backup_schema36", "migration":"migrate_family_tutelage", "validation":"validate_schema37"}[failure], fail)
    with pytest.raises(RuntimeError, match="injected tutelage"):
        store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 36
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema36.db.schema36-backup-*.db"))
    assert len(backups) == (0 if failure == "backup" else 1)
    if backups:
        assert snapshot(Store(backups[0])) == before


def test_schema36_structure_mismatch_is_rejected_before_backup(tmp_path):
    store = schema36_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("CREATE TABLE unexpected(value INTEGER)")
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="structure mismatch"):
        store.initialize()
    assert snapshot(store) == before
    assert not list(tmp_path.glob("*.schema36-backup-*.db"))
