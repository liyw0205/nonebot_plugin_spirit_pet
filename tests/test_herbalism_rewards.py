"""Contracts for the real-material herbalism route milestone loop."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.herbalism_reward_content import HerbalismReward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import herbalism_rewards

from .support import items, player, sql

NOW = 1_800_000_000


def seen(store, route, sites):
    for site in sites:
        sql(store, "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 0)",
            (f"herbalism_seen_{route}_{site}",))


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY user_id"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY item_id"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY quest_id"),
    }


def test_content_has_three_routes_and_ordered_milestones(game):
    rewards = game[0].content.herbalism_rewards
    assert len(rewards) == 9
    for route in game[0].content.herb_routes:
        assert [entry.threshold for entry in sorted(
            (item for item in rewards.values() if item.route == route),
            key=lambda item: item.threshold,
        )] == [1, 2, 4]
    assert HerbalismReward.model_validate({
        "id": "test_reward", "route": "brook", "threshold": 1,
        "name": "测试", "stones": 1, "items": {},
    }).threshold == 1
    with pytest.raises(ValueError):
        HerbalismReward.model_validate({
            "id": "test_reward", "route": "brook", "threshold": 1,
            "name": "测试", "stones": 0, "items": {},
        })


def test_unregistered_page_and_help_are_read_only(game, play):
    before = state(game[1])
    page = play("herbalism_rewards", user="ghost")
    assert page.title == "灵宠采药赏" and "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert "灵宠采药赏" in play("help", "血脉与道具").text()
    assert state(game[1]) == before


def test_page_uses_returned_sites_and_exposes_only_reached_claims(game, play):
    play("adopt", "青鸾")
    seen(game[1], "brook", (2, 3))
    page = play("herbalism_rewards")
    assert "溪谷药坡 · 2/4 处" in page.text()
    assert "1 处 · 溪谷初识" in page.text() and "2 处 · 溪谷熟路" in page.text()
    assert "4 处 · 溪谷尽览" in page.text() and "还差 2 处" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠采药领奖 溪谷药坡 1", "灵宠采药领奖 溪谷药坡 2",
    ]


def test_real_herbalism_return_unlocks_the_route_reward(game, play):
    play("adopt", "青鸾")
    play("herbalism", "出发 brook", op="herb-real-start")
    play("herbalism", "移动 2", op="herb-real-move")
    play("herbalism", "采集", op="herb-real-pick")
    play("herbalism", "移动 1", op="herb-real-home")
    play("herbalism", "返程", op="herb-real-return")
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id=?",
               ("herbalism_seen_brook_2",)) == [{"quest_id": "herbalism_seen_brook_2"}]
    reward_page = play("herbalism_rewards")
    assert "溪谷药坡 · 1/4 处" in reward_page.text()
    assert "灵宠采药领奖 溪谷药坡 1" in {link.command for link in reward_page.inline_commands}


def test_claim_pays_once_and_persists_a_ledger_record(game, play):
    play("adopt", "青鸾")
    seen(game[1], "brook", (2, 3, 6, 7))
    before = player(game[1])["stones"]
    reply = play("herbalism_rewards", "领奖 溪谷药坡 1", op="herb-reward-1")
    assert "溪谷初识" in reply.text() and "灵石 +80" in reply.text()
    assert player(game[1])["stones"] == before + 80
    assert items(game[1])["spirit_food"] >= 1
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?",
               ("herbalism_reward_brook_1",)) == [{"progress": 4, "claimed": 1}]
    assert play("herbalism_rewards", "领奖 溪谷药坡 1", op="herb-reward-1") == reply
    with pytest.raises(GameError, match="已经领取"):
        play("herbalism_rewards", "领奖 溪谷药坡 1", op="herb-reward-1b")


def test_bad_route_unmet_and_bad_arguments_do_not_write(game, play):
    play("adopt", "青鸾")
    before = state(game[1])
    for argument, message in (("领奖 不存在 1", "未找到"),
                              ("领奖 溪谷药坡 4", "仅带回 0"),
                              ("领奖 溪谷药坡 9", "没有此档"),
                              ("领奖 溪谷药坡", "格式"),
                              ("领奖 溪谷药坡 １", "数量")):
        with pytest.raises(GameError, match=message):
            play("herbalism_rewards", argument, op=f"bad-{argument}")
        assert state(game[1]) == before


def test_restart_recovers_claimed_status(game, play):
    play("adopt", "青鸾")
    seen(game[1], "ridge", (3,))
    play("herbalism_rewards", "领奖 赤岩药岭 1", op="herb-restart-claim")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "herbalism_rewards", "", "herb-restart-page", NOW)
    assert "赤岩初识" in page.text() and "已领取" in page.text()


def test_concurrent_claims_are_serialized(game, play):
    play("adopt", "青鸾")
    seen(game[1], "grove", (3,))
    def claim(index):
        try:
            return play("herbalism_rewards", "领奖 古木药涧 1", op=f"herb-concurrent-{index}").text()
        except GameError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (1, 2)))
    assert sum("已领取" in text for text in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS count FROM quest_progress WHERE quest_id=?",
               ("herbalism_reward_grove_1",)) == [{"count": 1}]
    assert player(game[1])["stones"] >= 80


def test_reward_failure_rolls_back_grant_and_claim_marker(game, play, monkeypatch):
    play("adopt", "青鸾")
    seen(game[1], "brook", (2,))
    before = state(game[1])
    monkeypatch.setattr(herbalism_rewards, "grant", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        play("herbalism_rewards", "领奖 溪谷药坡 1", op="herb-fail")
    assert state(game[1]) == before


def test_parser_and_native_message_keep_reward_links_separate(game, play):
    assert _parse("灵宠采药赏") == ("herbalism_rewards", "")
    assert _parse("灵宠采药领奖 溪谷药坡 1") == ("herbalism_rewards", "溪谷药坡 1")
    play("adopt", "青鸾")
    seen(game[1], "brook", (2,))
    page = play("herbalism_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}
