import subprocess
import sys
from pathlib import Path


def test_actual_nonebot_reverse_websocket_roundtrip():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/smoke_test.py"], cwd=root, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout
