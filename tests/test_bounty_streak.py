"""Bounty streak: full-clear days chain, milestones pay once."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import bounty
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400


def ctx_of(game, now=NOW, user="u1"):
    return Context(
        Repository(game[1].connect()),
        game[0].content,
        game[0].config,
        game[0].rng,
        user,
        now,
        f"probe-{user}",
    )


def seed_progress(game, now, amount=99, user="u1"):
    """Pretend every bounty metric was already reached today."""
    day = beijing_day(now)
    for metric in bounty.STAT_NAMES:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
            (user, f"stat_{metric}_day_{day}", amount),
        )


def clear_day(game, play, now, user="u1"):
    """Claim every bounty offered on that Beijing day."""
    seed_progress(game, now, user=user)
    for entry in bounty.todays(ctx_of(game, now, user)):
        play("bounty", f"领取 {entry.name}", user=user, now=now, op=f"clear-{entry.id}-{now}")


def test_full_clear_starts_and_extends_streak(game, play):
    play("adopt", "青鸾", now=NOW, op="streak-adopt")
    clear_day(game, play, NOW)
    assert bounty.streak(ctx_of(game, NOW)) == 1
    page = play("bounty", now=NOW + 1, op="streak-page-1")
    assert any(line.startswith("连击：1 天") for line in page.lines)

    clear_day(game, play, NOW + DAY)
    assert bounty.streak(ctx_of(game, NOW + DAY)) == 2
    assert "连击：2 天" in play("bounty", now=NOW + DAY + 1, op="streak-page-2").text()


def test_missing_a_day_resets_the_streak(game, play):
    play("adopt", "青鸾", now=NOW, op="reset-adopt")
    clear_day(game, play, NOW)
    clear_day(game, play, NOW + DAY)
    assert bounty.streak(ctx_of(game, NOW + DAY)) == 2
    # Skip a whole day, then finish the next one again.
    clear_day(game, play, NOW + 3 * DAY)
    assert bounty.streak(ctx_of(game, NOW + 3 * DAY)) == 1


def test_streak_milestone_pays_once(game, play):
    play("adopt", "青鸾", now=NOW, op="ms-adopt")
    for index in range(3):
        clear_day(game, play, NOW + index * DAY)
    assert bounty.streak(ctx_of(game, NOW + 2 * DAY)) == 3
    page = play("bounty", now=NOW + 2 * DAY + 1, op="ms-page")
    assert "连击 3 天奖励可领" in page.text()
    assert "灵宠赏金 连击领奖 3" in [link.command for link in page.inline_commands]

    before = player(game[1])["stones"]
    before_food = items(game[1])["spirit_food"]
    result = play("bounty", "连击领奖 3", now=NOW + 2 * DAY + 2, op="ms-claim")
    assert result.title == "赏金连击"
    assert player(game[1])["stones"] == before + 200
    assert items(game[1])["spirit_food"] == before_food + 2
    with pytest.raises(GameError, match="已领取"):
        play("bounty", "连击领奖 3", now=NOW + 2 * DAY + 3, op="ms-again")


def test_streak_claim_refuses_below_threshold_and_unknown_tier(game, play):
    play("adopt", "青鸾", now=NOW, op="refuse-adopt")
    clear_day(game, play, NOW)
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="尚未达成"):
        play("bounty", "连击领奖 7", now=NOW + 1, op="refuse-tier")
    with pytest.raises(GameError, match="档位可选"):
        play("bounty", "连击领奖 5", now=NOW + 2, op="refuse-unknown")
    with pytest.raises(GameError, match="格式"):
        play("bounty", "连击领奖", now=NOW + 3, op="refuse-format")
    assert player(game[1])["stones"] == stones


def test_objective_line_reports_streak(game, play):
    play("adopt", "青鸾", now=NOW, op="obj-adopt")
    clear_day(game, play, NOW)
    line = bounty.objective_line(ctx_of(game, NOW + 1), "u1")
    assert "连击 1 天" in line
