#!/usr/bin/env python3
"""Small, dependency-free process manager used by the generated ``xiupet`` command."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def _project() -> Path:
    return Path(os.environ.get("XIUPET_PROJECT", Path(__file__).resolve().parents[1])).expanduser().resolve()


def _state(project: Path) -> Path:
    path = project / ".xiupet"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_path(project: Path) -> Path:
    return _state(project) / "pid"


def _log_path(project: Path) -> Path:
    return _state(project) / "run.log"


def _read_pid(project: Path) -> int | None:
    try:
        value = int(_pid_path(project).read_text(encoding="ascii").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if value > 0 else None


def _running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _clear_pid(project: Path) -> None:
    try:
        _pid_path(project).unlink()
    except FileNotFoundError:
        pass


def _python(project: Path) -> Path:
    configured = os.environ.get("XIUPET_PYTHON")
    if configured:
        return Path(configured)
    if os.name == "nt":
        return project / ".venv" / "Scripts" / "python.exe"
    return project / ".venv" / "bin" / "python"


def _nb_command(project: Path) -> list[str]:
    executable = _python(project).with_name("nb.exe" if os.name == "nt" else "nb")
    if executable.is_file():
        return [str(executable), "run"]
    python = _python(project)
    if python.is_file():
        return [str(python), "-m", "nb_cli", "run"]
    return ["nb", "run"]


def status(project: Path) -> int:
    pid = _read_pid(project)
    if _running(pid):
        print(f"xiupet is running (pid {pid})")
        print(f"log: {_log_path(project)}")
        return 0
    if pid is not None:
        _clear_pid(project)
    print("xiupet is stopped")
    return 1


def start(project: Path) -> int:
    pid = _read_pid(project)
    if _running(pid):
        print(f"xiupet is already running (pid {pid})")
        return 0
    if pid is not None:
        _clear_pid(project)
    command = _nb_command(project)
    log = _log_path(project)
    log.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "PATH": str(_python(project).parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    with log.open("ab") as output:
        kwargs = {
            "cwd": project,
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": output,
            "stderr": subprocess.STDOUT,
            "close_fds": os.name != "nt",
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
    _pid_path(project).write_text(str(process.pid), encoding="ascii")
    time.sleep(0.15)
    if process.poll() is not None:
        _clear_pid(project)
        print(f"xiupet failed to start; inspect {log}", file=sys.stderr)
        return process.returncode or 1
    print(f"xiupet started (pid {process.pid})")
    print(f"log: {log}")
    return 0


def stop(project: Path) -> int:
    pid = _read_pid(project)
    if not _running(pid):
        _clear_pid(project)
        print("xiupet is already stopped")
        return 0
    assert pid is not None
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # ``nb`` supervises a separate Python process; terminate its whole
            # session so stop never leaves the server orphaned.
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 8
            while _running(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if _running(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        _clear_pid(project)
    print(f"xiupet stopped (pid {pid})")
    return 0


def uninstall(project: Path, yes: bool) -> int:
    if (project / ".git").exists() and not yes:
        print("Refusing to delete a Git checkout; use --yes or the installer with an explicit --directory.", file=sys.stderr)
        return 2
    if not yes:
        if not sys.stdin.isatty():
            print("uninstall is destructive; rerun as `xiupet uninstall --yes`", file=sys.stderr)
            return 2
        answer = input(f"Remove {project}, its environment and local data? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Uninstall cancelled.")
            return 0
    stop(project)
    command_file = project / ".xiupet-command"
    shortcut = None
    try:
        shortcut = Path(command_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, UnicodeError):
        pass
    os.chdir(Path.home())
    shutil.rmtree(project)
    if shortcut and shortcut.name in {"xiupet", "xiupet.cmd", "xiupet.ps1"}:
        try:
            shortcut.unlink()
        except FileNotFoundError:
            pass
    print(f"Uninstalled Spirit Pet from {project}")
    return 0


def update_deps(project: Path) -> int:
    setup = project / "scripts" / "installer" / "setup.py"
    result = subprocess.run([str(_python(project)), str(setup), "--directory", str(project), "--yes", "--no-start"], cwd=project)
    return result.returncode


def update(project: Path) -> int:
    if os.name == "nt":
        installer = project / "scripts" / "install.ps1"
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer),
                   "update", "-Directory", str(project), "-Yes", "-NoStart"]
    else:
        installer = project / "scripts" / "install.sh"
        command = ["bash", str(installer), "update", "--directory", str(project), "--yes", "--no-start"]
    if not installer.is_file():
        return update_deps(project)
    return subprocess.run(command, cwd=project).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xiupet", description="Manage the Spirit Pet NoneBot project.")
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "logs", "update", "update-deps", "uninstall"), nargs="?", default="status")
    parser.add_argument("--yes", action="store_true", help="confirm destructive uninstall")
    parser.add_argument("--lines", type=int, default=80, help="number of log lines to show")
    args = parser.parse_args(argv)
    project = _project()
    if args.action == "start":
        return start(project)
    if args.action == "stop":
        return stop(project)
    if args.action == "restart":
        stop(project)
        return start(project)
    if args.action == "status":
        return status(project)
    if args.action == "logs":
        try:
            lines = _log_path(project).read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            print(f"No log file yet: {_log_path(project)}")
            return 0
        print("\n".join(lines[-max(args.lines, 1):]))
        return 0
    if args.action == "update":
        return update(project)
    if args.action == "update-deps":
        return update_deps(project)
    return uninstall(project, args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
