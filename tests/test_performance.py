from argparse import Namespace
from pathlib import Path

import pytest

from scripts.perf_benchmark import run


def test_benchmark_is_bounded_and_removes_temporary_database():
    result = run(Namespace(
        users=32,
        sample_users=4,
        batch_size=8,
        iterations=1,
        concurrency=[1, 2],
        database=None,
        output=None,
        label="test",
        profile=False,
    ))

    assert result["users"] == 32
    assert result["sample_users"] == 4
    assert not Path(result["database"]).exists()
    assert result["cases"]
    assert all(case["samples"] > 0 for case in result["cases"])
    assert all(case["p99_ms"] >= case["p50_ms"] for case in result["cases"])
    assert all(case["transaction_begin"]["count"] == case["samples"] for case in result["cases"])
    assert all(
        case["transaction_begin"]["p99_ms"] >= case["transaction_begin"]["p50_ms"]
        for case in result["cases"]
    )
    assert "USING COVERING INDEX quest_progress_user_status" in " ".join(
        result["explain"]["cuisine_progress"]
    )
    pet_plan = " ".join(result["explain"]["pet_page"])
    assert "USING INDEX pets_owner" in pet_plan or "USING COVERING INDEX pets_owner" in pet_plan
    assert "sqlite_autoindex_quest_progress_1" in pet_plan


@pytest.mark.parametrize("users", [1000, 10000])
def test_benchmark_generation_scales_in_bounded_batches(users):
    result = run(Namespace(
        users=users,
        sample_users=2,
        batch_size=500,
        iterations=1,
        concurrency=[1],
        database=None,
        output=None,
        label=f"bounded-{users}",
        profile=False,
    ))

    assert result["users"] == users
    assert result["sample_users"] == 2
    assert not Path(result["database"]).exists()
