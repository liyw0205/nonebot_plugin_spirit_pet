"""灵宠签到全勤: a completed month signed end to end pays once."""

import calendar
from datetime import date, timedelta

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import checkin_full
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import player_uid, sql

NOW = 1_800_000_000


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


def today() -> date:
    return date.fromisoformat(beijing_day(NOW))


def previous_month() -> tuple[int, int]:
    first = today().replace(day=1)
    prior = first - timedelta(days=1)
    return prior.year, prior.month


def seed_month(store, user_id: str, year: int, month: int, skip: int | None = None) -> None:
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        if day == skip:
            continue
        sql(
            store,
            "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed)"
            " VALUES (?, ?, 1, 1)",
            (user_id, f"signin_day_{year:04d}-{month:02d}-{day:02d}"),
        )


def stones(store, user_id="u1") -> int:
    return sql(store, "SELECT stones FROM players WHERE user_id=?", (user_id,))[0]["stones"]


def items(store, user_id="u1") -> dict:
    return {
        row["item_id"]: row["quantity"]
        for row in sql(store, "SELECT item_id, quantity FROM inventory WHERE user_id=?", (user_id,))
    }


def test_page_lists_recent_months_without_claims(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    page = play("checkin_full", now=NOW, op="full-page")
    assert page.title == "签到全勤"
    year, month = previous_month()
    assert any(line.startswith(f"{year:04d}-{month:02d} · 已签 0/") for line in page.lines)
    assert not page.inline_commands


def test_full_month_pays_once(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    uid = "u1"
    year, month = previous_month()
    seed_month(game[1], uid, year, month)
    before_stones = stones(game[1])
    before_items = items(game[1])

    page = play("checkin_full", now=NOW, op="full-page-2")
    total = calendar.monthrange(year, month)[1]
    assert any(
        f"{year:04d}-{month:02d} · 已签 {total}/{total} 天 · 可领取" in line for line in page.lines
    )
    assert [link.command for link in page.inline_commands] == [
        f"灵宠签到全勤 领奖 {year:04d}-{month:02d}"
    ]

    result = play("checkin_full", f"领奖 {year:04d}-{month:02d}", now=NOW, op="full-claim")
    assert "奖励已领取" in result.text()
    assert stones(game[1]) == before_stones + checkin_full.STONES
    after_items = items(game[1])
    for item_id, amount in checkin_full.ITEMS.items():
        assert after_items.get(item_id, 0) == before_items.get(item_id, 0) + amount

    row = sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (uid, checkin_full.claim_id(year, month)),
    )[0]
    assert row == {"progress": total, "claimed": 1}

    with pytest.raises(GameError, match="已领取"):
        play("checkin_full", f"领奖 {year:04d}-{month:02d}", now=NOW + 1, op="full-again")


def test_bare_claim_picks_newest_eligible(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    uid = "u1"
    year, month = previous_month()
    seed_month(game[1], uid, year, month)
    assert "奖励已领取" in play("checkin_full", "领奖", now=NOW, op="full-bare").text()


def test_one_missing_day_blocks_the_claim(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    uid = "u1"
    year, month = previous_month()
    seed_month(game[1], uid, year, month, skip=5)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="尚未全勤"):
        play("checkin_full", f"领奖 {year:04d}-{month:02d}", now=NOW, op="full-gap")
    assert snapshot(game[1]) == before
    assert not play("checkin_full", now=NOW + 1, op="full-gap-page").inline_commands


def test_current_month_is_never_eligible(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    uid = "u1"
    current = today()
    seed_month(game[1], uid, current.year, current.month)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="尚未结束"):
        play(
            "checkin_full", f"领奖 {current.year:04d}-{current.month:02d}",
            now=NOW, op="full-current",
        )
    assert snapshot(game[1]) == before


def test_malformed_month_and_no_eligible_month(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="格式"):
        play("checkin_full", "领奖 2026-1", now=NOW, op="full-bad")
    with pytest.raises(GameError, match="没有可领取"):
        play("checkin_full", "领奖", now=NOW, op="full-none")
    expect = snapshot(game[1])
    assert [row["quest_id"] for row in expect[2]] == [row["quest_id"] for row in before[2]]
    assert expect[0] == before[0] and expect[1] == before[1]


def test_page_reports_claimed_month(game, play):
    play("adopt", "青鸾", now=NOW, op="full-adopt")
    uid = "u1"
    year, month = previous_month()
    seed_month(game[1], uid, year, month)
    play("checkin_full", f"领奖 {year:04d}-{month:02d}", now=NOW, op="full-claim-2")
    page = play("checkin_full", now=NOW + 60, op="full-page-3")
    assert any(f"{year:04d}-{month:02d} · 已签" in line and "已领取" in line for line in page.lines)
    assert not page.inline_commands
