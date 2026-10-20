import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000


def stock_gear(game, item_id, enhancement=0, quantity=1):
    with game[1].connect() as conn:
        if enhancement:
            conn.execute(
                "INSERT INTO unequipped_equipment(user_id,item_id,enhancement,quantity) VALUES ('u1',?,?,?) "
                "ON CONFLICT(user_id,item_id,enhancement) DO UPDATE SET quantity=quantity+?",
                (item_id, enhancement, quantity, quantity),
            )
        else:
            conn.execute(
                "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
                "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+?",
                (item_id, quantity, quantity),
            )


def grant_resources(game, stones=10000, ore=100):
    sql(game[1], f"UPDATE players SET stones={stones}")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',?) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+?",
            (ore, ore),
        )


def test_cost_three_tiers(game, play):
    from nonebot_plugin_spirit_pet.gameplay.reforge import reforge_cost

    assert reforge_cost(0) == (150, 0)
    assert reforge_cost(5) == (450, 10)
    assert reforge_cost(10) == (750, 20)


def test_reforge_rotates_to_next_gear_in_slot(game, play):
    play("adopt", "青鸾", now=NOW)
    # weapon slot: wind_feather(青岚翎) -> next by catalog order
    stock_gear(game, "wind_feather", 0, 1)
    grant_resources(game)
    before = player(game[1])["stones"]
    result = play("reforge", "青岚翎", now=NOW + 1, op="rf-1")
    assert "已重铸为" in result.lines[0]
    assert "花费灵石 150、锻灵矿 0" in result.lines[1]
    assert player(game[1])["stones"] == before - 150


def test_reforge_deterministic_target(game, play):
    play("adopt", "青鸾", now=NOW)
    stock_gear(game, "wind_feather", 0, 2)
    grant_resources(game)
    first = play("reforge", "青岚翎", now=NOW + 1, op="rf-det")
    assert "已重铸为" in first.lines[0]
    target_name = first.lines[0].split("已重铸为 ")[1].split(" +0")[0]
    # Same input -> same target.
    stock_gear(game, "wind_feather", 0, 2)
    second = play("reforge", "青岚翎", now=NOW + 2, op="rf-det2")
    assert target_name in second.lines[0]


def test_enhanced_source_costs_more_and_resets(game, play):
    play("adopt", "青鸾", now=NOW)
    stock_gear(game, "wind_feather", 5, 1)
    grant_resources(game)
    before = player(game[1])["stones"]
    result = play("reforge", "青岚翎", now=NOW + 1, op="rf-enh")
    assert "青岚翎 +5 已重铸为" in result.lines[0]
    assert "花费灵石 450、锻灵矿 10" in result.lines[1]
    assert player(game[1])["stones"] == before - 450


def test_insufficient_resources_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    stock_gear(game, "wind_feather", 10, 1)
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="灵石不足"):
        play("reforge", "青岚翎", now=NOW + 1, op="rf-poor")
    sql(game[1], "UPDATE players SET stones=10000")
    with pytest.raises(GameError, match="锻灵矿"):
        play("reforge", "青岚翎", now=NOW + 2, op="rf-no-ore")


def test_unknown_and_non_equipment_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="未找到该内容"):
        play("reforge", "不存在的装备", now=NOW, op="rf-unknown")
    with pytest.raises(GameError, match="未找到该装备"):
        play("reforge", "灵粮", now=NOW, op="rf-not-gear")


def test_replay_returns_original_reply(game, play):
    play("adopt", "青鸾", now=NOW)
    stock_gear(game, "wind_feather", 0, 3)
    grant_resources(game)
    first = play("reforge", "青岚翎", now=NOW + 1, op="rf-rep")
    assert play("reforge", "青岚翎", now=NOW + 2, op="rf-rep") == first
    # Inventory only consumed once for the replayed operation.
    remaining = sql(game[1], "SELECT quantity FROM inventory WHERE item_id='wind_feather'")[0]["quantity"]
    assert remaining == 2


def test_unequip_then_reforge_flow(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "青岚翎", now=NOW, op="rf-flow-buy")
    play("equipment", "青岚翎", now=NOW + 1, op="rf-flow-equip")
    with pytest.raises(GameError, match="道具数量不足|背包内"):
        play("reforge", "青岚翎", now=NOW + 2, op="rf-flow-worn")
    play("unequip", "青岚翎", now=NOW + 3, op="rf-flow-unequip")
    result = play("reforge", "青岚翎", now=NOW + 4, op="rf-flow-ok")
    assert "已重铸为" in result.lines[0]


def test_help_and_gear_help_page(game, play):
    page = play("reforge", now=NOW)
    assert page.title == "装备重铸"
    assert "费用：" in page.text()


def test_native_keyboard_clean_and_parse(game, play):
    play("adopt", "青鸾", now=NOW)
    stock_gear(game, "wind_feather", 0, 1)
    grant_resources(game)
    page = play("reforge", "青岚翎", now=NOW + 1, op="rf-native")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    assert message["keyboard"] or message["markdown"]
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠重铸 青岚翎") == ("reforge", "青岚翎")
    assert handlers._parse("灵宠重铸") == ("reforge", "")
