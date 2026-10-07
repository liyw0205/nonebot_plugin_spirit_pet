import json

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql
from .test_arena_matching import NOW, register


def test_report_is_immutable_after_rename_and_loadout_changes(game, play):
    register(game, play)
    attacker_pet_id = pet(game[1], "private-0")["pet_id"]
    sql(game[1], "INSERT INTO equipment(pet_id,slot,item_id) VALUES (?,'weapon','wind_feather')", (attacker_pet_id,))
    sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'wind_slash',1)",
        (attacker_pet_id,))
    result = play("pvp", "道友01", user="private-0", now=NOW, op="report-once")
    row = sql(game[1], "SELECT battle_id,snapshot,battle_log FROM battle_records")[0]
    snapshot = json.loads(row["snapshot"])
    assert snapshot["version"] == 2
    assert snapshot["scenario"] == {"id": "2028-01", "name": "2028-01 赛季"}
    assert snapshot["teams"][0]["members"][0]["dao_name"] == "道友00"
    assert snapshot["teams"][1]["members"][0]["dao_name"] == "道友01"
    assert snapshot["teams"][0]["members"][0]["realm_name"]
    assert snapshot["teams"][0]["members"][0]["layer"] == 1
    assert snapshot["teams"][0]["members"][0]["bloodline_name"]
    assert snapshot["teams"][0]["members"][0]["skills"][0]["name"]
    assert snapshot["teams"][0]["members"][0]["equipment"][0]["enhancement"] == 0
    history = play("battle_reports", user="private-0", now=NOW + 1)
    assert "论剑 · 2028-01 赛季" in history.text()
    sql(game[1], "UPDATE pets SET name='全新宠名' WHERE pet_id=?", (attacker_pet_id,))
    sql(game[1], "UPDATE learned_skills SET equipped=0,level=4,proficiency=99 WHERE pet_id=?", (attacker_pet_id,))
    sql(game[1], "DELETE FROM equipment WHERE pet_id=?", (attacker_pet_id,))
    play("dao_name", "改名后的道号", user="private-1", now=NOW + 1)
    detail = play("battle_reports", f"查看 {row['battle_id']}", user="private-0", now=NOW + 1)
    assert "道友01" in detail.text()
    assert "场景：2028-01 赛季" in detail.text()
    assert "改名后的道号" not in detail.text()
    assert "全新宠名" not in detail.text()
    assert "风刃术" in detail.text()
    assert "青岚翎" in detail.text()
    assert result.title == "论剑结算"
    assert json.loads(row["battle_log"])


def test_report_detail_requires_participation_and_survives_team_leave(game, play):
    register(game, play)
    report = play("spar", "道友01", user="private-0", now=NOW, op="spar-report")
    battle_id = sql(game[1], "SELECT battle_id FROM battle_records WHERE kind='spar'")[0]["battle_id"]
    play("team_create", user="private-0", now=NOW + 1)
    play("team_join", "道友00", user="private-1", now=NOW + 1)
    play("team_accept", "道友01", user="private-0", now=NOW + 1)
    play("team_leave", user="private-1", now=NOW + 1)
    assert play("battle_reports", f"查看 {battle_id}", user="private-1", now=NOW + 2).title.startswith("战报 #")
    with pytest.raises(GameError, match="不是该场战斗的参与者"):
        play("battle_reports", f"查看 {battle_id}", user="private-2", now=NOW + 2)
    assert report.title == "切磋结算"


def test_report_operation_is_idempotent_and_history_paginates(game, play):
    register(game, play)
    for index in range(6):
        play("spar", "道友01", user="private-0", now=NOW + index, op=f"spar-{index}")
    first = play("battle_reports", user="private-0", now=NOW + 10)
    second = play("battle_reports", "分页 2", user="private-0", now=NOW + 10)
    assert first.title == "灵宠战报 1/2"
    assert second.title == "灵宠战报 2/2"
    assert len(sql(game[1], "SELECT * FROM battle_records WHERE kind='spar'")) == 6
    play("spar", "道友01", user="private-0", now=NOW + 20, op="spar-0")
    assert len(sql(game[1], "SELECT * FROM battle_records WHERE kind='spar'")) == 6
    with pytest.raises(GameError, match="页"):
        play("battle_reports", "分页 3", user="private-0", now=NOW + 10)


def test_pve_and_team_battle_reports_keep_each_participant_permission(game, play):
    register(game, play)
    play("team_create", user="private-0", now=NOW)
    play("team_join", "道友00", user="private-1", now=NOW)
    play("team_accept", "道友01", user="private-0", now=NOW)
    play("team_ready", user="private-0", now=NOW)
    play("team_ready", user="private-1", now=NOW)
    play("team_challenge", user="private-0", now=NOW, op="team-report")
    row = sql(game[1], "SELECT * FROM battle_records WHERE operation_id='team-report'")[0]
    participants = sql(game[1],
        "SELECT user_id,side,permission FROM battle_participants WHERE battle_id=? ORDER BY user_id",
        (row["battle_id"],),
    )
    assert participants == [
        {"user_id": "private-0", "side": 0, "permission": "participant"},
        {"user_id": "private-1", "side": 0, "permission": "participant"},
    ]
    play("team_leave", user="private-1", now=NOW + 1)
    detail = play("battle_reports", f"详情 {row['battle_id']}", user="private-1", now=NOW + 2)
    assert "秘境敌手" in detail.text()


def test_permanent_battle_operation_replay_after_cache_expiry(game, play):
    register(game, play)
    first = play("challenge", "青岚林", user="private-0", now=NOW, op="pve-permanent")
    battle_id = sql(game[1], "SELECT battle_id FROM battle_records WHERE operation_id='pve-permanent'")[0]["battle_id"]
    snapshot = json.loads(sql(game[1], "SELECT snapshot FROM battle_records WHERE battle_id=?", (battle_id,))[0]["snapshot"])
    assert snapshot["scenario"] == {"id": "forest", "name": "青岚林"}
    future = NOW + 8 * 86400
    play("status", user="private-0", now=future)
    before = pet(game[1], "private-0"), player(game[1], "private-0")
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='pve-permanent'")
    assert play("challenge", "unknown-now", user="private-0", now=future,
                op="pve-permanent") == first
    assert "场景：青岚林" in play(
        "battle_reports", f"查看 {battle_id}", user="private-0", now=future,
    ).text()
    assert (pet(game[1], "private-0"), player(game[1], "private-0")) == before
    with pytest.raises(GameError, match="different user"):
        play("status", user="private-1", now=future, op="pve-permanent")


def test_report_detail_pages_preserve_snapshot_and_full_combat_log(game, play):
    register(game, play)
    play("pvp", "道友01", user="private-0", now=NOW, op="paged-detail")
    row = sql(game[1], "SELECT battle_id FROM battle_records WHERE operation_id='paged-detail'")[0]
    battle_id = row["battle_id"]
    snapshot = json.loads(sql(game[1], "SELECT snapshot FROM battle_records WHERE battle_id=?", (battle_id,))[0]["snapshot"])
    legacy_snapshot = dict(snapshot)
    legacy_snapshot["version"] = 1
    legacy_snapshot.pop("scenario", None)
    sql(game[1], "UPDATE battle_records SET battle_log=? WHERE battle_id=?",
        (json.dumps([f"完整战斗事件 {i}" for i in range(20)], ensure_ascii=False), battle_id))
    sql(game[1], "UPDATE battle_records SET snapshot=? WHERE battle_id=?",
        (json.dumps(legacy_snapshot, ensure_ascii=False), battle_id))
    first = play("battle_reports", f"查看 {battle_id}", user="private-0", now=NOW + 1)
    second = play("battle_reports", f"详情 {battle_id} 2", user="private-0", now=NOW + 1)
    assert first.title.endswith("1/3")
    assert second.title.endswith("2/3")
    assert "场景：" not in first.text()
    assert "道友00" in first.text() and "道友00" in second.text()
    assert "完整战斗事件 19" in play(
        "battle_reports", f"详情 {battle_id} 3", user="private-0", now=NOW + 1,
    ).text()
    assert snapshot["teams"][0]["members"][0]["dao_name"] == "道友00"
