import subprocess
import sys
from pathlib import Path


def test_plugin_index_metadata_declares_supported_adapters():
    from nonebot_plugin_spirit_pet import __plugin_meta__

    assert __plugin_meta__.name == "灵宠"
    assert __plugin_meta__.type == "application"
    assert __plugin_meta__.homepage == "https://github.com/liyw0205/nonebot_plugin_spirit_pet"
    assert __plugin_meta__.usage.startswith("灵宠帮助")
    assert __plugin_meta__.supported_adapters == {"~onebot.v11", "~qq"}


def test_actual_nonebot_reverse_websocket_roundtrip():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/smoke_test.py"], cwd=root, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout
