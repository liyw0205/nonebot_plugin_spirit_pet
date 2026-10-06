import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("script,expected", [("balance_report.py", 626), ("balance_specials.py", 120)])
def test_balance_cli_exports_parseable_portable_reports(tmp_path, script, expected):
    root = Path(__file__).resolve().parents[1]
    csv_path = tmp_path / "report.csv"
    json_path = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / script), "--runs", "1", "--seed", "20261007",
         "--csv", str(csv_path), "--output", str(json_path)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw = csv_path.read_bytes()
    assert b"\r" not in raw
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(rows) == report["scenario_count"] == report["battle_count"] == expected
    assert {row["trials"] for row in rows} == {"1"}
    assert [row["id"] for row in rows] == [row["id"] for row in report["scenarios"]]
