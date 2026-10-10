import random
import time

from ..content.catalog import Catalog
from ..core.config import Config
from ..domain.models import GameError, Reply
from ..storage.database import Store
from ..storage.repository import Repository
from .commands import ACTIONS
from .context import Context


class Game:
    def __init__(self, store: Store, config: Config, rng=None, content: Catalog | None = None):
        self.store = store
        self.config = config
        self.rng = rng if rng is not None else random.SystemRandom()
        self.content = content if content is not None else Catalog.load()

    def execute(
        self, user_id: str, action: str, argument: str, operation_id: str, now: int | None = None,
    ) -> Reply:
        if not user_id or not operation_id:
            raise ValueError("user ID and operation ID are required")
        command = ACTIONS.get(action)
        if command is None:
            raise GameError("未知指令，请发送“灵宠帮助”查看可用入口。")
        argument = argument.strip()
        if argument and not command.arguments:
            raise GameError("该指令不接受参数，请发送“灵宠帮助”查看用法。")
        timestamp = int(time.time()) if now is None else now

        def run(conn):
            repo = Repository(conn)
            persistent_battle = repo.battle_operation(operation_id, user_id)
            if persistent_battle is not None:
                return Reply(
                    persistent_battle["title"], tuple(persistent_battle["lines"]),
                    tuple(persistent_battle["commands"]),
                )
            context = Context(repo, self.content, self.config, self.rng, user_id, timestamp, operation_id)
            result = command.handler(context, argument)
            repo.save()
            return result

        return self.store.transact(user_id, operation_id, timestamp, run)
