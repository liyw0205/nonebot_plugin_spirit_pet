import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86_400


def test_three_games_listed_and_playable(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("play_game", now=NOW)
    assert "藏食寻宝 · 可游玩" in page.lines
    assert "灵息共振 · 可游玩" in page.lines
    assert "反应试炼 · 可游玩" in page.lines
    assert [link.label for link in page.inline_commands] == ["开始游戏"] * 3
    result = play("play_game", "藏食寻宝", now=NOW + 1, op="pg-1")
    assert "灵宠嬉戏" in result.title
    assert "亲密 +" in result.text()


def test_daily_limit_one(game, play):
    play("adopt", "青鸾", now=NOW)
    play("play_game", "灵息共振", now=NOW, op="pg-limit")
    with pytest.raises(GameError, match="今天已经和灵宠嬉戏过了"):
        play("play_game", "反应试炼", now=NOW + 1, op="pg-limit-2")
    # Next day resets and playing works again.
    result = play("play_game", "反应试炼", now=NOW + DAY, op="pg-next-day")
    assert result.title == "灵宠嬉戏"


def test_play_game_independent_from_bond(game, play):
    play("adopt", "青鸾", now=NOW)
    before = pet(game[1])["affinity"]
    play("play_game", "藏食寻宝", now=NOW, op="pg-ind")
    play("bond", now=NOW + 1, op="pg-bond")
    # bond adds its own +2 on top of the game's reward.
    after_game = pet(game[1])["affinity"]
    assert after_game > before
    assert pet(game[1])["affinity"] == after_game


def test_play_game_rewards_match_grade(game, play):
    play("adopt", "青鸾", now=NOW)
    # FixedRandom: randint(1,100)=1 -> low roll; qingluan initial affinity 0 -> bonus 0; score=1 -> 失手 +1.
    play("play_game", "反应试炼", now=NOW, op="pg-grade")
    assert pet(game[1])["affinity"] == 0 + 1
    assert items(game[1]).get("spirit_food", 0) == 3  # starter only, no food reward


def test_play_game_does_not_advance_daily_tasks(game, play):
    play("adopt", "青鸾", now=NOW)
    play("play_game", "藏食寻宝", now=NOW, op="pg-task")
    assert not sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id='bond_once'")


def test_outing_full_cycle_and_value_accumulation(game, play):
    play("adopt", "青鸾", now=NOW)
    before = player(game[1])["stones"]
    result = play("pet_outing", now=NOW, op="out-1")
    assert "游历值 +5（累计 5）" in result.text()
    assert "灵石 +" in result.text()
    assert player(game[1])["stones"] == before + 20  # FixedRandom minimum
    with pytest.raises(GameError, match="今天已经出游过了"):
        play("pet_outing", now=NOW + 1, op="out-2")
    # Next day works again.
    result2 = play("pet_outing", now=NOW + DAY, op="out-3")
    assert "游历值 +5（累计 10）" in result2.text()


def test_outing_with_pet_number_and_per_pet_independence(game, play):
    play("adopt", "青鸾", now=NOW)
    play("summon", now=NOW, op="out-second")  # second pet (青鸾 again)
    pet_ids = [row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets ORDER BY pet_id")]
    play("pet_outing", str(pet_ids[0]), now=NOW, op="out-a")
    play("pet_outing", str(pet_ids[1]), now=NOW + 1, op="out-b")
    values = {row["quest_id"]: row["progress"] for row in sql(
        game[1], "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE 'outing_value_%'",
    )}
    assert values[f"outing_value_{pet_ids[0]}"] == 5
    assert values[f"outing_value_{pet_ids[1]}"] == 5


def test_outing_rejects_sealed_and_unknown(game, play):
    play("adopt", "青鸾", now=NOW)
    play("summon", now=NOW, op="out-seal")
    play("switch", "2", now=NOW + 1, op="out-switch")
    play("pet_archive", "1", now=NOW + 2, op="out-archive")
    with pytest.raises(GameError, match="没有属于你|封存"):
        play("pet_outing", "1", now=NOW + 3, op="out-sealed")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("pet_outing", "999", now=NOW + 3, op="out-unknown")


def test_milestone_claim_flow(game, play):
    play("adopt", "青鸾", now=NOW)
    # Two outings = value 10, reaching tier 10.
    play("pet_outing", now=NOW, op="ms-1")
    play("pet_outing", now=NOW + DAY, op="ms-2")
    board = play("pet_outing_board", now=NOW + DAY + 1)
    assert "游历值 10" in board.text()
    assert any(link.command == "灵宠游历领奖 1 10" for link in board.inline_commands)
    before = player(game[1])["stones"]
    result = play("pet_outing_claim", "1 10", now=NOW + DAY + 2, op="ms-claim")
    assert "「初出茅庐」游历奖励已领取" in result.lines[0]
    assert player(game[1])["stones"] == before + 50
    with pytest.raises(GameError, match="已领取"):
        play("pet_outing_claim", "1 10", now=NOW + DAY + 3, op="ms-claim-again")
    with pytest.raises(GameError, match="尚未达成"):
        play("pet_outing_claim", "1 30", now=NOW + DAY + 4, op="ms-unreached")


def test_board_pagination(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("pet_outing_board", now=NOW)
    assert page.title == "灵宠游历赏 1/1"
    with pytest.raises(GameError, match="共 1 页"):
        play("pet_outing_board", "2", now=NOW)


def test_unregistered_read_only(game, play):
    page = play("play_game", user="u9", now=NOW)
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    board = play("pet_outing_board", user="u9", now=NOW)
    assert "尚未结契" in board.text()
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_replay_returns_original_reply(game, play):
    play("adopt", "青鸾", now=NOW)
    first = play("play_game", "藏食寻宝", now=NOW, op="pg-rep")
    assert play("play_game", "藏食寻宝", now=NOW + 1, op="pg-rep") == first
    first_out = play("pet_outing", now=NOW, op="out-rep")
    assert play("pet_outing", now=NOW + 1, op="out-rep") == first_out
    play("pet_outing", now=NOW + DAY, op="out-rep-2")
    claim = play("pet_outing_claim", "1 10", now=NOW + DAY + 1, op="claim-rep")
    assert play("pet_outing_claim", "1 10", now=NOW + DAY + 2, op="claim-rep") == claim


def test_native_keyboard_clean_and_parse(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("play_game", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠嬉戏") == ("play_game", "")
    assert handlers._parse("灵宠嬉戏 藏食寻宝") == ("play_game", "藏食寻宝")
    assert handlers._parse("灵宠出游") == ("pet_outing", "")
    assert handlers._parse("灵宠游历赏") == ("pet_outing_board", "")
    assert handlers._parse("灵宠游历领奖 1 10") == ("pet_outing_claim", "1 10")
