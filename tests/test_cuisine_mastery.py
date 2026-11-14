import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from .support import items, player, sql
from .test_commands import onebot_event
from .test_cuisine import add_items

NOW = 1_800_000_000


def account(game, play):
    play("adopt", "青鸾", now=NOW, op="mastery-adopt")


def test_content_covers_only_single_meals_with_ordered_milestones(game):
    rewards = game[0].content.cuisine_mastery_rewards
    assert set(entry.dish_id for entry in rewards.values()) == {
        "rice_porridge", "herb_soup", "lotus_pastry", "grain_cake", "moon_cake",
    }
    for dish_id in set(entry.dish_id for entry in rewards.values()):
        assert [entry.threshold for entry in sorted(rewards.values(), key=lambda e: e.threshold)
                if entry.dish_id == dish_id] == [1, 3, 6]


def test_unregistered_catalog_is_read_only_and_excludes_banquets(game, play):
    page = play("cuisine_mastery", user="ghost", now=NOW)
    assert page.title == "膳房菜谱精通"
    assert "尚未结契" in page.text()
    assert "百兽羹" not in page.text()
    assert sql(game[1], "SELECT * FROM players") == []


def test_real_instant_cooking_feeds_mastery_and_claim_is_idempotent(game, play):
    account(game, play)
    add_items(game, {"spirit_food": 6})
    play("cuisine_cook", "灵米粥 3", now=NOW, op="mastery-cook")
    page = play("cuisine_mastery", now=NOW)
    assert "灵米粥 · 成功 3 份 · 精通 2/3 级" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠膳房精通领奖 灵米粥 1", "灵宠膳房精通领奖 灵米粥 3",
    ]
    before = player(game[1])["stones"]
    first = play("cuisine_mastery_claim", "灵米粥 3", now=NOW, op="mastery-claim")
    assert "灵米熟手" in first.text()
    assert player(game[1])["stones"] == before + 180
    assert items(game[1])["forge_ore"] == 1
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='cuisine_mastery_rice_porridge_3'") == [
        {"progress": 3, "claimed": 1},
    ]
    assert play("cuisine_mastery_claim", "灵米粥 3", now=NOW + 1, op="mastery-claim") == first
    with pytest.raises(GameError, match="已领取"):
        play("cuisine_mastery_claim", "灵米粥 3", now=NOW + 1)


def test_real_staged_cooking_feeds_mastery_and_banquet_does_not(game, play):
    account(game, play)
    add_items(game, {"spirit_food": 4, "bloodline_essence": 2})
    play("cooking", "开锅 灵米粥", now=NOW, op="mastery-pot")
    for index, action in enumerate(("旺火", "旺火", "离火")):
        play("cooking", action, now=NOW, op=f"mastery-pot-{index}")
    page = play("cuisine_mastery", now=NOW)
    assert "灵米粥 · 成功 2 份 · 精通 1/3 级" in page.text()
    assert "百兽羹" not in page.text()


def test_unreached_and_bad_arguments_are_zero_write(game, play):
    account(game, play)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress"))
    with pytest.raises(GameError, match="尚未达到"):
        play("cuisine_mastery_claim", "灵米粥 1", now=NOW, op="mastery-unreached")
    for argument in ("灵米粥", "灵米粥 2", "灵米粥 1 extra", "不存在 1"):
        with pytest.raises(GameError):
            play("cuisine_mastery_claim", argument, now=NOW, op=f"mastery-bad-{argument}")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM quest_progress")) == before


def test_claim_survives_restart_and_concurrent_claims_are_single_pay(game, play):
    account(game, play)
    sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','cuisine_dish_rice_porridge',3,1)")
    before = player(game[1])["stones"]

    def attempt(index):
        try:
            return game[0].execute("u1", "cuisine_mastery_claim", "灵米粥 1", f"mastery-race-{index}", NOW)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert player(game[1])["stones"] == before + 80
    restarted = __import__("nonebot_plugin_spirit_pet.application.game", fromlist=["Game"]).Game(
        __import__("nonebot_plugin_spirit_pet.storage.database", fromlist=["Store"]).Store(game[1].path),
        Config(), game[0].rng, content=game[0].content,
    )
    with pytest.raises(GameError, match="已领取"):
        restarted.execute("u1", "cuisine_mastery_claim", "灵米粥 1", "mastery-after-restart", NOW + 1)


def test_reward_marker_failure_rolls_back_and_retry_is_clean(game, play):
    account(game, play)
    sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','cuisine_dish_rice_porridge',1,1)")
    before = (player(game[1])["stones"], items(game[1]))
    sql(game[1], "CREATE TRIGGER reject_cuisine_mastery BEFORE INSERT ON quest_progress "
                "WHEN NEW.quest_id='cuisine_mastery_rice_porridge_1' BEGIN SELECT RAISE(ABORT, 'mastery failure'); END")
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="mastery failure"):
        play("cuisine_mastery_claim", "灵米粥 1", now=NOW, op="mastery-failure")
    assert (player(game[1])["stones"], items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='cuisine_mastery_rice_porridge_1'")
    sql(game[1], "DROP TRIGGER reject_cuisine_mastery")
    assert "初识灵米" in play("cuisine_mastery_claim", "灵米粥 1", now=NOW, op="mastery-failure-retry").text()


def test_help_objectives_native_and_onebot_share_the_entry(game, play, monkeypatch):
    account(game, play)
    page = play("cuisine_mastery", now=NOW)
    assert handlers._parse("灵宠膳房精通") == ("cuisine_mastery", "")
    assert handlers._parse("灵宠膳房精通领奖 灵米粥 3") == ("cuisine_mastery_claim", "灵米粥 3")
    assert "灵宠膳房精通领奖 菜名 档位" in play("help", "成长").text()
    assert "膳房精通：" in play("objectives").text()
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in page.inline_commands}

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠膳房精通", 901), "!灵宠膳房精通")

    asyncio.run(run())
    assert "膳房菜谱精通" in str(bot.send.call_args.args[1])
