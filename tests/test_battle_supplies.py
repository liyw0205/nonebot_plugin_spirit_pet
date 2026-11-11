"""Contracts for the daily battle-supply preparation loop."""

import sqlite3
import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import battle_records, battle_supplies, loadout
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.application.context import Context

from .support import items, sql

NOW = 1_800_000_000
DAY = 86400


def ctx_of(game, user="u1", now=NOW):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng,
                   user, now, "read")


def account(play, species="青鸾", user="u1"):
    play("adopt", species, user=user)


def grant(game, item_id, amount=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def test_catalog_has_distinct_existing_consumables(game):
    supplies = game[0].content.battle_supplies
    assert len(supplies) == 3
    assert {entry.item_id for entry in supplies.values()} == {
        "energy_pill", "exp_pill", "affinity_pill",
    }
    assert all((entry.dealt, entry.taken) != (1, 1) for entry in supplies.values())


def test_unregistered_page_is_read_only(game, play):
    page = play("battle_supply", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_choose_consumes_one_pill_and_reaches_fighter(game, play):
    account(play)
    grant(game, "energy_pill", 2)
    reply = play("battle_supply", "选择 破阵灵酿", op="supply-choose")
    assert reply.title == "战备已定"
    assert items(game[1])["energy_pill"] == 1
    current = battle_supplies.active(ctx_of(game))
    assert current.id == "breakthrough_tonic"
    fighter = loadout.combatant(ctx_of(game))
    assert (fighter.dealt, fighter.taken) == pytest.approx((1.15, 1.15))


def test_only_one_daily_consumption_and_clear_does_not_refund(game, play):
    account(play)
    grant(game, "energy_pill", 1)
    grant(game, "exp_pill", 1)
    play("battle_supply", "选择 破阵灵酿", op="supply-one")
    with pytest.raises(GameError, match="已经准备"):
        play("battle_supply", "选择 定神灵酿")
    play("battle_supply", "清除", op="supply-clear")
    assert items(game[1])["energy_pill"] == 0
    with pytest.raises(GameError, match="已经消耗过"):
        play("battle_supply", "选择 定神灵酿")
    assert items(game[1])["exp_pill"] == 1


def test_next_beijing_day_is_empty_and_can_choose_again(game, play):
    account(play)
    grant(game, "energy_pill", 1)
    grant(game, "exp_pill", 1)
    play("battle_supply", "选择 破阵灵酿", now=NOW, op="supply-day-one")
    assert battle_supplies.active(ctx_of(game, now=NOW)).id == "breakthrough_tonic"
    assert battle_supplies.active(ctx_of(game, now=NOW + DAY)) is None
    reply = play("battle_supply", "选择 定神灵酿", now=NOW + DAY, op="supply-day-two")
    assert "定神灵酿" in reply.text()


def test_shortage_unknown_and_non_supply_are_zero_write(game, play):
    account(play)
    before = sql(game[1], "SELECT * FROM quest_progress")
    with pytest.raises(GameError, match="不足"):
        play("battle_supply", "选择 破阵灵酿")
    with pytest.raises(GameError, match="未找到该内容"):
        play("battle_supply", "选择 不存在")
    with pytest.raises(GameError, match="未找到该内容"):
        play("battle_supply", "选择 灵粮")
    assert sql(game[1], "SELECT * FROM quest_progress") == before


def test_operation_retry_does_not_consume_twice(game, play):
    account(play)
    grant(game, "affinity_pill", 2)
    first = play("battle_supply", "选择 同心灵酿", op="same-supply")
    second = play("battle_supply", "选择 同心灵酿", op="same-supply")
    assert second == first
    assert items(game[1])["affinity_pill"] == 1
    assert len(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'battle_supply_%'")) == 2


def test_failed_write_rolls_back_inventory_and_progress(game, play):
    account(play)
    grant(game, "energy_pill", 1)
    sql(
        game[1],
        "CREATE TRIGGER reject_supply AFTER INSERT ON quest_progress "
        "WHEN NEW.quest_id LIKE 'battle_supply_active_%' "
        "BEGIN SELECT RAISE(ABORT, 'injected supply failure'); END",
    )
    before = items(game[1])["energy_pill"]
    with pytest.raises(sqlite3.IntegrityError, match="injected supply failure"):
        play("battle_supply", "选择 破阵灵酿", op="supply-rollback")
    assert items(game[1])["energy_pill"] == before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'battle_supply_%'") == []
    sql(game[1], "DROP TRIGGER reject_supply")
    assert play("battle_supply", "选择 破阵灵酿", op="supply-rollback-retry").title == "战备已定"


def test_battle_snapshot_keeps_supply_name_and_rates(game, play):
    account(play)
    grant(game, "exp_pill", 1)
    play("battle_supply", "选择 定神灵酿", op="supply-snapshot")
    ctx = ctx_of(game)
    fighter = loadout.combatant(ctx)
    capture = battle_records.capture_snapshot(ctx, ([fighter], []), (["u1"], []))
    member = capture.snapshot["teams"][0]["members"][0]
    assert member["battle_supply"] == "定神灵酿"
    assert member["battle_dealt"] == pytest.approx(0.9)
    assert member["battle_taken"] == pytest.approx(0.82)


def test_page_objective_help_and_parse_are_connected(game, play):
    account(play)
    page = play("battle_supply")
    assert "破阵灵酿" in page.text()
    assert "选择战备" not in page.commands
    assert "战备：今日未准备" in play("objectives").text()
    assert "灵宠战备" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠战备 选择 同心灵酿") == ("battle_supply", "选择 同心灵酿")


def test_native_buttons_and_inline_links_do_not_overlap(game, play):
    account(play)
    grant(game, "energy_pill", 1)
    page = play("battle_supply")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert buttons == {f"{command}" for command in page.commands}
    assert not linked & buttons
