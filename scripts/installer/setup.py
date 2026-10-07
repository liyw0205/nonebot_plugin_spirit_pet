import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.dependencies import install_dependencies
from installer.environment import configure, show_start


def _command_directory():
    if os.name == "nt":
        return Path.home() / "bin"
    termux_prefix = os.environ.get("PREFIX", "")
    if termux_prefix and "com.termux/files/usr" in termux_prefix:
        return Path(termux_prefix) / "bin"
    return Path.home() / ".local" / "bin"


def install_xiupet_command(directory: Path, python: str | Path = sys.executable):
    """Install a user-local launcher without requiring root privileges."""
    command_dir = _command_directory()
    command_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        cmd_directory = str(directory).replace('"', '""')
        cmd_python = str(python).replace('"', '""')
        cmd_manager = str(directory / "scripts/xiupet.py").replace('"', '""')
        cmd_shortcut = str(command_dir / "xiupet.cmd").replace('"', '""')
        shortcut = command_dir / "xiupet.cmd"
        content = (
            "@echo off\r\n"
            f"set \"XIUPET_PROJECT={cmd_directory}\"\r\n"
            f"set \"XIUPET_PYTHON={cmd_python}\"\r\n"
            f"set \"XIUPET_COMMAND_PATH={cmd_shortcut}\"\r\n"
            f"\"{cmd_python}\" \"{cmd_manager}\" %*\r\n"
        )
    else:
        shortcut = command_dir / "xiupet"
        content = "#!/usr/bin/env bash\nset -euo pipefail\n"
        content += f"export XIUPET_PROJECT={shlex.quote(str(directory))}\n"
        content += f"export XIUPET_PYTHON={shlex.quote(str(python))}\n"
        content += f"export XIUPET_COMMAND_PATH={shlex.quote(str(shortcut))}\n"
        content += f"exec {shlex.quote(str(python))} {shlex.quote(str(directory / 'scripts/xiupet.py'))} \"$@\"\n"
    if shortcut.exists():
        existing = shortcut.read_text(encoding="utf-8", errors="replace")
        if existing != content and ("XIUPET_PROJECT" not in existing or "xiupet.py" not in existing):
            raise RuntimeError(f"Refusing to overwrite an existing command: {shortcut}")
    shortcut.write_text(content, encoding="utf-8", newline="" if os.name == "nt" else None)
    if os.name != "nt":
        shortcut.chmod(0o755)
    (directory / ".xiupet-command").write_text(str(shortcut), encoding="utf-8")
    (directory / ".xiupet-install").write_text("source-install\n", encoding="ascii")
    print(f"Generated management command: {shortcut}")
    if str(command_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {command_dir} to PATH to call xiupet from any directory.")
    return shortcut


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    install_dependencies(directory)
    configure(directory, args.host, args.port, args.yes)
    install_xiupet_command(directory, sys.executable)
    show_start(directory)
    if not args.no_start:
        print("Starting in the foreground with nb run. Ctrl+C stops the bot.", flush=True)
        executable = Path(sys.executable).with_name("nb.exe" if os.name == "nt" else "nb")
        command = [str(executable), "run"] if executable.is_file() else [sys.executable, "-m", "nb_cli", "run"]
        environment = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")}
        subprocess.run(command, cwd=directory, check=True, env=environment)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation stopped: {exc}", file=sys.stderr)
        sys.exit(1)
