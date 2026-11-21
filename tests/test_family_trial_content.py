from copy import deepcopy

import pytest

from nonebot_plugin_spirit_pet.content import catalog
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR


def test_family_trial_rotation_and_reward_budget_are_bounded():
    content = Catalog.load()
    assert set(content.family_trial_rotation) == set(content.family_trials)
    assert len(content.family_trial_rotation) == len(content.family_trials)
    assert all(trial.weekly_runs == 1 for trial in content.family_trials.values())


@pytest.mark.parametrize("edit", [
    lambda d: d["rotation"].append(d["rotation"][0]),
    lambda d: d["rotation"].pop(),
    lambda d: d["rotation"].append("unknown"),
    lambda d: d["trials"].append(d["trials"][0]),
    lambda d: d["trials"][0].update(weekly_runs=2),
    lambda d: d["trials"][0].update(minimum_members=3, maximum_members=2),
    lambda d: d["trials"][0].update(energy=0),
    lambda d: d["trials"][0].update(stages=[]),
    lambda d: d["trials"][0]["stages"][0].update(enemy="missing"),
    lambda d: d["trials"][0]["stages"][0].update(max_rounds=41),
    lambda d: d["trials"][0]["stages"][0].update(hp_scale=0),
    lambda d: d["trials"][0]["stages"][0]["reward"].update(items={"egg_qingluan": {"minimum": 1, "maximum": 1}}),
    lambda d: d["trials"][0]["bonus"].update(items={"missing": {"minimum": 1, "maximum": 1}}),
    lambda d: d["trials"][0]["bonus"].update(stones={"minimum": 10001, "maximum": 10001}),
    lambda d: d["trials"][0]["stages"][0].update(reward={"exp": {"minimum": 0, "maximum": 0}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}),
])
def test_invalid_family_trial_content_is_rejected(monkeypatch, edit):
    original = catalog._read
    data = deepcopy(original(DATA_DIR / "family_trials.json"))
    edit(data)
    monkeypatch.setattr(catalog, "_read", lambda path: data if path.name == "family_trials.json" else original(path))
    with pytest.raises(ValueError):
        Catalog.load()
