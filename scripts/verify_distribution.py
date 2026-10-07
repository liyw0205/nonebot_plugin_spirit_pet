from pathlib import Path
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "plugins" / "nonebot_plugin_spirit_pet"
WHEEL_PREFIX = "nonebot_plugin_spirit_pet/"


def verify(wheel: Path) -> None:
    expected = {
        WHEEL_PREFIX + path.relative_to(PACKAGE).as_posix()
        for path in (PACKAGE / "data").glob("*.json")
    }
    expected.add(WHEEL_PREFIX + "storage/schema.sql")
    with ZipFile(wheel) as archive:
        present = set(archive.namelist())
    missing = sorted(expected - present)
    if missing:
        raise SystemExit(f"wheel is missing runtime content: {', '.join(missing)}")
    print(f"Verified {len(expected) - 1} JSON files and storage/schema.sql in {wheel.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_distribution.py PATH_TO_WHEEL")
    verify(Path(sys.argv[1]))
