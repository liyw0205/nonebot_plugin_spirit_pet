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
    for name in ("install.sh", "xiupet.sh"):
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
    for name in ("install.sh", "xiupet.sh"):
        result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    result = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "[install|uninstall]" in result.stdout
    manager_help = subprocess.run(["bash", str(ROOT / "scripts/xiupet.sh"), "--help"], capture_output=True, text=True)
    assert manager_help.returncode == 0
    assert "does not update project source" in manager_help.stdout


def test_removed_branch_option_is_rejected_before_python_or_network_access():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/install.sh"), "install", "--branch=dev"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "Unknown option: --branch=dev" in result.stderr


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
    config = (destination / ".env").read_text(encoding="utf-8")
    assert "HOST=127.0.0.1" in config and "PORT=8080" in config
    assert len(next(line.split("=", 1)[1] for line in config.splitlines() if line.startswith("ONEBOT_V11_ACCESS_TOKEN="))) == 64
    command_file = bin_dir / "xiupet"
    assert command_file.is_symlink() and os.readlink(command_file) == str(destination / "scripts/xiupet.sh")
    assert os.access(command_file, os.X_OK)
    status = subprocess.run([str(command_file), "status"], capture_output=True, text=True, env=env)
    assert status.returncode == 1 and "xiupet is stopped" in status.stdout

    sentinel = "PRIVATE_CONFIG=keep this exactly\n"
    (destination / ".env").write_text(sentinel, encoding="utf-8")
    data_dir = destination / "data"
    data_dir.mkdir(parents=True)
    save = data_dir / "player.db"
    save.write_bytes(b"existing player save")
    option_first_command = [
        "bash", str(source_project / "scripts/install.sh"), "--directory", str(destination), "--yes", "--no-start",
    ]
    result = subprocess.run(option_first_command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / ".env").read_text(encoding="utf-8") == sentinel
    assert save.read_bytes() == b"existing player save"

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
    assert "--yes" in result.stderr
    assert (source_project / "pyproject.toml").is_file()


def test_uninstall_removes_marked_install_without_python(source_project, tmp_path):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    (source_project / ".xiupet-managed").write_text("managed\n", encoding="ascii")
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
    venv = source_project / ".venv"
    (venv / "bin").mkdir(parents=True)
    shutil.copy2(executable, venv / "bin/nb")
    env = {**os.environ, "XIUPET_PROJECT": str(source_project)}

    started = subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "start"], capture_output=True, text=True, env=env)
    assert started.returncode == 0, started.stdout + started.stderr
    assert subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "status"], capture_output=True, text=True, env=env).returncode == 0
    stopped = subprocess.run(["bash", str(source_project / "scripts/xiupet.sh"), "stop"], capture_output=True, text=True, env=env, timeout=15)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not (source_project / ".xiupet/pid").exists()


def test_installer_and_management_command_are_bash_and_use_nb_cli():
    shell_installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    manager = (ROOT / "scripts/xiupet.sh").read_text(encoding="utf-8")
    assert " -c " not in shell_installer
    assert '"$PYTHON" -m venv' in shell_installer
    assert '"$venv/bin/python" -m pip install' in shell_installer
    assert '"$venv/bin/nb" run' in shell_installer
    assert "python3" not in manager
    assert '"$NB" run' in manager
