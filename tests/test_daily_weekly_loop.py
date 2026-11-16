from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql
from .test_targeted_care import snapshot

NOW = beijing_week(1_800_000_000)[0] + 3600


def earn_day(play, now):
    play("sign", now=now)
    play("bond", "1", now=now)
    play("claim", "晨光初至", now=now, op=f"daily-sign-{now}")
    play("claim", "灵契相伴", now=now, op=f"daily-bond-{now}")


def test_three_days_of_real_daily_actions_unlock_two_weeklies_and_cumulative_reward(game, play):
    play("adopt", "青鸾", now=NOW)
    for day in range(3):
        earn_day(play, NOW + day * 86400)
    now = NOW + 2 * 86400
    page = play("weekly_quests", "4", now=now)
    assert "课业六成：6/6（可领取）" in page.text()
    assert "三日不辍：3/3（可领取）" in page.text()
    for link in page.inline_commands:
        if link.label == "领取奖励":
            play(*handlers._parse(link.command), now=now)
    tier = play("weekly_rewards", now=now)
    command = next(link.command for link in tier.inline_commands if "领奖 2" in link.command)
    before = player(game[1])["stones"], items(game[1])["spirit_food"]
    play(*handlers._parse(command), now=now)
    assert (player(game[1])["stones"], items(game[1])["spirit_food"]) == (before[0] + 120, before[1] + 2)
    assert len(sql(game[1], "SELECT * FROM duel_actions WHERE json_extract(snapshot,'$.kind')='daily_quest_claim'")) == 6


def test_daily_page_previews_and_projects_new_day_without_erasing_history(game, play):
    before = snapshot(game[1])
    assert "尚未结契" in play("quests", now=NOW).text()
    assert snapshot(game[1]) == before
    play("adopt", now=NOW)
    earn_day(play, NOW)
    before = snapshot(game[1])
    page = play("quests", now=NOW + 86400)
    assert "晨光初至：0/1（进行中）" in page.text()
    assert snapshot(game[1]) == before
    assert "系统日期" in play("quests", now=NOW - 86400).text()


def test_daily_and_weekly_receipts_survive_restart_date_rollover_and_old_messages(game, play):
    play("adopt", now=NOW)
    for day in range(3):
        earn_day(play, NOW + day * 86400)
    now = NOW + 2 * 86400
    week_claim = play("weekly_quest_claim", "课业六成", now=now, op="weekly-loop-claim")
    daily_claim = play("claim", "晨光初至", now=NOW, op=f"daily-sign-{NOW}")
    old_link = next(link.command for link in play("weekly_quests", "4", now=now).inline_commands
                    if "三日不辍" in link.command)
    daily_link = next(link.command for link in play("quests", now=now + 86400).inline_commands
                      if link.command == "灵宠签到")
    assert daily_link
    sql(game[1], "DELETE FROM operations")
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    before = snapshot(game[1])
    next_week = beijing_week(now)[1] + 3600
    assert reopened.execute("u1", "claim", "晨光初至", f"daily-sign-{NOW}", next_week) == daily_claim
    assert reopened.execute("u1", "weekly_quest_claim", "课业六成", "weekly-loop-claim", next_week) == week_claim
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="跨周"):
        play(*handlers._parse(old_link), now=next_week)
    with pytest.raises(GameError, match="系统日期"):
        play("claim", "温养灵契", now=NOW - 86400)
    assert "课业六成：0/6（未达成）" in play("weekly_quests", "4", now=next_week).text()
    with pytest.raises(GameError, match="系统日期"):
        play("weekly_quest_claim", "课业六成", now=NOW - 7 * 86400)


def test_daily_and_weekly_rewards_are_atomic_and_concurrent_claims_pay_once(game, play, monkeypatch):
    play("adopt", now=NOW)
    play("sign", now=NOW)
    before = snapshot(game[1])
    original = Repository.record_duel_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError, match="receipt failure"):
            play("claim", "晨光初至", now=NOW, op="retry-daily")
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='retry-daily'") == []
    play("claim", "晨光初至", now=NOW, op="retry-daily")
    play("bond", "1", now=NOW)
    play("claim", "灵契相伴", now=NOW)
    for day in (1, 2):
        earn_day(play, NOW + day * 86400)
    now = NOW + 2 * 86400
    before = snapshot(game[1])
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError, match="receipt failure"):
            play("weekly_quest_claim", "课业六成", now=now, op="retry-weekly")
    assert snapshot(game[1]) == before

    def attempt(index):
        try:
            return play("weekly_quest_claim", "课业六成", now=now, op=f"week-race-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    reward = game[0].content.weekly_quests["weekly_daily_claims"].reward
    assert player(game[1])["stones"] == before["players"][0]["stones"] + reward.stones.minimum


def test_daily_claim_link_cannot_claim_a_different_day(game, play):
    play("adopt", now=NOW)
    play("sign", now=NOW)
    command = next(link.command for link in play("quests", now=NOW).inline_commands if link.label == "领取奖励")
    assert command.endswith(f"日 {beijing_day(NOW)}")
    play("sign", now=NOW + 86400)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="跨日"):
        play(*handlers._parse(command), now=NOW + 86400)
    assert snapshot(game[1]) == before
