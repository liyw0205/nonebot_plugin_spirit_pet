"""Run reproducible balance checks without a bot connection or a player database."""

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv", type=Path, help="Write compact per-scenario results")
    parser.add_argument("--check", action="store_true", help="Exit nonzero on coverage or balance failures")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10000:
        parser.error("--runs must be from 1 to 10000")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src" / "plugins"))
    import nonebot

    nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="ERROR")
    from nonebot_plugin_spirit_pet.content.catalog import Catalog
    from nonebot_plugin_spirit_pet.core.config import Config
    from nonebot_plugin_spirit_pet.storage.database import Store
    from scripts.balance.report import run_report

    with tempfile.TemporaryDirectory(prefix="spirit-pet-balance-") as directory:
        store = Store(Path(directory) / "simulation.db")
        store.initialize()
        report = run_report(store, Catalog.load(), Config(), args.runs, args.seed)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        fields = [key for key in report["scenarios"][0] if key not in {"party", "units"}]
        with args.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(report["scenarios"])
    print(f"{report['scenario_count']} scenarios, {report['battle_count']} battles; {len(report['issues'])} issues")
    print(f"seed={args.seed}; content_sha256={report['content_sha256']}")
    for realm in dict.fromkeys(row["realm"] for row in report["scenarios"]):
        selected = [row for row in report["scenarios"] if row["realm"] == realm and row["profile"] == "prepared"]
        print(f"{realm}: prepared {len(selected)} scenarios; minimum win rate "
              f"{min(row['win_rate'] for row in selected):.1%}; mean "
              f"{sum(row['win_rate'] for row in selected) / len(selected):.1%}")
    for issue in report["issues"]:
        print(issue)
    return 1 if args.check and report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
