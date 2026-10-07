import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile


def configure(directory: Path, host: str, port: int, unattended=False):
    from dotenv import set_key

    destination = directory / ".env"
    if destination.exists() or destination.is_symlink():
        print(f"Keeping existing configuration unchanged: {destination}")
        return
    values = {"HOST": host, "PORT": str(port), "ONEBOT_V11_ACCESS_TOKEN": secrets.token_urlsafe(32)}
    if not unattended and sys.stdin.isatty():
        print("Configure OneBot V11 / QQBot. Blank answers keep safe defaults.")
        selected = input("Adapter: 1=OneBot V11, 2=QQBot, 3=both [1]: ").strip() or "1"
        if selected not in {"1", "2", "3"}:
            raise RuntimeError("Adapter choice must be 1, 2 or 3")
        if selected in {"2", "3"}:
            app_id = input("QQBot AppID (blank to configure later): ").strip()
            if app_id:
                secret = getpass.getpass("QQBot AppSecret (hidden): ")
                if not secret:
                    raise RuntimeError("AppSecret must not be empty when AppID is set")
                websocket = (input("QQ connection: 1=WebSocket, 2=Webhook [1]: ").strip() or "1")
                if websocket not in {"1", "2"}:
                    raise RuntimeError("QQ connection choice must be 1 or 2")
                values["QQ_BOTS"] = json.dumps([{
                    "id": app_id, "secret": secret,
                    "intent": {"c2c_group_at_messages": True}, "use_websocket": websocket == "1",
                }], ensure_ascii=True)
    # Finish all quoting and configuration before creating the destination.
    with tempfile.TemporaryDirectory(prefix=".spirit-pet-env-", dir=directory) as temporary:
        prepared = Path(temporary) / ".env"
        prepared.write_text((directory / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        for key, value in values.items():
            set_key(str(prepared), key, value, quote_mode="always")
        if os.name != "nt":
            prepared.chmod(0o600)
        try:
            # A same-directory hard link publishes the complete file atomically
            # while preserving no-overwrite semantics. Windows may lack links;
            # retain an exclusive-copy fallback and remove partial output on error.
            os.link(prepared, destination)
        except FileExistsError:
            raise
        except (AttributeError, OSError, NotImplementedError):
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as output, prepared.open("rb") as source:
                    shutil.copyfileobj(source, output)
            except BaseException:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
                raise
    if os.name != "nt":
        destination.chmod(0o600)
    print(f"Created private configuration: {destination}")
    print("OneBot token is stored in .env; copy it into your OneBot client's token field.")


def show_start(directory):
    python = sys.executable
    print(f"Project: {directory}")
    if os.name == "nt":
        print(f"Restart from the project directory: & \"{python}\" bot.py")
    else:
        print(f"Restart from the project directory: \"{python}\" bot.py")
    print("Connection guide: docs/CONNECTIONS.md. NapCat is optional; QQBot needs its own credentials.")
