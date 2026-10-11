from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql


NOW = 1_800_000_000


def account(play, user, dao):
    play("adopt", "青鸾", user=user)
    play("dao_name", dao, user=user)


def setup_team(game, play, users=("u1", "u2")):
    for index, user in enumerate(users):
        account(play, user, f"道友{index + 1}")
    play("team_create", user=users[0])
    for user in users[1:]:
        leader_name = player(game[1], users[0])["dao_name"]
        member_name = player(game[1], user)["dao_name"]
        play("team_join", leader_name, user=user)
        play("team_accept", member_name, user=users[0])
    for user in users:
        play("team_ready", user=user)


def test_catalog_lists_personal_clear_unlock_state_and_details(game, play):
    account(play, "u1", "青云")
    listing = play("stage_catalog")
    assert "1. 青木试锋 · 可挑战" in listing.text()
    assert "2. 月影追猎 · 未解锁" in listing.text()
    assert "进度：未解锁" in play("stage_catalog", "月影追猎").text()

    play("stage_challenge", "1")
    listing = play("stage_catalog")
    assert "1. 青木试锋 · 已通关" in listing.text()
    assert "2. 月影追猎 · 可挑战" in listing.text()
    assert "进度：可挑战" in play("stage_catalog", "月影追猎").text()
    assert "进度：已通关" in play("stage_catalog", "青木试锋").text()
    assert "霜封术" in play("stage_catalog", "冰魄封关").text()
    assert "每 8 次行动施展" in play("stage_catalog", "冰魄封关").text()


def test_unregistered_player_can_browse_without_creating_an_account(game, play):
    listing = play("stage_catalog")
    detail = play("stage_catalog", "青木试锋")
    assert "尚未结契" in listing.text()
    assert "进度：尚未结契" in detail.text()
    assert not sql(game[1], "SELECT * FROM players")


def test_stage_listing_detail_and_first_clear_are_transactional_and_durable(game, play):
    account(play, "u1", "青云")
    listing = play("stage_catalog")
    assert "青木试锋" in listing.text()
    detail = play("stage_catalog", "青木试锋")
    assert "单人" in detail.text() and "首通奖励" in detail.text()
    with pytest.raises(GameError, match="前置关卡"):
        play("stage_challenge", "2")

    before_exp = pet(game[1])["exp"]
    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    result = play("stage_challenge", "1", op="stage-first")
    assert result.title == "关卡首通"
    assert sql(game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'") == [{"stage_id": "stage_01"}]
    assert pet(game[1])["energy"] == 85
    assert player(game[1])["last_pve"] == NOW
    assert pet(game[1])["exp"] > before_exp
    assert player(game[1])["stones"] > before_stones
    assert items(game[1]) != before_items
    report = sql(game[1], "SELECT kind, battle_key, reply FROM battle_records WHERE operation_id='stage-first'")[0]
    assert report["kind"] == "pve_stage" and report["battle_key"] == "stage_01"
    battle_id = sql(game[1], "SELECT battle_id FROM battle_records WHERE operation_id='stage-first'")[0]["battle_id"]
    game[0].content = replace(
        game[0].content,
        stages={**game[0].content.stages, "stage_01": game[0].content.stages["stage_01"].model_copy(
            update={"name": "已更名关卡"},
        )},
    )
    detail = play("battle_reports", f"查看 {battle_id}")
    assert "场景：青木试锋" in detail.text()
    assert "已更名关卡" not in detail.text()

    sql(game[1], "DELETE FROM operations WHERE operation_id='stage-first'")
    state = (player(game[1]), pet(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pve_stage_progress"))
    assert play("stage_challenge", "1", op="stage-first", now=NOW + 1) == result
    assert (player(game[1]), pet(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pve_stage_progress")) == state


def test_failed_stage_consumes_action_resources_but_never_advances_or_rewards(game, play):
    account(play, "u1", "青云")
    service = game[0]
    enemy = service.content.enemies["wood_guard"]
    enemies = dict(service.content.enemies)
    enemies[enemy.id] = enemy.model_copy(update={
        "stats": Stats(hp=1_000_000, attack=1, defense=0, speed=1),
    })
    service.content = replace(service.content, enemies=enemies)
    before_exp = pet(game[1])["exp"]
    before_stones = player(game[1])["stones"]
    before_items = items(game[1])

    result = play("stage_challenge", "1", op="stage-loss")
    assert result.title == "关卡平局"
    assert "进度不变" in result.text()
    assert not sql(game[1], "SELECT * FROM pve_stage_progress")
    assert pet(game[1])["energy"] == 85
    assert player(game[1])["last_pve"] == NOW
    assert pet(game[1])["exp"] == before_exp
    assert player(game[1])["stones"] == before_stones
    assert items(game[1]) == before_items
    assert sql(game[1], "SELECT winner_side FROM battle_records WHERE operation_id='stage-loss'") == [{"winner_side": -1}]


def test_team_chapter_validates_leader_and_every_member_readiness_without_partial_cost(game, play):
    setup_team(game, play)
    stage = game[0].content.stages["stage_01"]
    stages = dict(game[0].content.stages)
    stages[stage.id] = stage.model_copy(update={"team": True})
    game[0].content = replace(game[0].content, stages=stages)
    play("team_unready", user="u2")
    before = (player(game[1], "u1"), player(game[1], "u2"), pet(game[1], "u1"), pet(game[1], "u2"))
    with pytest.raises(GameError, match="尚未准备"):
        play("team_stage_challenge", "1", user="u1")
    assert (player(game[1], "u1"), player(game[1], "u2"), pet(game[1], "u1"), pet(game[1], "u2")) == before
    assert not sql(game[1], "SELECT * FROM pve_stage_progress")

    play("team_ready", user="u2")
    with pytest.raises(GameError, match="仅队长"):
        play("team_stage_challenge", "1", user="u2")
    assert not sql(game[1], "SELECT * FROM pve_stage_progress")


def test_team_first_clear_rewards_only_newcomer_and_completed_member_can_assist(game, play):
    setup_team(game, play)
    stage = game[0].content.stages["stage_01"]
    stages = dict(game[0].content.stages)
    stages[stage.id] = stage.model_copy(update={"team": True})
    game[0].content = replace(game[0].content, stages=stages)
    first = play("team_stage_challenge", "1", user="u1", op="team-stage-first")
    assert first.title == "关卡首通"
    assert len(sql(game[1], "SELECT * FROM pve_stage_progress WHERE stage_id='stage_01'")) == 2
    first_rewards = {
        user: (pet(game[1], user)["exp"], player(game[1], user)["stones"], items(game[1], user))
        for user in ("u1", "u2")
    }

    account(play, "u3", "流云")
    play("team_join", player(game[1], "u1")["dao_name"], user="u3")
    play("team_accept", player(game[1], "u3")["dao_name"], user="u1")
    sql(game[1], "UPDATE players SET last_pve=NULL WHERE user_id IN ('u1','u2','u3')")
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id IN ('u1','u2','u3')")
    for user in ("u1", "u2", "u3"):
        play("team_ready", user=user)
    assisted = play("team_stage_challenge", "1", user="u1", op="team-stage-assist")
    assert assisted.title == "关卡首通"
    assert "流云首通" in assisted.text()
    for user in ("u1", "u2"):
        assert (pet(game[1], user)["exp"], player(game[1], user)["stones"], items(game[1], user)) == first_rewards[user]
    assert len(sql(game[1], "SELECT * FROM pve_stage_progress WHERE stage_id='stage_01'")) == 3
    participants = sql(game[1], "SELECT user_id FROM battle_participants WHERE battle_id=("
                       "SELECT battle_id FROM battle_records WHERE operation_id='team-stage-assist') ORDER BY user_id")
    assert [row["user_id"] for row in participants] == ["u1", "u2", "u3"]


def test_team_members_must_each_clear_the_previous_stage(game, play):
    setup_team(game, play)
    stage = game[0].content.stages["stage_04"]
    stages = dict(game[0].content.stages)
    stages[stage.id] = stage.model_copy(update={"min_realm": "qiling"})
    game[0].content = replace(game[0].content, stages=stages)
    sql(game[1], "INSERT INTO pve_stage_progress VALUES ('u1','stage_03',?,?)", (NOW, "seed-progress"))
    before = (pet(game[1], "u1"), pet(game[1], "u2"), player(game[1], "u1"), player(game[1], "u2"))
    with pytest.raises(GameError, match="尚未通关前置关卡"):
        play("team_stage_challenge", "4", user="u1")
    assert (pet(game[1], "u1"), pet(game[1], "u2"), player(game[1], "u1"), player(game[1], "u2")) == before
