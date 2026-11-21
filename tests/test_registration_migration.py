import json
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from nonebot_plugin_spirit_pet.domain.models import Reply
from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import (
    _legacy_schema, legacy_schema28, legacy_schema29, legacy_schema30, legacy_schema31, legacy_schema32,
)
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_week


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


def schema28_store(tmp_path):
    store = Store(tmp_path / "schema28.db")
    schema = legacy_schema28(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=28")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('old-user', 321)")
        conn.execute("INSERT INTO player_identity(user_id, legacy_dao_name) VALUES ('old-user', '旧道号')")
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('old-user','spirit_food',7)",
        )
        conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES ('old-user','sect_week_contrib_1799798400',123,1)",
        )
        conn.commit()
    return store


def schema29_store(tmp_path):
    store = Store(tmp_path / "schema29.db")
    schema = legacy_schema29(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=29")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('old-user', 321)")
        conn.execute("INSERT INTO player_identity(user_id, legacy_dao_name) VALUES ('old-user', '旧道号')")
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('old-user','spirit_food',7)",
        )
        conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES ('old-user','race_best_1799798400',88,1)",
        )
        conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES ('old-user','race_prize_1799798400',1,1)",
        )
        conn.commit()
    return store


def schema30_store(tmp_path):
    store = Store(tmp_path / "schema30.db")
    schema = legacy_schema30(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=30")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('old-user', 321)")
        conn.execute("INSERT INTO player_identity(user_id, legacy_dao_name) VALUES ('old-user', '旧道号')")
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('old-user','spirit_food',7)",
        )
        conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES ('old-user','sect_week_contrib_1799798400',123,1)",
        )
        conn.commit()
    return store


def schema31_store(tmp_path):
    store = Store(tmp_path / "schema31.db")
    schema = legacy_schema31(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=31")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('old-user', 321)")
        conn.execute("INSERT INTO player_identity(user_id, legacy_dao_name) VALUES ('old-user', '旧道号')")
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('old-user','spirit_food',7)",
        )
        conn.execute(
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) "
            "VALUES ('old-user','sect_week_contrib_1799798400',123,1)",
        )
        conn.commit()
    return store


def schema32_store(tmp_path, filename="schema32.db"):
    store = Store(tmp_path / filename)
    schema = legacy_schema32(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    now = 1_800_000_000
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema)
        conn.execute("PRAGMA user_version=32")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('old-user', 321)")
        conn.execute("INSERT INTO player_identity(user_id, legacy_dao_name) VALUES ('old-user', '旧道号')")
        conn.execute("INSERT INTO inventory(user_id,item_id,quantity) VALUES ('old-user','spirit_food',7)")
        conn.execute(
            "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
            ("wild-action", "old-user", now, "{}", '{"title":"遭遇","lines":[],"commands":[]}'),
        )
        battle_id = conn.execute(
            "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,played_at,reply,snapshot,battle_log) "
            "VALUES ('wild-battle','old-user','pve','wild_spirit_spring','遭遇',1,1,?,?,?,?)",
            (now, '{"title":"遭遇","lines":[],"commands":[]}', "{}", "[]"),
        ).lastrowid
        conn.execute(
            "INSERT INTO wild_capture_runs(operation_id,user_id,route_id,route_name,day_key,species_id,species_name,rarity,"
            "enemy_id,enemy_name,enemy_snapshot,capture_item_id,capture_item_name,capture_rate,max_attempts,same_species_limit,"
            "state,terminal_reason,attempt_count,battle_id,started_at,expires_at,finished_at) "
            "VALUES ('wild-action','old-user','spirit_spring','灵泉修行','2026-11-21','sanlinglu','三灵鹿','common',"
            "'wood_guard','木卫','{}','spirit_snare','缚灵索',0.8,3,3,'escaped','battle_lost',0,?,?,?,?)",
            (battle_id, now, now + 21_600, now),
        )
        conn.commit()
    return store


def schema33_store(tmp_path):
    store = schema32_store(tmp_path, "schema33.db")
    with closing(store.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        database.migrate_wild_survey_claims(conn)
        conn.execute("PRAGMA user_version=33")
        conn.commit()
    return store


def test_empty_database_initializes_schema37_anchor(tmp_path, monkeypatch):
    store = Store(tmp_path / "empty.db")
    activation = 1_800_000_000
    monkeypatch.setattr(database.time, "time", lambda: activation)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "wild_capture_runs", "wild_capture_attempts", "wild_survey_claims",
            "wild_habitat_weeks", "wild_habitat_contributions", "wild_habitat_claims",
            "pet_pedigree_operations", "pet_lineage_eggs", "pet_pedigree_claims",
            "family_trial_runs", "family_trial_members", "family_trial_stages", "family_trial_rewards",
            "family_tutelage_courses", "family_tutelage_lessons", "family_tutelage_exams", "family_tutelage_graduations",
        } <= tables
        week_start, _ = beijing_week(activation)
        expected_first = week_start if activation == week_start else week_start + 7 * 86_400
        assert tuple(conn.execute(
            "SELECT enabled_at,first_week_start,latest_week_start FROM race_league_config"
        ).fetchone()) == (activation, expected_first, None)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_empty_database_enabled_exactly_at_beijing_monday_uses_that_week(tmp_path, monkeypatch):
    activation = int(datetime(2026, 11, 23, tzinfo=BEIJING).timestamp())
    store = Store(tmp_path / "monday.db")
    monkeypatch.setattr(database.time, "time", lambda: activation)

    store.initialize()

    with closing(store.connect()) as conn:
        anchor = conn.execute(
            "SELECT enabled_at,first_week_start FROM race_league_config"
        ).fetchone()
        assert tuple(anchor) == (activation, activation)


def test_schema19_fixture_matches_alter_table_registration_column_order(tmp_path):
    store = schema19_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(players)")]
    assert columns[-1] == "registered_at"


def test_schema28_migration_adds_weekly_ledger_without_changing_player_state(tmp_path):
    store = schema28_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        original_players = conn.execute("SELECT * FROM players").fetchall()
        original_inventory = conn.execute("SELECT * FROM inventory").fetchall()
        original_progress = conn.execute("SELECT * FROM quest_progress").fetchall()

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 37
        assert [tuple(row) for row in conn.execute("SELECT * FROM players")] == original_players
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory")] == original_inventory
        assert [tuple(row) for row in conn.execute("SELECT * FROM quest_progress")] == original_progress
        assert conn.execute("SELECT COUNT(*) FROM sect_week_contributions").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    backups = list(tmp_path.glob("schema28.db.schema28-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 28
        assert "sect_week_contributions" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    schema29_backups = list(tmp_path.glob("schema28.db.schema29-backup-*.db"))
    assert len(schema29_backups) == 1
    schema30_backups = list(tmp_path.glob("schema28.db.schema30-backup-*.db"))
    assert len(schema30_backups) == 1
    schema31_backups = list(tmp_path.glob("schema28.db.schema31-backup-*.db"))
    assert len(schema31_backups) == 1


def test_schema29_migration_preserves_legacy_race_records_and_initializes_anchor(tmp_path, monkeypatch):
    store = schema29_store(tmp_path)
    activation = 1_800_000_000
    monkeypatch.setattr(database.time, "time", lambda: activation)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        anchor = conn.execute(
            "SELECT enabled_at, first_week_start FROM race_league_config WHERE singleton=1"
        ).fetchone()
        week_start, _ = beijing_week(activation)
        expected_first = week_start if activation == week_start else week_start + 7 * 86_400
        assert tuple(anchor) == (activation, expected_first)
        assert conn.execute(
            "SELECT progress, claimed FROM quest_progress WHERE quest_id='race_best_1799798400'"
        ).fetchone()[:] == (88, 1)
        assert conn.execute(
            "SELECT progress, claimed FROM quest_progress WHERE quest_id='race_prize_1799798400'"
        ).fetchone()[:] == (1, 1)
        assert conn.execute("SELECT COUNT(*) FROM race_track_bests").fetchone()[0] == 0
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
        assert conn.execute("SELECT quantity FROM inventory WHERE user_id='old-user'").fetchone()[0] == 7
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema29.db.schema29-backup-*.db"))
    assert len(backups) == 1


def test_schema30_migration_adds_isolated_ledgers_and_preserves_player_state(tmp_path):
    store = schema30_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        original_players = conn.execute("SELECT * FROM players").fetchall()
        original_inventory = conn.execute("SELECT * FROM inventory").fetchall()
        original_progress = conn.execute("SELECT * FROM quest_progress").fetchall()

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert [tuple(row) for row in conn.execute("SELECT * FROM players")] == original_players
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory")] == original_inventory
        assert [tuple(row) for row in conn.execute("SELECT * FROM quest_progress")] == original_progress
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims",
            "wild_capture_runs", "wild_capture_attempts", "wild_survey_claims",
        } <= tables
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    backups = list(tmp_path.glob("schema30.db.schema30-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 30
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {
            "sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims",
            "wild_capture_runs", "wild_capture_attempts",
        }.intersection(tables)
    schema31_backups = list(tmp_path.glob("schema30.db.schema31-backup-*.db"))
    assert len(schema31_backups) == 1
    with closing(sqlite3.connect(schema31_backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims"} <= tables
        assert not {"wild_capture_runs", "wild_capture_attempts"}.intersection(tables)


def test_failed_schema31_migration_rolls_back_new_tables_and_version(tmp_path, monkeypatch):
    store = schema30_store(tmp_path)
    original_migration = database.migrate_sect_boss

    def fail_after_create(conn):
        original_migration(conn)
        raise RuntimeError("injected schema 31 failure")

    monkeypatch.setattr(database, "migrate_sect_boss", fail_after_create)
    with pytest.raises(RuntimeError, match="injected schema 31 failure"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 30
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims"}.intersection(tables)
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_schema31_migration_adds_wild_capture_ledgers_and_preserves_player_state(tmp_path):
    store = schema31_store(tmp_path)
    with closing(sqlite3.connect(store.path)) as conn:
        original_players = conn.execute("SELECT * FROM players").fetchall()
        original_inventory = conn.execute("SELECT * FROM inventory").fetchall()
        original_progress = conn.execute("SELECT * FROM quest_progress").fetchall()

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 37
        assert [tuple(row) for row in conn.execute("SELECT * FROM players")] == original_players
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory")] == original_inventory
        assert [tuple(row) for row in conn.execute("SELECT * FROM quest_progress")] == original_progress
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims"} <= tables
        assert {"wild_capture_runs", "wild_capture_attempts", "wild_survey_claims"} <= tables
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    backups = list(tmp_path.glob("schema31.db.schema31-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "sect_boss_weeks" in tables
        assert "wild_capture_runs" not in tables


def test_failed_schema32_migration_rolls_back_new_tables_and_version(tmp_path, monkeypatch):
    store = schema31_store(tmp_path)
    original_migration = database.migrate_wild_capture

    def fail_after_create(conn):
        original_migration(conn)
        raise RuntimeError("injected schema 32 failure")

    monkeypatch.setattr(database, "migrate_wild_capture", fail_after_create)
    with pytest.raises(RuntimeError, match="injected schema 32 failure"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"wild_capture_runs", "wild_capture_attempts"}.intersection(tables)
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("schema31.db.schema31-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        assert "wild_capture_runs" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_schema32_migration_preserves_wild_evidence_and_creates_verified_backups(tmp_path):
    store = schema32_store(tmp_path)
    with closing(store.connect()) as conn:
        original_run = tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone())
        original_inventory = [tuple(row) for row in conn.execute("SELECT * FROM inventory")]

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
        assert tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone()) == original_run
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory")] == original_inventory
        assert conn.execute("SELECT COUNT(*) FROM wild_survey_claims").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wild_habitat_weeks").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    schema33_backups = list(tmp_path.glob("schema32.db.schema33-backup-*.db"))
    assert len(schema33_backups) == 1
    with closing(sqlite3.connect(schema33_backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 33
        assert "wild_habitat_weeks" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    backups = list(tmp_path.glob("schema32.db.schema32-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 32
        assert tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone()) == original_run
        assert "wild_survey_claims" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_failed_schema33_migration_rolls_back_and_keeps_schema32_backup(tmp_path, monkeypatch):
    store = schema32_store(tmp_path)
    original_migration = database.migrate_wild_survey_claims

    def fail_after_create(conn):
        original_migration(conn)
        raise RuntimeError("injected schema 33 failure")

    monkeypatch.setattr(database, "migrate_wild_survey_claims", fail_after_create)
    with pytest.raises(RuntimeError, match="injected schema 33 failure"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 32
        assert "wild_survey_claims" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
        assert conn.execute("SELECT COUNT(*) FROM wild_capture_runs").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("schema32.db.schema32-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 32


def test_schema33_migration_adds_isolated_habitat_ledgers_and_backup(tmp_path):
    store = schema33_store(tmp_path)
    with closing(store.connect()) as conn:
        original_run = tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone())
        original_inventory = [tuple(row) for row in conn.execute("SELECT * FROM inventory")]

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 37
        assert tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone()) == original_run
        assert [tuple(row) for row in conn.execute("SELECT * FROM inventory")] == original_inventory
        assert not conn.execute("SELECT * FROM wild_habitat_weeks").fetchall()
        assert not conn.execute("SELECT * FROM wild_habitat_contributions").fetchall()
        assert not conn.execute("SELECT * FROM wild_habitat_claims").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    backups = list(tmp_path.glob("schema33.db.schema33-backup-*.db"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 33
        assert tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone()) == original_run
        assert "wild_habitat_weeks" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    store.initialize()
    assert list(tmp_path.glob("schema33.db.schema33-backup-*.db")) == backups


@pytest.mark.parametrize("failure", ["backup", "migration", "validation"])
def test_failed_schema33_to34_migration_rolls_back_and_preserves_backup(tmp_path, monkeypatch, failure):
    store = schema33_store(tmp_path)
    with closing(store.connect()) as conn:
        original_run = tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone())
    original_migration = database.migrate_wild_habitat
    original_validation = database.validate_schema34

    def fail_backup(path):
        raise RuntimeError("injected habitat backup failure")

    def fail_migration(conn):
        original_migration(conn)
        raise RuntimeError("injected habitat migration failure")

    def fail_validation(conn, schema):
        original_validation(conn, schema)
        raise RuntimeError("injected habitat validation failure")

    target, replacement = {
        "backup": ("backup_schema33", fail_backup),
        "migration": ("migrate_wild_habitat", fail_migration),
        "validation": ("validate_schema34", fail_validation),
    }[failure]
    monkeypatch.setattr(database, target, replacement)
    message = {
        "backup": "injected habitat backup failure",
        "migration": "injected habitat migration failure",
        "validation": "injected habitat validation failure",
    }[failure]
    with pytest.raises(RuntimeError, match=message):
        store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 33
        assert tuple(conn.execute("SELECT * FROM wild_capture_runs").fetchone()) == original_run
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "wild_habitat_weeks" not in tables
        assert "wild_survey_claims" in tables
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    backups = list(tmp_path.glob("schema33.db.schema33-backup-*.db"))
    assert len(backups) == (0 if failure == "backup" else 1)


def test_failed_schema30_migration_rolls_back_new_tables_and_anchor(tmp_path, monkeypatch):
    store = schema29_store(tmp_path)
    original_migration = database.migrate_race_league

    def fail_after_create(conn, now):
        original_migration(conn, now)
        raise RuntimeError("injected schema 30 failure")

    monkeypatch.setattr(database, "migrate_race_league", fail_after_create)
    with pytest.raises(RuntimeError, match="injected schema 30 failure"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 29
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names.intersection({"race_league_config", "race_track_bests", "race_league_claims"})
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
    assert len(list(tmp_path.glob("schema29.db.schema29-backup-*.db"))) == 1


def test_schema28_failed_migration_rolls_back_and_preserves_backup(tmp_path, monkeypatch):
    store = schema28_store(tmp_path)
    original_migration = database.migrate_sect_week_contributions

    def fail_after_create(conn):
        original_migration(conn)
        raise RuntimeError("injected schema 29 failure")

    monkeypatch.setattr(database, "migrate_sect_week_contributions", fail_after_create)
    with pytest.raises(RuntimeError, match="injected schema 29 failure"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 28
        assert conn.execute("SELECT stones FROM players WHERE user_id='old-user'").fetchone()[0] == 321
        assert "sect_week_contributions" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert len(list(tmp_path.glob("schema28.db.schema28-backup-*.db"))) == 1


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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
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
