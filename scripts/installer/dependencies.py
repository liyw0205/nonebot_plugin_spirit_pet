import os
from importlib.metadata import distribution
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        import tomlkit as tomllib


def validate_project(directory):
    data = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
    config = data.get("tool", {}).get("nonebot", {})
    if "src/plugins" not in config.get("plugin_dirs", []):
        raise RuntimeError("pyproject.toml must load src/plugins; existing configuration was not changed")
    adapters = config.get("adapters", {})
    for package, module in (("nonebot-adapter-onebot", "nonebot.adapters.onebot.v11"), ("nonebot-adapter-qq", "nonebot.adapters.qq")):
        if not isinstance(adapters, dict) or not any(item.get("module_name") == module for item in adapters.get(package, [])):
            raise RuntimeError(f"Missing adapter declaration: {package}; restore the repository pyproject.toml")
    if not isinstance(config.get("plugins"), dict):
        raise RuntimeError("Expected the upstream installer [tool.nonebot.plugins] table format")


def ensure_local_package(package, runner, environment):
    installed = distribution(package)
    if not Path(installed.locate_file("")).resolve().is_relative_to(Path(sys.prefix).resolve()):
        # NoneBot's regular adapter package cannot span system and venv directories.
        # Install only this distribution locally; never uninstall the system copy.
        runner([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                "--ignore-installed", "--no-deps", f"{package}=={installed.version}"], check=True, env=environment)


def install_dependencies(directory, runner=subprocess.run):
    python = Path(sys.executable)
    environment = {**os.environ, "VIRTUAL_ENV": sys.prefix, "PATH": str(python.parent) + os.pathsep + os.environ.get("PATH", "")}
    validate_project(directory)
    # NB CLI writes project metadata. Use the real project file in a disposable copy,
    # so rerunning installation cannot rewrite a user's project configuration.
    with tempfile.TemporaryDirectory(prefix="spirit-pet-nb-") as temporary:
        workspace = Path(temporary)
        shutil.copy2(directory / "pyproject.toml", workspace / "pyproject.toml")
        base = [str(python), "-m", "nb_cli", "--python", str(python), "--cwd", str(workspace)]
        # Exact registry selectors avoid substring collisions, such as HTTPX2.
        for name in ("fastapi", "httpx", "websockets"):
            runner([*base, "driver", "install", f"nonebot2[{name}]", "--no-input"], check=True, env=environment)
            ensure_local_package("nonebot2", runner, environment)
            # NB CLI 1.5.0's driver installer can return zero after pip fails.
            runner([str(python), "-c", f"import nonebot.drivers.{name}"], check=True, env=environment)
        for name in ("onebot.v11", "qq"):
            runner([*base, "adapter", "install", f"nonebot.adapters.{name}", "--no-input"], check=True, env=environment)
            ensure_local_package("nonebot-adapter-onebot" if name == "onebot.v11" else "nonebot-adapter-qq", runner, environment)
            runner([str(python), "-c", f"import nonebot.adapters.{name}"], check=True, env=environment)
        validate_project(workspace)
    runner([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r", str(directory / "requirements.txt")], check=True, env=environment)
    runner([str(python), "-m", "pip", "check"], check=True, env=environment)
    runner([str(python), "-c", "from importlib.metadata import version; assert version('nb-cli') == '1.5.0'; "
            "import nonebot.drivers.fastapi, nonebot.drivers.httpx, nonebot.drivers.websockets; "
            "import nonebot.adapters.onebot.v11, nonebot.adapters.qq; "
            "print('Verified NB CLI 1.5.0, three drivers and both adapters')"], check=True, env=environment)
