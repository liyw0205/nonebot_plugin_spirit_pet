# spirit-pet-installer-bootstrap-v1
"""Standalone bootstrap: validated source archive, isolated venv, pinned NB CLI."""

import argparse
import gzip
from http.client import HTTPException
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "liyw0205/nonebot_plugin_spirit_pet"
SOURCES = (
    ("GitHub", ""),
    ("gh-proxy.com", "https://gh-proxy.com/"),
    ("gh.jasonzeng.dev", "https://gh.jasonzeng.dev/"),
    ("git.yylx.win", "https://git.yylx.win/"),
    ("wget.la", "https://wget.la/"),
)
MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
REQUIRED = (
    "pyproject.toml", ".env.example", "requirements.txt",
    "src/plugins/nonebot_plugin_spirit_pet/__init__.py", "scripts/installer/setup.py",
    "scripts/xiupet.py",
)
ACTION_CHOICES = ("install", "uninstall", "reinstall", "update", "update-deps")


class HTTPSOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("insecure download redirect")
        return super().redirect_request(request, response, code, message, headers, newurl)


def open_https(request, timeout):
    return build_opener(HTTPSOnlyRedirect()).open(request, timeout=timeout)


def validate_archive(payload):
    if not payload.startswith(b"\x1f\x8b"):
        raise ValueError("response is not gzip (possibly an HTML error page)")
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise ValueError("archive expands beyond the size limit")
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
        members = archive.getmembers()
        if not members or len(members) > 10_000:
            raise ValueError("archive has no members or too many members")
        roots, paths = set(), set()
        declared_bytes = 0
        for member in members:
            path = PurePosixPath(member.name)
            pax = getattr(member, "pax_headers", {}) or {}
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or any(char in member.name for char in '<>:"|?*') or not path.parts
                    or member.name.rstrip("/") != path.as_posix()
                    or any(part.endswith((".", " ")) or part.split(".")[0].upper() in WINDOWS_DEVICES for part in path.parts)
                    or member.type == tarfile.GNUTYPE_SPARSE or getattr(member, "sparse", None)
                    or any(key.startswith("GNU.sparse.") for key in pax)
                    or not (member.isfile() or member.isdir())):
                raise ValueError("archive contains an unsafe path, link or device")
            if member.isfile():
                if member.size < 0 or member.size > MAX_EXPANDED or declared_bytes + member.size > MAX_EXPANDED:
                    raise ValueError("archive declares files beyond the size limit")
                declared_bytes += member.size
            elif member.size != 0:
                raise ValueError("archive directory declares unexpected data")
            normalized = path.as_posix().casefold()
            if normalized in paths:
                raise ValueError("archive contains duplicate paths")
            paths.add(normalized)
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise ValueError("archive must have one repository root")
        root = roots.pop()
        regular = {member.name for member in members if member.isfile()}
        if any(f"{root}/{name}" not in regular for name in REQUIRED):
            raise ValueError("archive is missing Spirit Pet project files")
    return expanded, root


def download_source(branch, directory, *, opener=open_https, clock=time.monotonic):
    url = f"https://github.com/{REPOSITORY}/archive/refs/heads/{branch}.tar.gz"
    available = []
    for index, (name, prefix) in enumerate(SOURCES, 1):
        started = clock()
        try:
            request = Request(prefix + url, headers={"User-Agent": "spirit-pet-installer/1"})
            with opener(request, timeout=15) as response:
                if response.status != 200 or not response.geturl().startswith("https://"):
                    raise ValueError("unexpected HTTP status or insecure redirect")
                payload = response.read(MAX_DOWNLOAD + 1)
            if len(payload) > MAX_DOWNLOAD:
                raise ValueError("download exceeds the size limit")
            expanded, root = validate_archive(payload)
            elapsed = clock() - started
            path = directory / f"source-{index}.tar"
            path.write_bytes(expanded)
            available.append((elapsed, name, path, root))
            print(f"[{index}/5] {name}: OK, {elapsed * 1000:.0f} ms, archive validated", flush=True)
        except (OSError, HTTPException, ValueError, EOFError, tarfile.TarError) as exc:
            print(f"[{index}/5] {name}: FAILED, {type(exc).__name__}: {exc}", flush=True)
    if not available:
        raise RuntimeError("All five GitHub sources failed. Check DNS/TLS/network or use a complete local checkout.")
    _, name, archive_path, root = min(available, key=lambda item: item[0])
    print(f"Selected source: {name}", flush=True)
    destination = directory / "source"
    destination.mkdir()
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            relative = PurePosixPath(member.name).relative_to(root)
            if not relative.parts:
                continue
            output = destination.joinpath(*relative.parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target)
    return destination


def is_project(path):
    return all((path / name).is_file() for name in REQUIRED)


def prepare_project(source, target):
    if source == target:
        return
    if target.exists() and any(target.iterdir()):
        if is_project(target):
            print(f"Keeping existing project unchanged: {target}", flush=True)
            return
        raise RuntimeError(f"Refusing to overwrite nonempty unrecognized directory: {target}")
    target.mkdir(parents=True, exist_ok=True)
    # Copy source only: root runtime data, credentials, git internals and venvs stay out.
    for name in ("pyproject.toml", "requirements.txt", ".env.example", "README.md", "LICENSE", "src", "scripts", "docs"):
        origin, destination = source / name, target / name
        if origin.is_dir():
            shutil.copytree(origin, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif origin.is_file():
            shutil.copy2(origin, destination)


def update_project(source, target):
    """Refresh tracked application files without touching local state."""
    if source == target:
        return
    target.mkdir(parents=True, exist_ok=True)
    for name in ("pyproject.toml", "requirements.txt", ".env.example", "README.md", "LICENSE", "src", "scripts", "docs"):
        origin, destination = source / name, target / name
        if origin.is_dir():
            shutil.copytree(
                origin, destination, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        elif origin.is_file():
            shutil.copy2(origin, destination)


def project_directory(local, requested):
    if requested:
        candidate = requested.expanduser()
        if candidate.is_symlink():
            raise RuntimeError(f"Refusing to operate through a symlinked installation path: {candidate}")
        return candidate.resolve()
    return (local if is_project(local) else Path.home() / "spirit-pet").expanduser().resolve()


def uninstall_project(target, *, yes=False):
    """Stop and remove only an installation explicitly identified by the user."""
    target = target.expanduser().resolve()
    if not is_project(target):
        raise RuntimeError(f"Not a Spirit Pet installation: {target}")
    marker = target / ".xiupet-install"
    # A marker prevents an unqualified command from deleting a source checkout.
    if not marker.is_file() and not yes:
        raise RuntimeError("Refusing to remove an unmarked source checkout; pass --yes with --directory to confirm")
    if (target / ".git").exists() and not yes:
        raise RuntimeError("Refusing to delete a Git checkout; pass --yes with --directory to confirm")
    if not yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Uninstall is destructive; rerun with --yes in a non-interactive shell")
        answer = input(f"Remove {target}, its virtual environment and generated xiupet command? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Uninstall cancelled.")
            return
    manager = target / "scripts" / "xiupet.py"
    if manager.is_file():
        subprocess.run([sys.executable, str(manager), "stop"], cwd=target, check=False)
    command_path = target / ".xiupet-command"
    if command_path.is_file():
        try:
            shortcut = Path(command_path.read_text(encoding="utf-8").strip()).expanduser()
            if shortcut.name in {"xiupet", "xiupet.cmd", "xiupet.ps1"} and shortcut.is_file():
                shortcut.unlink()
        except (OSError, UnicodeError):
            pass
    os.chdir(Path.home())
    shutil.rmtree(target)
    print(f"Uninstalled Spirit Pet from {target}")


def run(command, **kwargs):
    print("Running: " + " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install and manage the Spirit Pet source project.")
    parser.add_argument("action", nargs="?", choices=ACTION_CHOICES, default="install")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--venv", type=Path, help="Explicit existing/new venv; default: project/.venv")
    parser.add_argument("--branch", choices=("main", "develop"), default=os.environ.get("SPIRIT_PET_BRANCH", "main"))
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Use safe defaults without configuration prompts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if not (3, 10) <= sys.version_info[:2] < (4, 0):
        parser.error("Python >=3.10,<4.0 is required")
    if args.branch not in {"main", "develop"} or not 1 <= args.port <= 65535:
        parser.error("Invalid branch or port")
    local = Path(__file__).resolve().parents[1]
    target = project_directory(local, args.directory)
    if args.action == "uninstall":
        uninstall_project(target, yes=args.yes)
        return
    with tempfile.TemporaryDirectory(prefix="spirit-pet-install-") as temporary:
        # An installed archive has no Git remote of its own. In update mode,
        # fetch a fresh validated archive instead of silently copying itself.
        if args.action == "update" and target == local and not (local / ".git").is_dir():
            source = download_source(args.branch, Path(temporary))
        elif is_project(local):
            source = local
        elif is_project(target):
            source = target
        else:
            source = download_source(args.branch, Path(temporary))
        if args.action == "update":
            update_project(source, target)
        else:
            prepare_project(source, target)
        if not is_project(target):
            raise RuntimeError("Incomplete project; no environment changes were made")
        venv = (args.venv or target / ".venv").expanduser().absolute()
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if args.action == "reinstall" and venv.exists():
            if not (venv / "pyvenv.cfg").is_file():
                raise RuntimeError(f"Not a usable virtual environment; refusing to replace: {venv}")
            shutil.rmtree(venv)
        if venv.exists():
            if not (venv / "pyvenv.cfg").is_file() or not python.is_file():
                raise RuntimeError(f"Not a usable virtual environment; refusing to replace: {venv}")
        else:
            command = [sys.executable, "-m", "venv"]
            if (os.environ.get("SPIRIT_PET_PLATFORM") == "termux"
                    or "com.termux/files/usr" in sys.base_prefix):
                command.append("--system-site-packages")
            run([*command, venv])
        run([python, "-c", "import sys; assert sys.prefix != sys.base_prefix; assert (3,10)<=sys.version_info[:2]<(4,0)"])
        run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "nb-cli==1.5.0"])
        command = [python, target / "scripts/installer/setup.py", "--directory", target,
                   "--host", args.host, "--port", str(args.port)]
        if args.no_start or args.action in {"update", "update-deps", "reinstall"}:
            command.append("--no-start")
        if args.yes:
            command.append("--yes")
        run(command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation stopped: {exc}", file=sys.stderr)
        sys.exit(1)
