import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

NOW = 1_800_000_000  # 2027-01-15 16:00 Beijing


def keyboard_commands(reply):
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    return [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def day_line(reply, day):
    return next(line for line in reply.lines if line.startswith(f"1月{day}日 · "))


def test_current_month_marks_signed_future_and_missed_days(game, play):
    play("adopt", "青鸾", now=NOW)
    play("sign", now=NOW)
    page = play("checkin_calendar", now=NOW + 1)
    assert page.title == "签到月历 2027-01"
    assert "当前连续 1 天 · 历史最佳 1 天。" in page.lines[0]
    assert "本月已签 1/31 天" in page.lines[1]
    assert day_line(page, 15) == "1月15日 · 已签到"
    assert day_line(page, 14) == "1月14日 · 未签"
    assert day_line(page, 16) == "1月16日 · 未到"
    assert page.commands[0] == "灵宠签到奖励"


def test_history_month_and_navigation_commands(game, play):
    play("adopt", "青鸾", now=NOW)
    play("sign", now=NOW)
    with game[1].connect() as conn:
        conn.executemany(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            [("u1", f"signin_day_2026-12-{day:02d}") for day in (30, 31)],
        )
    past = play("checkin_calendar", "2026-12", now=NOW + 1)
    assert past.title == "签到月历 2026-12"
    december = [line for line in past.lines if line.startswith("12月")]
    assert "12月30日 · 已签到" in december
    assert "12月31日 · 已签到" in december
    assert "12月29日 · 未签" in december
    assert "本月已签 2/31 天" in past.lines[1]
    # Past months navigate back to the current month; no forward month exists.
    assert past.commands[0] == "灵宠签到月历 2027-01"
    assert past.commands[1] == "灵宠签到奖励"
    current = play("checkin_calendar", now=NOW + 1)
    # The current month only navigates to an earlier month when history exists.
    assert current.commands == ("灵宠签到月历 2026-12", "灵宠签到奖励")


def test_longest_streak_within_month_counts_only_that_month(game, play):
    play("adopt", "青鸾", now=NOW)
    with game[1].connect() as conn:
        conn.executemany(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            [("u1", f"signin_day_2026-12-{day:02d}") for day in range(28, 32)]
            + [("u1", "signin_day_2027-01-01"), ("u1", "signin_day_2027-01-02")],
        )
    past = play("checkin_calendar", "2026-12", now=NOW + 1)
    assert "本月最长连续 4 天" in past.lines[1]
    assert "当前连续 0 天 · 历史最佳 6 天。" in past.lines[0]
    current = play("checkin_calendar", now=NOW + 1)
    assert "本月最长连续 2 天" in current.lines[1]


def test_legacy_account_shows_only_its_last_sign_day(game, play):
    play("adopt", "青鸾", now=NOW)
    sql = game[1]
    with sql.connect() as conn:
        conn.execute("UPDATE players SET sign_day='2026-11-20' WHERE user_id='u1'")
    page = play("checkin_calendar", "2026-11", now=NOW + 1)
    assert "11月20日 · 已签到" in page.lines
    assert "11月19日 · 未签" in page.lines
    assert "本月已签 1/30 天" in page.lines[1]


def test_unregistered_browse_is_read_only(game, play):
    page = play("checkin_calendar", user="u9", now=NOW)
    assert page.title == "签到月历 2027-01"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    from .support import sql

    assert sql(game[1], "SELECT user_id FROM players") == []


def test_invalid_month_arguments_are_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    for argument in ("2027-13", "2027-1", "abc", "2027/01", "2027-00"):
        with pytest.raises(GameError):
            play("checkin_calendar", argument, now=NOW + 1)
    with pytest.raises(GameError, match="尚未到来"):
        play("checkin_calendar", "2027-02", now=NOW + 1)


def test_rewards_page_links_calendar_and_native_keyboard_stays_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    rewards = play("checkin_rewards", now=NOW)
    assert "灵宠签到月历" in rewards.commands
    page = play("checkin_calendar", now=NOW + 1)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = keyboard_commands(page)
    assert len(buttons) <= 4
    assert buttons[0] == "灵宠签到奖励"
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_calendar_and_month_argument_parse():
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠签到月历") == ("checkin_calendar", "")
    assert handlers._parse("灵宠签到月历 2026-12") == ("checkin_calendar", "2026-12")
    assert handlers._parse("灵宠签到月历 2026-12 ") == ("checkin_calendar", "2026-12")
