"""Endgame mastery: the six weekly systems feed achievements, a title and 灵宠目标.

Every metric here is derived from per-week markers those systems already write, so
these tests care about two things: each metric counts only its own marker shape
(never a bonus marker, never another system's rows, never another player's), and
none of the pages that read them write anything.
"""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import achievements, titles
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "endgame")


def metric(game, name, user="u1"):
    return achievements._metric(context(game, user), user, name)


def metric_for(game, play, name, user="u1"):
    account(play, user)
    return metric(game, name, user)


def account(play, user="u1"):
    """quest_progress.user_id is a foreign key onto players, so adopt first."""
    play("adopt", "青鸾", user=user)


def mark(game, key, progress=1, claimed=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, key, progress, claimed),
    )


# ---------------------------------------------------------------- derivation

def test_duel_wins_counts_weekly_markers(game, play):
    account(play)
    mark(game, "duel_week_1700000000_songfeng")
    mark(game, "duel_week_1700000000_shiquan")
    mark(game, "duel_week_1700604800_songfeng")
    assert metric(game, "duel_wins") == 3
    # A live bout's state rows are not wins.
    mark(game, "duel_target", progress=2)
    mark(game, "duel_round", progress=3)
    assert metric(game, "duel_wins") == 3


def test_gauntlet_rounds_excludes_the_clear_bonus(game, play):
    account(play)
    mark(game, "gauntlet_1700000000_1")
    mark(game, "gauntlet_1700000000_2")
    mark(game, "gauntlet_1700000000_all")
    # A second ladder namespaces its keys with the ladder id.
    mark(game, "gauntlet_high_gauntlet_1700000000_1")
    assert metric(game, "gauntlet_rounds") == 3


def test_escort_full_counts_only_full_grades(game, play):
    account(play)
    mark(game, "escort_1700000000_medicine_run", progress=2)
    mark(game, "escort_1700000000_frost_escort", progress=1)   # partial
    mark(game, "escort_1700000000_dragon_road", progress=2)
    assert metric(game, "escort_full") == 2


def test_team_trial_clears_counts_weekly_clears(game, play):
    account(play)
    mark(game, "team_trial_1700000000_thunder_raid", progress=6)
    mark(game, "team_trial_1700604800_tide_hunt", progress=7)
    assert metric(game, "team_trial_clears") == 2


def test_forbidden_depths_excludes_the_all_clear_marker(game, play):
    account(play)
    mark(game, "forbidden_1700000000_ember_crypt_1")
    mark(game, "forbidden_1700000000_ember_crypt_2")
    mark(game, "forbidden_1700000000_all")
    assert metric(game, "forbidden_depths") == 2


def test_tribulation_slots_excludes_the_sweep_marker(game, play):
    account(play)
    mark(game, "trib_1700000000_1")
    mark(game, "trib_1700000000_2")
    mark(game, "trib_1700000000_all")
    assert metric(game, "tribulation_slots") == 2


def test_codex_week_clears_excludes_the_weekly_bonus(game, play):
    account(play)
    mark(game, "codex_week_1700000000_1")
    mark(game, "codex_week_1700000000_2")
    mark(game, "codex_week_all_1700000000")
    # Per-species trials are permanent, not the weekly rotation.
    mark(game, "codex_trial_qingluan", progress=4)
    assert metric(game, "codex_week_clears") == 2


def test_every_metric_is_isolated_per_player(game, play):
    account(play)
    account(play, 'u2')
    mark(game, "duel_week_1700000000_songfeng")
    mark(game, "gauntlet_1700000000_1")
    assert metric(game, "duel_wins", user="u2") == 0
    assert metric(game, "gauntlet_rounds", user="u2") == 0


def test_every_shipped_system_metric_is_zero_without_rows(game, play):
    account(play)
    for name in achievements.ENDGAME_MARKERS:
        assert metric(game, name) == 0


def test_every_endgame_metric_has_achievements(game):
    used = {entry.metric for entry in game[0].content.achievements.values()}
    assert set(achievements.ENDGAME_MARKERS) <= used


# ---------------------------------------------------------------- content

def test_each_new_metric_has_a_first_and_a_later_rung(game):
    for name in achievements.ENDGAME_MARKERS:
        targets = sorted(
            entry.target for entry in game[0].content.achievements.values() if entry.metric == name
        )
        assert len(targets) >= 2, name
        assert targets[0] == 1, name
        assert targets == sorted(set(targets)), name


def test_the_new_achievements_reward_only_shipped_items(game):
    content = game[0].content
    for entry in content.achievements.values():
        if entry.metric not in achievements.ENDGAME_MARKERS:
            continue
        assert entry.reward.stones > 0
        assert all(item in content.items for item in entry.reward.items)


def test_the_fellowship_title_uses_an_endgame_metric(game):
    title = next(t for t in game[0].content.titles.values() if t.id == "fellowship_veteran")
    assert title.metric in achievements.ENDGAME_MARKERS
    assert title.order == max(t.order for t in game[0].content.titles.values())


# ---------------------------------------------------------------- claim path

def test_an_endgame_achievement_can_be_claimed_once(game, play):
    play("adopt", "青鸾")
    mark(game, "duel_week_1700000000_songfeng")
    stones = player(game[1])["stones"]
    reply = play("achievement_claim", "斗法初胜")
    assert "斗法初胜" in reply.text()
    assert player(game[1])["stones"] > stones
    with pytest.raises(GameError):
        play("achievement_claim", "斗法初胜")


# ---------------------------------------------------------------- objectives

def test_the_endgame_line_summarises_systems_and_claims(game, play):
    play("adopt", "青鸾")
    assert "终局记录：0/6 个周常体系有通关记录" in play("objectives").text()
    mark(game, "duel_week_1700000000_songfeng")
    mark(game, "forbidden_1700000000_ember_crypt_1")
    page = play("objectives").text()
    assert "终局记录：2/6 个周常体系有通关记录" in page
    assert "斗法" in page and "禁地" in page
    assert "终局成就 2/" in page


def test_the_endgame_line_is_read_only(game, play):
    play("adopt", "青鸾")
    mark(game, "duel_week_1700000000_songfeng")
    before = sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY quest_id")
    stones = player(game[1])["stones"]
    play("objectives")
    after = sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY quest_id")
    assert after == before
    assert player(game[1])["stones"] == stones


def test_the_title_unlocks_at_its_threshold(game, play):
    play("adopt", "青鸾")
    for index in range(15):
        mark(game, f"team_trial_{1700000000 + index * 604800}_thunder_raid", progress=6)
    assert metric(game, "team_trial_clears") == 15
    page = play("titles").text()
    assert "同阵共济" in page
    earned = [
        title.name for title in game[0].content.titles.values()
        if title.id == "fellowship_veteran"
    ]
    assert earned == ["同阵共济"]
    assert "已获得" in page
