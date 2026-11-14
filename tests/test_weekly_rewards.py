import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql
from .test_weekly_expansion import seed_pve_win

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)
NEXT_WEEK = WEEK_END + 3600


def account(play):
    play("adopt", "青鸾")


def complete_two_real_quests(game, play):
    for index in range(5):
        seed_pve_win(game, NOW + index, f"milestone-light-{index}")
    play("weekly_quest_claim", "秘境历练", op="milestone-light-claim")
    for index in range(12):
        seed_pve_win(game, NOW + 100 + index, f"milestone-deep-{index}")
    play("weekly_quest_claim", "秘境苦战", op="milestone-deep-claim")


def test_content_has_four_strict_weekly_reward_tiers(game):
    entries = list(game[0].content.weekly_rewards.values())
    assert [entry.threshold for entry in sorted(entries, key=lambda item: item.threshold)] == [2, 4, 6, 9]
    assert all(entry.stones or entry.items for entry in entries)
    assert all(item in game[0].content.items for entry in entries for item in entry.items)


def test_help_and_transport_keep_weekly_reward_commands_reachable(game, play):
    assert handlers._parse("灵宠周常赏") == ("weekly_rewards", "")
    assert handlers._parse("灵宠周常赏 领奖 2") == ("weekly_rewards", "领奖 2")
    assert "灵宠周常赏 领奖 档位" in play("help", "成长").text()
    page = play("weekly_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert "灵宠周常赏" in str(message)


@pytest.mark.parametrize("argument", ["领奖", "领奖 0", "领奖 1", "领奖 7", "领奖 2 extra",
                                       "领奖 9", "领奖 2 周 2027-01-01", "领奖 ２"])
def test_invalid_weekly_reward_requests_are_read_only(game, play, argument):
    account(play)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress"))
    with pytest.raises(GameError):
        play("weekly_rewards", argument)
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress")) == before


def test_real_weekly_claims_unlock_and_pay_cumulative_reward(game, play):
    account(play)
    complete_two_real_quests(game, play)
    page = play("weekly_rewards")
    assert "已领取 2/15 项周常" in page.lines[0]
    assert "2 项 · 周行初成" in page.text() and "可领取" in page.text()
    assert any(link.command == "灵宠周常赏 领奖 2 周 2027-01-11" for link in page.inline_commands)
    before = player(game[1])["stones"]
    result = play("weekly_rewards", "领奖 2", op="weekly-tier-2")
    assert result.title == "灵宠周常赏"
    assert player(game[1])["stones"] == before + 120
    assert items(game[1])["spirit_food"] == 5
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id=?", (
        f"weekly_reward_{WEEK_START}_2",)) == [{"progress": 2, "claimed": 1}]


def test_weekly_reward_is_read_only_across_restart_and_resets_next_week(game, play):
    account(play)
    complete_two_real_quests(game, play)
    play("weekly_rewards", "领奖 2", op="weekly-tier-restart")
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id"))
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "weekly_rewards", "", "weekly-view-restart", NOW).text() == play("weekly_rewards").text()
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id")) == before
    with pytest.raises(GameError, match="仅领取 0 项周常"):
        reopened.execute("u1", "weekly_rewards", "领奖 2", "weekly-next-too-early", NEXT_WEEK)


def test_weekly_reward_replay_concurrency_and_failure_roll_back(game, play, monkeypatch):
    account(play)
    complete_two_real_quests(game, play)
    first = play("weekly_rewards", "领奖 2", op="weekly-replay")
    state = (player(game[1]), items(game[1]))
    assert play("weekly_rewards", "领奖 2", op="weekly-replay") == first
    with pytest.raises(GameError, match="已领取"):
        play("weekly_rewards", "领奖 2", op="weekly-again")
    assert (player(game[1]), items(game[1])) == state

    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES "
        "('u1','weekly_stage',?,1),('u1','weekly_adventure',?,1)",
        (WEEK_START, WEEK_START),
    )

    def attempt(index):
        try:
            return play("weekly_rewards", "领奖 4", op=f"weekly-race-{index}")
        except GameError as error:
            return error

    before_race = (player(game[1])["stones"], items(game[1]).get("forge_ore", 0))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert (player(game[1])["stones"], items(game[1]).get("forge_ore", 0)) == (
        before_race[0] + 240, before_race[1] + 2,
    )

    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES "
        "('u1','weekly_pvp',?,1),('u1','weekly_expedition',?,1),"
        "('u1','weekly_adventure_deep',?,1),('u1','weekly_stage_deep',?,1),"
        "('u1','weekly_achievement',?,1)",
        (WEEK_START,) * 5,
    )
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id"))
    sql(game[1], "CREATE TRIGGER reject_weekly_reward BEFORE INSERT ON quest_progress "
                 "WHEN NEW.quest_id LIKE 'weekly_reward_%' BEGIN SELECT RAISE(ABORT, 'weekly reward failure'); END")
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="weekly reward failure"):
        play("weekly_rewards", "领奖 9", op="weekly-failure")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress ORDER BY quest_id")) == before
    sql(game[1], "DROP TRIGGER reject_weekly_reward")
    result = play("weekly_rewards", "领奖 9", op="weekly-failure")
    assert "周行圆满已领取" in result.text()
