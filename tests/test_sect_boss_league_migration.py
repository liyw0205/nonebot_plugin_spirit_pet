from contextlib import closing
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.storage import database
from nonebot_plugin_spirit_pet.storage.registration import _without_sect_boss_league


def schema40_store(tmp_path):
    path = tmp_path / "schema40.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        schema = database.SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(_without_sect_boss_league(schema))
        database.initialize_race_league(conn, 1_800_000_000)
        conn.execute("INSERT INTO players(user_id,stones) VALUES ('u1',1234)")
        conn.execute("INSERT INTO player_identity(user_id) VALUES ('u1')")
        conn.execute(
            "INSERT INTO sect_boss_weeks(week_start,sect_id,enemy_id,boss_name,description,combat_snapshot,"
            "max_hp,current_hp,state,started_at,closed_at) VALUES "
            "(316800,'jian_ge','enemy','首领','描述','{}',9000,8000,'active',316800,NULL)"
        )
        conn.execute(
            "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,"
            "played_at,reply,snapshot,battle_log) VALUES "
            "('old-sect-boss-attack','u1','pve_stage','sect-boss:316800:jian_ge','首领',-1,1,316900,'{}','{}','[]')"
        )
        battle_id = conn.execute("SELECT battle_id FROM battle_records WHERE operation_id='old-sect-boss-attack'").fetchone()[0]
        conn.execute(
            "INSERT INTO sect_boss_attacks(week_start,sect_id,user_id,battle_day,attempt,operation_id,battle_id,"
            "hp_before,hp_after,damage,created_at) VALUES "
            "(316800,'jian_ge','u1','1970-01-05',1,'old-sect-boss-attack',?,9000,8000,1000,316900)",
            (battle_id,),
        )
        conn.execute(
            "INSERT INTO sect_boss_claims(week_start,sect_id,user_id,scope,tier,operation_id,claimed_at,"
            "reward_snapshot,reply) VALUES "
            "(316800,'jian_ge','u1','personal',1,'old-sect-boss-prize',317000,'{}','{}')"
        )
        conn.execute("PRAGMA user_version=40")
        conn.commit()
    return database.Store(path)


def all_rows(conn):
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')]
            for name in tables}


def test_schema40_backup_and_upgrade_preserve_shared_boss_data(tmp_path):
    store = schema40_store(tmp_path)
    with closing(store.connect()) as conn:
        before = all_rows(conn)

    store.initialize()

    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 41
        after = all_rows(conn)
        assert {name: after[name] for name in before} == before
        assert not conn.execute("SELECT * FROM sect_boss_league_seasons").fetchall()
        assert not conn.execute("SELECT * FROM sect_boss_league_entries").fetchall()
        assert not conn.execute("SELECT * FROM sect_boss_league_claims").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        identity_fks = conn.execute("PRAGMA foreign_key_list(sect_boss_league_entries)").fetchall()
        assert any(row["table"] == "player_identity" for row in identity_fks)
    backups = list(tmp_path.glob("schema40.db.schema40-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 40
        assert "sect_boss_league_seasons" not in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("boundary", [
    "validate_schema40", "backup_schema40", "migrate_sect_boss_league", "validate_schema41",
])
def test_schema40_upgrade_failure_preserves_original_and_verified_backup(tmp_path, monkeypatch, boundary):
    store = schema40_store(tmp_path)
    with closing(store.connect()) as conn:
        before = all_rows(conn)

    def fail(*args, **kwargs):
        raise RuntimeError("injected sect boss league migration failure")

    monkeypatch.setattr(database, boundary, fail)
    with pytest.raises(RuntimeError, match="injected sect boss league"):
        store.initialize()

    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 40
        assert all_rows(conn) == before
    backups = list(tmp_path.glob("schema40.db.schema40-backup-*.db"))
    assert len(backups) == (0 if boundary in {"validate_schema40", "backup_schema40"} else 1)
