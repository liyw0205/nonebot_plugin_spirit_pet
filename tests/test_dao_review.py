import math
import random
import tracemalloc
from contextlib import closing

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.gameplay.identity import random_name
from nonebot_plugin_spirit_pet.storage.repository import Repository


def test_names_roundtrip_through_independent_fixed_width_encoder(game):
    names = game[0].content.dao_names
    templates = []
    start = 0
    for template in names.templates:
        fields = [names.fields[field] for field in template]
        size = math.prod(len(entries) for entries in fields)
        templates.append((start, fields, size))
        start += size
    assert start == names.capacity >= 10_000_000
    lengths = [sum(len(entries[0]) for entries in fields) for _, fields, _ in templates]
    assert len(set(lengths)) == len(lengths)
    indexes = set(random.Random(814).sample(range(names.capacity), 2000))
    for base, fields, size in templates:
        indexes.update((base, base + size - 1))
        for position, entries in enumerate(fields):
            stride = math.prod(len(part) for part in fields[position + 1:])
            indexes.update(base + digit * stride for digit in range(len(entries)))
    for index in indexes:
        name = names.name_at(index)
        base, fields, _ = next(
            template for template in templates if sum(len(entries[0]) for entries in template[1]) == len(name)
        )
        offset, encoded = 0, 0
        for entries in fields:
            width = len(entries[0])
            digit = entries.index(name[offset:offset + width])
            encoded = encoded * len(entries) + digit
            offset += width
        assert base + encoded == index


def test_streaming_name_generation_keeps_memory_independent_of_pool_size(game):
    names = game[0].content.dao_names
    tracemalloc.start()
    try:
        checksum = sum(len(names.name_at((index * 104729) % names.capacity)) for index in range(10000))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert checksum > 0
    assert peak < 512_000


def test_four_thousand_consecutive_collisions_use_bounded_indexed_batches(game):
    count = 4096
    names = game[0].content.dao_names
    with closing(game[1].connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO players(user_id, dao_name, stones) VALUES (?, ?, 0)",
            ((f"review-owner-{index}", names.name_at(0 if index == 0 else count + index - 1))
             for index in range(count)),
        )
        repo = Repository(conn)
        ctx = Context(repo, game[0].content, game[0].config, game[0].rng, "review-new-player", 1800000000, "review")
        queries = []
        conn.set_trace_callback(queries.append)
        tracemalloc.start()
        try:
            result = random_name(ctx)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            conn.set_trace_callback(None)
        assert result == names.name_at(count * 2 - 1)
        assert not repo.players
        assert peak < 1_000_000
        lookups = [query for query in queries if query.startswith("SELECT") and "players" in query]
        batches = [query for query in lookups if " IN (" in query]
        assert len(lookups) <= math.ceil(count / 128) + 3
        assert len(batches) == math.ceil(count / 128)
        assert all(query.count(",") < 128 for query in batches)
        assert all("WHERE" in query or "COUNT(*)" in query for query in lookups)
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT dao_name FROM players WHERE dao_name COLLATE NOCASE IN (?, ?)",
            (names.name_at(0), names.name_at(1)),
        ).fetchall()
        assert any("SEARCH" in row["detail"] and "INDEX" in row["detail"] for row in plan)
        conn.rollback()
