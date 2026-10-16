from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.checkin_rewards import MILESTONES, claim_id

from .support import items, player, sql

BEIJING = timezone(timedelta(hours=8))
NOW = 1_800_000_000


def sign_days(play, count, *, start=NOW):
    replies = []
    for offset in range(count):
        replies.append(play("sign", now=start + offset * 86_400, op=f"sign-day-{offset}"))
    return replies


def test_catalog_previews_without_creating_an_account(game, play):
    reply = play("checkin_rewards", user="u9")
    assert reply.title == "连续签到奖励"
    assert [line.split(" 天 · ", 1)[0] for line in reply.lines[:4]] == ["3", "7", "14", "30"]
    assert "尚未结契" in reply.lines[-1]
    assert reply.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_sign_records_beijing_day_and_keeps_daily_quest_reward(game, play):
    play("adopt", "青鸾", now=NOW)
    reply = play("sign", now=NOW, op="first-sign")
    assert reply.title == "今日仙缘"
    assert "修为 +0，灵石 +200" in reply.lines
    assert "连续签到：当前 1 天 · 历史最佳 1 天。" in reply.lines
    assert reply.inline_commands[0].command == "灵宠签到奖励"
    assert reply.inline_commands[0].line == 2
    assert reply.commands == ("我的灵宠", "灵宠签到", "灵宠修炼", "灵宠历练")
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='signin_day_2027-01-15'") == [
        {"progress": 1},
    ]
    assert "晨光初至：1/1（可领取）" in play("quests", now=NOW).text()

    replay = play("sign", now=NOW, op="first-sign")
    assert replay == reply
    with pytest.raises(GameError, match="今日已领取仙缘"):
        play("sign", now=NOW + 1)


def test_sign_streak_crosses_beijing_midnight_and_breaks_after_a_missed_day(game, play):
    start = int(datetime(2027, 1, 15, 23, 59, tzinfo=BEIJING).timestamp())
    play("adopt", "青鸾", now=start)
    first = play("sign", now=start, op="late-sign")
    second = play("sign", now=start + 60, op="midnight-sign")
    assert "连续签到：当前 1 天 · 历史最佳 1 天。" in first.lines
    assert "连续签到：当前 2 天 · 历史最佳 2 天。" in second.lines
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'signin_day_%' ORDER BY quest_id") == [
        {"quest_id": "signin_day_2027-01-15"},
        {"quest_id": "signin_day_2027-01-16"},
    ]

    after_gap = play("checkin_rewards", now=start + 3 * 86_400)
    assert after_gap.lines[0] == "当前连续 0 天 · 历史最佳 2 天。"
    restarted = play("sign", now=start + 3 * 86_400, op="restart-sign")
    assert "连续签到：当前 1 天 · 历史最佳 2 天。" in restarted.lines


def test_historical_milestone_stays_claimable_after_a_streak_break(game, play):
    play("adopt", "青鸾", now=NOW)
    sign_days(play, 3)
    page = play("checkin_rewards", now=NOW + 2 * 86_400)
    assert page.lines[0] == "当前连续 3 天 · 历史最佳 3 天。"
    assert page.lines[1].endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠签到领奖 3"]

    broken = play("checkin_rewards", now=NOW + 4 * 86_400)
    assert broken.lines[0] == "当前连续 0 天 · 历史最佳 3 天。"
    assert broken.lines[1].endswith("可领取")
    hub = play("objectives", now=NOW + 4 * 86_400)
    assert hub.lines[0] == (
        "连续签到：可领 1 档（3 天）· 当前 0 天/最佳 3 天"
    )
    assert hub.inline_commands[0].line == 0
    assert hub.inline_commands[0].command == "灵宠签到奖励"

    before = player(game[1])["stones"]
    before_items = items(game[1])
    reward = play("checkin_reward_claim", "3", now=NOW + 4 * 86_400, op="streak-claim")
    assert reward.title == "连续签到奖励"
    assert player(game[1])["stones"] == before + 100
    assert items(game[1])["spirit_food"] == before_items.get("spirit_food", 0) + 1
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?", (claim_id(3),)) == [
        {"progress": 3, "claimed": 1},
    ]
    assert play("checkin_reward_claim", "3", now=NOW + 4 * 86_400, op="streak-claim") == reward
    with pytest.raises(GameError, match="3 天连续签到奖励已领取"):
        play("checkin_reward_claim", "3", now=NOW + 4 * 86_400)


def test_all_milestones_grant_once_at_their_thresholds(game, play):
    play("adopt", "青鸾", now=NOW)
    for offset in range(30):
        reply = play("sign", now=NOW + offset * 86_400, op=f"long-streak-{offset}")
        assert f"连续签到：当前 {offset + 1} 天 · 历史最佳 {offset + 1} 天。" in reply.lines

    for days, name, stones, reward_items in MILESTONES:
        page = play("checkin_rewards", now=NOW + 29 * 86_400)
        line = next(entry for entry in page.lines if entry.startswith(f"{days} 天 ·"))
        assert line.endswith("可领取")
        before_stones = player(game[1])["stones"]
        before_items = items(game[1])
        result = play("checkin_reward_claim", str(days), now=NOW + 29 * 86_400, op=f"milestone-{days}")
        assert result.lines[0] == f"{days} 天里程碑「{name}」已领取。"
        assert player(game[1])["stones"] == before_stones + stones
        for item, amount in reward_items.items():
            assert items(game[1])[item] == before_items.get(item, 0) + amount
        assert play("checkin_reward_claim", str(days), now=NOW + 29 * 86_400, op=f"milestone-{days}") == result


@pytest.mark.parametrize("argument", ["", "5", "03", "three"])
def test_claim_rejects_unknown_or_unreached_milestones(game, play, argument):
    play("adopt", "青鸾", now=NOW)
    sign_days(play, 2)
    if argument == "":
        with pytest.raises(GameError, match="格式：灵宠签到领奖"):
            play("checkin_reward_claim", argument, now=NOW + 86_400)
    elif argument == "5" or argument == "03" or argument == "three":
        with pytest.raises(GameError, match="格式：灵宠签到领奖"):
            play("checkin_reward_claim", argument, now=NOW + 86_400)

    with pytest.raises(GameError, match="尚未达成 3 天里程碑"):
        play("checkin_reward_claim", "3", now=NOW + 86_400)
    assert not sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'signin_reward_%'")


def test_missing_reward_definition_rolls_back_without_claiming(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    sign_days(play, 3)
    before = player(game[1])["stones"]
    monkeypatch.delitem(game[0].content.items, "spirit_food")
    with pytest.raises(GameError, match="连续签到奖励物品定义缺失"):
        play("checkin_reward_claim", "3", now=NOW + 2 * 86_400)
    assert player(game[1])["stones"] == before
    assert not sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id=?", (claim_id(3),))


def test_concurrent_claims_are_serialized(game, play):
    play("adopt", "青鸾", now=NOW)
    sign_days(play, 3)
    before = player(game[1])["stones"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(play, "checkin_reward_claim", "3", now=NOW + 2 * 86_400, op=f"parallel-{index}")
            for index in range(2)
        ]
        results = [future.exception() for future in futures]
    assert sum(error is None for error in results) == 1
    assert sum(isinstance(error, GameError) for error in results) == 1
    assert player(game[1])["stones"] == before + 100


def test_catalog_rejects_extra_arguments_and_help_exposes_both_commands(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="灵宠签到奖励 不接受参数"):
        play("checkin_rewards", "1", now=NOW)
    help_page = play("help", "成长", now=NOW)
    assert "灵宠签到奖励" in help_page.text()
    assert "灵宠签到领奖 天数" in help_page.text()


def test_sign_in_reward_commands_parse_with_their_arguments():
    assert handlers._parse("灵宠签到奖励") == ("checkin_rewards", "")
    assert handlers._parse("灵宠签到领奖 14") == ("checkin_reward_claim", "14")
