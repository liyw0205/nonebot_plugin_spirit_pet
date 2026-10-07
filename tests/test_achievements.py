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
        "species_collected", "pets_owned", "max_realm", "max_layer", "max_bloodline",
        "stage_clears", "pvp_wins", "pve_wins", "lineage_branches", "skills_learned",
        "max_skill_level", "skill_level_sum",
    } <= metrics
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


@pytest.mark.parametrize(("metric", "target"), [
    ("species_collected", 27), ("max_realm", 7), ("max_layer", 70),
    ("max_bloodline", 4), ("stage_clears", 8), ("max_skill_level", 5),
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


def test_metrics_are_derived_from_owned_state_and_permanent_records(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    other_pet = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
    with game[1].connect() as conn:
        conn.execute(
            "UPDATE pets SET realm=3,layer=10,bloodline=4,lineage_id='qingluan_lingfeng' WHERE pet_id=?",
            (pet_id,),
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
        conn.execute(
            "INSERT INTO seasons VALUES ('2099-01',1,100,NULL,1,'{}')"
        )
        conn.execute(
            "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,target_pet_id,winner_id,"
            "day,played_at,delta,operation_id,reply) VALUES ('2099-01','u1','u2',?,?, 'u1','2099-01-01',1,5,'pvp-win','{}')",
            (pet_id, other_pet),
        )
    assert metric_value(game, "u1", "species_collected") == 1
    assert metric_value(game, "u1", "pets_owned") == 1
    assert metric_value(game, "u1", "max_realm") == 4
    assert metric_value(game, "u1", "max_layer") == 40
    assert metric_value(game, "u1", "max_bloodline") == 4
    assert metric_value(game, "u1", "stage_clears") == 2
    assert metric_value(game, "u1", "pve_wins") == 1
    assert metric_value(game, "u1", "pvp_wins") == 1
    assert metric_value(game, "u1", "lineage_branches") == 1
    assert metric_value(game, "u1", "skills_learned") == 2
    assert metric_value(game, "u1", "max_skill_level") == 3
    assert metric_value(game, "u1", "skill_level_sum") == 5


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
