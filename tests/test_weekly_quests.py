import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)
LAST_WEEK = WEEK_START - 86400
NEXT_WEEK = WEEK_END + 3600


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def pet_id(game, user="u1"):
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))[0]["pet_id"]


def seed_pve_win(game, user, played_at, op):
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title,"
            " winner_side, rounds, played_at, reply, snapshot, battle_log)"
            " VALUES (?, ?, 'pve', 'forest', '秘境', 0, 3, ?, '{}', '{}', '[]')",
            (op, user, played_at),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, 0, 'participant')",
            (cursor.lastrowid, user),
        )


def seed_expedition(game, user, played_at, op):
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
            " started_at, finishes_at, state, reward_snapshot, settled_at)"
            " VALUES (?, ?, 'job', '任务', ?, ?, ?, 'claimed', '{}', ?)",
            (user, pet_id(game, user), op, played_at - 3600, played_at, played_at),
        )


def seed_discovery(game, user, encounter_id, played_at):
    sql(
        game[1],
        "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
        (user, encounter_id, played_at),
    )


def seed_stage_clear(game, user, stage_id, played_at, op):
    sql(
        game[1],
        "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id)"
        " VALUES (?, ?, ?, ?)",
        (user, stage_id, played_at, op),
    )


def seed_achievement_claim(game, user, achievement_id, played_at, op):
    sql(
        game[1],
        "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
        " reward_snapshot, reply) VALUES (?, ?, ?, ?, '{}', '{}')",
        (user, achievement_id, op, played_at),
    )


def seed_pvp_win(game, user, played_at, op, season_id="2027-01"):
    with game[1].connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot)"
            " VALUES (?, ?, ?, ?, '{}')",
            (season_id, WEEK_START - 86400 * 30, WEEK_END + 86400 * 30, WEEK_START - 86400 * 30),
        )
        conn.execute(
            "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id,"
            " target_pet_id, winner_id, day, played_at, delta, operation_id, reply)"
            " VALUES (?, ?, 'u2', ?, ?, ?, ?, ?, 10, ?, '{}')",
            (season_id, user, pet_id(game, user), pet_id(game, "u2"), user, beijing_day(played_at),
             played_at, op),
        )


def test_content_defines_fifteen_weekly_goals(game):
    quests = list(game[0].content.weekly_quests.values())
    assert len(quests) == 15
    assert {quest.metric for quest in quests} == {
        "weekly_pve_wins", "weekly_pvp_wins", "weekly_expedition_claims",
        "weekly_adventures", "weekly_stage_clears", "weekly_achievement_claims",
        "weekly_cuisine_orders", "weekly_cuisine_practice", "weekly_banquets",
    }
    for quest in quests:
        assert quest.target > 0 and quest.description
        assert all(item in game[0].content.items for item in quest.reward.items)


def test_catalog_previews_without_an_account(game, play):
    listing = play("weekly_quests")
    assert "尚未结契" in listing.text()
    assert beijing_day(WEEK_START) in listing.lines[0]
    assert links(listing) == [(1, "开始领养", "灵宠领养 ")]
    assert not sql(game[1], "SELECT * FROM players")


def test_catalog_shows_the_week_and_zero_progress(game, play):
    account(game, play)
    listing = play("weekly_quests")
    assert listing.title == "灵宠周常 1/3"
    assert listing.lines[0] == f"本周周期：{beijing_day(WEEK_START)} ~ {beijing_day(WEEK_END - 1)}（北京时间，周一 00:00 重置）"
    assert "秘境历练：0/5（未达成） · 灵石 800-800，锻灵矿 3-3" in listing.text()
    assert "论剑周赛：0/3（未达成） · 灵石 600-600，破境丹 1-1" in listing.text()
    assert links(listing) == []
    assert listing.commands == ("灵宠周常 2", "灵宠任务", "灵宠周常赏")
    assert play("weekly_quests", "2").title == "灵宠周常 2/3"


def test_weekly_metrics_count_only_the_current_week(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_pve_win(game, "u1", NOW, "wk-pve-in")
    seed_pve_win(game, "u1", LAST_WEEK, "wk-pve-old")
    seed_pvp_win(game, "u1", NOW, "wk-pvp-in")
    seed_pvp_win(game, "u1", NEXT_WEEK, "wk-pvp-new")
    seed_expedition(game, "u1", NOW, "wk-exp-in")
    seed_expedition(game, "u1", LAST_WEEK, "wk-exp-old")
    encounters = list(game[0].content.encounters)
    seed_discovery(game, "u1", encounters[0], NOW)
    seed_discovery(game, "u1", encounters[1], LAST_WEEK)
    seed_stage_clear(game, "u1", "stage_01", NOW, "wk-stage-in")
    seed_stage_clear(game, "u1", "tower_01", NOW, "wk-tower-in")
    seed_stage_clear(game, "u1", "stage_02", LAST_WEEK, "wk-stage-old")
    seed_achievement_claim(game, "u1", "first_bond", NOW, "wk-ach-in")
    seed_achievement_claim(game, "u1", "first_bond_old", LAST_WEEK, "wk-ach-old")

    text = play("weekly_quests").text()
    assert "秘境历练：1/5" in text
    assert "论剑周赛：1/3" in text
    assert "山海往来：1/3" in text
    assert "奇闻寻访：1/5" in text
    assert "关卡推进：1/2" in text
    # The sixth goal sits on the second page.
    assert "成就累积：1/2" in play("weekly_quests", "2").text()


def test_real_food_activities_drive_weekly_claims_and_nine_goal_reward(game, play):
    account(game, play)
    for dish_id in ("rice_porridge", "herb_soup", "lotus_pastry", "beast_soup", "grain_cake"):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
            (f"cuisine_dish_{dish_id}",),
        )
    for item_id, amount in (("meal_rice", 6), ("meal_herb", 2), ("spirit_food", 12)):
        sql(
            game[1],
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (item_id, amount),
        )
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")

    week = beijing_day(WEEK_START)
    play("cuisine_order_deliver", f"warm_meal {week}", op="weekly-food-order-warm")
    play("cuisine_order_deliver", f"herbal_meal {week}", op="weekly-food-order-herb")
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,99,1)",
        (f"cuisine_order_{week}_removed-order",),
    )

    abandoned_start = play(
        "cuisine_practice", "开始 灵米粥", now=NOW - 86400, op="weekly-food-abandon-start",
    )
    assert "已消耗 灵米粥" in abandoned_start.text()
    play("cuisine_practice", "放弃", now=NOW - 86400, op="weekly-food-abandon")
    for session in range(3):
        day = NOW + session * 86400
        suffix = f"weekly-food-practice-{session}"
        play("cuisine_practice", "开始 灵米粥", now=day, op=f"{suffix}-start")
        for step, action in enumerate(("稳火", "添香", "收盘")):
            play("cuisine_practice", action, now=day, op=f"{suffix}-{step}")

    banquet_time = NOW + 2 * 86400
    play("banquet", "开席", now=banquet_time, op="weekly-food-banquet")
    page = play("weekly_quests", "3", now=banquet_time)
    assert "膳房供货：2/2（可领取）" in page.text()
    assert "灶火精研：3/3（可领取）" in page.text()
    assert "家宴团圆：1/1（可领取）" in page.text()
    assert "removed-order" not in page.text()
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    markdown_payload = native["markdown"][0].data["markdown"]
    markdown = markdown_payload.content if hasattr(markdown_payload, "content") else markdown_payload["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)
    }
    assert "/灵宠周常领奖 膳房供货" in linked
    assert not linked & buttons
    assert len(buttons) <= 4

    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "weekly_quests", "3", "weekly-food-restart-page", banquet_time).text() == page.text()

    before_order_claim = (player(game[1])["stones"], items(game[1]).get("spirit_food", 0))
    operations = ("weekly-food-order-claim-a", "weekly-food-order-claim-b")

    def claim_orders(operation):
        try:
            return play("weekly_quest_claim", "膳房供货", now=banquet_time, op=operation)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        order_results = list(pool.map(claim_orders, operations))
    successes = [
        (operation, result)
        for operation, result in zip(operations, order_results)
        if not isinstance(result, GameError)
    ]
    assert len(successes) == 1
    successful_operation, successful_reply = successes[0]
    assert (player(game[1])["stones"], items(game[1])["spirit_food"]) == (
        before_order_claim[0] + 500, before_order_claim[1] + 3,
    )
    assert play(
        "weekly_quest_claim", "膳房供货", now=banquet_time, op=successful_operation,
    ) == successful_reply

    for quest, suffix in (("灶火精研", "practice"), ("家宴团圆", "banquet")):
        claim = play("weekly_quest_claim", quest, now=banquet_time, op=f"weekly-food-claim-{suffix}")
        assert f"{quest}已完成。" in claim.text()
        assert play(
            "weekly_quest_claim", quest, now=banquet_time, op=f"weekly-food-claim-{suffix}"
        ) == claim

    # The other six durable weekly receipts are prepared here so the real food
    # claims can exercise the new final cumulative tier end to end.
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES "
        "('u1','weekly_pve',?,1),('u1','weekly_pvp',?,1),('u1','weekly_expedition',?,1),"
        "('u1','weekly_adventure',?,1),('u1','weekly_stage',?,1),('u1','weekly_achievement',?,1)",
        (WEEK_START,) * 6,
    )
    reward_page = play("weekly_rewards", now=banquet_time)
    assert "已领取 9/15 项周常" in reward_page.lines[0]
    assert "9 项 · 周行圆满" in reward_page.text()
    before_stones = player(game[1])["stones"]
    before_meal = items(game[1]).get("meal_lotus", 0)
    reward = play("weekly_rewards", "领奖 9", now=banquet_time, op="weekly-food-final-tier")
    assert "周行圆满已领取" in reward.text()
    assert player(game[1])["stones"] == before_stones + 600
    assert items(game[1])["meal_lotus"] == before_meal + 1
    assert play("weekly_rewards", "领奖 9", now=banquet_time, op="weekly-food-final-tier") == reward
    with pytest.raises(GameError, match="已领取"):
        play("weekly_rewards", "领奖 9", now=banquet_time, op="weekly-food-final-tier-again")
    next_week = play("weekly_quests", "3", now=NEXT_WEEK)
    assert "膳房供货：0/2（未达成）" in next_week.text()
    assert "灶火精研：0/3（未达成）" in next_week.text()
    assert "家宴团圆：0/1（未达成）" in next_week.text()


def test_claim_grants_once_and_marks_the_week(game, play):
    account(game, play)
    seed_pve_win(game, "u1", NOW, "wk-claim-1")
    listing = play("weekly_quests")
    assert "秘境历练：1/5（未达成）" in listing.text()
    with pytest.raises(GameError, match="本周尚未达成"):
        play("weekly_quest_claim", "秘境历练", op="wk-claim-early")

    for index in range(2, 6):
        seed_pve_win(game, "u1", NOW, f"wk-claim-{index}")
    listing = play("weekly_quests")
    assert "秘境历练：5/5（可领取）" in listing.text()
    assert (1, "领取奖励", "灵宠周常领奖 秘境历练") in links(listing)

    before = (player(game[1])["stones"], items(game[1]).get("forge_ore", 0))
    claimed = play("weekly_quest_claim", "秘境历练", op="wk-claim")
    assert claimed.title == "周常奖励已领取"
    assert "秘境历练已完成。" in claimed.text()
    assert "灵石 +800" in claimed.text() and "锻灵矿 +3" in claimed.text()
    assert player(game[1])["stones"] == before[0] + 800
    assert items(game[1])["forge_ore"] == before[1] + 3
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='weekly_pve'",
    ) == [{"progress": WEEK_START, "claimed": 1}]
    assert "秘境历练：5/5（已领取）" in play("weekly_quests").text()

    after = (player(game[1])["stones"], items(game[1]))
    with pytest.raises(GameError, match="本周这项奖励已领取"):
        play("weekly_quest_claim", "秘境历练", op="wk-claim-again")
    assert (player(game[1])["stones"], items(game[1])) == after


def test_week_rollover_resets_progress_and_claim(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-roll-{index}")
    play("weekly_quest_claim", "秘境历练", op="wk-roll-claim", now=NOW)
    assert "秘境历练：5/5（已领取）" in play("weekly_quests", now=NOW).text()

    later = play("weekly_quests", now=WEEK_END + 3600)
    assert "秘境历练：0/5（未达成）" in later.text()
    assert beijing_day(WEEK_END) in later.lines[0]


def test_replay_does_not_grant_twice(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-replay-{index}")
    first = play("weekly_quest_claim", "秘境历练", op="wk-replay")
    state = (player(game[1])["stones"], items(game[1]))
    assert play("weekly_quest_claim", "秘境历练", op="wk-replay") == first
    assert (player(game[1])["stones"], items(game[1])) == state


def test_claim_rejects_an_unknown_goal(game, play):
    account(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("weekly_quest_claim", "不存在的周常")


def test_help_lists_the_weekly_entries(game, play):
    guide = play("help", "成长")
    assert "灵宠周常" in guide.text()
    assert "灵宠周常领奖 名称" in guide.text()
    assert "膳房订单、研修与家宴" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-native-{index}")
    listing = play("weekly_quests")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & buttons


def test_onebot_weekly_claim_uses_the_same_business_entry(game, play, monkeypatch):
    now = int(time.time())
    week_start, _ = beijing_week(now)
    play("adopt", "青鸾", user="12345", now=now)
    for index in range(5):
        seed_pve_win(game, "12345", now, f"wk-onebot-{index}")
    service, _ = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
        send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠周常", 710), "!灵宠周常")
        assert "本周周期" in bot.send.call_args.args[1]
        await handlers._run(
            bot, onebot_event("!灵宠周常领奖 秘境历练", 711), "!灵宠周常领奖 秘境历练",
        )
        assert "秘境历练已完成" in bot.send.call_args.args[1]

    asyncio.run(run())
    assert sql(
        game[1], "SELECT progress,claimed FROM quest_progress WHERE user_id='12345' AND quest_id='weekly_pve'",
    ) == [{"progress": week_start, "claimed": 1}]
