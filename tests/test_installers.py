import io
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from scripts import install_bootstrap as bootstrap
from scripts.installer import dependencies, environment, setup

ROOT = Path(__file__).resolve().parents[1]


def archive_bytes(extra=(), omit=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in bootstrap.REQUIRED:
            if name not in omit:
                info = tarfile.TarInfo("project-main/" + name)
                info.size = 4
                archive.addfile(info, io.BytesIO(b"test"))
        for info in extra:
            if isinstance(info, tuple):
                info, fileobj = info
            else:
                fileobj = io.BytesIO(b"")
            archive.addfile(info, fileobj)
    return buffer.getvalue()


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project with spaces"
    for name in bootstrap.REQUIRED:
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        origin = ROOT / name
        shutil.copy2(origin, destination)
    return directory


def test_five_download_sources_match_actual_upstream_mirrors():
    assert bootstrap.SOURCES == (
        ("GitHub", ""), ("gh-proxy.com", "https://gh-proxy.com/"),
        ("gh.jasonzeng.dev", "https://gh.jasonzeng.dev/"),
        ("git.yylx.win", "https://git.yylx.win/"), ("wget.la", "https://wget.la/"),
    )
    for script in ("install.sh", "install.ps1"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        for _, url in bootstrap.SOURCES[1:]:
            assert url in text
        assert "spirit-pet-installer-bootstrap-v1" in text
        assert "ast.parse" in text


def test_all_sources_are_probed_and_fastest_valid_archive_is_selected(tmp_path, capsys):
    payloads = [archive_bytes(), b"<html>success</html>", archive_bytes(), archive_bytes(), archive_bytes()]
    requested = []
    ticks = iter([0, 0.8, 1, 2, 2.2, 3, 3.4, 4, 4.9])

    class Response(io.BytesIO):
        status = 200

        def geturl(self):
            return "https://example.test/project.tar.gz"

    def opener(request, timeout):
        requested.append(request.full_url)
        assert timeout == 15
        return Response(payloads[len(requested) - 1])

    result = bootstrap.download_source("main", tmp_path, opener=opener, clock=lambda: next(ticks))
    assert bootstrap.is_project(result)
    assert len(requested) == 5
    output = capsys.readouterr().out
    assert "[2/5] gh-proxy.com: FAILED" in output
    assert "Selected source: gh.jasonzeng.dev" in output


def test_no_valid_source_fails_instead_of_using_html(tmp_path, capsys):
    def unavailable(*args, **kwargs):
        raise OSError("TLS unavailable")

    with pytest.raises(RuntimeError, match="All five"):
        bootstrap.download_source("main", tmp_path, opener=unavailable)
    assert capsys.readouterr().out.count("FAILED") == 5
    assert not (tmp_path / "source").exists()


@pytest.mark.parametrize("name", [
    "../outside", "/absolute", "project-main/../../escape", "project-main/a\\b", "project-main/C:drive",
    "project-main/.. /outside", "project-main/a.", "project-main/NUL.txt", "project-main/CoM1",
    "project-main/a?/b", "project-main/./bot.py", "project-main//bot.py",
])
def test_archive_rejects_unsafe_paths(name):
    with pytest.raises(ValueError, match="unsafe"):
        bootstrap.validate_archive(archive_bytes([tarfile.TarInfo(name)]))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_archive_rejects_links_and_special_files(kind):
    info = tarfile.TarInfo("project-main/link")
    info.type = kind
    info.linkname = "/outside"
    with pytest.raises(ValueError, match="unsafe"):
        bootstrap.validate_archive(archive_bytes([info]))


def test_archive_rejects_incomplete_duplicate_and_multiroot_content():
    with pytest.raises(ValueError, match="missing"):
        bootstrap.validate_archive(archive_bytes(omit=["pyproject.toml"]))
    with pytest.raises(ValueError, match="duplicate"):
        bootstrap.validate_archive(archive_bytes([tarfile.TarInfo("project-main/bot.py")]))
    with pytest.raises(ValueError, match="duplicate"):
        bootstrap.validate_archive(archive_bytes([tarfile.TarInfo("project-main/BOT.py")]))
    with pytest.raises(ValueError, match="one repository root"):
        bootstrap.validate_archive(archive_bytes([tarfile.TarInfo("other/file")]))


def test_archive_rejects_expansion_bombs_and_html(monkeypatch):
    monkeypatch.setattr(bootstrap, "MAX_EXPANDED", 10)
    with pytest.raises(ValueError, match="size limit"):
        bootstrap.validate_archive(archive_bytes())
    with pytest.raises(ValueError, match="not gzip"):
        bootstrap.validate_archive(b"<html>200 OK</html>")


def test_archive_rejects_declared_size_and_sparse_pax(monkeypatch):
    monkeypatch.setattr(bootstrap, "MAX_EXPANDED", 100_000)
    oversized = tarfile.TarInfo("project-main/huge.bin")
    oversized.size = bootstrap.MAX_EXPANDED + 1
    oversized_payload = io.BytesIO(b"x" * oversized.size)
    with pytest.raises(ValueError, match="size limit"):
        bootstrap.validate_archive(archive_bytes([(oversized, oversized_payload)]))
    sparse = tarfile.TarInfo("project-main/sparse.bin")
    sparse.size = 1
    sparse.pax_headers = {"GNU.sparse.map": "0,1", "GNU.sparse.size": "104857601"}
    with pytest.raises(ValueError, match="unsafe"):
        bootstrap.validate_archive(archive_bytes([(sparse, io.BytesIO(b"x"))]))


def test_truncated_http_response_does_not_skip_remaining_sources(tmp_path, capsys):
    calls = []

    def truncated(request, **kwargs):
        calls.append(request.full_url)
        raise IncompleteRead(b"partial", 100)

    with pytest.raises(RuntimeError, match="All five"):
        bootstrap.download_source("develop", tmp_path, opener=truncated)
    assert len(calls) == 5
    assert capsys.readouterr().out.count("FAILED, IncompleteRead:") == 5


def test_source_copy_excludes_credentials_runtime_data_and_venv(project, tmp_path):
    (project / ".env").write_text("SECRET=kept", encoding="utf-8")
    (project / "data").mkdir()
    (project / "data/game.db").write_bytes(b"live database")
    target = tmp_path / "new installation"
    bootstrap.prepare_project(project, target)
    assert bootstrap.is_project(target)
    assert not (target / ".env").exists()
    assert not (target / "data").exists()
    assert not (target / ".venv").exists()


def test_existing_project_and_nonproject_directories_are_not_overwritten(project, tmp_path):
    original = (project / "bot.py").read_bytes()
    bootstrap.prepare_project(tmp_path / "unused", project)
    assert (project / "bot.py").read_bytes() == original
    unrelated = tmp_path / "personal"
    unrelated.mkdir()
    (unrelated / "notes.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Refusing"):
        bootstrap.prepare_project(project, unrelated)
    assert (unrelated / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_bootstrap_sequence_creates_venv_then_pins_nb_cli_then_runs_setup(project, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(bootstrap, "run", lambda command, **kwargs: commands.append([str(part) for part in command]))
    venv = tmp_path / "isolated env"
    bootstrap.main(["--directory", str(project), "--venv", str(venv), "--yes", "--no-start"])
    assert commands[0][:3] == [sys.executable, "-m", "venv"]
    assert commands[0][-1] == str(venv)
    assert "nb-cli==1.5.0" in commands[2]
    assert "--upgrade" not in commands[2]
    assert commands[3][1] == str(project / "scripts/installer/setup.py")
    assert "--yes" in commands[3] and "--no-start" in commands[3]


def test_develop_is_accepted_and_dev_is_rejected(project, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(bootstrap, "run", lambda command, **kwargs: commands.append(command))
    bootstrap.main(["--directory", str(project), "--venv", str(tmp_path / "env"), "--branch", "develop", "--no-start"])
    assert commands
    with pytest.raises(SystemExit):
        bootstrap.main(["--branch", "dev"])
    monkeypatch.setenv("SPIRIT_PET_BRANCH", "dev")
    with pytest.raises(SystemExit):
        bootstrap.main([])


def test_termux_shares_system_extensions_but_normal_venvs_do_not(project, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(bootstrap, "run", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(bootstrap.sys, "base_prefix", "/usr")
    monkeypatch.setenv("SPIRIT_PET_PLATFORM", "termux")
    bootstrap.main(["--directory", str(project), "--venv", str(tmp_path / "termux"), "--no-start"])
    assert "--system-site-packages" in commands[0]
    commands.clear()
    monkeypatch.delenv("SPIRIT_PET_PLATFORM")
    bootstrap.main(["--directory", str(project), "--venv", str(tmp_path / "linux"), "--no-start"])
    assert "--system-site-packages" not in commands[0]


def test_bootstrap_rejects_nonvenv_without_deleting_it(project, tmp_path, monkeypatch):
    venv = tmp_path / "not a venv"
    venv.mkdir()
    (venv / "keep").write_text("original", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "run", lambda *args, **kwargs: pytest.fail("must not install"))
    with pytest.raises(RuntimeError, match="refusing to replace"):
        bootstrap.main(["--directory", str(project), "--venv", str(venv), "--no-start"])
    assert (venv / "keep").read_text(encoding="utf-8") == "original"


def test_dependency_install_uses_nb_commands_and_preserves_project_bytes(project):
    commands = []
    original = (project / "pyproject.toml").read_bytes()

    def runner(command, **kwargs):
        commands.append(command)
        assert kwargs["check"]
        assert kwargs["env"]["VIRTUAL_ENV"] == sys.prefix

    dependencies.install_dependencies(project, runner=runner)
    nb_commands = [command for command in commands if "install" in command and ("driver" in command or "adapter" in command)]
    assert [command[-4:] for command in nb_commands] == [
        ["driver", "install", "nonebot2[fastapi]", "--no-input"],
        ["driver", "install", "nonebot2[httpx]", "--no-input"],
        ["driver", "install", "nonebot2[websockets]", "--no-input"],
        ["adapter", "install", "nonebot.adapters.onebot.v11", "--no-input"],
        ["adapter", "install", "nonebot.adapters.qq", "--no-input"],
    ]
    assert all(command[:4] == [sys.executable, "-m", "nb_cli", "--python"] for command in nb_commands)
    assert (project / "pyproject.toml").read_bytes() == original
    assert any(command[1:4] == ["-m", "pip", "check"] for command in commands)


def test_driver_zero_exit_does_not_hide_failed_installation(project):
    def runner(command, **kwargs):
        if command[-1] == "import nonebot.drivers.fastapi":
            raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        dependencies.install_dependencies(project, runner=runner)


def test_shared_system_nonebot_packages_are_installed_locally_without_uninstall(tmp_path, monkeypatch):
    local = tmp_path / "venv"
    monkeypatch.setattr(dependencies.sys, "prefix", str(local))
    installed = SimpleNamespace(version="2.5.0", locate_file=lambda _: tmp_path / "system" / "site-packages")
    monkeypatch.setattr(dependencies, "distribution", lambda _: installed)
    commands = []
    dependencies.ensure_local_package("nonebot2", lambda command, **kwargs: commands.append(command), {})
    assert commands[0][-3:] == ["--ignore-installed", "--no-deps", "nonebot2==2.5.0"]
    assert "--force-reinstall" not in commands[0]
    installed.locate_file = lambda _: local / "lib" / "site-packages"
    dependencies.ensure_local_package("nonebot2", lambda command, **kwargs: commands.append(command), {})
    assert len(commands) == 1


def test_wrong_pyproject_format_stops_instead_of_rewriting(project):
    path = project / "pyproject.toml"
    path.write_text('[tool.nonebot]\nplugin_dirs=[]\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="src/plugins"):
        dependencies.validate_project(project)
    assert path.read_text(encoding="utf-8") == '[tool.nonebot]\nplugin_dirs=[]\n'


def test_configuration_is_private_generates_a_token_and_never_overwrites(project):
    environment.configure(project, "127.0.0.1", 8090, unattended=True)
    values = dotenv_values(project / ".env")
    assert values["PORT"] == "8090"
    assert values["HOST"] == "127.0.0.1"
    assert len(values["ONEBOT_V11_ACCESS_TOKEN"]) >= 40
    assert values["QQ_BOTS"] == "[]"
    if os.name != "nt":
        assert (project / ".env").stat().st_mode & 0o777 == 0o600
    before = (project / ".env").read_bytes()
    environment.configure(project, "0.0.0.0", 8080, unattended=True)
    assert (project / ".env").read_bytes() == before


def test_configuration_does_not_follow_dangling_symlink(project, tmp_path):
    target = tmp_path / "must not create"
    try:
        (project / ".env").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    environment.configure(project, "0.0.0.0", 8080, unattended=True)
    assert not target.exists()


def test_qq_credentials_roundtrip_without_terminal_disclosure(project, monkeypatch, capsys):
    answers = iter(["3", "12345", "2"])
    secret = "quoted'\"secret\\value"
    monkeypatch.setattr(environment.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(environment.getpass, "getpass", lambda _: secret)
    environment.configure(project, "127.0.0.1", 8080)
    credentials = json.loads(dotenv_values(project / ".env")["QQ_BOTS"])
    assert credentials == [{"id": "12345", "secret": secret, "intent": {"c2c_group_at_messages": True}, "use_websocket": False}]
    assert secret not in capsys.readouterr().out


def test_failed_configuration_does_not_leave_a_partial_env(project, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("quoting failed")

    monkeypatch.setattr("dotenv.set_key", fail)
    with pytest.raises(RuntimeError, match="quoting failed"):
        environment.configure(project, "127.0.0.1", 8080, unattended=True)
    assert not (project / ".env").exists()
    assert not list(project.glob(".spirit-pet-env-*"))


def test_no_start_finishes_after_dependency_and_environment_configuration(project, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "install_dependencies", lambda path: calls.append("dependencies"))
    monkeypatch.setattr(setup, "configure", lambda *args: calls.append("environment"))
    monkeypatch.setattr(setup, "show_start", lambda path: calls.append("instructions"))
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kwargs: calls.append("start"))
    setup.main(["--directory", str(project), "--no-start"])
    assert calls == ["dependencies", "environment", "instructions"]
    calls.clear()
    setup.main(["--directory", str(project)])
    assert calls == ["dependencies", "environment", "instructions", "start"]


def test_windows_restart_instruction_is_executable_with_spaces(project, monkeypatch, capsys):
    monkeypatch.setattr(environment.os, "name", "nt")
    monkeypatch.setattr(environment.sys, "executable", str(project / "venv with spaces" / "Scripts" / "python.exe"))
    environment.show_start(project)
    assert '& "' in capsys.readouterr().out


@pytest.mark.parametrize("name", ["install.sh", "install_termux.sh"])
def test_shell_entrypoints_have_valid_syntax(name):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_help_does_not_install_system_packages():
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    result = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "main|develop" in result.stdout


def test_shell_rejects_bad_branch_before_system_install():
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash unavailable")
    result = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--branch", "dev"], capture_output=True, text=True)
    assert result.returncode == 1
    assert "main or develop" in result.stderr


def test_shell_installs_curl_with_python_when_linux_bootstrap_needs_it():
    text = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    assert "! command -v curl" in text
    assert "apt-get install -y python3 python3-venv python3-pip curl" in text


def test_powershell_entrypoint_has_valid_syntax():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell unavailable")
    command = "$errors=$null; $tokens=$null; [System.Management.Automation.Language.Parser]::ParseFile($env:SPIRIT_PET_TEST_SCRIPT, [ref]$tokens, [ref]$errors) | Out-Null; if ($errors) { $errors | Out-String | Write-Error; exit 1 }"
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, env={**os.environ, "SPIRIT_PET_TEST_SCRIPT": str(ROOT / "scripts/install.ps1")})
    assert result.returncode == 0, result.stderr
