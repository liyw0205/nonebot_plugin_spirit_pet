from copy import deepcopy
from types import SimpleNamespace

import pytest

from nonebot_plugin_spirit_pet.content import catalog
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.gameplay.family_duel import current_duel
from nonebot_plugin_spirit_pet.utils.time import beijing_week


def test_weekly_duel_rotation_and_rating_contracts_are_bounded():
    content = Catalog.load()
    assert set(content.family_duel_rotation) == set(content.family_duels)
    assert len(content.family_duel_rotation) == 3
    for duel in content.family_duels.values():
        assert duel.ratings[1].max_rounds < duel.ratings[0].max_rounds
        assert duel.ratings[1].require_both_alive
        assert duel.max_rounds <= 40


def test_beijing_week_rotation_visits_each_duel_once_then_repeats():
    content = Catalog.load()
    start = beijing_week(1_800_000_000)[0]
    context = SimpleNamespace(content=content, now=start)
    ids = [current_duel(context, start + 7 * 86400 * index).id for index in range(4)]
    assert len(set(ids[:3])) == 3
    assert ids[3] == ids[0]


@pytest.mark.parametrize("edit", [
    lambda d: d["rotation"].append(d["rotation"][0]),
    lambda d: d["rotation"].pop(),
    lambda d: d["duels"][0].update(enemies=["missing"]),
    lambda d: d["duels"][0].update(max_rounds=41),
    lambda d: d["duels"][0]["ratings"][1].update(max_rounds=30),
    lambda d: d["duels"][0]["ratings"][1].update(require_both_alive=False),
    lambda d: d["duels"][0]["ratings"][1]["reward"].update(
        items={"egg_qingluan": {"minimum": 1, "maximum": 1}},
    ),
    lambda d: d["duels"][0]["ratings"][1]["reward"].update(
        stones={"minimum": 1, "maximum": 1},
    ),
])
def test_invalid_family_duel_content_is_rejected_at_catalog_load(monkeypatch, edit):
    original = catalog._read
    data = deepcopy(original(DATA_DIR / "family_duels.json"))
    edit(data)
    monkeypatch.setattr(catalog, "_read", lambda path: data if path.name == "family_duels.json" else original(path))
    with pytest.raises(ValueError):
        Catalog.load()
