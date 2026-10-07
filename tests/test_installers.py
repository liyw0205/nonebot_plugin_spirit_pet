import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source_project(tmp_path):
    project = tmp_path / "source project"
    (project / "scripts").mkdir(parents=True)
    (project / "src/plugins/nonebot_plugin_spirit_pet").mkdir(parents=True)
    for name in ("pyproject.toml", "requirements.txt", ".env.example", "LICENSE"):
        shutil.copy2(ROOT / name, project / name)
    for name in ("install.sh", "xiupet.sh", "install.ps1", "xiupet.ps1"):
        shutil.copy2(ROOT / "scripts" / name, project / "scripts" / name)
    shutil.copy2(
        ROOT / "src/plugins/nonebot_plugin_spirit_pet/__init__.py",
        project / "src/plugins/nonebot_plugin_spirit_pet/__init__.py",
    )
    return project


def fake_python(tmp_path):
    binary = tmp_path / "fake python"
    nb = tmp_path / "fake nb"
    nb.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    nb.chmod(0o755)
    binary.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = --version ] && [ -n \"${SPIRIT_PET_TEST_PYTHON_MARKER:-}\" ] && [ ! -f \"$SPIRIT_PET_TEST_PYTHON_MARKER\" ]; then exit 1; fi\n"
        "if [ \"$1\" = --version ]; then printf 'Python 3.12.0\\n'; exit 0; fi\n"
        "if [ \"$1\" = -m ] && [ \"$2\" = venv ]; then\n"
        "  mkdir -p \"$3/bin\"\n"
        "  printf 'home = fake\\n' > \"$3/pyvenv.cfg\"\n"
        "  cp \"$SPIRIT_PET_TEST_PYTHON\" \"$3/bin/python\"\n"
        "  cp \"$SPIRIT_PET_TEST_NB\" \"$3/bin/nb\"\n"
        "  cp \"$SPIRIT_PET_TEST_NB\" \"$3/bin/pip\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, nb


def test_shell_entrypoints_parse_and_help_without_python_or_system_changes():
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    for name in ("install.sh", "install_termux.sh", "xiupet.sh"):
        result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    result = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "install|uninstall|reinstall|update|update-deps" in result.stdout


def test_bad_branch_is_rejected_before_python_or_network_access():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/install.sh"), "--branch", "dev"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "Branch must be main or develop" in result.stderr


def test_install_copies_source_creates_env_and_shell_command_then_preserves_config(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    python, nb = fake_python(tmp_path)
    destination = tmp_path / "installed bot"
    bin_dir = tmp_path / "commands"
    env = {
        **os.environ,
        "SPIRIT_PET_PYTHON": str(python),
        "SPIRIT_PET_TEST_PYTHON": str(python),
        "SPIRIT_PET_TEST_NB": str(nb),
        "SPIRIT_PET_BIN_DIR": str(bin_dir),
        "SPIRIT_PET_SKIP_SYSTEM": "1",
    }
    command = ["bash", str(source_project / "scripts/install.sh"), "install", "--directory", str(destination), "--yes", "--no-start"]
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / ".venv/bin/nb").is_file()
    assert (destination / ".xiupet-venv").read_text(encoding="utf-8").strip() == str(destination / ".venv")
    config = (destination / ".env").read_text(encoding="utf-8")
    assert "HOST=127.0.0.1" in config and "PORT=8080" in config
    assert len(next(line.split("=", 1)[1] for line in config.splitlines() if line.startswith("ONEBOT_V11_ACCESS_TOKEN="))) == 64
    command_file = bin_dir / "xiupet"
    assert command_file.is_file() and os.access(command_file, os.X_OK)
    assert "XIUPET_PROJECT=" in command_file.read_text(encoding="utf-8")
    status = subprocess.run([str(command_file), "status"], capture_output=True, text=True, env=env)
    assert status.returncode == 1 and "xiupet is stopped" in status.stdout

    sentinel = "PRIVATE_CONFIG=keep this exactly\n"
    (destination / ".env").write_text(sentinel, encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / ".env").read_text(encoding="utf-8") == sentinel

    uninstall = subprocess.run(
        ["bash", str(source_project / "scripts/install.sh"), "uninstall", "--directory", str(destination), "--yes"],
        capture_output=True, text=True,
    )
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not destination.exists()
    assert not command_file.exists()


def test_missing_python_is_prepared_by_apt_before_install(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    python, nb = fake_python(tmp_path)
    marker = tmp_path / "python-installed"
    package_log = tmp_path / "apt.log"
    bin_dir = tmp_path / "commands"
    bin_dir.mkdir()
    apt = bin_dir / "apt-get"
    apt.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$SPIRIT_PET_TEST_APT_LOG\"\n"
        "touch \"$SPIRIT_PET_TEST_PYTHON_MARKER\"\n",
        encoding="utf-8",
    )
    sudo = bin_dir / "sudo"
    sudo.write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    apt.chmod(0o755)
    sudo.chmod(0o755)
    destination = tmp_path / "installed bot"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SPIRIT_PET_PYTHON": str(python),
        "SPIRIT_PET_TEST_PYTHON": str(python),
        "SPIRIT_PET_TEST_NB": str(nb),
        "SPIRIT_PET_TEST_PYTHON_MARKER": str(marker),
        "SPIRIT_PET_TEST_APT_LOG": str(package_log),
        "SPIRIT_PET_BIN_DIR": str(tmp_path / "commands-installed"),
    }
    env.pop("SPIRIT_PET_SKIP_SYSTEM", None)
    result = subprocess.run(
        ["bash", str(source_project / "scripts/install.sh"), "install", "--directory", str(destination), "--yes", "--no-start"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_file()
    assert "python3-venv" in package_log.read_text(encoding="utf-8")
    assert (destination / ".venv/bin/nb").is_file()


def test_uninstall_refuses_unmarked_directory_without_confirmation(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    result = subprocess.run(
        ["bash", str(source_project / "scripts/install.sh"), "uninstall", "--directory", str(source_project)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "unmarked source checkout" in result.stderr
    assert (source_project / "pyproject.toml").is_file()


def test_uninstall_removes_marked_install_without_python(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    (source_project / ".xiupet-install").write_text("source-install\n", encoding="ascii")
    result = subprocess.run(
        ["bash", str(source_project / "scripts/install.sh"), "uninstall", "--directory", str(source_project), "--yes"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not source_project.exists()


def test_linux_management_command_uses_nb_and_can_start_stop_status(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    environment = tmp_path / "env with spaces"
    (environment / "bin").mkdir(parents=True)
    executable = environment / "bin/nb"
    executable.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    executable.chmod(0o755)
    (source_project / ".xiupet-venv").write_text(str(environment), encoding="utf-8")
    env = {**os.environ, "XIUPET_PROJECT": str(source_project)}

    started = subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "start"], capture_output=True, text=True, env=env)
    assert started.returncode == 0, started.stdout + started.stderr
    assert subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "status"], capture_output=True, text=True, env=env).returncode == 0
    stopped = subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "stop"], capture_output=True, text=True, env=env, timeout=15)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not (source_project / ".xiupet/pid").exists()


def test_installers_are_native_and_contain_no_inline_python_code():
    shell_installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/install.ps1").read_text(encoding="utf-8")
    manager = (ROOT / "scripts/xiupet.ps1").read_text(encoding="utf-8")
    assert " -c " not in shell_installer
    assert "install_bootstrap.py" not in installer
    assert "Python content validated" not in installer
    assert " -c " not in installer
    assert "Scripts/nb.exe" in installer and "run" in installer
    assert "Start-Process" in manager and "taskkill.exe" in manager
    assert "xiupet.py" not in manager


def test_powershell_entrypoints_parse_when_powershell_is_available():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell unavailable")
    for path in (ROOT / "scripts/install.ps1", ROOT / "scripts/xiupet.ps1"):
        command = (
            "$errors=$null; $tokens=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile($env:SPIRIT_PET_TEST_SCRIPT, "
            "[ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors) { $errors | Out-String | Write-Error; exit 1 }"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True,
            env={**os.environ, "SPIRIT_PET_TEST_SCRIPT": str(path)},
        )
        assert result.returncode == 0, result.stderr
