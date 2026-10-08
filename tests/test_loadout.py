from contextlib import closing
import json

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, effectiveness, fight
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql


def stats(game):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, "u1", 1800000000, "read-stats")
        return combatant(ctx).stats


def rich(game, play, species="青鸾"):
    play("adopt", species)
    sql(game[1], "UPDATE players SET stones=10000")


def test_equipment_real_stats_and_no_duplication_on_replay(game, play):
    rich(game, play)
    before = stats(game)
    play("buy", "青岚翎")
    reply = play("equipment", "青岚翎", op="equip")
    assert play("equipment", "青岚翎", op="equip") == reply
    assert stats(game).attack == before.attack + 6
    assert stats(game).speed == before.speed + 5
    assert items(game[1])["wind_feather"] == 0
    with pytest.raises(GameError, match="已经装备"):
        play("equipment", "青岚翎")
    play("unequip", "灵器", op="unequip")
    play("unequip", "灵器", op="unequip")
    assert items(game[1])["wind_feather"] == 1
    assert stats(game) == before


def test_equipment_set_requires_all_pieces_and_adds_combat_bonus(game, play):
    rich(game, play)
    before = stats(game)
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    single = stats(game)
    assert single.attack == before.attack + 6
    assert "套装：青岚风铃 1/2 · 未激活" in play("equipment").text()

    play("buy", "灵心铃")
    play("equipment", "灵心铃")
    full = stats(game)
    assert full.attack == single.attack + 4
    assert full.speed == single.speed + 2 + 8
    assert "套装：青岚风铃 2/2 · 已激活" in play("equipment").text()
    assert "灵宠套装" in play("equipment").commands

    play("unequip", "饰品")
    assert stats(game) == single


def test_equipment_set_cannot_combine_pieces_across_pets(game, play):
    rich(game, play)
    play("buy", "青岚翎")
    play("buy", "灵心铃")
    play("equipment", "青岚翎")
    play("summon")
    second = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    play("switch", str(second))
    play("equipment", "灵心铃")
    assert "套装：青岚风铃 1/2 · 未激活" in play("equipment").text()


def test_equipment_set_catalog_and_battle_snapshot(game, play):
    rich(game, play)
    detail = play("equipment_sets", "青岚风铃")
    assert "青岚翎、灵心铃" in detail.text()
    assert "攻击 +4 速度 +8" in detail.text()
    page = play("equipment_sets")
    assert "青岚风铃" in page.text()

    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    play("buy", "灵心铃")
    play("equipment", "灵心铃")
    reply = play("challenge", "青岚林", op="set-battle")
    assert reply.title == "秘境获胜"
    row = sql(game[1], "SELECT snapshot FROM battle_records WHERE operation_id='set-battle'")[0]
    snapshot = json.loads(row["snapshot"])
    assert snapshot["teams"][0]["members"][0]["equipment_sets"] == ["青岚风铃"]
    detail = play("battle_reports", "查看 1")
    assert "套装 青岚风铃" in detail.text()


def test_element_and_species_category_equipment_restrictions(game, play):
    rich(game, play, "玄狐")
    play("buy", "青岚翎")
    play("buy", "龙鳞甲")
    with pytest.raises(GameError, match="元素不兼容"):
        play("equipment", "青岚翎")
    with pytest.raises(GameError, match="类别不兼容"):
        play("equipment", "龙鳞甲")
    assert items(game[1])["wind_feather"] == items(game[1])["dragon_scale"] == 1
    assert not sql(game[1], "SELECT * FROM equipment")


def test_swapping_and_multi_pet_ownership_cannot_copy_equipment(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET species_id='sanlinglu'")
    play("buy", "青岚翎")
    play("buy", "赤焰牙")
    play("equipment", "青岚翎")
    play("equipment", "赤焰牙")
    assert items(game[1])["wind_feather"] == 1
    assert items(game[1])["fire_fang"] == 0
    play("summon")
    second = sql(game[1], "SELECT MAX(pet_id) pet_id FROM pets")[0]["pet_id"]
    play("switch", str(second))
    play("equipment", "青岚翎")
    play("switch", "1")
    assert "赤焰牙" in play("equipment").text()
    with pytest.raises(GameError, match="不足"):
        play("equipment", "青岚翎")


def test_fire_pet_cannot_learn_water_and_book_is_not_lost(game, play):
    rich(game, play, "玄狐")
    play("buy", "水箭术诀")
    with pytest.raises(GameError, match="元素不兼容"):
        play("learn", "水箭术")
    assert items(game[1])["book_water_arrow"] == 1
    assert not sql(game[1], "SELECT * FROM learned_skills")


def test_three_element_pet_learns_each_and_requires_all_for_combo(game, play):
    rich(game, play)
    sql(game[1], "UPDATE pets SET species_id='sanlinglu'")
    for skill in ("风刃术", "赤焰术", "青木回春"):
        play("buy", skill + "诀")
        play("learn", skill)
    rows = sql(game[1], "SELECT * FROM learned_skills")
    assert len(rows) == 3
    assert sum(row["equipped"] for row in rows) == 2
    with pytest.raises(GameError, match="已满"):
        play("equip_skill", "青木回春")
    play("unequip_skill", "风刃术")
    play("equip_skill", "青木回春")
    play("buy", "风火燎原诀")
    with pytest.raises(GameError, match="境界"):
        play("learn", "风火燎原")
    sql(game[1], "UPDATE pets SET realm=1")
    play("learn", "风火燎原")
    assert len(sql(game[1], "SELECT * FROM learned_skills")) == 4


def test_composite_skill_not_allowed_with_just_one_required_element(game, play):
    rich(game, play, "玄狐")
    sql(game[1], "UPDATE pets SET realm=1")
    play("buy", "风火燎原诀")
    with pytest.raises(GameError, match="同时具备"):
        play("learn", "风火燎原")
    assert items(game[1])["book_windfire"] == 1


def test_skill_replay_and_duplicate_learning_do_not_consume_extra_books(game, play):
    rich(game, play)
    play("buy", "风刃术诀 2")
    first = play("learn", "风刃术", op="learn")
    assert play("learn", "风刃术", op="learn") == first
    with pytest.raises(GameError, match="已经学会"):
        play("learn", "风刃术")
    assert items(game[1])["book_wind_slash"] == 1


def test_equipment_and_skill_changes_invalidate_team_readiness(game, play):
    rich(game, play)
    play("team_create")
    play("team_ready")
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None
    play("team_ready")
    play("buy", "风刃术诀")
    play("learn", "风刃术")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


def test_learned_skill_reaches_real_pve_combat(game, play):
    rich(game, play)
    play("buy", "风刃术诀")
    play("learn", "风刃术")
    reply = play("challenge", "青岚林")
    assert "施展风刃术" in reply.text()


def test_elemental_matchups_and_healing_are_active(game):
    service = game[0]
    elements = service.content.elements
    assert effectiveness("fire", "metal", elements) == 1.25
    assert effectiveness("fire", "water", elements) == 0.8
    assert effectiveness(None, "water", elements) == 1
    skill = service.content.skills["wood_heal"]
    base = service.content.species["qingluan"].stats
    healer = Fighter.create("healer", base, ("wood",), (skill,))
    healer.hp = 60
    enemy = Fighter.create("enemy", base, ("earth",))
    result = fight([healer], [enemy], service.rng, elements)
    assert any("施展青木回春" in line and "恢复" in line for line in result.lines)
