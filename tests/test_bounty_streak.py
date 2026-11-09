"""Bounty streak: full-clear days chain, milestones pay once."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import bounty
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from datetime import datetime, timedelta, timezone

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


CST = timezone(timedelta(hours=8))


def late_night(now=NOW):
    """23:59 Beijing time on the day containing ``now``."""
    day = datetime.fromtimestamp(now, CST).date()
    return int(datetime(day.year, day.month, day.day, 23, 59, tzinfo=CST).timestamp())


def bounty_snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(
            store,
            "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
            " ORDER BY user_id, quest_id",
        ),
    )


def test_midnight_boundary_counts_as_two_consecutive_days(game, play):
    """23:59 then 00:01 is two days, not a 24h delta."""
    play("adopt", "青鸾", now=NOW, op="mid-adopt")
    first = late_night(NOW)
    clear_day(game, play, first)
    assert bounty.streak(ctx_of(game, first)) == 1
    clear_day(game, play, first + 120)
    assert bounty.streak(ctx_of(game, first + 120)) == 2


def test_partial_clear_does_not_advance_the_streak(game, play):
    play("adopt", "青鸾", now=NOW, op="partial-adopt")
    seed_progress(game, NOW)
    offered = bounty.todays(ctx_of(game, NOW))
    play("bounty", f"领取 {offered[0].name}", now=NOW, op="partial-1")
    play("bounty", f"领取 {offered[1].name}", now=NOW + 1, op="partial-2")
    assert bounty.streak(ctx_of(game, NOW)) == 0
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id='bounty_streak_day'") == []
    play("bounty", f"领取 {offered[2].name}", now=NOW + 2, op="partial-3")
    assert bounty.streak(ctx_of(game, NOW + 3)) == 1


def test_duplicate_claim_keeps_the_streak_at_one(game, play):
    play("adopt", "青鸾", now=NOW, op="dup-adopt")
    clear_day(game, play, NOW)
    first = bounty.todays(ctx_of(game, NOW))[0]
    with pytest.raises(GameError, match="今日已领取"):
        play("bounty", f"领取 {first.name}", now=NOW + 1, op="dup-new-op")
    assert bounty.streak(ctx_of(game, NOW + 1)) == 1


def test_replayed_claim_returns_cached_reply_and_keeps_streak(game, play):
    play("adopt", "青鸾", now=NOW, op="replay-adopt")
    seed_progress(game, NOW)
    target = bounty.todays(ctx_of(game, NOW))[0]
    first = play("bounty", f"领取 {target.name}", now=NOW, op="replay-claim")
    again = play("bounty", f"领取 {target.name}", now=NOW + 1, op="replay-claim")
    assert again == first
    assert bounty.streak(ctx_of(game, NOW + 2)) == 0


def test_milestone_refusals_are_transaction_safe(game, play):
    play("adopt", "青鸾", now=NOW, op="safe-adopt")
    clear_day(game, play, NOW)  # streak 1, below every tier
    before = bounty_snapshot(game[1])
    with pytest.raises(GameError, match="尚未达成"):
        play("bounty", "连击领奖 3", now=NOW + 1, op="safe-below")
    with pytest.raises(GameError, match="档位可选"):
        play("bounty", "连击领奖 5", now=NOW + 2, op="safe-tier")
    with pytest.raises(GameError, match="格式"):
        play("bounty", "连击领奖", now=NOW + 3, op="safe-format")
    assert bounty_snapshot(game[1]) == before
