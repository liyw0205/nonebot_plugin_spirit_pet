from contextlib import closing
from pathlib import Path
import sys
import tempfile


def main(target: Path) -> None:
    target = target.resolve()
    sys.path.insert(0, str(target))

    import nonebot

    nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="WARNING")

    from nonebot_plugin_spirit_pet.content.catalog import Catalog
    from nonebot_plugin_spirit_pet.storage.database import SCHEMA_VERSION, Store

    module_path = Path(sys.modules[Catalog.__module__].__file__).resolve()
    if target not in module_path.parents:
        raise RuntimeError("plugin modules were not imported from the installed wheel")

    content = Catalog.load()
    with tempfile.TemporaryDirectory(prefix="spirit-pet-wheel-") as directory:
        store = Store(Path(directory) / "smoke.db")
        store.initialize()
        with closing(store.connect()) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
    if len(content.species) != 27 or len(content.stages) != 8 or version != SCHEMA_VERSION:
        raise RuntimeError("wheel runtime content or schema verification failed")
    print(f"Loaded wheel runtime content: {len(content.species)} species, {len(content.stages)} stages, schema {version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_distribution.py INSTALLED_WHEEL_TARGET")
    main(Path(sys.argv[1]))
