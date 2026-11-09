"""灵宠切磋周目标: spar battles feed three weekly goals, each paid once."""

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import spar_goals
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player_uid, sql

NOW = 1_800_000_000
WEEK = 7 * 86_400


def snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(
            store,
            "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
            " ORDER BY user_id, quest_id",
        ),
    )


def two_players(game, play, now=NOW):
    play("adopt", "青鸾", now=now, op="sg-adopt-1")
    play("adopt", "青鸾", user="u2", now=now, op="sg-adopt-2")


def spar(game, play, now=NOW, op="sg-spar"):
    play("spar", str(player_uid(game[1], "u2")), now=now, op=op)


def week_start(now=NOW):
    return beijing_week(now)[0]


def test_one_spar_counts_for_both_sides(game, play):
    two_players(game, play)
    spar(game, play)
    start = week_start()
    rows = {
        (row["user_id"], row["quest_id"]): row["progress"]
        for row in sql(
            game[1],
            "SELECT user_id, quest_id, progress FROM quest_progress WHERE quest_id LIKE 'spar_wk_%'",
        )
    }
    assert rows[("u1", f"spar_wk_battles_{start}")] == 1
    assert rows[("u2", f"spar_wk_battles_{start}")] == 1
    wins = [rows.get(("u1", f"spar_wk_wins_{start}"), 0), rows.get(("u2", f"spar_wk_wins_{start}"), 0)]
    assert sum(wins) == 1
    assert spar_goals.value(_ctx(game), "opponents", "u1") == 1
    assert spar_goals.value(_ctx(game), "opponents", "u2") == 1


def test_same_rival_counts_once(game, play):
    two_players(game, play)
    spar(game, play, op="sg-a")
    spar(game, play, now=NOW + 60, op="sg-b")
    assert spar_goals.value(_ctx(game), "battles", "u1") == 2
    assert spar_goals.value(_ctx(game), "opponents", "u1") == 1


def test_page_shows_progress_and_claim_link(game, play):
    two_players(game, play)
    spar(game, play, op="sg-page-a")
    spar(game, play, now=NOW + 60, op="sg-page-b")
    page = play("spar_goals", now=NOW + 120, op="sg-page")
    text = page.text()
    assert "交手 可领取" in text
    assert "胜场" in text and "对手 1/2" in text
    assert "灵宠切磋领奖 交手" in [link.command for link in page.inline_commands]


def test_goal_pays_once(game, play):
    two_players(game, play)
    spar(game, play, op="sg-claim-a")
    spar(game, play, now=NOW + 60, op="sg-claim-b")
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    food = items(game[1])["spirit_food"]
    result = play("spar_goal_claim", "交手", now=NOW + 120, op="sg-claim")
    assert result.title == "切磋周目标"
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones + 120
    assert items(game[1])["spirit_food"] == food + 1
    with pytest.raises(GameError, match="已经领取"):
        play("spar_goal_claim", "交手", now=NOW + 180, op="sg-claim-again")


def test_refusals_write_nothing(game, play):
    two_players(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="尚未达成"):
        play("spar_goal_claim", "胜场", now=NOW, op="sg-ref-1")
    with pytest.raises(GameError, match="目标可选"):
        play("spar_goal_claim", "不存在", now=NOW + 1, op="sg-ref-2")
    with pytest.raises(GameError, match="格式"):
        play("spar_goal_claim", now=NOW + 2, op="sg-ref-3")
    assert snapshot(game[1]) == before


def test_new_week_resets_progress(game, play):
    two_players(game, play)
    spar(game, play, op="sg-week-a")
    spar(game, play, now=NOW + 60, op="sg-week-b")
    assert spar_goals.value(_ctx(game), "battles", "u1") == 2
    later = _ctx(game, now=NOW + WEEK)
    assert spar_goals.value(later, "battles", "u1") == 0
    assert spar_goals.claimable(later, "u1") == []


def test_objectives_and_today(game, play):
    two_players(game, play)
    spar(game, play, op="sg-disc-a")
    spar(game, play, now=NOW + 60, op="sg-disc-b")
    objectives = play("objectives", now=NOW + 120, op="sg-obj")
    assert any(line.startswith("切磋：") for line in objectives.lines)
    today = play("today", now=NOW + 180, op="sg-today")
    assert "切磋目标可领" in today.text()


def _ctx(game, now=NOW, user="u1"):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(
        Repository(game[1].connect()),
        game[0].content,
        game[0].config,
        game[0].rng,
        user,
        now,
        f"probe-{user}",
    )
