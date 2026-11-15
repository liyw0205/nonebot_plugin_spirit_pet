from argparse import Namespace
from scripts.market_perf_benchmark import run_pair


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


def test_market_benchmark_pair_reuses_fixture_and_cleans_temporary_database():
    result = run_pair(_args("pair"))
    assert result["users"] == 64
    assert result["sample_users"] == 16
    assert result["seed_id"] == "market-fixed-20261116"
    assert result["market_rows"] == 80
    assert result["fixture_bytes"] > 0
    assert {case["action"] for case in result["after"]["cases"]} == {
        "board", "bid_board", "mine", "records", "bid_records", "buy", "fill",
    }
    for variant in (result["before"], result["after"]):
        assert all(case["error_rate"] == 0 for case in variant["cases"])
        assert all(case["p99_ms"] >= case["p50_ms"] for case in variant["cases"])
        assert all(case["sql_statements"] > 0 for case in variant["cases"])
    assert all(result["after"]["correctness"].values())
    assert "market_listing_board" in " ".join(result["after"]["explain"]["listing_page"])
    assert "market_listing_expiry" in " ".join(result["after"]["explain"]["listing_expiry"])
    assert "market_bid_board" in " ".join(result["after"]["explain"]["bid_page"])
    assert "market_bid_expiry" in " ".join(result["after"]["explain"]["bid_expiry"])
    assert result["variant"] == "pair"
    assert len(result["before"]["cases"]) == 14
    assert len(result["after"]["cases"]) == 14
    assert result["seed_id"] == "market-fixed-20261116"
    assert result["market_rows"] == 80
    assert all(case["samples"] == 16 for case in result["before"]["cases"])
    assert all(case["samples"] == 16 for case in result["after"]["cases"])
