import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.state import Pet
from nonebot_plugin_spirit_pet.gameplay.combat import pet_stats
from nonebot_plugin_spirit_pet.gameplay.lineage import stat_multipliers

from .support import items, pet, player, sql
from .test_loadout import stats


@pytest.fixture
def lineage_dir(tmp_path):
    directory = tmp_path / "content"
    shutil.copytree(DATA_DIR, directory)
    return directory


def edit(directory, change):
    path = directory / "lineages.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def prepare(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    sql(game[1], "UPDATE pets SET exp=10000, bloodline=1")
    sql(game[1], "INSERT INTO inventory VALUES ('u1', 'bloodline_essence', 100)")


def state(game):
    return player(game[1]), pet(game[1]), items(game[1])


def test_each_species_has_two_distinct_branches_with_tradeoffs():
    content = Catalog.load()
    count = Counter(lineage.species_id for lineage in content.lineages.values())
    assert len(content.lineages) == 54
    assert count == {species: 2 for species in content.species}
    for species in content.species:
        choices = [branch for branch in content.lineages.values() if branch.species_id == species]
        left, right = [branch.stat_multipliers.model_dump() for branch in choices]
        assert any(left[key] > right[key] for key in left)
        assert any(right[key] > left[key] for key in left)
        assert all(branch.min_bloodline == 1 for branch in choices)


def test_lineage_catalog_can_inspect_species_before_adoption(game, play):
    reply = play("lineage_catalog", "青鸾")
    assert "凌风鸾脉" in reply.text()
    assert "青木鸾脉" in reply.text()
    assert "不可更换" in reply.text()
    assert reply.commands == ("灵宠图鉴 青鸾",)
    with pytest.raises(GameError, match="尚未结契"):
        play("lineage_catalog")
    play("adopt", "青鸾")
    assert pet(game[1])["lineage_id"] is None
    assert stat_multipliers(Pet(**pet(game[1])), game[0].content).model_dump() == {
        "hp": 1, "attack": 1, "defense": 1, "speed": 1,
    }


@pytest.mark.parametrize("argument", ["", "青鸾", "qingluan"])
def test_lineage_catalog_offers_only_available_current_pet_choices(game, play, argument):
    prepare(game, play)
    reply = play("lineage_catalog", argument)
    assert set(reply.commands) == {"灵宠分支 凌风鸾脉", "灵宠分支 青木鸾脉"}
    play("lineage_choose", "凌风鸾脉")
    reply = play("lineage_catalog", argument)
    assert "凌风鸾脉（已选）" in reply.text()
    assert reply.commands == ("灵宠图鉴 青鸾", "我的灵宠")


def test_other_species_catalog_never_offers_an_invalid_branch_button(game, play):
    prepare(game, play)
    reply = play("lineage_catalog", "玄狐")
    assert "夜焰狐脉" in reply.text()
    assert reply.commands == ("灵宠图鉴 玄狐", "我的灵宠")


@pytest.mark.parametrize("statement", [
    "UPDATE pets SET bloodline=0", "UPDATE pets SET exp=0", "UPDATE players SET stones=0",
    "UPDATE inventory SET quantity=0 WHERE item_id='bloodline_essence'",
])
def test_unmet_branch_requirement_catalog_only_offers_queries(game, play, statement):
    prepare(game, play)
    sql(game[1], statement)
    assert play("lineage_catalog").commands == ("灵宠图鉴 青鸾", "我的灵宠")


def test_choose_lineage_charges_once_and_persists_stat_tradeoff(game, play):
    prepare(game, play)
    before_player, before_pet, before_items = state(game)
    base = pet_stats(Pet(**before_pet), game[0].content)
    branch = game[0].content.lineages["qingluan_lingfeng"]
    reply = play("lineage_choose", branch.name, op="choose-lineage")
    assert play("lineage_choose", branch.name, op="choose-lineage") == reply
    after_player, after_pet, after_items = state(game)
    assert after_pet["lineage_id"] == branch.id
    assert after_player["stones"] == before_player["stones"] - branch.cost.stones
    assert after_pet["exp"] == before_pet["exp"] - branch.cost.exp
    assert after_items["bloodline_essence"] == before_items["bloodline_essence"] - 3
    after = pet_stats(Pet(**after_pet), game[0].content)
    assert after.speed > base.speed
    assert after.attack > base.attack
    assert after.defense < base.defense
    assert "凌风鸾脉（已选）" in play("lineage_catalog").text()
    assert "凌风鸾脉" in play("status").text()


@pytest.mark.parametrize("argument,error", [
    ("", "指定"), ("不存在", "未找到"), ("夜焰狐脉", "不属于"),
])
def test_invalid_branch_selection_never_charges(game, play, argument, error):
    prepare(game, play)
    before = state(game)
    with pytest.raises(GameError, match=error):
        play("lineage_choose", argument)
    assert state(game) == before


def test_bloodline_requirement_and_locked_choice(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE pets SET bloodline=0")
    before = state(game)
    with pytest.raises(GameError, match="灵血"):
        play("lineage_choose", "凌风鸾脉")
    assert state(game) == before
    sql(game[1], "UPDATE pets SET bloodline=1")
    play("lineage_choose", "凌风鸾脉")
    before = state(game)
    for name in ("凌风鸾脉", "青木鸾脉"):
        with pytest.raises(GameError, match="不能重复"):
            play("lineage_choose", name)
        assert state(game) == before


@pytest.mark.parametrize("statement", [
    "UPDATE pets SET exp=0", "UPDATE players SET stones=0",
    "UPDATE inventory SET quantity=0 WHERE item_id='bloodline_essence'",
])
def test_insufficient_resources_roll_back(game, play, statement):
    prepare(game, play)
    sql(game[1], statement)
    before = state(game)
    with pytest.raises(GameError):
        play("lineage_choose", "凌风鸾脉")
    assert state(game) == before


def test_late_missing_material_rolls_back_earlier_material(game, play):
    prepare(game, play)
    content = game[0].content
    branches = dict(content.lineages)
    old = branches["qingluan_lingfeng"]
    branches[old.id] = old.model_copy(update={"cost": old.cost.model_copy(update={
        "items": {"bloodline_essence": 3, "forge_ore": 99},
    })})
    game[0].content = replace(content, lineages=branches)
    before = state(game)
    with pytest.raises(GameError, match="不足"):
        play("lineage_choose", old.name)
    assert state(game) == before


def test_lineage_preserves_loadout_and_does_not_multiply_equipment(game, play):
    prepare(game, play)
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    play("buy", "风刃术诀")
    play("learn", "风刃术")
    worn = sql(game[1], "SELECT * FROM equipment")
    learned = sql(game[1], "SELECT * FROM learned_skills")
    template = game[0].content.species["qingluan"]
    play("lineage_choose", "青木鸾脉")
    assert sql(game[1], "SELECT * FROM equipment") == worn
    assert sql(game[1], "SELECT * FROM learned_skills") == learned
    assert game[0].content.species["qingluan"] == template
    base = pet_stats(Pet(**pet(game[1])), game[0].content)
    combined = stats(game)
    assert combined.attack == base.attack + 6
    assert combined.speed == base.speed + 5
    play("evolve")
    assert pet(game[1])["lineage_id"] == "qingluan_qingmu"
    assert pet(game[1])["bloodline"] == 2
    assert pet(game[1])["species_id"] == "qingluan"
    assert sql(game[1], "SELECT * FROM learned_skills") == learned


def test_lineage_is_per_pet_and_invalidates_team_readiness(game, play):
    prepare(game, play)
    first = pet(game[1])["pet_id"]
    play("team_create")
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] == first
    play("lineage_choose", "凌风鸾脉")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None
    play("summon")
    pets = sql(game[1], "SELECT pet_id, lineage_id FROM pets ORDER BY pet_id")
    assert pets[0]["lineage_id"] == "qingluan_lingfeng"
    assert pets[1]["lineage_id"] is None
    play("switch", str(pets[1]["pet_id"]))
    sql(game[1], "UPDATE pets SET bloodline=1, exp=1000 WHERE pet_id=?", (pets[1]["pet_id"],))
    play("lineage_choose", "青木鸾脉")
    assert pet(game[1])["lineage_id"] == "qingluan_qingmu"
    play("switch", str(first))
    assert pet(game[1])["lineage_id"] == "qingluan_lingfeng"


def test_concurrent_distinct_operations_choose_only_once(game, play):
    prepare(game, play)
    before = state(game)

    def choose(index):
        try:
            return game[0].execute("u1", "lineage_choose", "凌风鸾脉", f"branch-{index}", 1800000000)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(choose, range(4)))
    assert sum(reply is not None for reply in replies) == 1
    assert player(game[1])["stones"] == before[0]["stones"] - 300
    assert items(game[1])["bloodline_essence"] == before[2]["bloodline_essence"] - 3


@pytest.mark.parametrize("branch,bloodline", [
    ("unknown", 1), ("xuanhu_yeyan", 1), ("qingluan_lingfeng", 0),
])
def test_invalid_persisted_branch_refuses_instead_of_applying_wrong_stats(game, play, branch, bloodline):
    prepare(game, play)
    runtime = Pet(**pet(game[1]))
    runtime.lineage_id = branch
    runtime.bloodline = bloodline
    with pytest.raises(GameError, match="分支数据无效"):
        pet_stats(runtime, game[0].content)


@pytest.mark.parametrize("change,error", [
    (lambda rows: rows.pop(0), "at least two"),
    (lambda rows: rows[0].update(species_id="unknown"), "lineage species"),
    (lambda rows: rows[0].update(min_bloodline=10), "lineage bloodline"),
    (lambda rows: rows[0].update(min_bloodline=0), "min_bloodline"),
    (lambda rows: rows[0].update(cost={"exp": 0, "stones": 0, "items": {}}), "have a cost"),
    (lambda rows: rows[0]["cost"].update(items={"unknown": 1}), "lineage cost"),
    (lambda rows: rows[0]["cost"].update(items={"spirit_food": 1}), "materials"),
    (lambda rows: rows[0].update(stat_multipliers={}), "improve"),
    (lambda rows: rows[1].update(stat_multipliers=rows[0]["stat_multipliers"]), "distinct stat"),
    (lambda rows: rows[0]["stat_multipliers"].update(attack=3), "attack"),
])
def test_lineage_content_validation(lineage_dir, change, error):
    edit(lineage_dir, change)
    with pytest.raises(ValueError, match=error):
        Catalog.load(lineage_dir)


@pytest.mark.parametrize("field", ["selected_at", "owner_id", "cooldown", "primary_element"])
def test_lineage_definitions_reject_runtime_and_element_mutations(lineage_dir, field):
    edit(lineage_dir, lambda rows: rows[0].update({field: 1}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(lineage_dir)
