from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, Store
from nonebot_plugin_spirit_pet.storage.registration import _without_family_trials, validate_schema35


def schema35_store(tmp_path):
    store = Store(tmp_path / "schema35.db")
    with closing(store.connect()) as conn:
        conn.executescript(_without_family_trials(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=35")
        conn.execute("INSERT INTO players(user_id,stones,registered_at) VALUES ('legacy',5432,100)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('legacy')")
        for number in (1, 2, 3):
            conn.execute("INSERT INTO pets(pet_id,user_id,species_id,name,energy_updated) VALUES (?,'legacy','qingluan',?,100)", (number, f"伙伴{number}"))
        conn.execute("UPDATE players SET active_pet_id=1 WHERE user_id='legacy'")
        conn.execute("INSERT INTO inventory VALUES ('legacy','egg_qingluan',4)")
        conn.execute("INSERT INTO pet_pedigree_operations(operation_id,user_id,kind,created_at,snapshot,reply) VALUES ('breed','legacy','breed',100,'{}','{}')")
        conn.execute("INSERT INTO pet_lineage_eggs(user_id,item_id,species_id,parent_a_id,parent_a_name,parent_a_species_id,parent_b_id,parent_b_name,parent_b_species_id,operation_id,status,child_pet_id,child_name,created_at,finished_at) VALUES ('legacy','egg_qingluan','qingluan',1,'伙伴1','qingluan',2,'伙伴2','qingluan','breed','hatched',3,'伙伴3',100,200)")
    return store


def snapshot(store):
    with closing(store.connect()) as conn:
        return {row[0]: [tuple(value) for value in conn.execute(f'SELECT * FROM "{row[0]}" ORDER BY rowid')]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_schema35_migration_preserves_every_existing_row_and_verified_backup(tmp_path):
    store = schema35_store(tmp_path)
    before = snapshot(store)
    with closing(store.connect()) as conn:
        validate_schema35(conn, SCHEMA_PATH.read_text(encoding="utf-8"))
    store.initialize()
    after = snapshot(store)
    for table in ("family_trial_runs", "family_trial_members", "family_trial_stages", "family_trial_rewards",
                  "family_tutelage_courses", "family_tutelage_lessons", "family_tutelage_exams", "family_tutelage_graduations"):
        assert after.pop(table) == []
    assert before == after
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema35.db.schema35-backup-*.db"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert snapshot(Store(backups[0])) == before
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 35
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    store.initialize()
    assert list(tmp_path.glob("schema35.db.schema35-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "migration", "validation"])
def test_failed_schema35_migration_rolls_back_schema_data_and_preserves_backup(tmp_path, monkeypatch, failure):
    store = schema35_store(tmp_path)
    before = snapshot(store)
    original_migrate = database.migrate_family_trials
    original_validate = database.validate_schema36

    def fail(*args):
        if failure == "migration":
            original_migrate(*args)
        if failure == "validation":
            original_validate(*args)
        raise RuntimeError("injected family trial migration")

    monkeypatch.setattr(database, {"backup": "backup_schema35", "migration": "migrate_family_trials", "validation": "validate_schema36"}[failure], fail)
    with pytest.raises(RuntimeError, match="injected family trial"):
        store.initialize()
    assert snapshot(store) == before
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 35
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema35.db.schema35-backup-*.db"))
    assert len(backups) == (0 if failure == "backup" else 1)
    if backups:
        assert snapshot(Store(backups[0])) == before


def test_schema35_mismatch_refuses_before_backup(tmp_path):
    store = schema35_store(tmp_path)
    with closing(store.connect()) as conn:
        conn.execute("CREATE TABLE surprise(value INTEGER)")
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="structure mismatch"):
        store.initialize()
    assert snapshot(store) == before
    assert not list(tmp_path.glob("*.schema35-backup-*.db"))
