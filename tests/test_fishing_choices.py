"""Bait decisions, persistent basket and atomic settlement contracts."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.domain.fishing_content import FishingBait
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import fishing
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql

NOW = 1_800_000_000
DAY = 86400


def snapshot(store, *, cache=True):
    with closing(store.connect()) as conn:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) if cache or row[0] != "operations"]
        return {name: sorted(tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"'))
                for name in names}


def account(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE inventory SET quantity=20 WHERE user_id='u1' AND item_id='spirit_food'")
    sql(game[1], "INSERT INTO inventory VALUES ('u1','forge_ore',20)")


class Roll:
    def __init__(self, roll):
        self.roll = roll
        self.calls = 0

    def randint(self, start, stop):
        self.calls += 1
        return self.roll if self.calls % 2 else start


@pytest.mark.parametrize("bait,expected", [
    ("", [50, 30, 15, 5]), ("grain", [50, 30, 45, 5]),
    ("mineral", [50, 90, 15, 5]), ("aura", [50, 30, 15, 15]),
])
def test_effective_weights(game, bait, expected):
    content = game[0].content
    assert fishing.weights(content.fishing_spots["creek"], content.fishing_baits.get(bait)) == expected


@pytest.mark.parametrize("bait,roll,item", [
    ("谷香饵", 50, "spirit_food"), ("谷香饵", 51, "forge_ore"),
    ("谷香饵", 80, "forge_ore"), ("谷香饵", 81, "seed_spirit_rice"),
    ("谷香饵", 125, "seed_spirit_rice"), ("谷香饵", 126, "exp_pill"),
    ("谷香饵", 130, "exp_pill"), ("晶砂饵", 140, "forge_ore"),
    ("灵光饵", 110, "exp_pill"), ("素饵", 81, "seed_spirit_rice"),
])
def test_cast_uses_displayed_weights_and_costs(game, play, bait, roll, item):
    account(game, play)
    game[0].rng = Roll(roll)
    before = items(game[1])
    reply = play("fishing", f"溪口 {bait}", now=NOW, op="weighted")
    assert pet(game[1])["energy"] == 92
    ledger = sql(game[1], "SELECT * FROM fishing_casts")[0]
    saved = json.loads(ledger["snapshot"])
    assert saved["item_id"] == item and saved["amount"] == 1
    expected = dict(before)
    if saved["cost_item"]:
        expected[saved["cost_item"]] -= saved["cost_quantity"]
    expected[item] = expected.get(item, 0) + 1
    assert items(game[1]) == expected
    assert saved["bait_name"] == bait
    assert json.loads(ledger["reply"])["lines"] == list(reply.lines)
    assert "鱼篓" in " ".join(reply.commands)


def test_details_and_basket_are_read_only_and_show_exact_chances(game, play):
    account(game, play)
    sql(game[1], "UPDATE pets SET energy=10, energy_updated=?", (NOW - DAY,))
    before = snapshot(game[1], cache=False)
    for arg in ("", "详情 溪口", "详情 溪口 谷香饵", "详情 深潭", "鱼篓"):
        reply = play("fishing", arg, now=NOW)
        assert not set(reply.commands) & {link.command for link in reply.inline_commands}
        assert len(reply.commands) <= 4
    detail = play("fishing", "详情 溪口 谷香饵", now=NOW)
    assert "45/130（约 34.6%）" in detail.text()
    assert "灵粮 ×1（持有 20）" in detail.text()
    assert "灵宠垂钓 溪口 谷香饵" in {link.command for link in detail.inline_commands}
    assert snapshot(game[1], cache=False) == before


def test_unregistered_and_no_active_pet_previews_keep_adoption_entry(game, play):
    before = snapshot(game[1], cache=False)
    for arg in ("", "详情 溪口 谷香饵", "鱼篓"):
        reply = play("fishing", arg, user="new")
        assert "灵宠领养 " in {link.command for link in reply.inline_commands}
    assert snapshot(game[1], cache=False) == before
    account(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    reply = play("fishing", "详情 溪口")
    assert "灵宠列表" in {link.command for link in reply.inline_commands}
    assert not any(link.command == "灵宠垂钓 溪口" for link in reply.inline_commands)


@pytest.mark.parametrize("arg", [
    "溪口 错饵", "溪口 谷香饵 多余", "详情", "详情 溪口 错饵", "鱼篓 0",
    "鱼篓 2", "鱼篓 1 多余", "分页", "详情 深潭 灵光饵", "深潭 灵光饵", "未知 谷香饵",
])
def test_invalid_requests_write_nothing(game, play, arg):
    account(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("fishing", arg, now=NOW)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("condition,pattern", [
    ("stock", "灵粮不足"), ("energy", "精力不足"), ("realm", "需要"),
    ("cap", "次数已用完"), ("archived", "封存"), ("active", "尚未选择"),
    ("expedition", "外出派遣"),
])
def test_blocked_casts_have_honest_actions_and_zero_writes(game, play, condition, pattern):
    account(game, play)
    spot = "溪口"
    if condition == "stock":
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    if condition == "energy":
        sql(game[1], "UPDATE pets SET energy=0,energy_updated=?", (NOW,))
    if condition == "realm":
        spot = "深潭"
    if condition == "cap":
        for index in range(3):
            play("fishing", "溪口", now=NOW, op=f"used-{index}")
    if condition == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    if condition == "active":
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    if condition == "expedition":
        play("expedition_start", "采灵药", now=NOW)
    preview = play("fishing", f"详情 {spot} 谷香饵", now=NOW)
    assert not any(link.command == f"灵宠垂钓 {spot} 谷香饵" for link in preview.inline_commands)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=pattern):
        play("fishing", f"{spot} 谷香饵", now=NOW)
    assert snapshot(game[1]) == before


def test_permanent_reply_replays_after_cache_eviction_and_restart(game, play):
    account(game, play)
    reply = play("fishing", "溪口 谷香饵", now=NOW, op="durable")
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    service = Game(game[1], game[0].config, content=game[0].content)
    assert service.execute("u1", "fishing", "灵渊 灵光饵", "durable", NOW + 8 * DAY) == reply
    assert snapshot(game[1], cache=False) == before
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="different user"):
        service.execute("u2", "fishing", "", "durable", NOW + 8 * DAY)
    assert snapshot(game[1]) == before
    basket = play("fishing", "鱼篓", now=NOW + 8 * DAY)
    assert "溪口 / 谷香饵" in basket.text() and "消耗精力 8、灵粮 ×1" in basket.text()


def test_concurrent_same_operation_casts_once(game, play):
    account(game, play)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: game[0].execute(
            "u1", "fishing", "溪口 谷香饵", "parallel-cast", NOW,
        ), range(2)))
    assert replies[0] == replies[1]
    assert len(sql(game[1], "SELECT * FROM fishing_casts")) == 1
    assert pet(game[1])["energy"] == 92


@pytest.mark.parametrize("failure", ["loot", "bonus", "ledger"])
def test_settlement_failure_rolls_every_table_back(game, play, monkeypatch, failure):
    account(game, play)
    for item in ("forge_ore", "seed_spirit_rice", "exp_pill"):
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1',?,1,1)", (f"fish_creek_{item}",))
    before = snapshot(game[1])

    def fail(*args, **kwargs):
        raise RuntimeError("injected fishing failure")

    if failure == "bonus":
        monkeypatch.setattr(fishing, "_grant", fail)
    else:
        monkeypatch.setattr(Repository, "add_item" if failure == "loot" else "record_fishing_cast", fail)
    with pytest.raises(RuntimeError, match="injected fishing"):
        play("fishing", "溪口 谷香饵", now=NOW)
    assert snapshot(game[1]) == before


def test_basket_pagination_and_snapshot_names_survive_content_changes(game, play):
    account(game, play)
    for index in range(7):
        play("fishing", "溪口", now=NOW + index * DAY)
    item = game[0].content.items["spirit_food"]
    game[0].content.items["spirit_food"] = item.model_copy(update={"name": "后改名字"})
    page1 = play("fishing", "鱼篓", now=NOW + 8 * DAY)
    page2 = play("fishing", "鱼篓 2", now=NOW + 8 * DAY)
    assert len(page1.lines) == 6 and len(page2.lines) == 3
    assert "灵粮" in page1.text() and "后改名字" not in page1.text()
    assert "灵宠垂钓 鱼篓 2" in page1.commands and "灵宠垂钓 鱼篓 1" in page2.commands
    assert "鱼篓共 0 竿" in play("fishing", "鱼篓", user="other").text()


@pytest.mark.parametrize("field,value", [
    ("cost_quantity", 0), ("multiplier", 1), ("favored_items", []),
    ("favored_items", ["forge_ore", "forge_ore"]), ("id", "plain"), ("description", " "),
])
def test_bait_content_bounds(game, field, value):
    data = game[0].content.fishing_baits["grain"].model_dump()
    with pytest.raises(ValidationError):
        FishingBait.model_validate({**data, field: value})


def test_catalog_rejects_unknown_bait_cost_and_noncatch_target(game):
    for update in ({"cost_item": "no_item"}, {"favored_items": ["breakthrough_pill"]}):
        bait = game[0].content.fishing_baits["grain"].model_copy(update=update)
        catalog = replace(game[0].content, fishing_baits={"grain": bait})
        with pytest.raises(ValueError):
            Catalog._validate_fishing_spots(catalog)
