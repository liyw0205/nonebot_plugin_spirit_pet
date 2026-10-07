import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from scripts import install_bootstrap as bootstrap
from scripts.installer import environment


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path):
    project = tmp_path / "installation with spaces"
    for name in bootstrap.REQUIRED:
        destination = project / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    return project


@pytest.mark.parametrize("logical_size", [bootstrap.MAX_EXPANDED + 1, 10**12])
def test_small_sparse_archive_cannot_bypass_expanded_size_limit(logical_size):
    compressed = io.BytesIO()
    with tarfile.open(fileobj=compressed, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name in (*bootstrap.REQUIRED, "docs/sparse.txt"):
            member = tarfile.TarInfo("project-main/" + name)
            member.size = 2
            if name == "docs/sparse.txt":
                member.pax_headers = {
                    "GNU.sparse.map": f"0,1,{logical_size - 1},1",
                    "GNU.sparse.size": str(logical_size),
                }
            archive.addfile(member, io.BytesIO(b"AB"))
    assert len(compressed.getvalue()) < 1024
    with pytest.raises(ValueError):
        bootstrap.validate_archive(compressed.getvalue())


def test_failed_env_copy_cleans_its_partial_file_without_touching_database(installation, monkeypatch):
    database = installation / "data" / "pet.db"
    database.parent.mkdir()
    database.write_bytes(b"existing-database-sentinel")

    def no_hardlinks(*args, **kwargs):
        raise OSError("hard links are unavailable")

    def disk_full(source, target):
        target.write(b"HOST='")
        raise OSError("simulated full disk")

    monkeypatch.setattr(environment.os, "link", no_hardlinks, raising=False)
    monkeypatch.setattr(environment.shutil, "copyfileobj", disk_full)
    with pytest.raises(OSError, match="simulated full disk"):
        environment.configure(installation, "127.0.0.1", 8080, unattended=True)
    assert not (installation / ".env").exists()
    assert database.read_bytes() == b"existing-database-sentinel"
    assert not list(installation.glob(".spirit-pet-env-*"))


def test_fallback_copy_cannot_replace_configuration_created_by_another_process(installation, monkeypatch):
    destination = installation / ".env"
    original_open = os.open

    def no_hardlinks(*args, **kwargs):
        raise NotImplementedError("hard links are unavailable")

    def concurrent_create(path, flags, *args, **kwargs):
        if Path(path) == destination and flags & os.O_EXCL:
            destination.write_bytes(b"EXISTING_SECRET=keep-this-exactly\n")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(environment.os, "link", no_hardlinks, raising=False)
    monkeypatch.setattr(environment.os, "open", concurrent_create)
    with pytest.raises(FileExistsError):
        environment.configure(installation, "127.0.0.1", 8080, unattended=True)
    assert destination.read_bytes() == b"EXISTING_SECRET=keep-this-exactly\n"


def test_existing_venv_and_runtime_files_are_kept_while_selected_python_is_used(installation, tmp_path, monkeypatch):
    venv = tmp_path / "chosen environment with spaces"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"existing-interpreter-sentinel")
    (venv / "pyvenv.cfg").write_bytes(b"existing-venv-config")
    (venv / "unrelated-package.txt").write_bytes(b"keep-this-package")
    (installation / ".env").write_bytes(b"EXISTING_SECRET=not-for-output\n")
    database = installation / "data" / "pet.db"
    database.parent.mkdir()
    database.write_bytes(b"existing-database-sentinel")
    protected = [python, venv / "pyvenv.cfg", venv / "unrelated-package.txt",
                 installation / ".env", database, installation / "pyproject.toml"]
    before = {path: path.read_bytes() for path in protected}
    commands = []
    monkeypatch.setattr(bootstrap, "run", lambda command, **kwargs: commands.append(list(map(str, command))))
    bootstrap.main(["--directory", str(installation), "--venv", str(venv), "--no-start", "--yes"])
    assert commands and all(command[0] == str(python) for command in commands)
    assert not any(command[1:3] == ["-m", "venv"] for command in commands)
    assert commands[-1][1] == str(installation / "scripts/installer/setup.py")
    assert commands[-1][commands[-1].index("--directory") + 1] == str(installation)
    assert {path: path.read_bytes() for path in protected} == before


def test_windows_restart_instruction_uses_powershell_call_operator(monkeypatch, capsys):
    python = r"C:\Users\Demo User\Spirit Pet\.venv\Scripts\python.exe"
    monkeypatch.setattr(environment, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(environment, "sys", SimpleNamespace(executable=python))
    environment.show_start(r"C:\Users\Demo User\Spirit Pet")
    assert f'& "{python}" bot.py' in capsys.readouterr().out


def test_linux_with_python_but_without_curl_attempts_supported_package_install(tmp_path):
    bash, shell, dirname = shutil.which("bash"), shutil.which("sh"), shutil.which("dirname")
    if not all((bash, shell, dirname)):
        pytest.skip("POSIX shell tools unavailable")
    binary = tmp_path / "isolated tools"
    binary.mkdir()
    trace = tmp_path / "package calls"
    programs = {
        "python3": "exit 0\n",
        "id": "printf '0\\n'\n",
        "apt-get": 'printf "%s\\n" "$*" >> "$SPIRIT_PET_REVIEW_TRACE"\n'
                   'if [ "$1" = update ]; then exit 0; fi\nexit 31\n',
    }
    for name, body in programs.items():
        path = binary / name
        path.write_text(f"#!{shell}\n{body}", encoding="utf-8")
        path.chmod(0o700)
    (binary / "dirname").symlink_to(dirname)
    script = tmp_path / "standalone installer.sh"
    shutil.copy2(ROOT / "scripts/install.sh", script)
    result = subprocess.run([bash, str(script), "--no-start"], capture_output=True, text=True, timeout=10, env={
        **os.environ, "PATH": str(binary), "PREFIX": "/usr", "SPIRIT_PET_PLATFORM": "linux",
        "SPIRIT_PET_SKIP_SYSTEM": "0", "SPIRIT_PET_BRANCH": "main",
        "SPIRIT_PET_PYTHON": str(binary / "python3"), "SPIRIT_PET_REVIEW_TRACE": str(trace),
    })
    assert trace.is_file(), result.stderr
    assert "curl" in trace.read_text(encoding="utf-8")
    assert result.returncode == 31
