import copy
import math
import random
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.domain.battle_content import DaoNames
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay.identity import random_name
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql


def definitions():
    return Catalog.load().dao_names


def generate(game, queries=None):
    def run(conn):
        if queries is not None:
            conn.set_trace_callback(queries.append)
        repo = Repository(conn)
        ctx = Context(repo, game[0].content, game[0].config, game[0].rng,
                      "private-identifier-not-a-name", 1800000000, "generate-only")
        name = random_name(ctx)
        assert not repo.players
        return Reply(name, ())

    return game[1].transact("private-identifier-not-a-name", "generate-only", 1800000000, run).title


def test_default_capacity_counts_unique_outputs_not_only_combinations():
    names = definitions()
    widths = {}
    for field, entries in names.fields.items():
        assert len({entry.lower() for entry in entries}) == len(entries)
        assert len({len(entry) for entry in entries}) == 1
        assert all(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]+", entry) for entry in entries)
        widths[field] = len(entries[0])
    lengths = [sum(widths[field] for field in template) for template in names.templates]
    assert lengths == [6, 8]
    assert len(set(lengths)) == len(lengths)
    capacities = [math.prod(len(names.fields[field]) for field in template) for template in names.templates]
    assert capacities == [10_485_760, 10_485_760]
    assert names.capacity == sum(capacities) == 20_971_520


def test_mixed_radix_decoding_has_correct_template_and_component_boundaries():
    names = definitions()
    start = 0
    for template in names.templates:
        size = math.prod(len(names.fields[field]) for field in template)
        assert names.name_at(start) == "".join(names.fields[field][0] for field in template)
        assert names.name_at(start + size - 1) == "".join(names.fields[field][-1] for field in template)
        assert names.name_at(start + 1) == (
            "".join(names.fields[field][0] for field in template[:-1]) + names.fields[template[-1]][1]
        )
        for position in range(len(template) - 1):
            stride = math.prod(len(names.fields[field]) for field in template[position + 1:])
            assert names.name_at(start + stride) == "".join(
                names.fields[field][int(index == position)] for index, field in enumerate(template)
            )
        start += size
    indexes = random.Random(31).sample(range(names.capacity), 20000)
    outputs = [names.name_at(index) for index in indexes]
    assert len(set(outputs)) == len(outputs)
    assert all(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", name) for name in outputs)


@pytest.mark.parametrize("index", [-1, 20_971_520, True, 1.5, "1"])
def test_ordinal_bounds_are_strict(index):
    with pytest.raises((ValueError, TypeError)):
        definitions().name_at(index)


@pytest.mark.parametrize("change", [
    lambda data: data["fields"]["qualities"].__setitem__(1, data["fields"]["qualities"][0]),
    lambda data: data["fields"]["qualities"].__setitem__(slice(0, 2), ["A", "a"]),
    lambda data: data["fields"]["qualities"].__setitem__(0, "青云"),
    lambda data: data["templates"].append(data["templates"][0][:]),
    lambda data: data["templates"].append(["paths", "origins", "titles"]),
    lambda data: data["templates"].__setitem__(0, ["missing"]),
    lambda data: data["templates"].__setitem__(0, ["origins"] * 7),
    lambda data: data["templates"].__setitem__(0, ["qualities"]),
    lambda data: data["fields"].__setitem__("paths", ["问道"]),
    lambda data: data["fields"].__setitem__("titles", []),
    lambda data: data.__setitem__("fields", {}),
    lambda data: data.__setitem__("templates", []),
    lambda data: data["templates"].__setitem__(0, []),
    lambda data: data["fields"]["qualities"].__setitem__(0, "-"),
    lambda data: data.__setitem__("created_at", 1),
])
def test_unprovable_or_too_small_name_spaces_are_rejected(change):
    data = copy.deepcopy(definitions().model_dump())
    change(data)
    with pytest.raises(ValidationError):
        DaoNames.model_validate(data)


def test_fixed_random_collision_uses_bounded_indexed_batches_not_identity_cache(game):
    names = game[0].content.dao_names
    indexes = [0, *range(130, 259)]
    with closing(game[1].connect()) as conn:
        conn.executemany("INSERT INTO players(user_id, dao_name, stones) VALUES (?, ?, 0)",
                         ((f"occupied-{index}", names.name_at(index)) for index in indexes))
    queries = []
    assert generate(game, queries) == names.name_at(259)
    lookups = [query for query in queries if query.startswith("SELECT") and "players" in query]
    assert len(lookups) <= 5
    assert any(" IN (" in query for query in lookups)
    assert all("WHERE" in query or "COUNT(*)" in query for query in lookups)


def test_case_insensitive_manual_name_blocks_the_generated_candidate(game):
    original = game[0].content.dao_names
    data = original.model_dump()
    data["fields"]["qualities"][0] = "A"
    names = DaoNames.model_validate(data)
    game[0].content = replace(game[0].content, dao_names=names)
    sql(game[1], "INSERT INTO players(user_id, dao_name, stones) VALUES ('manual', ?, 0)",
        (names.name_at(0).lower(),))
    assert generate(game) == names.name_at(1)


def test_random_probe_retries_another_ordinal_without_loading_players(game):
    names = game[0].content.dao_names
    sql(game[1], "INSERT INTO players(user_id, dao_name, stones) VALUES ('occupied', ?, 0)",
        (names.name_at(0),))

    class SequenceRandom:
        calls = 0

        def randint(self, start, stop):
            assert (start, stop) == (0, names.capacity - 1)
            self.calls += 1
            return 0 if self.calls == 1 else stop

    rng = SequenceRandom()
    game[0].rng = rng
    queries = []
    assert generate(game, queries) == names.name_at(names.capacity - 1)
    assert rng.calls == 2
    assert not any("COUNT(*)" in query for query in queries)


def test_random_repeated_collisions_stop_after_sixteen_draws(game):
    names = game[0].content.dao_names
    sql(game[1], "INSERT INTO players(user_id, dao_name, stones) VALUES ('occupied', ?, 0)",
        (names.name_at(0),))

    class RepeatedRandom:
        calls = 0

        def randint(self, start, stop):
            self.calls += 1
            assert self.calls <= 16
            return 0

    rng = RepeatedRandom()
    game[0].rng = rng
    assert generate(game) == names.name_at(1)
    assert rng.calls == 16


def test_fallback_respects_case_insensitive_collision_and_wraps_ordinals(game):
    names = DaoNames.model_construct(fields={"first": ["A", "玄"], "second": ["云", "月"]},
                                    templates=[["first", "second"]])
    game[0].content = replace(game[0].content, dao_names=names)
    with closing(game[1].connect()) as conn:
        conn.executemany("INSERT INTO players(user_id, dao_name, stones) VALUES (?, ?, 0)", [
            ("occupied-first", names.name_at(0).lower()),
            ("occupied-last", names.name_at(3)),
            ("manual-name", "自拟道号"),
        ])
    queries = []
    assert generate(game, queries) == names.name_at(1)
    assert any(" IN (" in query and "a云" not in query and "A云" in query for query in queries)


def test_exhausted_test_space_rejects_without_a_numeric_or_id_suffix(game):
    names = DaoNames.model_construct(fields={"first": ["青", "玄"], "second": ["云", "月"]},
                                    templates=[["first", "second"]])
    game[0].content = replace(game[0].content, dao_names=names)
    with closing(game[1].connect()) as conn:
        conn.executemany("INSERT INTO players(user_id, dao_name, stones) VALUES (?, ?, 0)",
                         ((f"occupied-{index}", names.name_at(index)) for index in range(names.capacity)))
    with pytest.raises(GameError, match="道号.*用尽|道号.*可用"):
        generate(game)
    assert len(sql(game[1], "SELECT dao_name FROM players")) == 4


def test_seeded_generation_varies_lengths_titles_and_components(game, play):
    game[0].rng = random.Random(7821)
    for index in range(80):
        play("adopt", "青鸾", user=f"private-style-{index}")
    names = [row["dao_name"] for row in sql(game[1], "SELECT dao_name FROM players")]
    assert len(set(names)) == 80
    assert {len(name) for name in names} == {6, 8}
    assert len({name[-2:] for name in names}) >= 20
    assert len({name[:2] for name in names}) >= 40
    assert all("private" not in name and not any(char.isdigit() for char in name) for name in names)


def test_concurrent_adoption_remains_unique_and_hides_platform_ids(game):
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda index: game[0].execute(
            f"private-platform-{index}", "adopt", "青鸾", f"create-{index}", 1800000000,
        ), range(24)))
    names = [row["dao_name"] for row in sql(game[1], "SELECT dao_name FROM players")]
    assert len(names) == len(set(names)) == 24
    assert all("private-platform" not in reply.text() for reply in replies)
    with pytest.raises(sqlite3.IntegrityError):
        sql(game[1], "INSERT INTO players(user_id, dao_name, stones) VALUES ('duplicate', ?, 0)", (names[0],))
