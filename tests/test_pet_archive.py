from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql


def pet_ids(game, user="u1"):
    return [row["pet_id"] for row in sql(
        game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,),
    )]


def test_archive_preserves_pet_history_and_can_be_restored(game, play):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    play("summon")
    archived_id = pet_ids(game)[1]
    sql(game[1], "UPDATE pets SET species_id='xuanhu', name='藏灵', realm=6, layer=8, exp=4321 WHERE pet_id=?",
        (archived_id,))
    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, 'weapon', 'wind_feather', 4)",
        (archived_id,))
    sql(game[1], "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) "
                 "VALUES (?, 'wind_slash', 0, 3, 15)", (archived_id,))
    before_equipment = sql(game[1], "SELECT * FROM equipment WHERE pet_id=?", (archived_id,))
    before_skills = sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (archived_id,))

    archived = play("pet_archive", str(archived_id), op="archive-pet")

    assert archived.title == "灵宠封存"
    assert play("pet_archive", str(archived_id), op="archive-pet") == archived
    assert sql(game[1], "SELECT archived, realm, layer, exp FROM pets WHERE pet_id=?", (archived_id,)) == [
        {"archived": 1, "realm": 6, "layer": 8, "exp": 4321},
    ]
    assert sql(game[1], "SELECT * FROM equipment WHERE pet_id=?", (archived_id,)) == before_equipment
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (archived_id,)) == before_skills
    assert player(game[1])["active_pet_id"] == active_id
    assert "玄狐 · 已拥有" in play("collection").text()
    assert "藏灵" not in play("rank").text()
    with pytest.raises(GameError, match="已封存"):
        play("switch", str(archived_id))

    archive_page = play("pet_archive_list")
    assert f"编号 {archived_id}：藏灵" in archive_page.text()
    assert f"灵宠复原 {archived_id}" in archive_page.commands
    assert "封存 1 只" in play("pet_list").text()

    restored = play("pet_restore", str(archived_id), op="restore-pet")
    assert restored.title == "灵宠复原"
    assert play("pet_restore", str(archived_id), op="restore-pet") == restored
    assert sql(game[1], "SELECT archived FROM pets WHERE pet_id=?", (archived_id,)) == [{"archived": 0}]
    assert sql(game[1], "SELECT * FROM equipment WHERE pet_id=?", (archived_id,)) == before_equipment
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (archived_id,)) == before_skills
    assert player(game[1])["active_pet_id"] == active_id


def test_archive_frees_hatching_capacity_but_restore_needs_an_open_slot(game, play):
    play("adopt", "青鸾")
    game[0].config.spirit_pet_max_pets = 2
    play("summon")
    archived_id = pet_ids(game)[1]
    egg = next(item for item in game[0].content.items.values() if item.kind == "pet_egg")
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, 1)", (egg.id,))

    play("pet_archive", str(archived_id))
    hatched = play("use", egg.id)
    assert hatched.title == "灵卵孵化"
    new_id = pet_ids(game)[-1]
    assert len(pet_ids(game)) == 3
    with pytest.raises(GameError, match="名额已满"):
        play("pet_restore", str(archived_id))

    play("pet_archive", str(new_id))
    play("pet_restore", str(archived_id))
    assert sql(game[1], "SELECT COUNT(*) AS count FROM pets WHERE user_id='u1' AND archived=0") == [
        {"count": 2},
    ]
    assert sql(game[1], "SELECT archived FROM pets WHERE pet_id=?", (new_id,)) == [{"archived": 1}]


def test_active_or_unsettled_expedition_pets_cannot_be_archived(game, play):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    with pytest.raises(GameError, match="出战灵宠"):
        play("pet_archive", str(active_id))

    play("summon")
    other_id = pet_ids(game)[1]
    play("expedition_start", "采灵药")
    play("switch", str(other_id))
    before = sql(game[1], "SELECT archived FROM pets WHERE pet_id=?", (active_id,))
    with pytest.raises(GameError, match="未结行程"):
        play("pet_archive", str(active_id))
    assert sql(game[1], "SELECT archived FROM pets WHERE pet_id=?", (active_id,)) == before == [
        {"archived": 0},
    ]


def test_concurrent_restore_never_exceeds_roster_limit(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    game[0].config.spirit_pet_max_pets = 3
    play("summon", "2")
    ids = pet_ids(game)
    play("pet_archive", str(ids[1]))
    play("pet_archive", str(ids[2]))
    game[0].config.spirit_pet_max_pets = 2

    def restore(pet_id):
        try:
            game[0].execute("u1", "pet_restore", str(pet_id), f"restore-{pet_id}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(restore, ids[1:])) == 1
    assert sql(game[1], "SELECT COUNT(*) AS count FROM pets WHERE user_id='u1' AND archived=0") == [
        {"count": 2},
    ]
    assert sql(game[1], "SELECT COUNT(*) AS count FROM pets WHERE user_id='u1' AND archived=1") == [
        {"count": 1},
    ]
