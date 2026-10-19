import json

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000  # 2027-01-15 Beijing
SEASON = "2027-01"


def seed_match(game, challenger, target, *, winner, played, season=SEASON, operation=None):
    snapshot = game[0].content.arena.model_dump_json()
    sql(game[1], (
        "INSERT INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(season_id) DO NOTHING"
    ), (season, NOW - 86400 * 20, NOW + 86400 * 10, played, snapshot))
    challenger_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (challenger,),
    )[0]["pet_id"]
    target_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (target,),
    )[0]["pet_id"]
    sql(game[1], (
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'r')"
    ), (season, challenger, target, challenger_pet, target_pet, winner, season, played,
        0 if winner is None else 20,
        operation or f"op-{season}-{played}-{challenger}-{target}-{winner or 'draw'}"))


def streak_page(play):
    page = play("pvp_streak_rewards")
    return page


def milestone_row(page, streak):
    return next(line for line in page.lines if line.startswith(f"{streak} 连胜 · "))


def test_streak_counts_both_perspectives_and_survives_seasons(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    # u1 challenges and wins twice, then defends (u2 challenges) and wins again.
    seed_match(game, "u1", "u2", winner="u1", played=NOW)
    seed_match(game, "u1", "u2", winner="u1", played=NOW + 1)
    seed_match(game, "u2", "u1", winner="u1", played=NOW + 2)
    page = play("pvp_streak_rewards", now=NOW + 3)
    assert "当前 3 连胜 · 历史最佳 3 连胜。" in page.lines[0]
    assert milestone_row(page, "3").endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠连胜领奖 3"]


def test_draw_pauses_streak_but_keeps_best(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index, winner in enumerate(("u1", "u1", None, "u1")):
        seed_match(game, "u1", "u2", winner=winner, played=NOW + index, operation=f"dr-{index}")
    page = play("pvp_streak_rewards", now=NOW + 4)
    # W W D W: the draw pauses the momentum (当前无连胜 right after it) but the
    # trailing win restarts a 1-run; the historical best keeps the 3-win run.
    assert "当前 1 连胜 · 历史最佳 3 连胜。" in page.lines[0]


def test_loss_breaks_streak_but_claimed资格_remains(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index, winner in enumerate(("u1", "u1", "u1", "u2")):
        seed_match(game, "u1", "u2", winner=winner, played=NOW + index, operation=f"ls-{index}")
    page = play("pvp_streak_rewards", now=NOW + 4)
    assert "当前 1 连败 · 历史最佳 3 连胜。" in page.lines[0]
    assert milestone_row(page, "3").endswith("可领取")
    result = play("pvp_streak_claim", "3", now=NOW + 5, op="streak-claim-3")
    assert "3 连胜里程碑「初露锋芒」已领取。" in result.lines[0]
    assert sql(game[1],
        "SELECT progress, claimed FROM quest_progress WHERE quest_id='pvp_streak_3'",
    ) == [{"progress": 3, "claimed": 1}]
    # After a loss the reached milestone stays claimable/claimed, never withdrawn.
    after = play("pvp_streak_rewards", now=NOW + 6)
    assert milestone_row(after, "3").endswith("已领取")


def test_all_milestones_grant_once_with_persistent_credentials(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    # 20 straight wins for u1 (alternating perspectives to exercise both sides).
    for index in range(20):
        if index % 2 == 0:
            seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"w{index}")
        else:
            seed_match(game, "u2", "u1", winner="u1", played=NOW + index, operation=f"w{index}")
    before = player(game[1])["stones"]
    for streak in (3, 5, 10, 20):
        result = play("pvp_streak_claim", str(streak), now=NOW + 30, op=f"sc-{streak}")
        assert f"{streak} 连胜里程碑" in result.lines[0]
        assert play("pvp_streak_claim", str(streak), now=NOW + 30, op=f"sc-{streak}") == result
    assert sql(game[1],
        "SELECT quest_id, progress, claimed FROM quest_progress WHERE quest_id LIKE 'pvp_streak_%' ORDER BY quest_id",
    ) == [
        {"quest_id": "pvp_streak_10", "progress": 20, "claimed": 1},
        {"quest_id": "pvp_streak_20", "progress": 20, "claimed": 1},
        {"quest_id": "pvp_streak_3", "progress": 20, "claimed": 1},
        {"quest_id": "pvp_streak_5", "progress": 20, "claimed": 1},
    ]
    assert player(game[1])["stones"] == before + 150 + 350 + 800 + 1800
    assert items(game[1])["breakthrough_pill"] == 1


def test_claim_rejects_unknown_unreached_and_duplicate(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    with pytest.raises(GameError, match="格式：灵宠连胜领奖"):
        play("pvp_streak_claim", "4", now=NOW)
    with pytest.raises(GameError, match="尚未达成 3 连胜"):
        play("pvp_streak_claim", "3", now=NOW)
    seed_match(game, "u1", "u2", winner="u1", played=NOW, operation="one-win")
    seed_match(game, "u1", "u2", winner="u1", played=NOW + 1, operation="two-win")
    seed_match(game, "u1", "u2", winner="u1", played=NOW + 2, operation="three-win")
    play("pvp_streak_claim", "3", now=NOW + 3, op="claim-3")
    with pytest.raises(GameError, match="已领取"):
        play("pvp_streak_claim", "3", now=NOW + 3, op="claim-3-again")


def test_missing_reward_definition_rolls_back(game, play):
    from dataclasses import replace
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(3):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"mr-{index}")
    original = game[0].content
    game[0].content = replace(
        original,
        items={key: value for key, value in original.items.items() if key != "spirit_food"},
    )
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="物品定义缺失或类型错误"):
        play("pvp_streak_claim", "3", now=NOW + 4, op="rollback-streak")
    assert player(game[1])["stones"] == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='pvp_streak_3'")


def test_unregistered_read_only_and_argument_rejection(game, play):
    page = play("pvp_streak_rewards", user="u9", now=NOW)
    assert page.title == "论剑连胜奖励"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="不接受参数"):
        play("pvp_streak_rewards", "3", now=NOW)


def test_season_page_shows_momentum_and_links(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    seed_match(game, "u1", "u2", winner="u1", played=NOW)
    season = play("season", now=NOW + 1)
    assert "连胜势头：当前 1 连胜。" in season.text()
    assert "灵宠连胜奖励" in season.text()
    assert any(link.command == "灵宠连胜奖励" for link in season.inline_commands)


def test_objectives_hub_reports_streak_line(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(3):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"hub-{index}")
    hub = play("objectives", now=NOW + 4)
    assert "论剑连胜：可领 1 档（3 连胜）· 历史最佳 3 连胜" in hub.text()


def test_native_keyboard_clean_and_parse(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(3):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"nk-{index}")
    page = play("pvp_streak_rewards", now=NOW + 4)
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

    assert handlers._parse("灵宠连胜奖励") == ("pvp_streak_rewards", "")
    assert handlers._parse("灵宠连胜领奖 5") == ("pvp_streak_claim", "5")
    assert handlers._parse("灵宠论剑战绩 10001") == ("pvp_head_to_head", "10001")
