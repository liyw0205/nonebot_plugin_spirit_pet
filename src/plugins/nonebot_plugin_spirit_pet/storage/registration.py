"""Player registration metadata and stable public UID migrations."""

import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing

from ..utils.time import beijing_week

REGISTRATION_COLUMN = "    registered_at INTEGER CHECK (registered_at >= 0),\n"
RUNTIME_INDEXES = (
    "CREATE INDEX quest_progress_user_status ON quest_progress(user_id, quest_id, progress, claimed)",
    "CREATE INDEX pets_owner_species ON pets(user_id, archived, species_id, pet_id)",
    "CREATE INDEX market_listing_expiry ON market_listings(state, expires_at, listing_id)",
    "CREATE INDEX market_sales_seller_time ON market_sales(seller_id, sold_at DESC, listing_id DESC)",
    "CREATE INDEX market_sales_trend ON market_sales(sold_at, item_id, unit_price, quantity)",
    "CREATE INDEX market_bid_expiry ON market_bids(state, expires_at, bid_id)",
    "CREATE INDEX market_bid_sales_buyer_time ON market_bid_sales(buyer_id, sold_at DESC, bid_id DESC)",
    "CREATE INDEX market_bid_sales_seller_time ON market_bid_sales(seller_id, sold_at DESC, bid_id DESC)",
    "CREATE INDEX market_bid_sales_trend ON market_bid_sales(sold_at, item_id, unit_price, quantity)",
)


def _legacy_schema(current_schema: str, version: int) -> str:
    # Older fixtures are derived from the current file, so strip the newer market tables and the
    # schema-21 expedition changes first; otherwise an 18/19 fixture would already contain newer
    # structures and never match.
    schema = re.sub(
        r"CREATE TABLE player_identity \([\s\S]*?\n\);\n", "", legacy_schema20(current_schema)
    )
    match = re.search(r"CREATE TABLE players \(([\s\S]*?)\n\);", schema)
    if match is None:
        raise RuntimeError("Current schema is missing players table")
    body = match.group(1)
    body = body.replace(
        "    user_id TEXT PRIMARY KEY,\n",
        "    user_id TEXT PRIMARY KEY,\n    dao_name TEXT NOT NULL UNIQUE COLLATE NOCASE,\n",
        1,
    )
    if version == 18:
        body = body.replace(REGISTRATION_COLUMN, "")
    elif version == 19:
        body = body.replace(REGISTRATION_COLUMN, "", 1)
        last_column = "    last_pvp INTEGER,\n"
        body = body.replace(last_column, last_column + REGISTRATION_COLUMN, 1)
    return schema[:match.start(1)] + body + schema[match.end(1):]


def _validate_schema(
    conn: sqlite3.Connection, expected_schema: str, version: int,
    *, optional_indexes: tuple[str, ...] = (),
) -> None:
    def normalize(sql: str) -> str:
        sql = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", sql.strip())
        return re.sub(r"\s+", " ", sql)

    def definitions(database):
        return {
            (row[0], row[1]): normalize(row[2])
            for row in database.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }

    with closing(sqlite3.connect(":memory:")) as expected:
        expected.executescript(expected_schema)
        actual_definitions = definitions(conn)
        expected_definitions = definitions(expected)
        for statement in optional_indexes:
            expected.execute(statement)
            index_row = expected.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name=?",
                (statement.split()[2],),
            ).fetchone()
            if index_row is None:
                raise RuntimeError(f"Invalid optional schema index for version {version}")
            existing = actual_definitions.pop((index_row[0], index_row[1]), None)
            if existing is not None and existing != normalize(index_row[2]):
                raise RuntimeError(f"Schema {version} has a malformed optional index {index_row[1]}")
        if actual_definitions != expected_definitions:
            raise RuntimeError(f"Unsupported spirit pet schema version: {version} (structure mismatch)")
    if conn.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError(f"Schema {version} integrity/foreign key check failed; database preserved")


def validate_schema18(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, _legacy_schema(current_schema, 18), 18)


def validate_schema19(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, _legacy_schema(current_schema, 19), 19)


def legacy_schema20(current_schema: str) -> str:
    """Reconstruct schema 20 from the current schema: no market tables, no expedition slot."""
    schema = legacy_schema21(current_schema).replace(
        "    slot INTEGER NOT NULL DEFAULT 0 CHECK (slot IN (0, 1)),\n", "", 1,
    )
    return schema.replace(
        "CREATE UNIQUE INDEX expedition_running_slot ON expeditions(user_id, slot) WHERE state='running';",
        "CREATE UNIQUE INDEX expedition_running_player ON expeditions(user_id) WHERE state='running';",
        1,
    )


def validate_schema20(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema20(current_schema), 20)


def legacy_schema21(current_schema: str) -> str:
    """Reconstruct schema 21 from the current schema: no player market tables."""
    schema = legacy_schema22(current_schema)
    schema = re.sub(r"CREATE TABLE market_listings \([\s\S]*?\n\);\n", "", schema, count=1)
    schema = re.sub(r"CREATE TABLE market_sales \([\s\S]*?\n\);\n", "", schema, count=1)
    for name in ("market_listing_board", "market_listing_seller", "market_sales_seller"):
        schema = re.sub(rf"CREATE INDEX {name} [^;]*;\n", "", schema, count=1)
    if "market_" in schema:
        raise RuntimeError("Current schema still carries market definitions")
    return schema


def legacy_schema25(current_schema: str) -> str:
    """Reconstruct schema 25 from the current schema: no market buy orders."""
    schema = legacy_schema26(current_schema)
    for table in ("market_bids", "market_bid_sales"):
        schema = re.sub(rf"CREATE TABLE {table} \([\s\S]*?\n\);\n", "", schema, count=1)
    for name in ("market_bid_board", "market_bid_buyer", "market_bid_sales_seller", "market_bid_sales_buyer"):
        schema = re.sub(rf"CREATE INDEX {name} [^;]*;\n", "", schema, count=1)
    if "market_bid" in schema:
        raise RuntimeError("Current schema still carries buy-order definitions")
    return schema


def validate_schema26(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema26(current_schema), 26)


def legacy_schema26(current_schema: str) -> str:
    """Reconstruct schema 26 without the durable fishing ledger."""
    schema = re.sub(r"CREATE TABLE fishing_casts \([\s\S]*?\n\);\n", "", legacy_schema27(current_schema), count=1)
    return re.sub(r"CREATE INDEX fishing_cast_history [^;]*;\n", "", schema, count=1)


def validate_schema27(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema27(current_schema), 27)


def legacy_schema28(current_schema: str) -> str:
    return re.sub(
        r"CREATE TABLE sect_week_contributions \([\s\S]*?\n\);\n",
        "",
        legacy_schema29(current_schema),
        count=1,
    )


def legacy_schema29(current_schema: str) -> str:
    schema = legacy_schema30(current_schema)
    for table in ("race_league_config", "race_track_bests", "race_league_claims"):
        schema = re.sub(rf"CREATE TABLE {table} \([\s\S]*?\n\);\n", "", schema, count=1)
    return re.sub(r"CREATE INDEX race_track_week_board[\s\S]*?;\n", "", schema, count=1)


def legacy_schema30(current_schema: str) -> str:
    schema = legacy_schema31(current_schema)
    for table in ("sect_boss_weeks", "sect_boss_attacks", "sect_boss_claims"):
        schema = re.sub(rf"CREATE TABLE {table} \([\s\S]*?\n\);\n", "", schema, count=1)
    for index in ("sect_boss_attack_rank", "sect_boss_attack_history", "sect_boss_claim_history"):
        schema = re.sub(rf"CREATE INDEX {index} [^;]*;\n", "", schema, count=1)
    return schema


def legacy_schema27(current_schema: str) -> str:
    schema = re.sub(
        r"CREATE TABLE duel_actions \([\s\S]*?\n\);\n", "", legacy_schema28(current_schema), count=1,
    )
    return re.sub(r"CREATE INDEX duel_action_history [^;]*;\n", "", schema, count=1)


def validate_schema28(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(
        conn,
        legacy_schema28(current_schema),
        28,
        optional_indexes=RUNTIME_INDEXES,
    )


def validate_schema29(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema29(current_schema), 29, optional_indexes=RUNTIME_INDEXES)


def validate_schema30(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema30(current_schema), 30, optional_indexes=RUNTIME_INDEXES)


def validate_schema31(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema31(current_schema), 31, optional_indexes=RUNTIME_INDEXES)


def legacy_schema31(current_schema: str) -> str:
    schema = current_schema
    for table in ("wild_capture_runs", "wild_capture_attempts"):
        schema = re.sub(rf"CREATE TABLE {table} \([\s\S]*?\n\);\n", "", schema, count=1)
    for index in (
        "wild_capture_one_pending", "wild_capture_history", "wild_capture_daily",
        "wild_capture_attempt_history",
    ):
        schema = re.sub(rf"CREATE (?:UNIQUE )?INDEX {index} [^;]*;\n", "", schema, count=1)
    if "wild_capture_" in schema:
        raise RuntimeError("Current schema still carries wild capture definitions")
    return schema


def validate_schema32(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, current_schema, 32, optional_indexes=RUNTIME_INDEXES)


def backup_schema27(path: Path) -> Path:
    return _backup_schema(path, 27)


def backup_schema28(path: Path) -> Path:
    return _backup_schema(path, 28)


def backup_schema29(path: Path) -> Path:
    return _backup_schema(path, 29)


def backup_schema30(path: Path) -> Path:
    return _backup_schema(path, 30)


def backup_schema31(path: Path) -> Path:
    return _backup_schema(path, 31)


def migrate_wild_capture(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for pattern in (
        r"CREATE TABLE wild_capture_runs \([\s\S]*?\n\);",
        r"CREATE (?:UNIQUE )?INDEX wild_capture_one_pending [^;]*;",
        r"CREATE INDEX wild_capture_history [^;]*;",
        r"CREATE INDEX wild_capture_daily [^;]*;",
        r"CREATE TABLE wild_capture_attempts \([\s\S]*?\n\);",
        r"CREATE INDEX wild_capture_attempt_history [^;]*;",
    ):
        match = re.search(pattern, schema)
        if match is None:
            raise RuntimeError("Current schema is missing wild capture definitions")
        conn.execute(match.group(0))


def migrate_sect_boss(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for pattern in (
        r"CREATE TABLE sect_boss_weeks \([\s\S]*?\n\);",
        r"CREATE TABLE sect_boss_attacks \([\s\S]*?\n\);",
        r"CREATE INDEX sect_boss_attack_rank [^;]*;",
        r"CREATE INDEX sect_boss_attack_history [^;]*;",
        r"CREATE TABLE sect_boss_claims \([\s\S]*?\n\);",
        r"CREATE INDEX sect_boss_claim_history [^;]*;",
    ):
        match = re.search(pattern, schema)
        if match is None:
            raise RuntimeError("Current schema is missing sect boss definitions")
        conn.execute(match.group(0))


def migrate_sect_week_contributions(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE sect_week_contributions \([\s\S]*?\n\);", schema)
    if match is None:
        raise RuntimeError("Current schema is missing sect weekly contribution ledger")
    conn.execute(match.group(0))


def initialize_race_league(conn: sqlite3.Connection, now: int) -> None:
    week_start, _ = beijing_week(now)
    first_week_start = week_start if week_start == now else week_start + 7 * 86_400
    conn.execute(
        "INSERT INTO race_league_config(singleton, enabled_at, first_week_start) VALUES (1, ?, ?)",
        (now, first_week_start),
    )


def migrate_race_league(conn: sqlite3.Connection, now: int) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for pattern in (
        r"CREATE TABLE race_league_config \([\s\S]*?\n\);",
        r"CREATE TABLE race_track_bests \([\s\S]*?\n\);",
        r"CREATE INDEX race_track_week_board[\s\S]*?;",
        r"CREATE TABLE race_league_claims \([\s\S]*?\n\);",
    ):
        match = re.search(pattern, schema)
        if match is None:
            raise RuntimeError("Current schema is missing race league definitions")
        conn.execute(match.group(0))
    initialize_race_league(conn, now)


def migrate_duel_table(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for pattern in (
        r"CREATE TABLE duel_actions \([\s\S]*?\n\);",
        r"CREATE INDEX duel_action_history [^;]*;",
    ):
        match = re.search(pattern, schema)
        if match is None:
            raise RuntimeError("Current schema is missing duel action definitions")
        conn.execute(match.group(0))


def backup_schema26(path: Path) -> Path:
    return _backup_schema(path, 26)


def migrate_fishing_table(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for pattern in (
        r"CREATE TABLE fishing_casts \([\s\S]*?\n\);",
        r"CREATE INDEX fishing_cast_history [^;]*;",
    ):
        match = re.search(pattern, schema)
        if match is None:
            raise RuntimeError("Current schema is missing fishing ledger definitions")
        conn.execute(match.group(0))


def migrate_bid_tables(conn: sqlite3.Connection) -> None:
    """Schema 26: a standing buy order needs its escrow row and its ledger."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for table in ("market_bids", "market_bid_sales"):
        match = re.search(rf"CREATE TABLE {table} \([\s\S]*?\n\);", schema)
        if match is None:
            raise RuntimeError(f"Current schema is missing {table}")
        conn.execute(match.group(0))
    for name in ("market_bid_board", "market_bid_buyer", "market_bid_sales_seller", "market_bid_sales_buyer"):
        index = re.search(rf"CREATE INDEX {name} [^;]*;", schema)
        if index is None:
            raise RuntimeError(f"Current schema is missing {name}")
        conn.execute(index.group(0))


def backup_schema25(path: Path) -> Path:
    return _backup_schema(path, 25)


def validate_schema25(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema25(current_schema), 25)


def legacy_schema24(current_schema: str) -> str:
    """Reconstruct schema 24 from the current schema: no battle-report shares."""
    schema = re.sub(
        r"CREATE TABLE battle_shares \([\s\S]*?\n\);\n", "", legacy_schema25(current_schema), count=1,
    )
    for name in ("battle_share_owner", "battle_share_battle"):
        schema = re.sub(rf"CREATE INDEX {name} [^;]*;\n", "", schema, count=1)
    if "battle_share" in schema:
        raise RuntimeError("Current schema still carries share definitions")
    return schema


def migrate_share_tables(conn: sqlite3.Connection) -> None:
    """Schema 25: a revocable share code needs its own table."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE battle_shares \([\s\S]*?\n\);", schema)
    if match is None:
        raise RuntimeError("Current schema is missing battle_shares")
    conn.execute(match.group(0))
    for name in ("battle_share_owner", "battle_share_battle"):
        index = re.search(rf"CREATE INDEX {name} [^;]*;", schema)
        if index is None:
            raise RuntimeError(f"Current schema is missing {name}")
        conn.execute(index.group(0))


def backup_schema24(path: Path) -> Path:
    return _backup_schema(path, 24)


def validate_schema24(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema24(current_schema), 24)


def legacy_schema23(current_schema: str) -> str:
    """Reconstruct schema 23 from the current schema: no friend tables."""
    schema = legacy_schema24(current_schema)
    for table in ("friend_links", "friend_requests"):
        schema = re.sub(rf"CREATE TABLE {table} \([\s\S]*?\n\);\n", "", schema, count=1)
    for name in ("friend_link_low", "friend_link_high", "friend_request_inbox", "friend_request_outbox"):
        schema = re.sub(rf"CREATE INDEX {name} [^;]*;\n", "", schema, count=1)
    if "friend_" in schema:
        raise RuntimeError("Current schema still carries friend definitions")
    return schema


def migrate_friend_tables(conn: sqlite3.Connection) -> None:
    """Schema 24: a player-managed friendship needs link and request tables."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for table in ("friend_links", "friend_requests"):
        match = re.search(rf"CREATE TABLE {table} \([\s\S]*?\n\);", schema)
        if match is None:
            raise RuntimeError(f"Current schema is missing {table}")
        conn.execute(match.group(0))
    for name in ("friend_link_low", "friend_link_high", "friend_request_inbox", "friend_request_outbox"):
        match = re.search(rf"CREATE INDEX {name} [^;]*;", schema)
        if match is None:
            raise RuntimeError(f"Current schema is missing {name}")
        conn.execute(match.group(0))


def backup_schema23(path: Path) -> Path:
    return _backup_schema(path, 23)


def legacy_schema22(current_schema: str) -> str:
    """Reconstruct schema 22 from the current schema: no mailbox tables."""
    schema = re.sub(r"CREATE TABLE mail_messages \([\s\S]*?\n\);\n", "", legacy_schema23(current_schema), count=1)
    for name in ("mail_inbox", "mail_outbox"):
        schema = re.sub(rf"CREATE INDEX {name} [^;]*;\n", "", schema, count=1)
    if "mail_" in schema:
        raise RuntimeError("Current schema still carries mailbox definitions")
    return schema


def validate_schema23(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema23(current_schema), 23)


def migrate_mail_tables(conn: sqlite3.Connection) -> None:
    """Schema 23: an asynchronous player mailbox needs a real message table."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TABLE mail_messages \([\s\S]*?\n\);", schema)
    if match is None:
        raise RuntimeError("Current schema is missing mail_messages")
    conn.execute(match.group(0))
    for name in ("mail_inbox", "mail_outbox"):
        index = re.search(rf"CREATE INDEX {name} [^;]*;", schema)
        if index is None:
            raise RuntimeError(f"Current schema is missing {name}")
        conn.execute(index.group(0))


def backup_schema22(path: Path) -> Path:
    return _backup_schema(path, 22)


def validate_schema22(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema22(current_schema), 22)


def migrate_market_tables(conn: sqlite3.Connection) -> None:
    """Schema 22: the player market needs real listing and sale tables."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    for table in ("market_listings", "market_sales"):
        match = re.search(rf"CREATE TABLE {table} \([\s\S]*?\n\);", schema)
        if match is None:
            raise RuntimeError(f"Current schema is missing {table}")
        conn.execute(match.group(0))
    for name in ("market_listing_board", "market_listing_seller", "market_sales_seller"):
        match = re.search(rf"CREATE INDEX {name} [^;]*;", schema)
        if match is None:
            raise RuntimeError(f"Current schema is missing {name}")
        conn.execute(match.group(0))


def validate_schema21(conn: sqlite3.Connection, current_schema: str) -> None:
    _validate_schema(conn, legacy_schema21(current_schema), 21)


def migrate_expedition_slots(conn: sqlite3.Connection) -> None:
    """Schema 21: one running job per line instead of one per player."""
    conn.execute(
        "ALTER TABLE expeditions ADD COLUMN slot INTEGER NOT NULL DEFAULT 0 "
        "CHECK (slot IN (0, 1))"
    )
    conn.execute("DROP INDEX expedition_running_player")
    conn.execute(
        "CREATE UNIQUE INDEX expedition_running_slot ON expeditions(user_id, slot) "
        "WHERE state='running'"
    )


def backup_schema18(path: Path) -> Path:
    return _backup_schema(path, 18)


def backup_schema19(path: Path) -> Path:
    return _backup_schema(path, 19)


def backup_schema20(path: Path) -> Path:
    return _backup_schema(path, 20)


def backup_schema21(path: Path) -> Path:
    return _backup_schema(path, 21)


def _backup_schema(path: Path, version: int) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=path.name + f".schema{version}-backup-", suffix=".db", dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    os.chmod(backup, 0o600)
    try:
        # The caller holds BEGIN IMMEDIATE, before any writes. A separate reader sees that exact state.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(backup)) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA user_version").fetchone()[0] != version:
                    raise RuntimeError(f"Schema {version} backup version mismatch")
                if writer.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or writer.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError(f"Schema {version} backup verification failed")
        return backup
    except BaseException:
        backup.unlink(missing_ok=True)
        raise


def migrate_player_identity(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    identity_match = re.search(r"CREATE TABLE player_identity \([\s\S]*?\n\);", schema)
    match = re.search(r"CREATE TABLE players \([\s\S]*?\n\);", schema)
    if identity_match is None or match is None:
        raise RuntimeError("Current schema is missing player identity tables")
    conn.execute(identity_match.group(0))
    players_sql = match.group(0)
    conn.execute(
        "INSERT INTO player_identity(user_id, legacy_dao_name) "
        "SELECT user_id, dao_name FROM players ORDER BY rowid"
    )

    new_table = players_sql.replace("CREATE TABLE players (", "CREATE TABLE players_new (", 1)
    conn.execute(new_table)
    columns = (
        "user_id, stones, active_pet_id, registered_at, sign_day, last_bond_day, current_bond_streak, "
        "best_bond_streak, quest_day, last_train, last_explore, last_pve, last_pvp"
    )
    conn.execute(
        f"INSERT INTO players_new(rowid, {columns}) SELECT rowid, {columns} FROM players ORDER BY rowid"
    )
    conn.execute("DROP TABLE players")
    conn.execute("ALTER TABLE players_new RENAME TO players")


def add_registration_times(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE players ADD COLUMN registered_at INTEGER CHECK (registered_at >= 0)")
    candidates: dict[str, list[int]] = {}
    for user_id, created_at, payload in conn.execute("SELECT user_id, created_at, reply FROM operations"):
        try:
            reply = json.loads(payload)
            lines = reply["lines"]
            if reply["title"] != "灵契初成" or not isinstance(lines, list) or len(lines) < 2:
                continue
            if not re.fullmatch(r"你的道号：[\u4e00-\u9fffA-Za-z0-9]{2,12}。", lines[0]):
                continue
            adoption = re.fullmatch(r"你与.+缔结了灵契，编号 ([0-9]+)。", lines[1])
            if adoption is None or type(created_at) is not int or created_at < 0:
                continue
            pet = conn.execute("SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (user_id, int(adoption[1]))).fetchone()
            if pet:
                candidates.setdefault(user_id, []).append(created_at)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    # Multiple adoption-shaped records are ambiguous; ordinary queries are never evidence.
    for user_id, times in candidates.items():
        if len(times) == 1:
            conn.execute("UPDATE players SET registered_at=? WHERE user_id=?", (times[0], user_id))
