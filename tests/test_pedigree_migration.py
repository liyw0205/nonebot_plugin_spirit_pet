import sqlite3
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, Store
from nonebot_plugin_spirit_pet.storage.registration import validate_schema34


def schema34_store(path):
    store = Store(path / "schema34.db")
    store.initialize()
    with closing(store.connect()) as conn:
        conn.execute("INSERT INTO players(user_id,stones,registered_at) VALUES ('legacy',321,100)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('legacy')")
        pet_id = conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) "
            "VALUES ('legacy','qingluan','旧伙伴',100)",
        ).lastrowid
        conn.execute("UPDATE players SET active_pet_id=? WHERE user_id='legacy'", (pet_id,))
        conn.execute("INSERT INTO inventory(user_id,item_id,quantity) VALUES ('legacy','egg_qingluan',4)")
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in (
            "family_duel_league_claims", "family_duel_league_runs",
            "family_duel_league_entries", "family_duel_league_seasons",
            "sect_boss_league_claims", "sect_boss_league_entries", "sect_boss_league_seasons",
            "family_duel_rewards", "family_duel_runs",
            "family_outing_rewards", "family_outing_steps", "family_outing_runs",
            "family_tutelage_graduations", "family_tutelage_exams", "family_tutelage_lessons", "family_tutelage_courses",
            "family_trial_rewards", "family_trial_stages", "family_trial_members", "family_trial_runs",
            "pet_pedigree_claims", "pet_lineage_eggs", "pet_pedigree_operations",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version=34")
    return store


def _legacy_state(conn):
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("players", "player_identity", "pets", "inventory")
    }


def test_schema34_migration_preserves_unknown_egg_stock_and_creates_verified_backup(tmp_path):
    store = schema34_store(tmp_path)
    with closing(store.connect()) as conn:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        validate_schema34(conn, schema)
        before = _legacy_state(conn)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert _legacy_state(conn) == before
        assert not conn.execute("SELECT * FROM pet_lineage_eggs").fetchall()
        assert not conn.execute("SELECT * FROM pet_pedigree_operations").fetchall()
        assert not conn.execute("SELECT * FROM pet_pedigree_claims").fetchall()
        for table in ("family_duel_league_seasons", "family_duel_league_entries",
                      "family_duel_league_runs", "family_duel_league_claims"):
            assert not conn.execute(f"SELECT * FROM {table}").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    backups = list(tmp_path.glob("schema34.db.schema34-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 34
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        )}
        assert not {"pet_lineage_eggs", "pet_pedigree_operations", "pet_pedigree_claims"} & tables
        assert not {"family_duel_league_seasons", "family_duel_league_entries",
                    "family_duel_league_runs", "family_duel_league_claims"} & tables
        assert conn.execute("SELECT quantity FROM inventory WHERE item_id='egg_qingluan'").fetchone()[0] == 4
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("failure", ["backup", "migration", "validation"])
def test_failed_schema34_migration_rolls_back_and_keeps_verified_backup(tmp_path, monkeypatch, failure):
    store = schema34_store(tmp_path)
    original_migrate = database.migrate_pedigree
    original_validate = database.validate_schema35

    def fail_backup(path):
        raise RuntimeError("injected pedigree backup failure")

    def fail_migration(conn):
        original_migrate(conn)
        raise RuntimeError("injected pedigree migration failure")

    def fail_validation(conn, schema):
        original_validate(conn, schema)
        raise RuntimeError("injected pedigree validation failure")

    target, replacement = {
        "backup": ("backup_schema34", fail_backup),
        "migration": ("migrate_pedigree", fail_migration),
        "validation": ("validate_schema35", fail_validation),
    }[failure]
    monkeypatch.setattr(database, target, replacement)
    with pytest.raises(RuntimeError, match=f"injected pedigree {failure} failure"):
        store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 34
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        )}
        assert not {"pet_lineage_eggs", "pet_pedigree_operations", "pet_pedigree_claims"} & tables
        assert conn.execute("SELECT stones FROM players WHERE user_id='legacy'").fetchone()[0] == 321
        assert conn.execute("SELECT quantity FROM inventory WHERE item_id='egg_qingluan'").fetchone()[0] == 4
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("schema34.db.schema34-backup-*.db"))
    assert len(backups) == (0 if failure == "backup" else 1)
    if backups:
        with closing(sqlite3.connect(backups[0])) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 34
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
