import json
import sqlite3
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import achievements
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql


@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit(directory, change):
    path = directory / "achievements.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def metric_value(game, user, metric):
    values = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config,
                      game[0].rng, user, 1_800_000_000, f"metric-{user}-{metric}")
        values.append(achievements._metric(ctx, user, metric))
        return Reply("metric", ())

    game[1].transact(user, f"metric-{user}-{metric}", 1_800_000_000, run)
    return values[-1]


def test_catalog_has_definition_only_achievements_and_all_required_metrics():
    content = Catalog.load()
    assert len(content.species) == 27
    assert len(content.achievements) >= 20
    metrics = {entry.metric for entry in content.achievements.values()}
    assert {
        "species_collected", "duplicate_species", "pets_owned", "max_realm", "max_layer", "max_bloodline",
        "stage_clears", "pvp_wins", "pve_wins", "team_pve_wins", "lineage_branches", "skills_learned",
        "max_skill_level", "skill_level_sum", "expedition_claims", "max_affinity",
        "best_bond_streak", "adventures_discovered",
    } <= metrics
    assert {1, 10, 30} <= {
        entry.target for entry in content.achievements.values() if entry.metric == "team_pve_wins"
    }
    assert {
        achievement.target for achievement in content.achievements.values()
        if achievement.metric == "max_layer"
    } >= set(range(10, 71, 10))


@pytest.mark.parametrize("field", ["created_at", "user_id", "progress", "claimed", "timestamp"])
def test_achievement_definitions_reject_runtime_state(content_dir, field):
    edit(content_dir, lambda entries: entries[0].update({field: 1}))
    with pytest.raises(ValidationError, match="Extra inputs"):
        Catalog.load(content_dir)


def test_achievement_reward_references_are_validated(content_dir):
    edit(content_dir, lambda entries: entries[0]["reward"]["items"].update(unknown_item=1))
    with pytest.raises(ValueError, match="unknown achievement reward items"):
        Catalog.load(content_dir)


def test_achievement_targets_cannot_exceed_available_content(content_dir):
    edit(content_dir, lambda entries: next(e for e in entries if e["metric"] == "max_layer").update(target=71))
    with pytest.raises(ValueError, match="exceeds available max_layer"):
        Catalog.load(content_dir)


def test_adventure_discovery_achievement_cannot_exceed_catalog(content_dir):
    def add_invalid_milestone(entries):
        invalid = dict(next(
            entry for entry in entries
            if entry["metric"] == "adventures_discovered" and entry["target"] == 14
        ))
        invalid.update(id="adventure_fifteen", name="奇闻超限", target=15)
        entries.append(invalid)

    edit(content_dir, add_invalid_milestone)
    with pytest.raises(ValueError, match="exceeds available adventures_discovered"):
        Catalog.load(content_dir)


def test_duplicate_species_target_cannot_exceed_species_catalog(content_dir):
    edit(content_dir, lambda entries: next(
        e for e in entries if e["metric"] == "duplicate_species"
    ).update(target=28))
    with pytest.raises(ValueError, match="exceeds available duplicate_species"):
        Catalog.load(content_dir)


@pytest.mark.parametrize(("metric", "target"), [
    ("species_collected", 27), ("max_realm", 7), ("max_layer", 70),
    ("max_bloodline", 4), ("stage_clears", 8), ("max_skill_level", 5),
    ("max_affinity", 100), ("adventures_discovered", 14),
])
def test_achievement_catalog_requires_final_milestones(content_dir, metric, target):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if (entry["metric"], entry["target"]) != (metric, target)]
    ))
    with pytest.raises(ValueError, match=f"missing final achievement milestone for {metric}"):
        Catalog.load(content_dir)


def test_achievement_catalog_requires_every_realm_ten_layer_milestone(content_dir):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if (entry["metric"], entry["target"]) != ("max_layer", 40)]
    ))
    with pytest.raises(ValueError, match="missing realm layer achievement milestone"):
        Catalog.load(content_dir)


def test_achievement_catalog_requires_expedition_tracking(content_dir):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if entry["metric"] != "expedition_claims"]
    ))
    with pytest.raises(ValueError, match="missing achievement metrics"):
        Catalog.load(content_dir)


def test_achievement_catalog_requires_affinity_milestones(content_dir):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if not (
            entry["metric"] == "max_affinity" and entry["target"] == 50
        )]
    ))
    with pytest.raises(ValueError, match="missing affinity achievement milestone"):
        Catalog.load(content_dir)


@pytest.mark.parametrize("target", [7, 30])
def test_achievement_catalog_requires_bond_streak_milestones(content_dir, target):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if not (
            entry["metric"] == "best_bond_streak" and entry["target"] == target
        )]
    ))
    with pytest.raises(ValueError, match="missing bond streak achievement milestone"):
        Catalog.load(content_dir)


@pytest.mark.parametrize("target", [1, 10, 30])
def test_achievement_catalog_requires_team_victory_milestones(content_dir, target):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if not (
            entry["metric"] == "team_pve_wins" and entry["target"] == target
        )]
    ))
    with pytest.raises(ValueError, match="missing team PVE achievement milestone"):
        Catalog.load(content_dir)


@pytest.mark.parametrize("target", [5, 10])
def test_achievement_catalog_requires_adventure_discovery_milestones(content_dir, target):
    edit(content_dir, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if not (
            entry["metric"] == "adventures_discovered" and entry["target"] == target
        )]
    ))
    with pytest.raises(ValueError, match="missing adventure discovery achievement milestone"):
        Catalog.load(content_dir)


def test_collection_shows_all_species_and_ownership_across_pages(game, play):
    first = play("collection")
    second = play("collection", "2")
    third = play("collection", "3")
    assert "0/27" in first.text()
    assert len([line for line in first.lines if "未收集" in line]) == 9
    assert len([line for line in second.lines if "未收集" in line]) == 9
    assert len([line for line in third.lines if "未收集" in line]) == 9
    assert "灵宠收集 2" in first.commands
    play("adopt", "青鸾")
    assert "1/27" in play("collection").text()
    assert "青鸾 · 已拥有" in play("collection").text()
    with pytest.raises(GameError, match="共 3 页"):
        play("collection", "4")


def test_duplicate_species_collection_and_achievement_claim(game, play):
    play("adopt", "青鸾")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1','qingluan','青鸾二号',1800000000)"
        )
    assert metric_value(game, "u1", "duplicate_species") == 1
    collection = play("collection")
    assert "同族复数 1 种" in collection.text()
    assert "青鸾 · 已拥有（2只）" in collection.text()
    assert "灵宠成就领奖 同族双灵" in play("achievements").commands
    claim = play("achievement_claim", "同族双灵", op="duplicate-achievement")
    assert play("achievement_claim", "同族双灵", op="duplicate-achievement") == claim
    assert player(game[1])["stones"] == 280


def test_three_duplicate_species_unlocks_second_collecting_milestone(game, play):
    play("adopt", "青鸾")
    with game[1].connect() as conn:
        for species_id, name in (("qingluan", "青鸾二号"), ("xuanhu", "玄狐一号"),
                                 ("xuanhu", "玄狐二号"), ("baize", "白泽一号"),
                                 ("baize", "白泽二号")):
            conn.execute(
                "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1',?,?,1800000000)",
                (species_id, name),
            )
    assert metric_value(game, "u1", "duplicate_species") == 3
    assert "同族复数 3 种" in play("collection").text()
    assert "灵宠成就领奖 三族同脉" in play("achievements").commands


def test_duplicate_species_achievement_counts_archived_pets(game, play):
    play("adopt", "青鸾")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,archived,energy_updated) "
            "VALUES ('u1','qingluan','青鸾二号',1,1800000000)"
        )
    assert metric_value(game, "u1", "duplicate_species") == 1
    assert "同族双灵 · 可领奖" in play("achievements").text()


def test_metrics_are_derived_from_owned_state_and_permanent_records(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    other_pet = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
    with game[1].connect() as conn:
        conn.execute(
            "UPDATE pets SET realm=3,layer=10,bloodline=4,affinity=100,lineage_id='qingluan_lingfeng' WHERE pet_id=?",
            (pet_id,),
        )
        conn.execute("UPDATE players SET best_bond_streak=32 WHERE user_id='u1'")
        conn.executemany(
            "INSERT INTO adventure_discoveries(user_id,encounter_id,discovered_at) VALUES ('u1',?,1)",
            (("spring",), ("mountain",)),
        )
        conn.execute(
            "INSERT INTO learned_skills(pet_id,skill_id,equipped,level,proficiency) VALUES (?,?,0,?,0)",
            (pet_id, "wind_slash", 3),
        )
        conn.execute(
            "INSERT INTO learned_skills(pet_id,skill_id,equipped,level,proficiency) VALUES (?,?,0,?,0)",
            (pet_id, "meditation", 2),
        )
        conn.execute(
            "INSERT INTO learned_skills(pet_id,skill_id,equipped,level,proficiency) VALUES (?,?,0,?,0)",
            (other_pet, "wind_slash", 4),
        )
        conn.execute("INSERT INTO pve_stage_progress VALUES ('u1','stage_01',1,'stage-clear-1')")
        conn.execute("INSERT INTO pve_stage_progress VALUES ('u1','stage_02',2,'stage-clear-2')")
        for operation, kind, winner in (("pve-win", "pve", 0), ("pve-loss", "pve_stage", 1), ("pvp-no", "pvp", 0)):
            cursor = conn.execute(
                "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,"
                "played_at,reply,snapshot,battle_log) VALUES (?,'u1',?,'','test',?,1,1,'{}','{}','[]')",
                (operation, kind, winner),
            )
            conn.execute("INSERT INTO battle_participants VALUES (?, 'u1', 0, 'participant')", (cursor.lastrowid,))
        for operation, winner in (("team-pve-win", 0), ("team-pve-loss", 1), ("team-pve-draw", -1)):
            cursor = conn.execute(
                "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,"
                "played_at,reply,snapshot,battle_log) VALUES (?,'u1','pve','','team test',?,1,1,'{}','{}','[]')",
                (operation, winner),
            )
            for user_id in ("u1", "u2"):
                conn.execute(
                    "INSERT INTO battle_participants VALUES (?, ?, 0, 'participant')",
                    (cursor.lastrowid, user_id),
                )
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,"
            "played_at,reply,snapshot,battle_log) VALUES ('team-stage-win','u1','pve_stage','','team stage',"
            "0,1,1,'{}','{}','[]')"
        )
        for user_id in ("u1", "u2"):
            conn.execute(
                "INSERT INTO battle_participants VALUES (?, ?, 0, 'participant')",
                (cursor.lastrowid, user_id),
            )
        conn.execute(
            "INSERT INTO seasons VALUES ('2099-01',1,100,NULL,1,'{}')"
        )
        conn.execute(
            "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,target_pet_id,winner_id,"
            "day,played_at,delta,operation_id,reply) VALUES ('2099-01','u1','u2',?,?, 'u1','2099-01-01',1,5,'pvp-win','{}')",
            (pet_id, other_pet),
        )
        for user_id, owned_pet_id in (("u1", pet_id), ("u2", other_pet)):
            conn.execute(
                "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,"
                "finishes_at,state,reward_snapshot,settled_at) VALUES (?,?,'herb_gathering','采灵药',?,1,2,"
                "'claimed','{}',2)",
                (user_id, owned_pet_id, f"claimed-{user_id}"),
            )
    assert metric_value(game, "u1", "species_collected") == 1
    assert metric_value(game, "u1", "duplicate_species") == 0
    assert metric_value(game, "u1", "pets_owned") == 1
    assert metric_value(game, "u1", "max_realm") == 4
    assert metric_value(game, "u1", "max_layer") == 40
    assert metric_value(game, "u1", "max_bloodline") == 4
    assert metric_value(game, "u1", "stage_clears") == 2
    assert metric_value(game, "u1", "pve_wins") == 3
    assert metric_value(game, "u1", "team_pve_wins") == 2
    assert metric_value(game, "u2", "team_pve_wins") == 2
    assert metric_value(game, "u1", "pvp_wins") == 1
    assert metric_value(game, "u1", "lineage_branches") == 1
    assert metric_value(game, "u1", "skills_learned") == 2
    assert metric_value(game, "u1", "max_skill_level") == 3
    assert metric_value(game, "u1", "skill_level_sum") == 5
    assert metric_value(game, "u1", "expedition_claims") == 1
    assert metric_value(game, "u1", "max_affinity") == 100
    assert metric_value(game, "u1", "best_bond_streak") == 32
    assert metric_value(game, "u1", "adventures_discovered") == 2
    assert metric_value(game, "u2", "adventures_discovered") == 0


def test_bond_streak_achievements_unlock_and_claim_at_seven_and_thirty_days(game, play):
    start = 1_800_000_000
    play("adopt", "青鸾", now=start)
    for day in range(6):
        play("bond", now=start + day * 86400)
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "七日相守", now=start + 5 * 86400)

    play("bond", now=start + 6 * 86400)
    assert player(game[1])["best_bond_streak"] == 7
    play("achievement_claim", "七日相守", now=start + 6 * 86400)
    for day in range(7, 29):
        play("bond", now=start + day * 86400)
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "朝夕不倦", now=start + 28 * 86400)

    play("bond", now=start + 29 * 86400)
    assert player(game[1])["current_bond_streak"] == 30
    assert player(game[1])["best_bond_streak"] == 30
    play("achievement_claim", "朝夕不倦", now=start + 29 * 86400)
    assert sql(game[1], "SELECT achievement_id FROM achievement_claims WHERE user_id='u1' ORDER BY achievement_id") == [
        {"achievement_id": "bond_streak_month"},
        {"achievement_id": "bond_streak_week"},
    ]


def test_affinity_achievements_measure_one_pet_and_unlock_at_both_milestones(game, play):
    play("adopt", "青鸾")
    play("summon")
    owned = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id")
    assert len(owned) == 2
    sql(game[1], "UPDATE pets SET affinity=40 WHERE user_id='u1'")
    assert metric_value(game, "u1", "max_affinity") == 40
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "心意渐明")

    sql(game[1], "UPDATE pets SET affinity=50 WHERE pet_id=?", (owned[0]["pet_id"],))
    play("achievement_claim", "心意渐明")
    sql(game[1], "UPDATE pets SET affinity=100 WHERE pet_id=?", (owned[0]["pet_id"],))
    play("achievement_claim", "心有灵犀")
    assert sql(game[1], "SELECT achievement_id FROM achievement_claims WHERE user_id='u1' ORDER BY achievement_id") == [
        {"achievement_id": "affinity_fifty"},
        {"achievement_id": "affinity_full"},
    ]


def test_achievement_claim_rewards_once_and_replays_permanently(game, play):
    play("adopt", "青鸾", now=1000)
    before = player(game[1])["stones"]
    first = play("achievement_claim", "初结灵契", now=1000, op="achievement-original")
    assert first.title == "成就奖励已领取"
    saved = sql(game[1], "SELECT * FROM achievement_claims")[0]
    snapshot = json.loads(saved["reward_snapshot"])
    assert snapshot["achievement_id"] == "first_contract"
    assert snapshot["items"] == [{"item_id": "spirit_food", "name": "灵粮", "amount": 2}]
    assert player(game[1])["stones"] == before + 100
    assert items(game[1])["spirit_food"] == 5
    with pytest.raises(GameError, match="已领取"):
        play("achievement_claim", "初结灵契", now=1001, op="achievement-duplicate")
    play("identity", now=1_000 + 604_802, op="expire-old-operation")
    replay = play("achievement_claim", "任意输入被消息ID幂等挡住", now=1_000 + 604_803, op="achievement-original")
    assert replay == first
    assert player(game[1])["stones"] == before + 100
    assert len(sql(game[1], "SELECT * FROM achievement_claims")) == 1


def test_claim_operation_id_cannot_be_reused_by_another_identity(game, play):
    play("adopt", "青鸾", user="u1", now=1000)
    play("adopt", "玄狐", user="u2", now=1000)
    play("achievement_claim", "初结灵契", user="u1", now=1000, op="permanent-owner")
    play("identity", user="u2", now=1_000 + 604_802, op="expire-cross-user-cache")
    with pytest.raises(GameError, match="其他身份"):
        play("achievement_claim", "初结灵契", user="u2", now=1_000 + 604_803, op="permanent-owner")
    assert len(sql(game[1], "SELECT * FROM achievement_claims")) == 1


def test_concurrent_claim_is_single_grant_and_single_permanent_claim(game, play):
    play("adopt", "青鸾")

    def claim(index):
        try:
            play("achievement_claim", "初结灵契", op=f"parallel-achievement-{index}")
            return "claimed"
        except GameError:
            return "already-claimed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ["already-claimed", "claimed"]
    assert len(sql(game[1], "SELECT * FROM achievement_claims")) == 1
    assert player(game[1])["stones"] == 200
    assert items(game[1])["spirit_food"] == 5


def test_late_reward_failure_rolls_back_claim_and_player_rewards(game, play):
    play("adopt", "青鸾")
    before_player, before_items = player(game[1]), items(game[1])
    with game[1].connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_achievement_reward BEFORE INSERT ON inventory "
            "WHEN NEW.item_id='spirit_food' BEGIN SELECT RAISE(ABORT,'injected reward failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected reward failure"):
        play("achievement_claim", "初结灵契", op="rollback-achievement")
    assert not sql(game[1], "SELECT * FROM achievement_claims")
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items
