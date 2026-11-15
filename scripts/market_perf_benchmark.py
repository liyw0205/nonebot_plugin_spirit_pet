"""Bounded before/after benchmark for the player market paths.

The before variant deliberately restores the old Python-side pagination and full
active-row sweep. Both variants use the same deterministic SQLite seed and the
same Game/message adapters; no configured player database is opened.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "plugins"))

import nonebot

nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="WARNING")

from nonebot_plugin_spirit_pet.adapters.messaging import _plain_reply, _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.gameplay import market
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.pagination import Page
from nonebot_plugin_spirit_pet.utils.arguments import quantity

NOW = 1_800_000_000
FIXED_SEED = "market-fixed-20261116"
DEFAULT_USERS = 1_000_000
DEFAULT_HISTORY = 200_000
_ORIGINAL_QUERY_PAGE = market._query_page
_ORIGINAL_SWEEP = market._known_or_expired


class TimedStore(Store):
    def __init__(self, path: Path):
        super().__init__(path)
        self.begin_samples: list[tuple[str, float]] = []
        self.sql_statements = 0
        self.sql_selects = 0
        self._metric_lock = threading.Lock()
        self._transaction_recorder = self.begin_samples.append

    def connect(self):
        conn = super().connect()
        conn.set_trace_callback(self._trace)
        return conn

    def _trace(self, statement: str) -> None:
        if not statement:
            return
        with self._metric_lock:
            self.sql_statements += 1
            if statement.lstrip().upper().startswith("SELECT"):
                self.sql_selects += 1

    def reset_metrics(self) -> None:
        with self._metric_lock:
            self.sql_statements = 0
            self.sql_selects = 0
        self.begin_samples.clear()

    def metrics(self) -> tuple[int, int]:
        with self._metric_lock:
            return self.sql_statements, self.sql_selects


def _uid(index: int) -> str:
    return f"market-{index:07d}"


def _fixture_bytes(path: Path) -> int:
    return sum(candidate.stat().st_size for candidate in path.parent.glob(f"{path.name}*"))


def _seed(
    path: Path, users: int, batch_size: int, history: int, market_rows: int,
) -> dict[str, int | str]:
    catalog = Catalog.load()
    item = next(entry for entry in catalog.items.values() if entry.id == "forge_ore")
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("BEGIN IMMEDIATE")
        for start in range(0, users, batch_size):
            stop = min(users, start + batch_size)
            players = [(_uid(i), 1_000_000_000, i + 1, NOW) for i in range(start, stop)]
            conn.executemany(
                "INSERT INTO players(user_id,stones,active_pet_id,registered_at) VALUES (?,?,?,?)",
                players,
            )
            conn.executemany("INSERT INTO player_identity(user_id) VALUES (?)", [(_uid(i),) for i in range(start, stop)])
            conn.executemany(
                "INSERT INTO pets(pet_id,user_id,species_id,name,affinity,energy_updated) VALUES (?,?,?,?,?,?)",
                [(i + 1, _uid(i), "qingluan", "青鸾", 10, NOW) for i in range(start, stop)],
            )
            conn.executemany(
                "INSERT INTO active_pet_slots(user_id,slot,pet_id) VALUES (?,1,?)",
                [(_uid(i), i + 1) for i in range(start, stop)],
            )
            conn.executemany(
                "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,?,?)",
                [(_uid(i), item.id, 100) for i in range(start, stop)],
            )
            conn.executemany(
                "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1)",
                [(_uid(i), "market_stall", 1) for i in range(start, stop)],
            )
        for start in range(0, market_rows, batch_size):
            stop = min(market_rows, start + batch_size)
            listings = []
            sales = []
            bids = []
            bid_sales = []
            for i in range(start, stop):
                seller = _uid((i + users // 4) % users)
                other = _uid((i + users // 4 + 1) % users)
                bid_buyer = _uid((i + users * 3 // 4) % users)
                bid_seller = _uid((i + users * 3 // 4 + 1) % users)
                listing_id = i + 1
                if i < history:
                    listings.append((listing_id, seller, item.id, 1, 10, NOW, NOW + 86400, "sold", NOW, other))
                    sales.append((listing_id, seller, other, item.id, 1, 10, 10, 1, 9, NOW))
                else:
                    listings.append((listing_id, seller, item.id, 1, 10, NOW, NOW + 86400, "active", None, None))
                bid_id = i + 1
                if i < history:
                    bids.append((bid_id, bid_buyer, item.id, 1, 10, 10, NOW, NOW + 86400, "filled", NOW, bid_seller))
                    bid_sales.append((bid_id, bid_buyer, bid_seller, item.id, 1, 10, 10, 1, 9, NOW))
                else:
                    bids.append((bid_id, bid_buyer, item.id, 1, 10, 10, NOW, NOW + 86400, "active", None, None))
            conn.executemany(
                "INSERT INTO market_listings(listing_id,seller_id,item_id,quantity,unit_price,created_at,expires_at,state,closed_at,buyer_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                listings,
            )
            conn.executemany(
                "INSERT INTO market_sales(listing_id,seller_id,buyer_id,item_id,quantity,unit_price,gross,fee,net,sold_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                sales,
            )
            conn.executemany(
                "INSERT INTO market_bids(bid_id,buyer_id,item_id,quantity,unit_price,escrow,created_at,expires_at,state,closed_at,seller_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                bids,
            )
            conn.executemany(
                "INSERT INTO market_bid_sales(bid_id,buyer_id,seller_id,item_id,quantity,unit_price,gross,fee,net,sold_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                bid_sales,
            )
        conn.commit()
        conn.execute("PRAGMA optimize")
    return {
        "users": users,
        "history": history,
        "market_rows": market_rows,
        "item": item.name,
        "active_start": history + 1,
        "active_count": market_rows - history,
        "active_bid_start": history + 1,
    }


def _legacy_page(ctx, query, args, count_query, count_args, argument, title, command, page_size):
    rows = ctx.repo.conn.execute(query, args).fetchall()
    number = quantity(argument or "1", 999)
    total = len(rows)
    pages = max(1, (total + page_size - 1) // page_size)
    if number > pages:
        raise market.GameError(f"{title}共 {pages} 页。")
    navigation = []
    if number > 1:
        navigation.append(f"{command} {number - 1}")
    if number < pages:
        navigation.append(f"{command} {number + 1}")
    offset = (number - 1) * page_size
    return Page(tuple(rows[offset:offset + page_size]), number, pages, tuple(navigation)), total


def _legacy_sweep(ctx, table):
    if table == "market_listings":
        columns = "listing_id, seller_id, item_id, quantity, expires_at"
    else:
        columns = "bid_id, buyer_id, item_id, escrow, expires_at"
    return ctx.repo.conn.execute(
        f"SELECT {columns} FROM {table} WHERE state='active' ORDER BY rowid",
    ).fetchall()


def _configure_variant(variant: str) -> None:
    if variant == "before":
        market._query_page = _legacy_page
        market._known_or_expired = _legacy_sweep
    else:
        market._query_page = _ORIGINAL_QUERY_PAGE
        market._known_or_expired = _ORIGINAL_SWEEP


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round((len(values) - 1) * percentile)))]


def _measure(game, config, seed, action, argument, users, concurrency, iterations, phase, case_slot):
    samples = []
    logic_samples = []
    plain_samples = []
    qq_samples = []
    sweep_samples = []
    errors = []
    plain_bytes = 0
    qq_bytes = 0
    begin_start = len(game.store.begin_samples)
    sql_start, select_start = game.store.metrics()
    started_cpu = time.process_time()
    started = time.perf_counter()
    active_start = int(seed["active_start"])
    original_sweep = market._known_or_expired

    def timed_sweep(ctx, table):
        started_sweep = time.perf_counter()
        try:
            return original_sweep(ctx, table)
        finally:
            sweep_samples.append((time.perf_counter() - started_sweep) * 1000)

    market._known_or_expired = timed_sweep

    def call(index):
        user_index = index % len(users)
        user = users[user_index]
        if action == "buy":
            target = active_start + (
                (case_slot * len(users) + index) % int(seed["active_count"])
            )
            argument_value = f"购买 {target}"
            op = f"market-{phase}-buy-{case_slot}-{index}"
        elif action == "fill":
            target = int(seed["active_bid_start"]) + (
                (case_slot * len(users) + index) % int(seed["active_count"])
            )
            user = users[(user_index + len(users) // 2) % len(users)]
            argument_value = f"应单 {target}"
            op = f"market-{phase}-fill-{case_slot}-{index}"
        else:
            argument_value = argument
            op = f"market-{phase}-{action}-{case_slot}-{index}"
        started_call = time.perf_counter()
        try:
            started_logic = time.perf_counter()
            reply = game.execute(user, "market", argument_value, op, NOW)
            logic_elapsed = (time.perf_counter() - started_logic) * 1000
            started_plain = time.perf_counter()
            plain = _plain_reply(reply, config.spirit_pet_command_prefix)
            plain_elapsed = (time.perf_counter() - started_plain) * 1000
            started_qq = time.perf_counter()
            _, qq = _qq_segments(reply, config, allow_keyboard=True)
            qq_elapsed = (time.perf_counter() - started_qq) * 1000
            return (
                (time.perf_counter() - started_call) * 1000,
                logic_elapsed, plain_elapsed, qq_elapsed,
                len(plain.encode()), len(str(qq).encode()), None,
            )
        except Exception as exc:
            return (
                (time.perf_counter() - started_call) * 1000,
                0, 0, 0, 0, 0, type(exc).__name__,
            )

    total_calls = max(1, iterations * len(users))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(call, index) for index in range(total_calls)]
        for future in as_completed(futures):
            elapsed, logic, plain_elapsed, qq_elapsed, plain_size, qq_size, error = future.result()
            samples.append(elapsed)
            logic_samples.append(logic)
            plain_samples.append(plain_elapsed)
            qq_samples.append(qq_elapsed)
            plain_bytes += plain_size
            qq_bytes += qq_size
            if error:
                errors.append(error)
    try:
        waits = [sample[1] for sample in game.store.begin_samples[begin_start:]]
        sql_total, sql_selects = game.store.metrics()
        sql_total -= sql_start
        sql_selects -= select_start
        return {
            "action": action,
            "concurrency": concurrency,
            "samples": len(samples),
            "p50_ms": round(_percentile(samples, 0.50), 3),
            "p95_ms": round(_percentile(samples, 0.95), 3),
            "p99_ms": round(_percentile(samples, 0.99), 3),
            "logic_p95_ms": round(_percentile(logic_samples, 0.95), 3),
            "plain_serialize_p95_ms": round(_percentile(plain_samples, 0.95), 3),
            "qq_serialize_p95_ms": round(_percentile(qq_samples, 0.95), 3),
            "expiry_sweep_p95_ms": round(_percentile(sweep_samples, 0.95), 3),
            "expiry_sweep_calls": len(sweep_samples),
            "error_rate": round(len(errors) / len(samples), 6) if samples else 0.0,
            "errors": {name: errors.count(name) for name in sorted(set(errors))},
            "cpu_seconds": round(time.process_time() - started_cpu, 3),
            "wall_seconds": round(time.perf_counter() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "onebot_response_bytes_avg": round(plain_bytes / len(samples)) if samples else 0,
            "qq_response_bytes_avg": round(qq_bytes / len(samples)) if samples else 0,
            "lock_wait_p50_ms": round(_percentile(waits, 0.50), 3),
            "lock_wait_p95_ms": round(_percentile(waits, 0.95), 3),
            "lock_wait_p99_ms": round(_percentile(waits, 0.99), 3),
            "sql_statements": sql_total,
            "sql_selects": sql_selects,
            "sql_statements_avg": round(sql_total / len(samples), 3) if samples else 0,
        }
    finally:
        market._known_or_expired = original_sweep


def _correctness(path: Path, config: Config, content: Catalog) -> dict[str, bool | int]:
    """Exercise operation replay, concurrent replay, and post-write freshness."""
    fresh_path = path.with_name("correctness.db")
    _seed(fresh_path, 64, 16, 16, 80)
    store = Store(fresh_path)
    store.initialize()
    game = Game(store, config, content=content)
    listing_id = 17
    buyer = _uid(0)
    operation = "market-correctness-replay"
    first = game.execute(buyer, "market", f"购买 {listing_id}", operation, NOW)
    replay = game.execute(buyer, "market", f"购买 {listing_id}", operation, NOW)
    with closing(store.connect()) as conn:
        sales = int(conn.execute("SELECT COUNT(*) FROM market_sales WHERE listing_id=?", (listing_id,)).fetchone()[0])
        inventory = int(conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id='forge_ore'", (buyer,)
        ).fetchone()[0])
    fresh = Game(store, config, content=content).execute(
        buyer, "market", "", "market-correctness-fresh-read", NOW,
    )

    concurrent_path = path.with_name("concurrent.db")
    _seed(concurrent_path, 64, 16, 16, 80)
    concurrent_store = Store(concurrent_path)
    concurrent_store.initialize()
    concurrent_game = Game(concurrent_store, config, content=content)

    def replay_call(_index):
        return concurrent_game.execute(
            buyer, "market", "购买 17", "market-correctness-concurrent", NOW,
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        replies = list(pool.map(replay_call, range(16)))
    with closing(concurrent_store.connect()) as conn:
        concurrent_sales = int(conn.execute(
            "SELECT COUNT(*) FROM market_sales WHERE listing_id=17",
        ).fetchone()[0])
    fresh_path.unlink(missing_ok=True)
    concurrent_path.unlink(missing_ok=True)
    return {
        "replay_same_reply": first == replay,
        "replay_single_sale": sales == 1 and inventory == 101,
        "fresh_read_after_write": "在售 63 件" in fresh.text(),
        "concurrent_same_operation_same_reply": all(
            reply == replies[0] for reply in replies
        ),
        "concurrent_single_sale": concurrent_sales == 1,
        "replay_sales": sales,
        "concurrent_sales": concurrent_sales,
    }


def _explain(path: Path) -> dict[str, list[str]]:
    store = Store(path)
    with closing(store.connect()) as conn:
        queries = {
            "listing_page": "EXPLAIN QUERY PLAN SELECT * FROM market_listings WHERE state='active' ORDER BY item_id, unit_price, listing_id LIMIT 5 OFFSET 0",
            "listing_expiry": "EXPLAIN QUERY PLAN SELECT listing_id FROM market_listings WHERE state='active' AND expires_at<=?",
            "listing_records": "EXPLAIN QUERY PLAN SELECT * FROM market_sales WHERE seller_id=? ORDER BY sold_at DESC, listing_id DESC LIMIT 5 OFFSET 0",
            "bid_page": "EXPLAIN QUERY PLAN SELECT * FROM market_bids WHERE state='active' ORDER BY item_id, unit_price DESC, bid_id LIMIT 5 OFFSET 0",
            "bid_expiry": "EXPLAIN QUERY PLAN SELECT bid_id FROM market_bids WHERE state='active' AND expires_at<=?",
            "bid_records": "EXPLAIN QUERY PLAN SELECT * FROM market_bid_sales WHERE buyer_id=? OR seller_id=? ORDER BY sold_at DESC, bid_id DESC LIMIT 5 OFFSET 0",
        }
        args = {
            "listing_expiry": (NOW,),
            "listing_records": (_uid(0),),
            "bid_expiry": (NOW,),
            "bid_records": (_uid(0), _uid(0)),
        }
        result = {}
        for name, sql in queries.items():
            result[name] = [str(dict(row)) for row in conn.execute(sql, args.get(name, ())).fetchall()]
        return result


def run(args: argparse.Namespace) -> dict:
    directory = Path(tempfile.mkdtemp(prefix="spirit-pet-market-perf-")) if args.database is None else None
    path = Path(args.database) if args.database else directory / "market.db"
    try:
        sample_count = min(args.sample_users, args.users)
        active_needed = 2 * (args.iterations + 1) * sample_count
        market_rows = max(args.users, args.history + active_needed)
        seed = _seed(path, args.users, args.batch_size, args.history, market_rows)
        _configure_variant(args.variant)
        config = Config(spirit_pet_db=path, spirit_pet_qq_mode="native", spirit_pet_qq_keyboard=True)
        store = TimedStore(path)
        store.initialize()
        game = Game(store, config, content=Catalog.load())
        store.reset_metrics()
        users = [_uid(i) for i in range(sample_count)]
        if not users:
            raise ValueError("users must leave at least one active listing")
        cases = []
        actions = (("board", ""), ("bid_board", "求购"), ("mine", "我的"), ("records", "记录"), ("bid_records", "求购记录"), ("buy", ""), ("fill", ""))
        case_slot = 0
        for phase, iterations in (("cold", 1), ("hot", args.iterations)):
            for action, argument in actions:
                for concurrency in args.concurrency:
                    measured = _measure(
                        game, config, seed, action, argument, users, concurrency, iterations, phase, case_slot,
                    )
                    measured["phase"] = phase
                    measured["variant"] = args.variant
                    cases.append(measured)
                    case_slot += 1
        return {
            "variant": args.variant,
            "seed_id": FIXED_SEED,
            "users": args.users,
            "history": args.history,
            "market_rows": market_rows,
            "sample_users": len(users),
            "database": str(path),
            "fixture_bytes": _fixture_bytes(path),
            "seed": seed,
            "explain": _explain(path),
            "correctness": _correctness(path, config, Catalog.load()),
            "cases": cases,
        }
    finally:
        market._query_page = _ORIGINAL_QUERY_PAGE
        market._known_or_expired = _ORIGINAL_SWEEP
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("before", "after"), default="after")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--history", type=int, default=DEFAULT_HISTORY)
    parser.add_argument("--sample-users", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 50])
    parser.add_argument("--database")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(args)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
