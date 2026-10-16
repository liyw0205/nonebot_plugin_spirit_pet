import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.companionship_rewards import MILESTONES, claim_id

from .support import items, player, sql

NOW = 1_800_000_000


def bond_days(play, count, *, start=NOW):
    return [
        play("bond", now=start + offset * 86_400, op=f"bond-day-{offset}")
        for offset in range(count)
    ]


def _keyboard_buttons(message):
    return [
        button
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def _markdown_links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def test_catalog_previews_without_creating_a_player(game, play):
    reply = play("bond_rewards", user="u9", now=NOW)

    assert reply.title == "连续陪伴奖励"
    assert [line.split(" 天 · ", 1)[0] for line in reply.lines[:4]] == ["3", "7", "14", "30"]
    assert "尚未结契" in reply.lines[-1]
    assert reply.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_historical_qualification_survives_a_gap_and_claims_from_the_hub(game, play):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 3)

    now_after_gap = NOW + 5 * 86_400
    page = play("bond_rewards", now=now_after_gap)
    assert page.lines[0] == "当前连续 0 天 · 历史最佳 3 天。"
    assert page.lines[1].endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠陪伴领奖 3"]

    hub = play("objectives", now=now_after_gap)
    assert hub.lines[1] == "连续陪伴：可领 1 档（3 天）· 当前 0 天/最佳 3 天"
    assert hub.inline_commands[1].command == "灵宠陪伴奖励"

    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    reward = play("bond_reward_claim", "3", now=now_after_gap, op="bond-streak-claim")
    assert reward.title == "连续陪伴奖励"
    assert reward.lines[0] == "3 天里程碑「初识相伴」已领取。"
    assert player(game[1])["stones"] == before_stones + 80
    assert items(game[1])["spirit_food"] == before_items.get("spirit_food", 0) + 1
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(3),),
    ) == [{"progress": 3, "claimed": 1}]
    assert play("bond_reward_claim", "3", now=now_after_gap, op="bond-streak-claim") == reward
    with pytest.raises(GameError, match="3 天连续陪伴奖励已领取"):
        play("bond_reward_claim", "3", now=now_after_gap)


def test_each_milestone_grants_its_fixed_reward_once(game, play):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 30)
    page = play("bond_rewards", now=NOW + 29 * 86_400)
    assert [link.command for link in page.inline_commands] == [
        f"灵宠陪伴领奖 {days}" for days, _, _, _ in MILESTONES
    ]
    assert all(page.lines[link.line].endswith("可领取") for link in page.inline_commands)

    for days, name, stones, reward_items in MILESTONES:
        before_stones = player(game[1])["stones"]
        before_items = items(game[1])
        result = play("bond_reward_claim", str(days), now=NOW + 29 * 86_400, op=f"bond-reward-{days}")
        assert result.lines[0] == f"{days} 天里程碑「{name}」已领取。"
        assert player(game[1])["stones"] == before_stones + stones
        for item, amount in reward_items.items():
            assert items(game[1])[item] == before_items.get(item, 0) + amount
        assert play("bond_reward_claim", str(days), now=NOW + 29 * 86_400, op=f"bond-reward-{days}") == result


@pytest.mark.parametrize("argument", ["", "03", "5", "many"])
def test_claim_rejects_bad_arguments_and_unreached_milestones(game, play, argument):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 2)

    with pytest.raises(GameError, match="格式：灵宠陪伴领奖"):
        play("bond_reward_claim", argument, now=NOW + 86_400)
    with pytest.raises(GameError, match="尚未达成 3 天里程碑"):
        play("bond_reward_claim", "3", now=NOW + 86_400)
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'bond_streak_reward_%'") == []


def test_missing_reward_item_rolls_back_without_claiming(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 3)
    before_stones = player(game[1])["stones"]
    monkeypatch.delitem(game[0].content.items, "spirit_food")

    with pytest.raises(GameError, match="连续陪伴奖励物品定义缺失"):
        play("bond_reward_claim", "3", now=NOW + 2 * 86_400)

    assert player(game[1])["stones"] == before_stones
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id=?", (claim_id(3),)) == []


def test_daily_refresh_keeps_companionship_claims_permanent(game, play):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 3)
    play("bond_reward_claim", "3", now=NOW + 2 * 86_400)

    play("quests", now=NOW + 4 * 86_400)
    assert sql(
        game[1], "SELECT quest_id, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(3),),
    ) == [{"quest_id": claim_id(3), "claimed": 1}]


def test_interaction_commands_help_and_native_links(game, play):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 3)
    bond_reply = play("bond", now=NOW + 3 * 86_400)
    assert "灵宠陪伴奖励" in bond_reply.commands

    page = play("bond_rewards", now=NOW + 3 * 86_400)
    assert handlers._parse("灵宠陪伴奖励") == ("bond_rewards", "")
    assert handlers._parse("灵宠陪伴领奖 7") == ("bond_reward_claim", "7")
    help_page = play("help", "成长", now=NOW)
    assert "灵宠陪伴奖励" in help_page.text()
    assert "灵宠陪伴领奖 天数" in help_page.text()
    with pytest.raises(GameError, match="灵宠陪伴奖励 不接受参数"):
        play("bond_rewards", "3", now=NOW)

    pytest.importorskip("nonebot.adapters.qq")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert len(_keyboard_buttons(message)) <= 4
    assert _markdown_links(message) == [("领取奖励", "/灵宠陪伴领奖 3")]


def test_concurrent_claims_only_grant_a_milestone_once(game, play):
    play("adopt", "青鸾", now=NOW)
    bond_days(play, 3)
    before_stones = player(game[1])["stones"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(play, "bond_reward_claim", "3", now=NOW + 2 * 86_400, op=f"parallel-bond-{index}")
            for index in range(2)
        ]
        errors = [future.exception() for future in futures]

    assert sum(error is None for error in errors) == 1
    assert sum(isinstance(error, GameError) for error in errors) == 1
    assert player(game[1])["stones"] == before_stones + 80
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?", (claim_id(3),)) == [
        {"claimed": 1},
    ]
