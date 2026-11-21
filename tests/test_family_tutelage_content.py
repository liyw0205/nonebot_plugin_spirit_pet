from copy import deepcopy

import pytest

from nonebot_plugin_spirit_pet.content import catalog
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR


def test_four_courses_reuse_existing_skills_materials_and_bounded_rewards():
    content = Catalog.load()
    assert {course.skill for course in content.family_tutelage.values()} == {
        "wind_slash", "fireball", "water_arrow", "wood_heal",
    }
    assert content.family_tutelage_rules.lessons == 2
    assert content.family_tutelage_rules.interval == 600
    for course in content.family_tutelage.values():
        assert course.proficiency <= 20
        assert all(content.items[key].kind == "material" for key in course.lesson_materials)


@pytest.mark.parametrize("edit", [
    lambda d: d["courses"].append(d["courses"][0]),
    lambda d: d["courses"].pop(),
    lambda d: d["courses"][0].update(skill="missing"),
    lambda d: d["courses"][0].update(enemy="missing"),
    lambda d: d["courses"][0].update(parent_level=5),
    lambda d: d["courses"][0].update(lesson_energy=0),
    lambda d: d["courses"][0].update(lesson_stones=True),
    lambda d: d["courses"][0].update(lesson_materials={"missing": 1}),
    lambda d: d["courses"][0].update(lesson_materials={"egg_qingluan": 1}),
    lambda d: d["courses"][0].update(lesson_materials={"energy_pill": 1}),
    lambda d: d["courses"][0].update(lesson_materials={"forge_ore": 0}),
    lambda d: d["courses"][0].update(proficiency=21),
    lambda d: d["courses"][0].update(max_rounds=41),
    lambda d: d["rules"].update(lessons=3),
    lambda d: d["rules"].update(interval=0),
    lambda d: d["rules"].update(duration=1),
    lambda d: d["rules"].update(attempts=4),
    lambda d: d["rules"].update(weekly_starts=4),
])
def test_invalid_tutelage_content_fails_at_catalog_load(monkeypatch, edit):
    original = catalog._read
    data = deepcopy(original(DATA_DIR / "family_tutelage.json"))
    edit(data)
    monkeypatch.setattr(catalog, "_read", lambda path: data if path.name == "family_tutelage.json" else original(path))
    with pytest.raises(ValueError):
        Catalog.load()
