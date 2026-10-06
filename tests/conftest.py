import sys
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


@pytest.fixture
def game(tmp_path):
    store = Store(tmp_path / "shared" / "spirit.db")
    store.initialize()
    return Game(store, Config(), FixedRandom()), store


@pytest.fixture
def play(game):
    import itertools

    counter = itertools.count()

    def execute(action, arg="", user="u1", now=1_800_000_000, op=None):
        return game[0].execute(user, action, arg, op or f"test-{next(counter)}", now)

    return execute
