"""Lineup coverage gaps for the 1-3 pet battle roster (active_pet_slots).

Existing coverage lives in ``test_multi_pet_lineup.py`` (roster writes, per-pet
energy, one reward set) and ``test_lineup_settlement.py`` (team reward shape,
realm gate).  This module adds the boundaries those files do not touch: message
replay, whole-lineup rollback, shared PVE cooldown edges, expedition occupancy
of a non-leading slot, roster validation, ready invalidation, the five-pet team
cap, report snapshots and the free spar path.
"""

import json
from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import adventure, pve_stages
from nonebot_plugin_spirit_pet.gameplay.arena import battles as arena_battles
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql
from .test_battles import setup_team, two_players
from .test_lineup_settlement import roster

NOW = 1_800_000_000
DURATION = 3600
SPECIES = ("qingluan", "xuanhu", "baize")
# One damage skill that every species in SPECIES can actually carry.
SKILL_BY_SPECIES = {"qingluan": "wind_slash", "xuanhu": "fireball", "baize": "metal_edge"}


def label(store, pet_ids, prefix):
    """Rename pets so battle logs and error texts identify a roster slot."""
    for index, pet_id in enumerate(pet_ids):
        sql(store, "UPDATE pets SET name=? WHERE pet_id=?", (f"{prefix}{index + 1}", pet_id))


def teach(store, pet_ids):
    """Give each pet one equipped skill, so proficiency writes stay observable."""
    for pet_id, species_id in zip(pet_ids, SPECIES):
        sql(store, "INSERT INTO learned_skills(pet_id, skill_id, level, proficiency, equipped) "
                   "VALUES (?, ?, 1, 0, 1)", (pet_id, SKILL_BY_SPECIES[species_id]))


def armed_roster(game, play, user="u1", tag="甲", realm=None):
    """Three distinct-species pets at full energy, named, skilled and optionally levelled."""
    pet_ids = roster(game, play, user)
    label(game[1], pet_ids, tag)
    teach(game[1], pet_ids)
    if realm is not None:
        sql(game[1], "UPDATE pets SET realm=? WHERE pet_id IN (?,?,?)", (realm, *pet_ids))
    return pet_ids


def dispatch(store, user, pet_id, now=NOW):
    """Record a running expedition, the same row expeditions.start would leave."""
    sql(store, "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, "
               "started_at, finishes_at, state, reward_snapshot) VALUES (?, ?, 'gather_herbs', '采灵药', ?, ?, ?, "
               "'running', ?)",
        (user, pet_id, f"lineup-coverage-{user}-{pet_id}", now, now + DURATION,
         json.dumps({"exp": 30, "stones": 40, "items": {"spirit_food": 1}})))


def slots(store, user="u1"):
    return sql(store, "SELECT slot, pet_id FROM active_pet_slots WHERE user_id=? ORDER BY slot", (user,))


def ready_rows(store):
    return sql(store, "SELECT user_id, ready_pet_id, ready_pet_ids FROM team_members ORDER BY user_id")


def scripted_battle(left, right, rng, elements):
    def uses(team):
        return {
            unit.pet_id: {unit.skills[0].id: 1}
            for unit in team if unit.pet_id is not None and unit.skills
        }

    return Battle(0, 1, ("测试结算",), (uses(left), uses(right)), ("测试结算",))


def mastery_rows(store, pet_ids):
    placeholders = ",".join("?" for _ in pet_ids)
    return sql(
        store,
        f"SELECT pet_id, skill_id, level, proficiency FROM learned_skills "
        f"WHERE pet_id IN ({placeholders}) ORDER BY pet_id",
        tuple(pet_ids),
    )


def energies(store, pet_ids):
    placeholders = ",".join("?" for _ in pet_ids)
    rows = sql(store, f"SELECT energy FROM pets WHERE pet_id IN ({placeholders}) ORDER BY pet_id", tuple(pet_ids))
    return [row["energy"] for row in rows]


def last_snapshot(game, side=0):
    record = sql(game[1], "SELECT snapshot FROM battle_records ORDER BY battle_id DESC LIMIT 1")[0]
    return json.loads(record["snapshot"])["teams"][side]["members"]


def test_replayed_operation_key_charges_and_rewards_three_pet_dungeon_once(game, play, monkeypatch):
    play("adopt", "青鸾")
    pet_ids = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    monkeypatch.setattr(adventure, "fight", scripted_battle)

    first = play("challenge", "青岚林", op="lineup-replay")
    assert first.title == "秘境获胜"
    # 固定随机源取下界：一名成员一份掉落，与三只出战宠物无关。
    assert energies(game[1], pet_ids) == [80, 80, 80]
    stones, owned = player(game[1])["stones"], items(game[1])
    assert owned["bloodline_essence"] == 1 and owned["forge_ore"] == 1
    mastery = mastery_rows(game[1], pet_ids)
    assert [row["proficiency"] for row in mastery] == [
        game[0].content.rules.skill_proficiency_per_use
    ] * 3
    quests = sql(game[1], "SELECT quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert quests == [{"quest_id": "pve_once", "progress": 1}]
    snapshots = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")

    assert play("challenge", "青岚林", op="lineup-replay") == first
    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == snapshots
    assert player(game[1])["stones"] == stones and items(game[1]) == owned
    assert sql(game[1], "SELECT quest_id, progress FROM quest_progress ORDER BY quest_id") == quests
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1
    assert len(sql(game[1], "SELECT * FROM battle_participants")) == 1
    assert mastery_rows(game[1], pet_ids) == mastery

    # 七天回复缓存过期后仍须靠 battle_records 幂等，不会二次扣费。
    sql(game[1], "DELETE FROM operations WHERE operation_id='lineup-replay'")
    assert play("challenge", "青岚林", op="lineup-replay") == first
    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == snapshots
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1


def test_three_pet_stage_awards_mastery_to_each_casting_pet(game, play, monkeypatch):
    play("adopt", "青鸾")
    pet_ids = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    monkeypatch.setattr(pve_stages, "fight", scripted_battle)

    result = play("stage_challenge", "1", op="lineup-stage-mastery")

    assert result.title == "关卡首通"
    assert [row["proficiency"] for row in mastery_rows(game[1], pet_ids)] == [
        game[0].content.rules.skill_proficiency_per_use
    ] * 3


def test_ranked_pvp_awards_mastery_to_each_attacking_pet_only(game, play, monkeypatch):
    two_players(play)
    attacker = armed_roster(game, play, realm=1)
    defender = armed_roster(game, play, user="u2", tag="乙", realm=1)
    play("lineup", " ".join(str(pet_id) for pet_id in attacker))
    play("lineup", " ".join(str(pet_id) for pet_id in defender), user="u2")
    monkeypatch.setattr(arena_battles, "fight", scripted_battle)

    result = play("pvp", "赤霄", op="lineup-pvp-mastery")

    assert result.title == "论剑结算"
    per_use = game[0].content.rules.skill_proficiency_per_use
    assert [row["proficiency"] for row in mastery_rows(game[1], attacker)] == [per_use] * 3
    assert [row["proficiency"] for row in mastery_rows(game[1], defender)] == [0] * 3


def test_replayed_operation_key_stays_bound_to_its_owner(game, play):
    play("adopt", "青鸾")
    pet_ids = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    first = play("challenge", "青岚林", op="lineup-owner")
    play("adopt", "玄狐", user="u2")
    play("lineup", str(sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]), user="u2")

    with pytest.raises(GameError, match="operation ID reused by a different user"):
        play("challenge", "青岚林", user="u2", op="lineup-owner")
    assert play("challenge", "青岚林", op="lineup-owner") == first
    assert energies(game[1], pet_ids) == [80, 80, 80]
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1


def test_team_dungeon_rolls_back_all_three_leader_pets_when_one_pet_lacks_energy(game, play):
    setup_team(game, play)
    leader_pets = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in leader_pets))
    play("team_ready")
    play("team_ready", user="u2")
    # 末位出战宠物精力不足，前两只与队友宠物都不应被扣。
    sql(game[1], "UPDATE pets SET energy=5 WHERE pet_id=?", (leader_pets[-1],))
    pets_before = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")
    players_before = sql(game[1], "SELECT user_id, stones, last_pve FROM players ORDER BY user_id")
    ready_before = ready_rows(game[1])

    with pytest.raises(GameError, match="精力不足，需要 30 点"):
        play("team_challenge", "上古灵殿", op="lineup-rollback")

    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == pets_before
    assert sql(game[1], "SELECT user_id, stones, last_pve FROM players ORDER BY user_id") == players_before
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert not sql(game[1], "SELECT * FROM quest_progress")
    assert ready_rows(game[1]) == ready_before

    # 补齐精力后同一阵容才真正开战，证明上面是整体回滚而不是校验恒失败。
    sql(game[1], "UPDATE pets SET energy=100 WHERE pet_id=?", (leader_pets[-1],))
    assert play("team_challenge", "上古灵殿", op="lineup-after-rollback").title == "秘境获胜"
    assert energies(game[1], leader_pets) == [70, 70, 70]


def test_team_stage_rolls_back_three_pet_lineup_without_writing_progress(game, play):
    setup_team(game, play)
    leader_pets = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in leader_pets))
    sql(game[1], "UPDATE pets SET realm=3")
    for user in ("u1", "u2"):
        sql(game[1], "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id) "
                     "VALUES (?, 'stage_03', ?, 'seed')", (user, NOW))
    play("team_ready")
    play("team_ready", user="u2")
    sql(game[1], "UPDATE pets SET energy=10 WHERE pet_id=?", (leader_pets[1],))
    pets_before = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")
    progress_before = sql(game[1], "SELECT user_id, stage_id FROM pve_stage_progress ORDER BY user_id, stage_id")

    with pytest.raises(GameError, match="精力不足，需要 30 点"):
        play("team_stage_challenge", "古殿同契", op="stage-rollback")

    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == pets_before
    progress_now = sql(game[1], "SELECT user_id, stage_id FROM pve_stage_progress ORDER BY user_id, stage_id")
    assert progress_now == progress_before
    assert not sql(game[1], "SELECT * FROM pve_stage_progress WHERE stage_id='stage_04'")
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert not sql(game[1], "SELECT * FROM quest_progress")
    assert ready_rows(game[1]) == [
        {"user_id": "u1", "ready_pet_id": leader_pets[0],
         "ready_pet_ids": json.dumps(leader_pets)},
        {"user_id": "u2", "ready_pet_id": pet(game[1], "u2")["pet_id"],
         "ready_pet_ids": json.dumps([pet(game[1], "u2")["pet_id"]])},
    ]

    sql(game[1], "UPDATE pets SET energy=100 WHERE pet_id=?", (leader_pets[1],))
    assert play("team_stage_challenge", "古殿同契", op="stage-retry").title == "关卡首通"
    assert sql(game[1], "SELECT user_id FROM pve_stage_progress WHERE stage_id='stage_04' ORDER BY user_id") == [
        {"user_id": "u1"}, {"user_id": "u2"}]


def test_three_pet_pve_cooldown_is_shared_and_lifts_on_the_boundary_second(game, play):
    play("adopt", "青鸾")
    pet_ids = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    assert play("challenge", "青岚林", op="cooldown-first").title == "秘境获胜"
    snapshots = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")

    with pytest.raises(GameError, match="调息 1 秒"):
        play("challenge", "青岚林", now=NOW + 599)
    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == snapshots
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1

    # 冷却记在玩家上：临场换成一只没出战的灵宠也躲不开共享 PVE 冷却。
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", "1")
    spare = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    sql(game[1], "UPDATE pets SET species_id='jiaolong', energy=100 WHERE pet_id=?", (spare,))
    play("lineup", str(spare))
    with pytest.raises(GameError, match="调息"):
        play("challenge", "青岚林", now=NOW + 599)

    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    assert play("challenge", "青岚林", now=NOW + 600, op="cooldown-edge").title == "秘境获胜"
    # 600 秒内每只回 2 点精力，再扣 20 点体力后是 62。
    assert energies(game[1], pet_ids) == [62, 62, 62]


def test_dispatched_second_pet_blocks_dungeon_and_arena_until_dropped_from_lineup(game, play):
    two_players(play)
    attacker = armed_roster(game, play, tag="甲", realm=1)
    armed_roster(game, play, user="u2", tag="乙", realm=1)
    play("lineup", " ".join(str(pet_id) for pet_id in attacker))
    dispatch(game[1], "u1", attacker[1])

    for action, arg in (("challenge", "青岚林"), ("pvp", "赤霄")):
        with pytest.raises(GameError, match="派遣"):
            play(action, arg, op=f"busy-{action}")
    # 报错必须指向被派遣的第二只，而不是首位灵宠。
    with pytest.raises(GameError, match="甲2"):
        play("challenge", "青岚林")
    assert energies(game[1], attacker) == [100, 100, 100]
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert not sql(game[1], "SELECT * FROM pvp_results")

    play("lineup", f"{attacker[0]} {attacker[2]}")
    assert play("challenge", "青岚林", op="swap-pve").title == "秘境获胜"
    assert play("pvp", "赤霄", op="swap-pvp").title == "论剑结算"
    assert energies(game[1], attacker) == [60, 100, 60]


def test_lineup_rejects_zero_four_duplicate_foreign_and_archived_pet_ids(game, play):
    play("adopt", "青鸾")
    pet_ids = armed_roster(game, play)
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", "1")
    fourth = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    sql(game[1], "UPDATE pets SET species_id='jiaolong' WHERE pet_id=?", (fourth,))
    play("adopt", "玄狐", user="u2")
    foreign = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]

    play("lineup", f"{pet_ids[0]} {pet_ids[1]}")
    keep_slots, keep_active = slots(game[1]), player(game[1])["active_pet_id"]

    # 空参数是只读查看，不是「0 只」写入；阵容必须一字不动。
    view = play("lineup", "")
    assert view.title == "灵宠出战阵容" and len(view.lines) == 2
    assert slots(game[1]) == keep_slots and player(game[1])["active_pet_id"] == keep_active

    with closing(game[1].connect()) as conn:
        with pytest.raises(GameError, match="出战阵容需要 1-3 只灵宠"):
            Repository(conn).set_active_pets("u1", [])
    assert slots(game[1]) == keep_slots

    play("pet_archive", str(pet_ids[2]))
    cases = (
        (" ".join(str(pet_id) for pet_id in (*pet_ids, fourth)), "最多三只"),
        (f"{pet_ids[0]} {pet_ids[1]} {pet_ids[0]}", "不能重复出战"),
        (f"{pet_ids[0]} {foreign}", "只能选择属于你的灵宠出战"),
        (f"{pet_ids[0]} {pet_ids[2]}", "封存灵宠不能出战"),
    )
    for argument, message in cases:
        with pytest.raises(GameError, match=message):
            play("lineup", argument)
        assert slots(game[1]) == keep_slots
        assert player(game[1])["active_pet_id"] == keep_active


def test_lineup_change_clears_only_the_owners_team_ready_row(game, play):
    setup_team(game, play)
    pet_ids = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))
    play("team_ready")
    play("team_ready", user="u2")
    assert ready_rows(game[1]) == [
        {"user_id": "u1", "ready_pet_id": pet_ids[0], "ready_pet_ids": json.dumps(pet_ids)},
        {"user_id": "u2", "ready_pet_id": pet(game[1], "u2")["pet_id"],
         "ready_pet_ids": json.dumps([pet(game[1], "u2")["pet_id"]])},
    ]

    play("lineup", f"{pet_ids[0]} {pet_ids[2]}")
    rows = {row["user_id"]: row for row in ready_rows(game[1])}
    assert rows["u1"] == {"user_id": "u1", "ready_pet_id": None, "ready_pet_ids": ""}
    assert rows["u2"]["ready_pet_id"] is not None
    with pytest.raises(GameError, match="全体"):
        play("team_challenge", "上古灵殿")


def test_member_and_leader_changes_clear_the_whole_team_ready_state(game, play):
    setup_team(game, play)
    leader_pets = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in leader_pets))
    play("adopt", "玄狐", user="u3")
    play("dao_name", "月华", user="u3")
    play("team_ready")
    play("team_ready", user="u2")

    play("team_join", "青云", user="u3")
    play("team_accept", "月华")
    assert all(row["ready_pet_id"] is None and row["ready_pet_ids"] == "" for row in ready_rows(game[1]))

    play("team_ready")
    play("team_ready", user="u2")
    play("team_ready", user="u3")
    rows = {row["user_id"]: row for row in ready_rows(game[1])}
    assert rows["u1"]["ready_pet_ids"] == json.dumps(leader_pets)
    assert sum(row["ready_pet_id"] is not None for row in ready_rows(game[1])) == 3

    play("team_transfer", "赤霄")
    assert all(row["ready_pet_id"] is None and row["ready_pet_ids"] == "" for row in ready_rows(game[1]))


def test_team_battle_allows_five_pets_and_rejects_a_sixth(game, play):
    team_id = setup_team(game, play)
    leader_pets = armed_roster(game, play)
    play("lineup", " ".join(str(pet_id) for pet_id in leader_pets))
    play("adopt", "玄狐", user="u3")
    play("dao_name", "月华", user="u3")
    play("team_join", "青云", user="u3")
    play("team_accept", "月华")
    sql(game[1], "UPDATE pets SET layer=5")
    for user in ("u1", "u2", "u3"):
        play("team_ready", user=user)

    result = play("team_challenge", "上古灵殿", op="five-pets")
    assert result.title == "秘境获胜"
    # 队长三宠 + 两名队友各一宠 = 整队五只，正好落在上限内。
    assert len(last_snapshot(game)) == 5

    # max_team_size 目前为 3，四名成员的队伍无法通过指令组出；直接写入成员行以驱动五只上限守卫。
    play("adopt", "青鸾", user="u4")
    play("dao_name", "流火", user="u4")
    sql(game[1], "INSERT INTO team_members(user_id, team_id) VALUES ('u4', ?)", (team_id,))
    for user in ("u1", "u2", "u3", "u4"):
        play("team_ready", user=user)
    pets_before = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")
    records = len(sql(game[1], "SELECT * FROM battle_records"))

    with pytest.raises(GameError, match="最多出战五只"):
        play("team_challenge", "上古灵殿", now=NOW + 600, op="six-pets")
    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id") == pets_before
    assert len(sql(game[1], "SELECT * FROM battle_records")) == records


def test_three_pet_arena_report_snapshots_members_and_limits_access(game, play):
    two_players(play)
    play("adopt", "玄狐", user="u3")
    play("dao_name", "月华", user="u3")
    attacker = armed_roster(game, play, tag="甲", realm=1)
    defender = armed_roster(game, play, user="u2", tag="乙", realm=1)
    play("lineup", " ".join(str(pet_id) for pet_id in attacker))
    play("lineup", " ".join(str(pet_id) for pet_id in defender), user="u2")

    play("pvp", "赤霄", op="report-pvp")
    rows = sql(game[1], "SELECT battle_id, kind, snapshot FROM battle_records")
    assert len(rows) == 1 and rows[0]["kind"] == "pvp"
    snapshot = json.loads(rows[0]["snapshot"])
    assert [len(team["members"]) for team in snapshot["teams"]] == [3, 3]
    assert [member["pet_name"] for member in snapshot["teams"][0]["members"]] == ["甲1", "甲2", "甲3"]
    assert [member["dao_name"] for member in snapshot["teams"][0]["members"]] == ["青云"] * 3

    participants = sql(game[1], "SELECT user_id, side, permission FROM battle_participants ORDER BY side, user_id")
    assert len(participants) == len({(row["user_id"], row["side"]) for row in participants}) == 2
    assert {row["permission"] for row in participants} == {"participant", "defender"}

    battle_id = rows[0]["battle_id"]
    assert play("battle_reports", f"查看 {battle_id}", user="u2").title.startswith(f"战报 #{battle_id}")
    with pytest.raises(GameError, match="不是该场战斗的参与者"):
        play("battle_reports", f"查看 {battle_id}", user="u3")
    assert "甲1、甲2、甲3" in play("battle_reports", user="u1").text()


def test_spar_fights_with_full_lineups_and_charges_neither_side(game, play):
    two_players(play)
    attacker = armed_roster(game, play, tag="甲", realm=1)
    defender = armed_roster(game, play, user="u2", tag="乙", realm=1)
    play("lineup", " ".join(str(pet_id) for pet_id in attacker))
    play("lineup", " ".join(str(pet_id) for pet_id in defender), user="u2")
    pets_before = sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id")
    mastery_before = sql(
        game[1], "SELECT pet_id, skill_id, level, proficiency FROM learned_skills ORDER BY pet_id")
    players_before = sql(game[1], "SELECT user_id, last_pvp, last_pve, stones FROM players ORDER BY user_id")

    result = play("spar", "赤霄", op="spar-full")
    assert result.lines[0].startswith("青云的3宠阵容 对 赤霄的3宠阵容镜像")
    snapshot = json.loads(sql(game[1], "SELECT snapshot FROM battle_records")[0]["snapshot"])
    assert [len(team["members"]) for team in snapshot["teams"]] == [3, 3]

    assert sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id") == pets_before
    mastery_now = sql(
        game[1], "SELECT pet_id, skill_id, level, proficiency FROM learned_skills ORDER BY pet_id")
    assert mastery_now == mastery_before
    assert sql(game[1], "SELECT user_id, last_pvp, last_pve, stones FROM players ORDER BY user_id") == players_before
    assert not sql(game[1], "SELECT * FROM pvp_results")
    assert not sql(game[1], "SELECT * FROM season_entries")
    assert not sql(game[1], "SELECT * FROM quest_progress")

    # 双方整份阵容都真的上场出招，上面的“零消耗/零熟练度”不是因为没打。
    log = json.loads(sql(game[1], "SELECT battle_log FROM battle_records")[0]["battle_log"])
    for name in ("甲1", "甲2", "甲3", "乙1", "乙2", "乙3"):
        assert any(name in line for line in log)
    assert pet(game[1], "u2")["energy"] == 100
