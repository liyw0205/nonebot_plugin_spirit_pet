import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR


@pytest.fixture
def stage_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit(directory, change):
    path = directory / "stages.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_stage_catalog_is_ordered_linear_and_has_solo_and_team_chapters():
    content = Catalog.load()
    ordered = sorted(content.stages.values(), key=lambda stage: stage.order)
    assert len(ordered) >= 8
    assert [stage.order for stage in ordered] == list(range(1, len(ordered) + 1))
    assert ordered[0].previous_id is None
    assert all(stage.previous_id == ordered[index - 1].id for index, stage in enumerate(ordered[1:], 1))
    assert any(stage.team for stage in ordered)
    assert any(not stage.team for stage in ordered)
    assert all(set(stage.model_dump()) == {
        "id", "name", "description", "order", "min_realm", "enemies", "energy", "reward", "team", "previous_id",
    } for stage in ordered)


@pytest.mark.parametrize("field", [
    "created_at", "started_at", "finishes_at", "owner_id", "pet_id", "state", "progress",
    "first_cleared_at", "cooldown", "reward_snapshot",
])
def test_static_stage_definition_rejects_runtime_state_and_time_fields(stage_dir, field):
    edit(stage_dir, lambda rows: rows[0].update({field: 123}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(stage_dir)


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows[0].update(min_realm="unknown"), "unknown stage realm"),
    (lambda rows: rows[0].update(enemies=["unknown"]), "unknown stage enemies"),
    (lambda rows: rows[0]["reward"]["items"].update(unknown={"minimum": 1, "maximum": 1}),
     "unknown stage reward items"),
    (lambda rows: rows[1].update(previous_id="unknown"), "unknown stage prerequisite"),
    (lambda rows: rows[1].update(previous_id="stage_08"), "stage previous_id"),
    (lambda rows: rows[1].update(order=4), "stage orders must be contiguous"),
])
def test_invalid_stage_references_or_progression_are_rejected(stage_dir, change, match):
    edit(stage_dir, change)
    with pytest.raises(ValueError, match=match):
        Catalog.load(stage_dir)


@pytest.mark.parametrize("field", ["team", "order", "energy", "previous_id"])
def test_stage_definitions_reject_invalid_types(stage_dir, field):
    values = {"team": "yes", "order": True, "energy": "15", "previous_id": 123}
    edit(stage_dir, lambda rows: rows[0].update({field: values[field]}))
    with pytest.raises(ValidationError):
        Catalog.load(stage_dir)
