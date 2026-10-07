import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.dependencies import install_dependencies
from installer.environment import configure, show_start


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
    show_start(directory)
    if not args.no_start:
        print("Starting in the foreground. Ctrl+C stops the bot.", flush=True)
        subprocess.run([sys.executable, "bot.py"], cwd=directory, check=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation stopped: {exc}", file=sys.stderr)
        sys.exit(1)
