"""Bounded SQLite/game benchmark for the high-frequency player read paths.

The command never uses the configured player database.  It creates a temporary
database (or an explicitly supplied path), seeds it in batches, and measures the
same ``Game.execute`` and message adapters used by the real adapters.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import resource
import shutil
import statistics
import sys
import tempfile
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
from nonebot_plugin_spirit_pet.storage.database import Store


NOW = 1_800_000_000
DEFAULT_SAMPLE = 100


class _TimedStore(Store):
    """Keep lock-wait instrumentation out of the production Store API."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.begin_samples: list[tuple[str, float]] = []
        self.special_replay_queries = 0
        self.operation_preflight_queries = 0
        self._transaction_recorder = self.begin_samples.append

    def connect(self):
        conn = super().connect()
        conn.set_trace_callback(self._trace)
        return conn

    def _trace(self, statement: str) -> None:
        if "/* special-replay */" in statement:
            self.special_replay_queries += 1
        if "/* operation-preflight */" in statement and "SELECT" in statement and "reply" in statement:
            self.operation_preflight_queries += 1

    def clear_begin_samples(self) -> None:
        self.begin_samples.clear()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, int(round((len(values) - 1) * percentile)))
    return values[index]


def _seed(path: Path, users: int, batch_size: int, catalog: Catalog) -> dict[str, str]:
    store = Store(path)
    store.initialize()
    dishes = sorted(catalog.cuisine.values(), key=lambda dish: (dish.level, dish.id))[:3]
    species = next(species for species in catalog.species.values() if species.starter)
    rows_per_user = []
    for dish in dishes:
        rows_per_user.append((f"cuisine_dish_{dish.id}", 6, 1))
        # Claimed tiers have a receipt row; the 6-portion tier is intentionally
        # absent so the benchmark exercises one real settlement and then replay.
        rows_per_user.extend((f"cuisine_mastery_{dish.id}_{threshold}", 6, 1) for threshold in (1, 3))
    with closing(store.connect()) as conn:
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("BEGIN IMMEDIATE")
        for start in range(0, users, batch_size):
            stop = min(users, start + batch_size)
            players = [(f"perf-{index:07d}", 100000, None, NOW) for index in range(start, stop)]
            conn.executemany(
                "INSERT INTO players(user_id,stones,active_pet_id,registered_at) VALUES (?,?,?,?)",
                players,
            )
            conn.executemany("INSERT INTO player_identity(user_id) VALUES (?)", [(row[0],) for row in players])
            pets = [
                (index + 1, f"perf-{index:07d}", species.id, species.name, species.initial_affinity, NOW)
                for index in range(start, stop)
            ]
            conn.executemany(
                "INSERT INTO pets(pet_id,user_id,species_id,name,affinity,energy_updated) VALUES (?,?,?,?,?,?)",
                pets,
            )
            conn.executemany(
                "UPDATE players SET active_pet_id=? WHERE user_id=?",
                [(row[0], row[1]) for row in pets],
            )
            conn.executemany(
                "INSERT INTO active_pet_slots(user_id,slot,pet_id) VALUES (?,1,?)",
                [(row[1], row[0]) for row in pets],
            )
            progress = []
            inventory = []
            for index in range(start, stop):
                user_id = f"perf-{index:07d}"
                progress.extend((user_id, quest_id, value, claimed) for quest_id, value, claimed in rows_per_user)
                item_ids = {item_id for dish in dishes for item_id in dish.ingredients}
                inventory.extend((user_id, item_id, 1000) for item_id in item_ids)
            conn.executemany(
                "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,?)",
                progress,
            )
            conn.executemany("INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,?,?)", inventory)
        conn.commit()
        conn.execute("PRAGMA optimize")
    return {"user_id": "perf-0000000", "dish": dishes[0].name, "dish_id": dishes[0].id}


def _explain(path: Path, user_id: str) -> dict[str, list[str]]:
    store = Store(path)
    with closing(store.connect()) as conn:
        plans = {
            "cuisine_progress": conn.execute(
                "EXPLAIN QUERY PLAN SELECT quest_id,progress,claimed FROM quest_progress "
                "WHERE user_id=? AND quest_id LIKE 'cuisine_%'", (user_id,)
            ).fetchall(),
            "pet_page": conn.execute(
                "EXPLAIN QUERY PLAN SELECT p.*, EXISTS("
                "SELECT 1 FROM quest_progress q "
                "WHERE q.user_id=p.user_id AND q.quest_id=? || CAST(p.pet_id AS TEXT) AND q.claimed=1"
                ") AS ascended FROM pets p WHERE p.user_id=? AND p.archived=0 "
                "ORDER BY p.pet_id LIMIT 5 OFFSET 0", ("ascended_", user_id)
            ).fetchall(),
            "pet_count": conn.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM pets WHERE user_id=? AND archived=0", (user_id,)
            ).fetchall(),
            "pet_counts": conn.execute(
                "EXPLAIN QUERY PLAN SELECT SUM(archived=0), SUM(archived=1) "
                "FROM pets WHERE user_id=?", (user_id,)
            ).fetchall(),
            "co_training_candidates": conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM pets "
                "WHERE user_id=? AND archived=0 AND species_id=? AND pet_id!=? ORDER BY pet_id",
                (user_id, "benchmark-species", 0),
            ).fetchall(),
            "special_replay": conn.execute(
                "EXPLAIN QUERY PLAN SELECT user_id FROM duel_actions WHERE operation_id=? "
                "UNION ALL SELECT initiator_id FROM battle_records WHERE operation_id=? "
                "UNION ALL SELECT user_id FROM fishing_casts WHERE operation_id=?",
                ("explain-operation", "explain-operation", "explain-operation"),
            ).fetchall(),
        }
    return {name: [str(dict(row)) for row in rows] for name, rows in plans.items()}


def _measure_case(
    game: Game, users: list[str], action: str, argument: str, concurrency: int,
    iterations: int, config: Config, dish: str,
) -> dict:
    samples: list[float] = []
    errors: list[str] = []
    onebot_bytes = 0
    qq_bytes = 0
    started_cpu = time.process_time()
    started = time.perf_counter()
    fixed_claim_ops = {user: f"perf-claim-{user}" for user in users}
    begin_start = len(game.store.begin_samples)
    replay_start = game.store.special_replay_queries
    preflight_start = game.store.operation_preflight_queries

    def call(index: int):
        user = users[index % len(users)]
        op = fixed_claim_ops[user] if action == "cuisine_mastery_claim" else f"perf-{action}-{index}-{iterations}"
        begin = time.perf_counter()
        try:
            reply = game.execute(user, action, argument if action != "cuisine_mastery_claim" else f"{dish} 6", op, NOW)
            plain = _plain_reply(reply, config.spirit_pet_command_prefix)
            _, qq = _qq_segments(reply, config, allow_keyboard=True)
            return time.perf_counter() - begin, len(plain.encode()), len(str(qq).encode()), None
        except Exception as exc:  # benchmark reports errors instead of hiding them
            return time.perf_counter() - begin, 0, 0, type(exc).__name__

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(call, index) for index in range(max(1, iterations * len(users)))]
        for future in as_completed(futures):
            elapsed, plain_size, rich_size, error = future.result()
            samples.append(elapsed * 1000)
            onebot_bytes += plain_size
            qq_bytes += rich_size
            if error:
                errors.append(error)
    elapsed = time.perf_counter() - started
    begin_samples = game.store.begin_samples[begin_start:]
    begin_waits = [sample for _, sample in begin_samples]
    immediate_waits = [sample for mode, sample in begin_samples if mode == "BEGIN IMMEDIATE"]

    def wait_stats(values: list[float]) -> dict[str, float]:
        return {
            "count": len(values),
            "total_ms": round(sum(values), 3),
            "p50_ms": round(_percentile(values, 0.50), 3),
            "p95_ms": round(_percentile(values, 0.95), 3),
            "p99_ms": round(_percentile(values, 0.99), 3),
        }

    return {
        "action": action,
        "concurrency": concurrency,
        "samples": len(samples),
        "p50_ms": round(_percentile(samples, 0.50), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "p99_ms": round(_percentile(samples, 0.99), 3),
        "error_rate": round(len(errors) / len(samples), 6) if samples else 0.0,
        "errors": dict((name, errors.count(name)) for name in sorted(set(errors))),
        "cpu_seconds": round(time.process_time() - started_cpu, 3),
        "wall_seconds": round(elapsed, 3),
        "onebot_response_bytes_avg": round(onebot_bytes / len(samples)) if samples else 0,
        "qq_response_bytes_avg": round(qq_bytes / len(samples)) if samples else 0,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "transaction_begin": wait_stats(begin_waits),
        "immediate_begin": wait_stats(immediate_waits),
        "special_replay_queries": game.store.special_replay_queries - replay_start,
        "operation_preflight_queries": game.store.operation_preflight_queries - preflight_start,
    }


def run(args: argparse.Namespace) -> dict:
    catalog = Catalog.load()
    temporary = args.database is None
    directory = Path(tempfile.mkdtemp(prefix="spirit-pet-perf-")) if temporary else None
    path = Path(args.database) if args.database else directory / "benchmark.db"
    try:
        seed_info = _seed(path, args.users, args.batch_size, catalog)
        config = Config(spirit_pet_db=path, spirit_pet_qq_mode="native", spirit_pet_qq_keyboard=True)
        store = _TimedStore(path)
        store.initialize()
        store.clear_begin_samples()
        game = Game(store, config, content=catalog)
        users = [f"perf-{index:07d}" for index in range(min(args.sample_users, args.users))]
        actions = (
            ("identity", ""), ("pet_list", "1"), ("help", "成长"), ("cuisine", ""),
            ("cuisine_mastery", ""), ("quests", ""), ("cuisine_mastery_claim", ""),
        )
        cases = []
        for phase, iterations in (("cold", 1), ("hot", args.iterations)):
            for action, argument in actions:
                for concurrency in args.concurrency:
                    result = _measure_case(game, users, action, argument, concurrency, iterations, config, seed_info["dish"])
                    result["phase"] = phase
                    cases.append(result)
        profile_text = ""
        if args.profile:
            profiler = cProfile.Profile()
            profiler.enable()
            game.execute(seed_info["user_id"], "cuisine_mastery", "", "perf-profile", NOW)
            profiler.disable()
            stream = io.StringIO()
            import pstats

            pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats()
            profile_text = stream.getvalue().splitlines()[:25]
        return {
            "label": args.label,
            "users": args.users,
            "sample_users": len(users),
            "batch_size": args.batch_size,
            "database": str(path),
            "seed": seed_info,
            "explain": _explain(path, seed_info["user_id"]),
            "cases": cases,
            "profile": profile_text,
        }
    finally:
        if temporary and directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--sample-users", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 50])
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--label", default="after")
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.users <= 1_000_000:
        parser.error("--users must be between 1 and 1000000")
    if not 1 <= args.batch_size <= 100_000:
        parser.error("--batch-size must be between 1 and 100000")
    if not 1 <= args.sample_users <= args.users:
        parser.error("--sample-users must be between 1 and --users")
    result = run(args)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
