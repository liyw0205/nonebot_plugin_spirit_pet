from copy import deepcopy
from itertools import product

import pytest

from nonebot_plugin_spirit_pet.content import catalog
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR


def test_three_routes_have_complete_stories_and_all_bounded_reward_paths():
    content = Catalog.load()
    definitions = content.family_outings
    paths = list(product(definitions.choices, repeat=3))
    gains = set()
    for path in paths:
        score = sum(choice.rapport for choice in path)
        gains.add(max((tier for tier in definitions.tiers if tier.rapport <= score), key=lambda tier: tier.rapport).bond_exp)
        assert sum(choice.parent_energy for choice in path) <= 24
        assert sum(choice.child_energy for choice in path) <= 24
    assert gains == {8, 12, 16}
    assert len(paths) == 27
    assert {route.scene for route in definitions.routes} == {"brook", "grove", "ridge"}
    for route in definitions.routes:
        for stage in route.stages:
            for outcome in stage.outcomes.values():
                assert "亲本" in outcome.format(parent="亲本", child="后代")


@pytest.mark.parametrize("edit", [
    lambda d: d["routes"].pop(),
    lambda d: d["routes"].append(d["routes"][0]),
    lambda d: d["routes"][0].update(scene="missing"),
    lambda d: d["routes"][0]["stages"].pop(),
    lambda d: d["routes"][0]["stages"][0].update(text="    "),
    lambda d: d["routes"][0]["stages"][0].update(text="{stranger}在散步"),
    lambda d: d["routes"][0]["stages"][0].update(text="{parent.name}在散步"),
    lambda d: d["routes"][0]["stages"][0].update(text="{parent!r}在散步"),
    lambda d: d["routes"][0]["stages"][0].update(text="{parent:>1000}在散步"),
    lambda d: d["routes"][0]["stages"][0].update(text="{parent在散步"),
    lambda d: d["routes"][0]["stages"][0]["outcomes"].pop("guide"),
    lambda d: d["routes"][0]["stages"][0]["outcomes"].update(guide="    "),
    lambda d: d["routes"][0]["stages"][1].update(name=d["routes"][0]["stages"][0]["name"]),
    lambda d: d["choices"][0].update(id="rest"),
    lambda d: d["choices"][0].update(parent_energy=0),
    lambda d: d["choices"][0].update(child_energy=9),
    lambda d: d["choices"][0].update(food=True),
    lambda d: d["choices"][0].update(rapport=4),
    lambda d: [choice.update(food=1) for choice in d["choices"]],
    lambda d: d.update(food_item="energy_pill"),
    lambda d: d["tiers"][0].update(rapport=1),
    lambda d: d["tiers"][1].update(rapport=0),
    lambda d: d["tiers"][1].update(bond_exp=8),
    lambda d: d["tiers"][2].update(bond_exp=17),
    lambda d: d["tiers"][1].update(rapport=1),
    lambda d: [choice.update(rapport=1) for choice in d["choices"]],
    lambda d: d["rules"].update(weekly_starts=3),
    lambda d: d["rules"].update(duration=604800),
])
def test_bad_family_outing_content_fails_at_catalog_load(monkeypatch, edit):
    original = catalog._read
    data = deepcopy(original(DATA_DIR / "family_outings.json"))
    edit(data)
    monkeypatch.setattr(catalog, "_read", lambda path: data if path.name == "family_outings.json" else original(path))
    with pytest.raises(ValueError):
        Catalog.load()
