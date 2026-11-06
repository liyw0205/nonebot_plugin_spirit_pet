import shutil
import sys
from contextlib import closing
from pathlib import Path

import nonebot
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "plugins"))
nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="WARNING")

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.storage.database import Store


class FixedRandom:
    def randint(self, start, stop):
        return start

    def random(self):
        return 0.0


@pytest.fixture(scope="session")
def store_template(tmp_path_factory):
    """Build the schema once; each test copies the finished file.

    ``Store.initialize()`` costs ~26ms per test because it executes the whole
    schema. Copying a checkpointed template keeps every test on its own database
    (full isolation) while skipping that DDL. Content is still parsed per test:
    several tests mutate nested ``content`` dicts in place.
    """
    path = tmp_path_factory.mktemp("template") / "template.db"
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture
def game(tmp_path, store_template):
    path = tmp_path / "shared" / "spirit.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store_template, path)
    store = Store(path)
    return Game(store, Config(), FixedRandom()), store


@pytest.fixture
def play(game):
    import itertools

    counter = itertools.count()

    def execute(action, arg="", user="u1", now=1_800_000_000, op=None):
        return game[0].execute(user, action, arg, op or f"test-{next(counter)}", now)

    return execute
