from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_user_upgrade_docs_use_release_update_flow():
    documents = {
        "README.md": "### 更新正式 Release",
        "docs/INSTALLATION.md": "## 更新正式 Release 安装",
        "docs/CONFIGURATION.md": "## 升级与回滚",
    }
    asset_url = "releases/latest/download/project.tar.gz"

    for path, heading in documents.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "git pull" not in text
        section = text.split(heading, 1)[1]
        steps = ["xiupet stop", "cp .env", "database_admin.py backup", "xiupet update", "xiupet start"]
        positions = [section.index(step) for step in steps]
        assert positions == sorted(positions), path
        assert asset_url in section
        assert ".env" in section and "data/" in section
