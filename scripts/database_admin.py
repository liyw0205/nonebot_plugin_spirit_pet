"""Create and verify non-overwriting SQLite snapshots for a Spirit Pet database."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile


def _existing_database(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"database is not a file: {resolved}")
    return resolved


def verify_database(path: Path, expected_schema: int | None = None) -> int:
    source = _existing_database(path)
    uri = f"{source.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=15)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if integrity != [("ok",)]:
        raise RuntimeError(f"SQLite integrity check failed: {integrity[:5]}")
    if violations:
        raise RuntimeError(f"SQLite foreign key check failed: {len(violations)} violation(s)")
    if expected_schema is not None and version != expected_schema:
        raise RuntimeError(f"schema version {version} does not match expected version {expected_schema}")
    return version


def _snapshot_database(source_path: Path, destination_path: Path) -> int:
    source = _existing_database(source_path)
    destination = destination_path.expanduser()
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if source == destination:
        raise ValueError("source and destination must be different files")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        source_uri = f"{source.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=15)) as reader:
            with closing(sqlite3.connect(temporary, timeout=15)) as writer:
                reader.backup(writer)
        version = verify_database(temporary)
        if os.name != "nt":
            temporary.chmod(0o600)
        # A hard link publishes the complete snapshot atomically without replacing a destination.
        os.link(temporary, destination)
        return verify_database(destination, version)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(source: Path, destination: Path) -> int:
    """Copy a consistent database snapshot without replacing an existing file."""
    return _snapshot_database(source, destination)


def restore_database(backup: Path, destination: Path) -> int:
    """Restore a backup into a new path, preserving the original database."""
    return _snapshot_database(backup, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="check a database without modifying it")
    verify.add_argument("database", type=Path)
    verify.add_argument("--schema-version", type=int)
    for name, source_label in (("backup", "source"), ("restore", "backup")):
        action = commands.add_parser(name, help=f"{name} into a new, non-overwriting path")
        action.add_argument(source_label, type=Path)
        action.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            version = verify_database(args.database, args.schema_version)
            print(f"Database verified: schema {version}")
        elif args.command == "backup":
            version = backup_database(args.source, args.destination)
            print(f"Backup created and verified: {args.destination} (schema {version})")
        else:
            version = restore_database(args.backup, args.destination)
            print(f"Restored copy created and verified: {args.destination} (schema {version})")
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
