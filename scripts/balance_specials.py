"""Run isolated, reproducible lineage and active-effect balance scenarios."""

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
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--check", action="store_true")
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
    from scripts.balance.special_report import run_special_report

    with tempfile.TemporaryDirectory(prefix="spirit-pet-specials-") as directory:
        store = Store(Path(directory) / "simulation.db")
        store.initialize()
        report = run_special_report(store, Catalog.load(), Config(), args.runs, args.seed)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        excluded = {"party", "opponents", "effect_activations", "left_units", "right_units"}
        fields = [key for key in report["scenarios"][0] if key not in excluded]
        with args.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(report["scenarios"])
    covered = report["coverage"]
    print(f"{report['scenario_count']} scenarios, {report['battle_count']} battles; {len(report['issues'])} issues")
    print(f"lineages={covered['lineages_exercised']}/{covered['lineages_expected']}; "
          f"effects={covered['effects_triggered']}/{covered['effects_expected']}")
    print(f"seed={args.seed}; content_sha256={report['content_sha256']}")
    for row in report["scenarios"]:
        if row["category"] in {"effect", "skill"} and row["variant"] == "selected":
            print(f"{row['subject']}: wins={row['wins']}/{row['trials']}; "
                  f"casts={row['tracked_skill_casts']}; activations={row['actual_effect_activations']}")
    for issue in report["issues"]:
        print(issue)
    return 1 if args.check and report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
