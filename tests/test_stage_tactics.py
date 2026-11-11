from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config

from .conftest import FixedRandom

from .support import items, pet, player, sql


NOW = 1_800_000_000


def account(game, play):
    play("adopt", "青鸾", op="adopt-stage-tactics")


def test_unregistered_player_can_browse_tactical_entry_without_writes(game, play):
    reply = play("stage_tactics")
    assert "尚未结契" in reply.text()
    assert not sql(game[1], "SELECT * FROM players")


def test_start_persists_round_state_and_blocks_parallel_automatic_clear(game, play):
    account(game, play)
    reply = play("stage_tactics", "开始 1", op="tactic-start")
    assert reply.title == "战术关卡开局"
    assert pet(game[1])["energy"] == 85
    assert player(game[1])["last_pve"] == NOW
    state = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'stage_tactic_%'")
    assert {row["quest_id"] for row in state} >= {
        "stage_tactic_stage", "stage_tactic_pet", "stage_tactic_round", "stage_tactic_hp", "stage_tactic_enemy_0",
    }
    with pytest.raises(GameError, match="进行中的关卡战术"):
        play("stage_challenge", "1", op="automatic-blocked")
    page = play("stage_tactics")
    assert "敌方预告" in page.text() and "强攻" in page.text()


def test_each_exchange_updates_durable_state_and_replay_survives_operation_cleanup(game, play):
    account(game, play)
    play("stage_tactics", "开始 1", op="tactic-start")
    first = play("stage_tactics", "强攻", op="tactic-round-1")
    before = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'stage_tactic_%' ORDER BY quest_id")
    sql(game[1], "DELETE FROM operations WHERE operation_id='tactic-round-1'")
    replay = play("stage_tactics", "强攻", op="tactic-round-1", now=NOW + 86400)
    assert replay == first
    assert sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'stage_tactic_%' ORDER BY quest_id") == before
    assert sql(game[1], "SELECT COUNT(*) AS count FROM duel_actions WHERE operation_id='tactic-round-1'")[0]["count"] == 1


def test_active_tactical_state_survives_game_restart(game, play):
    account(game, play)
    play("stage_tactics", "开始 1", op="restart-tactic-start")
    restarted = Game(game[1], Config(), FixedRandom())
    page = restarted.execute("u1", "stage_tactics", "", "restart-tactic-page", NOW + 60)
    assert "第 1 回合" in page.text() and "敌方预告" in page.text()
    reply = restarted.execute("u1", "stage_tactics", "强攻", "restart-tactic-round", NOW + 60)
    assert reply.title.startswith("战术关卡")


def test_tactical_win_settles_first_clear_growth_and_battle_report(game, play):
    account(game, play)
    before_exp = pet(game[1])["exp"]
    before_stones = player(game[1])["stones"]
    play("stage_tactics", "开始 1", op="tactic-start")
    moves = ("强攻", "稳守", "破法", "强攻", "稳守", "破法")
    result = None
    for index, move in enumerate(moves):
        result = play("stage_tactics", move, op=f"tactic-win-{index}")
        if result.title in {"战术关卡首通", "战术关卡胜利", "战术关卡败退", "战术关卡平局"}:
            break
    assert result is not None and result.title == "战术关卡首通"
    assert "逐回合判断成功" in result.text()
    assert sql(game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'") == [{"stage_id": "stage_01"}]
    assert pet(game[1])["exp"] > before_exp
    assert player(game[1])["stones"] > before_stones
    report = sql(game[1], "SELECT kind, battle_key, winner_side, rounds FROM battle_records WHERE operation_id LIKE 'tactic-win-%' ORDER BY battle_id DESC LIMIT 1")[0]
    assert report["kind"] == "pve_stage" and report["battle_key"] == "stage_01" and report["winner_side"] == 0
    assert report["rounds"] >= 1
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id IN ('stage_tactic_stage', 'stage_tactic_round')")
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE user_id='u1' AND quest_id='stage_tactic_clear_stage_01'") == [{"claimed": 1}]


def test_failed_tactical_attempt_consumes_no_growth_and_leaves_no_active_state(game, play):
    account(game, play)
    service = game[0]
    enemy = service.content.enemies["wood_guard"]
    enemies = dict(service.content.enemies)
    enemies[enemy.id] = enemy.model_copy(update={"stats": Stats(hp=1_000_000, attack=1_000_000, defense=0, speed=1)})
    service.content = replace(service.content, enemies=enemies)
    before = (pet(game[1])["exp"], player(game[1])["stones"], items(game[1]))
    play("stage_tactics", "开始 1", op="tactic-loss-start")
    result = play("stage_tactics", "强攻", op="tactic-loss")
    assert result.title == "战术关卡败退"
    assert "进度不变" in result.text()
    assert not sql(game[1], "SELECT * FROM pve_stage_progress")
    assert (pet(game[1])["exp"], player(game[1])["stones"], items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id='stage_tactic_stage'")
    assert sql(game[1], "SELECT winner_side FROM battle_records WHERE operation_id='tactic-loss'") == [{"winner_side": 1}]


def test_team_stage_and_invalid_actions_are_rejected_without_state(game, play):
    account(game, play)
    with pytest.raises(GameError, match="组队关卡不能"):
        play("stage_tactics", "开始 4", op="team-stage-tactic")
    with pytest.raises(GameError, match="格式"):
        play("stage_tactics", "乱来", op="bad-stage-tactic")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'stage_tactic_%'")


def test_help_objectives_and_alias_expose_the_play_loop(game, play):
    account(game, play)
    help_reply = play("help", "秘境与关卡")
    assert "灵宠关卡战术 开始 编号" in help_reply.text()
    objective = play("objectives", op="stage-objectives")
    assert "关卡战术：已完成 0/" in objective.text()
    assert any(command == "灵宠关卡战术" for command in (action.command for action in objective.inline_commands))
    from nonebot_plugin_spirit_pet.adapters.handlers import _parse

    assert _parse("灵宠关卡战术") == ("stage_tactics", "")
