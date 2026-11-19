import random
import sqlite3
import threading
import time

from ..content.catalog import Catalog
from ..core.config import Config
from ..domain.models import GameError, Reply
from ..storage.database import Store
from ..storage.repository import Repository
from .commands import ACTIONS
from .context import Context


# These handlers only assemble a reply from persisted state.  They can use a
# deferred SQLite transaction so concurrent readers do not queue behind the
# write lock used by state-changing commands.
READ_ONLY_ACTIONS = frozenset({
    "help", "pet_list", "cuisine", "cuisine_orders", "cuisine_mastery",
})


def _market_read_only(argument: str) -> bool:
    """Classify market lookups without treating settlement actions as reads."""
    parts = argument.split()
    if not parts or parts[0].isdecimal():
        return True
    if parts[0] in {"我的", "记录", "求购记录", "行情", "掌柜", "掌柜记录"}:
        return True
    return parts[0] == "求购" and (
        len(parts) == 1 or (len(parts) == 2 and parts[1].isdecimal())
    )


def _contracts_read_only(argument: str) -> bool:
    """Keep contract discovery and previews out of the state-saving path."""
    parts = argument.split()
    if not parts:
        return True
    if parts[0] != "组合":
        return False
    if len(parts) == 1 or (len(parts) == 2 and parts[1].isdecimal()):
        return True
    return (len(parts) == 5 and parts[1] == "预览") or (
        len(parts) == 2 and parts[1] == "记录"
    )


def _assignment_chain_read_only(argument: str) -> bool:
    """Only the catalogue and history views are safe deferred reads."""
    parts = argument.split()
    return not parts or parts[0] == "记录"


def _vein_read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or parts[0] in {"预览", "记录"}


def _ruin_read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or parts[0] in {"预览", "记录"}


def _cave_read_only(argument: str) -> bool:
    parts = argument.split()
    return parts[:1] == ["共建"] and (len(parts) == 1 or parts[1] == "记录")


def _farm_contract_read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or (parts[0] == "记录" and len(parts) <= 2)


def _cuisine_coop_read_only(argument: str) -> bool:
    parts = argument.split()
    return not parts or parts[0] in {"预览", "详情", "记录"}


class Game:
    def __init__(self, store: Store, config: Config, rng=None, content: Catalog | None = None):
        self.store = store
        self.config = config
        self.rng = rng if rng is not None else random.SystemRandom()
        self.content = content if content is not None else Catalog.load()
        self._market_sweep_cache: dict[tuple[str, tuple[str, ...], int], tuple] = {}
        self._market_sweep_lock = threading.Lock()
        self._market_version_lock = threading.Lock()
        self._market_count_cache: dict[tuple[str, int], int] = {}
        self._market_trend_cache: dict[tuple[int, int], tuple[dict, ...]] = {}
        self._market_version_conn: sqlite3.Connection | None = None

    def _market_data_version(self) -> int:
        with self._market_version_lock:
            if self._market_version_conn is None:
                self._market_version_conn = sqlite3.connect(
                    self.store.path, timeout=15, isolation_level=None, check_same_thread=False,
                )
            return int(self._market_version_conn.execute("PRAGMA data_version").fetchone()[0])

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
        read_only = action in READ_ONLY_ACTIONS or (
            action == "market" and _market_read_only(argument)
        ) or (
            action == "contracts" and _contracts_read_only(argument)
        ) or (
            action == "daily_assignment_chain" and _assignment_chain_read_only(argument)
        ) or (
            action == "vein_expedition" and _vein_read_only(argument)
        ) or (
            action == "ruin_expedition" and _ruin_read_only(argument)
        ) or (
            action == "cave" and _cave_read_only(argument)
        ) or (
            action == "farm_contracts" and _farm_contract_read_only(argument)
        ) or (
            action == "item_trade" and (
                not argument.split() or argument.split()[0] in {"预览", "详情", "记录"}
            )
        ) or (
            action == "cuisine_coop" and _cuisine_coop_read_only(argument)
        )
        market_initial_version = self._market_data_version() if action == "market" else None
        def run(conn):
            if read_only:
                context = Context(repo=Repository(conn), content=self.content, config=self.config,
                                   rng=self.rng, user_id=user_id, now=timestamp,
                                   operation_id=operation_id,
                                   market_sweep_cache=self._market_sweep_cache,
                                   market_sweep_lock=self._market_sweep_lock,
                                   market_count_cache=self._market_count_cache,
                                   market_data_version=self._market_data_version,
                                   market_initial_data_version=market_initial_version,
                                   market_trend_cache=self._market_trend_cache)
                if command.registered:
                    context.player()
                return command.handler(context, argument)
            repo = Repository(conn)
            persistent = repo.special_operation(operation_id)
            if persistent is not None:
                kind, owner, payload = persistent
                if owner != user_id:
                    raise GameError("operation ID reused by a different user")
                if kind == "battle":
                    return Reply(payload["title"], tuple(payload["lines"]), tuple(payload["commands"]))
                return Reply.from_data(payload)
            context = Context(
                repo, self.content, self.config, self.rng, user_id, timestamp, operation_id,
                self._market_sweep_cache, self._market_sweep_lock, self._market_count_cache,
                self._market_data_version,
                market_initial_version,
                {}, self._market_trend_cache,
            )
            if command.registered:
                context.player()
            result = command.handler(context, argument)
            repo.save()
            return result

        return self.store.transact(
            user_id, operation_id, timestamp, run,
            immediate=not read_only,
            record_operation=not read_only,
            retry_deferred_on_busy=action == "market" and read_only,
        )
