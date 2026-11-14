import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.daily_shop_reward_content import DailyShopReward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import daily_shop
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000
DAY = 86_400


def account(play):
    play("adopt", "青鸾", now=NOW, op="reward-adopt")


def seed_purchases(game, total, user="u1"):
    for index in range(total):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
            (user, f"shop_offer_2027-01-{index + 1:02d}_seed"),
        )


def test_content_has_strict_milestones_and_existing_items(game):
    entries = sorted(game[0].content.daily_shop_rewards.values(), key=lambda entry: entry.threshold)
    assert [entry.threshold for entry in entries] == [1, 5, 12]
    assert all(entry.stones or entry.items for entry in entries)
    assert all(item in game[0].content.items for entry in entries for item in entry.items)
    with pytest.raises(ValidationError):
        DailyShopReward.model_validate({"id": "empty", "name": "空", "threshold": 1})
    with pytest.raises(ValidationError):
        DailyShopReward.model_validate({"id": "bad", "name": "坏", "threshold": 0, "stones": 1})


def test_counts_featured_units_and_excludes_normal_shop(game, play):
    account(play)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id='u1'")
    offer = next(item for item in daily_shop.offers(_context(game)) if item.stock >= 2)
    item = game[0].content.items[offer.item]
    play("daily_shop", f"{item.name} 2", now=NOW, op="featured-buy")
    play("buy", f"{item.name} 1", now=NOW + 1, op="normal-buy")
    page = play("daily_shop_rewards", now=NOW + 1)
    assert "特供购买：2 件" in page.lines[0]
    assert "1 件 · 初逛灵坊" in page.text() and "可领取" in page.text()
    assert "5 件 · 熟客回馈" in page.text() and "还差 3 件" in page.text()


def _context(game, now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config,
        game[0].rng, "u1", now, "reward-context",
    )


def test_claim_persists_across_restart_and_rejects_bad_tiers(game, play):
    account(play)
    seed_purchases(game, 1)
    before = player(game[1])["stones"]
    before_food = items(game[1]).get("spirit_food", 0)
    result = play("daily_shop_reward_claim", "1", op="shop-reward-1")
    assert result.title == "灵宠特供累计赏"
    assert player(game[1])["stones"] == before + 80
    assert items(game[1])["spirit_food"] == before_food + 1
    assert sql(game[1], "SELECT progress,claimed FROM quest_progress WHERE quest_id='daily_shop_reward_1'") == [
        {"progress": 1, "claimed": 1},
    ]
    restarted = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    with pytest.raises(GameError, match="已领取"):
        restarted.execute("u1", "daily_shop_reward_claim", "1", "shop-reward-repeat", NOW + DAY)
    for argument in ("", "0", "2", "1 extra", "１"):
        with pytest.raises(GameError):
            play("daily_shop_reward_claim", argument, op=f"shop-reward-invalid-{argument}")


def test_unregistered_page_is_read_only_and_objectives_link_once(game, play):
    before = sql(game[1], "SELECT * FROM players")
    page = play("daily_shop_rewards", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players") == before
    account(play)
    seed_purchases(game, 5)
    objective = play("objectives")
    assert any(line.startswith("特供累计赏：购买 5 件") for line in objective.lines)
    assert [link.command for link in objective.inline_commands].count("灵宠特供赏") == 1


def test_concurrent_claims_are_serialized(game, play):
    account(play)
    seed_purchases(game, 1)

    def attempt(index):
        try:
            return play("daily_shop_reward_claim", "1", op=f"shop-reward-parallel-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id='daily_shop_reward_1'") == [{"n": 1}]
    assert player(game[1])["stones"] == game[0].content.rules.starter_stones + 80


def test_reward_marker_failure_rolls_back_and_retry_is_clean(game, play):
    account(play)
    seed_purchases(game, 1)
    before = (player(game[1]), items(game[1]))
    sql(
        game[1],
        "CREATE TRIGGER reject_daily_shop_reward BEFORE INSERT ON quest_progress "
        "WHEN NEW.quest_id='daily_shop_reward_1' BEGIN SELECT RAISE(ABORT, 'daily shop reward failure'); END",
    )
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="daily shop reward failure"):
        play("daily_shop_reward_claim", "1", op="shop-reward-failure")
    assert (player(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='daily_shop_reward_1'")
    sql(game[1], "DROP TRIGGER reject_daily_shop_reward")
    play("daily_shop_reward_claim", "1", op="shop-reward-retry")
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE quest_id='daily_shop_reward_1'") == [{"claimed": 1}]


def test_help_parser_and_native_actions_do_not_duplicate(game, play, monkeypatch):
    account(play)
    seed_purchases(game, 12)
    page = play("daily_shop_rewards")
    assert handlers._parse("灵宠特供赏") == ("daily_shop_rewards", "")
    assert handlers._parse("灵宠特供领奖 1") == ("daily_shop_reward_claim", "1")
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    assert handlers._parse("!灵宠特供领奖 1") == ("daily_shop_reward_claim", "1")
    assert handlers._parse("灵宠特供领奖 1") == ("daily_shop_reward_claim", "1")
    help_page = play("help", "血脉与道具")
    assert sum("灵宠特供赏" in line for line in help_page.lines) == 1
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    markdown = "\n".join(segment.data["markdown"].content for segment in native["markdown"])
    links = {
        parse_qs(urlparse(url).query)["command"][0].lstrip("/")
        for url in __import__("re").findall(r"\]\((mqqapi://[^)]+)\)", markdown)
    }
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & links
    assert links == {"灵宠特供领奖 1", "灵宠特供领奖 5", "灵宠特供领奖 12"}


def test_onebot_uses_the_same_featured_reward_commands(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 301), "!灵宠领养 青鸾")
        for index in range(1, 6):
            sql(
                game[1],
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
                ("12345", f"shop_offer_2027-01-{index:02d}_onebot"),
            )
        await handlers._run(bot, onebot_event("!灵宠特供赏", 302), "!灵宠特供赏")
        await handlers._run(bot, onebot_event("!灵宠特供领奖 1", 303), "!灵宠特供领奖 1")

    asyncio.run(run())
    assert bot.send.await_count == 3
    assert "特供购买：5 件" in str(bot.send.call_args_list[1].args[1])
    assert "初逛灵坊已领取" in str(bot.send.call_args_list[2].args[1])
