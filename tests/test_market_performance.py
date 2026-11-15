from argparse import Namespace
from pathlib import Path

from scripts.market_perf_benchmark import run


def _args(variant):
    return Namespace(
        variant=variant,
        users=64,
        history=16,
        sample_users=16,
        batch_size=16,
        iterations=1,
        concurrency=[16],
        database=None,
        output=None,
    )


def test_market_benchmark_is_bounded_and_cleans_temporary_database():
    result = run(_args("after"))
    assert result["users"] == 64
    assert result["sample_users"] == 16
    assert result["seed_id"] == "market-fixed-20261116"
    assert result["market_rows"] == 80
    assert result["fixture_bytes"] > 0
    assert not Path(result["database"]).exists()
    assert {case["action"] for case in result["cases"]} == {
        "board", "bid_board", "mine", "records", "bid_records", "buy", "fill",
    }
    assert all(case["error_rate"] == 0 for case in result["cases"])
    assert all(case["p99_ms"] >= case["p50_ms"] for case in result["cases"])
    assert all(case["sql_statements"] > 0 for case in result["cases"])
    assert all(result["correctness"].values())
    assert "market_listing_board" in " ".join(result["explain"]["listing_page"])
    assert "market_listing_expiry" in " ".join(result["explain"]["listing_expiry"])
    assert "market_bid_board" in " ".join(result["explain"]["bid_page"])
    assert "market_bid_expiry" in " ".join(result["explain"]["bid_expiry"])


def test_market_before_variant_keeps_same_player_cases():
    result = run(_args("before"))
    assert result["variant"] == "before"
    assert len(result["cases"]) == 14
    assert result["seed_id"] == "market-fixed-20261116"
    assert result["market_rows"] == 80
    assert all(case["samples"] == 16 for case in result["cases"])
    assert all(case["error_rate"] == 0 for case in result["cases"])
    assert all(result["correctness"].values())
