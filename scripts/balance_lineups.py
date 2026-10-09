"""Run finite solo-three-pet and team-five-pet comparisons in a temporary database."""

import argparse
import json
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--json", type=Path, help="Save the complete structured report")
    parser.add_argument("--markdown", type=Path, help="Save the comparison and yield report")
    parser.add_argument("--check", action="store_true", help="Exit nonzero on coverage or settlement/balance failures")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10000:
        parser.error("--runs must be from 1 to 10000")
    if args.json and args.markdown and args.json.resolve() == args.markdown.resolve():
        parser.error("--json and --markdown must have different output paths")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src" / "plugins"))
    import nonebot

    nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="ERROR")
    from nonebot_plugin_spirit_pet.content.catalog import Catalog
    from nonebot_plugin_spirit_pet.core.config import Config
    from nonebot_plugin_spirit_pet.storage.database import Store
    from scripts.balance.lineup_report import lineup_markdown, run_lineup_report

    with tempfile.TemporaryDirectory(prefix="spirit-pet-lineups-") as directory:
        store = Store(Path(directory) / "simulation.db")
        store.initialize()
        report = run_lineup_report(store, Catalog.load(), Config(), args.runs, args.seed)
    for target, payload in ((args.json, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
                            (args.markdown, lineup_markdown(report))):
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
    print(f"{report['scenario_count']} scenarios, {report['battle_count']} battles; {len(report['issues'])} issues")
    print(f"seed={args.seed}; content_sha256={report['content_sha256']}")
    for kind, count in (("solo", 3), ("team", 5)):
        rows = [row for row in report["scenarios"] if row["variant"] == "multi" and row["pet_count"] == count]
        prepared = [row for row in rows if row["profile"] == "prepared"]
        print(f"{kind}: {len(rows)} multi scenarios; prepared minimum win rate "
              f"{min(row['win_rate'] for row in prepared):.1%}")
    for issue in report["issues"]:
        print(issue)
    return 1 if args.check and report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
