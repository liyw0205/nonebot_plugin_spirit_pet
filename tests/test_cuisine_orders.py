import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import cuisine_orders
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql
from .test_commands import onebot_event
from .test_cuisine import add_items

NOW = 1_800_000_000


def adopt(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW, op=f"adopt-order-{user}")


def order_rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id,progress,claimed FROM quest_progress WHERE user_id=? "
        "AND quest_id LIKE 'cuisine_order_%' ORDER BY quest_id",
        (user,),
    )


def snapshot(game, user="u1"):
    return {
        "player": sql(game[1], "SELECT * FROM players WHERE user_id=?", (user,)),
        "inventory": sql(game[1], "SELECT * FROM inventory WHERE user_id=? ORDER BY item_id", (user,)),
        "progress": sql(game[1], "SELECT * FROM quest_progress WHERE user_id=? ORDER BY quest_id", (user,)),
        "actions": sql(game[1], "SELECT * FROM duel_actions WHERE user_id=? ORDER BY action_id", (user,)),
    }


def test_content_and_read_only_commands_are_available(game, play):
    orders = game[0].content.cuisine_orders
    assert [orders[key].required_reputation for key in ("warm_meal", "herbal_meal", "lotus_meal")] == [0, 1, 3]
    assert handlers._parse("灵宠膳房订单") == ("cuisine_orders", "")
    assert handlers._parse("灵宠订单交付 warm_meal") == ("cuisine_order_deliver", "warm_meal")

    before = snapshot(game)
    page = play("cuisine_orders", user="ghost", now=NOW)
    assert page.title == "灵宠膳房订单"
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    assert snapshot(game) == before
    guide = play("help", "成长", now=NOW)
    assert "灵宠膳房订单" in guide.text()
    assert "灵宠订单交付 订单编号" in guide.text()


def test_real_cuisine_products_unlock_and_complete_weekly_order_chain(game, play):
    adopt(game, play)
    add_items(game, {
        "spirit_food": 24, "forge_ore": 12, "bloodline_essence": 8,
    })
    start_stones = player(game[1])["stones"]

    listing = play("cuisine_orders", now=NOW)
    assert "warm_meal · 暖胃订单 · 厨艺 1 级 · 交付 灵米粥 ×2" in listing.text()
    assert [link.command for link in listing.inline_commands] == []
    assert items(game[1]).get("meal_rice", 0) == 0

    play("cuisine_cook", "灵米粥 2", now=NOW, op="produce-rice")
    listing = play("cuisine_orders", now=NOW)
    link = next(link for link in listing.inline_commands if "warm_meal" in link.command)
    assert link.command == f"灵宠订单交付 warm_meal {beijing_day(beijing_week(NOW)[0])}"
    _, native = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    markdown = native["markdown"][0].data["markdown"].content
    assert "交付灵膳" in markdown
    links = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)
    }
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert f"/灵宠订单交付 warm_meal {beijing_day(beijing_week(NOW)[0])}" in links
    assert not buttons & links

    first = play("cuisine_order_deliver", f"warm_meal {beijing_day(beijing_week(NOW)[0])}",
                 now=NOW, op="deliver-warm")
    assert "订单声望 0 → 1" in first.text()
    assert "灵石 +80" in first.text()
    assert items(game[1])["meal_rice"] == 0
    assert player(game[1])["stones"] == start_stones - 20 + 80
    assert order_rows(game) == [{
        "quest_id": cuisine_orders._key(beijing_day(beijing_week(NOW)[0]), "warm_meal"),
        "progress": 1, "claimed": 1,
    }]

    with pytest.raises(GameError, match="不足"):
        play("cuisine_order_deliver", "herbal_meal", now=NOW, op="locked-herbal")
    play("cuisine_cook", "百草羹 2", now=NOW, op="produce-herb")
    herb = play("cuisine_order_deliver", "herbal_meal", now=NOW, op="deliver-herb")
    assert "订单声望 1 → 3" in herb.text()
    assert items(game[1])["meal_herb"] == 0
    with pytest.raises(GameError, match="不足"):
        play("cuisine_order_deliver", "lotus_meal", now=NOW, op="locked-lotus")

    play("cuisine_cook", "元灵莲酥 3", now=NOW + 86400, op="produce-lotus")
    lotus = play("cuisine_order_deliver", "lotus_meal", now=NOW + 86400, op="deliver-lotus")
    assert "订单声望 3 → 6" in lotus.text()
    assert items(game[1])["meal_lotus"] == 0
    assert len(order_rows(game)) == 3
    assert "本周已交付 3/3 · 声望 6 · 可交付 0 份" in play("objectives", now=NOW).text()


def test_invalid_shortage_stale_and_duplicate_delivery_are_noops(game, play):
    adopt(game, play)
    add_items(game, {"meal_rice": 2})
    with pytest.raises(GameError, match="厨艺不足"):
        play("cuisine_order_deliver", "herbal_meal", now=NOW, op="level-gate")
    with pytest.raises(GameError, match="格式"):
        play("cuisine_order_deliver", "warm_meal extra date", now=NOW)
    with pytest.raises(GameError, match="没有这份"):
        play("cuisine_order_deliver", "unknown", now=NOW)
    with pytest.raises(GameError, match="跨周"):
        play("cuisine_order_deliver", f"warm_meal 2025-01-06", now=NOW)
    play("cuisine_order_deliver", "warm_meal", now=NOW, op="valid-delivery")
    before = snapshot(game)
    with pytest.raises(GameError, match="已交付"):
        play("cuisine_order_deliver", "warm_meal", now=NOW, op="repeat-delivery")
    with pytest.raises(GameError, match="不足"):
        play("cuisine_order_deliver", "herbal_meal", now=NOW, op="no-herb")
    assert snapshot(game) == before


def test_order_reputation_gate_is_independent_of_cuisine_and_inventory(game, play):
    adopt(game, play)
    for dish_id in ("rice_porridge", "herb_soup"):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,?,1)",
            (f"cuisine_dish_{dish_id}", 1),
        )
    add_items(game, {"meal_lotus": 3})
    before = snapshot(game)
    with pytest.raises(GameError, match="声望不足"):
        play("cuisine_order_deliver", "lotus_meal", now=NOW, op="reputation-gate")
    assert snapshot(game) == before


def test_unknown_order_receipts_do_not_grant_reputation(game, play):
    adopt(game, play)
    week = beijing_day(beijing_week(NOW)[0])
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,?,1)",
        (f"cuisine_order_{week}_unknown", 100),
    )
    page = play("cuisine_orders", now=NOW)
    assert "订单声望 0" in page.lines[0]


def test_week_rollover_restarts_reputation_and_old_inline_command_expires(game, play):
    adopt(game, play)
    add_items(game, {"meal_rice": 2})
    week = beijing_day(beijing_week(NOW)[0])
    play("cuisine_order_deliver", f"warm_meal {week}", now=NOW, op="old-week-order")
    next_week = NOW + 7 * 86400
    page = play("cuisine_orders", now=next_week)
    assert "订单声望 0" in page.lines[0]
    with pytest.raises(GameError, match="跨周"):
        play("cuisine_order_deliver", f"warm_meal {week}", now=next_week, op="stale-link")
    assert len(order_rows(game)) == 1


def test_delivery_operation_and_week_state_survive_reopen(game, play):
    adopt(game, play)
    add_items(game, {"meal_rice": 2})
    week = beijing_day(beijing_week(NOW)[0])
    first = play("cuisine_order_deliver", f"warm_meal {week}", now=NOW, op="persist-order")
    reopened = Game(game[1].__class__(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "cuisine_order_deliver", f"warm_meal {week}", "persist-order", NOW) == first
    page = reopened.execute("u1", "cuisine_orders", "", "persist-page", NOW)
    assert "订单声望 1" in page.lines[0]
    assert "暖胃订单" in page.lines[2] and "已交付" in page.lines[2]


def test_concurrent_delivery_has_one_payout_and_one_consumption(game, play):
    adopt(game, play)
    add_items(game, {"meal_rice": 2})

    def attempt(operation):
        try:
            reply = game[0].execute("u1", "cuisine_order_deliver", "warm_meal", operation, NOW)
            return "ok", reply
        except GameError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("order-race-a", "order-race-b")))
    assert [kind for kind, _ in results].count("ok") == 1
    assert [kind for kind, _ in results].count("error") == 1
    assert items(game[1])["meal_rice"] == 0
    assert order_rows(game)[0]["progress"] == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cuisine_order'")[0]["n"] == 1


def test_failed_reward_write_rolls_back_food_reputation_and_stones(game, play, monkeypatch):
    adopt(game, play)
    add_items(game, {"meal_rice": 2})
    before = snapshot(game)
    original = Repository.add_item

    def fail_reward(self, user_id, item_id, amount):
        if item_id == "spirit_food":
            raise RuntimeError("injected cuisine order reward-item failure")
        return original(self, user_id, item_id, amount)

    monkeypatch.setattr(Repository, "add_item", fail_reward)
    with pytest.raises(RuntimeError, match="injected cuisine order reward-item failure"):
        play("cuisine_order_deliver", "warm_meal", now=NOW, op="failed-order-reward")
    assert snapshot(game) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='failed-order-reward'")


def test_onebot_delivery_uses_the_same_business_entry(game, play, monkeypatch):
    adopt(game, play, user="12345")
    add_items(game, {"meal_rice": 2}, user="12345")
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠膳房订单", 710), "!灵宠膳房订单")
        assert "交付灵膳（!灵宠订单交付 warm_meal" in bot.send.call_args.args[1]
        await handlers._run(bot, onebot_event("!灵宠订单交付 warm_meal", 711),
                            "!灵宠订单交付 warm_meal")
        assert "订单声望 0 → 1" in bot.send.call_args.args[1]

    asyncio.run(run())
    assert items(store, "12345")["meal_rice"] == 0
    assert order_rows((service, store), "12345")[0]["progress"] == 1
