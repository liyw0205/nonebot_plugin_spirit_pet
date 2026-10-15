import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
WIND = "青岚翎"        # wind_feather, weapon, wind (the adopted 青鸾 can wear it)
FIRE = "赤焰牙"        # fire_fang, weapon
THUNDER = "震雷角"     # thunder_horn, weapon
METAL = "金魄镰"       # metal_scythe, weapon
CHARM = "灵心铃"       # spirit_bell, charm


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def fund(game, stones=5000, ore=20):
    sql(game[1], "UPDATE players SET stones=?", (stones,))
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'forge_ore', ?) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
        (ore,),
    )


def seed_bag(game, item_id, enhancement, quantity=1):
    if enhancement == 0:
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, ?) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (item_id, quantity),
        )
        return
    sql(
        game[1],
        "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) "
        "VALUES ('u1', ?, ?, ?) ON CONFLICT(user_id, item_id, enhancement) "
        "DO UPDATE SET quantity=quantity+excluded.quantity",
        (item_id, enhancement, quantity),
    )


def bag(game, item_id):
    zero = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id=?", (item_id,))
    rows = sql(
        game[1],
        "SELECT enhancement, quantity FROM unequipped_equipment WHERE user_id='u1' AND item_id=? "
        "AND quantity>0 ORDER BY enhancement",
        (item_id,),
    )
    return (zero[0]["quantity"] if zero else 0), [(row["enhancement"], row["quantity"]) for row in rows]


def test_inheritance_moves_the_level_and_charges_by_level(game, play):
    account(game, play)
    fund(game)
    seed_bag(game, "fire_fang", 3)
    seed_bag(game, "wind_feather", 0)

    result = play("inheritance", f"{FIRE} {WIND}", op="inherit-1")
    assert result.title == "强化继承完成"
    assert f"{FIRE}的 +3 已继承给{WIND}。" in result.text()
    assert f"{FIRE}回到 +0，{WIND}变为 +3。" in result.text()
    assert "消耗 240 灵石、锻灵矿 3。" in result.text()
    assert player(game[1])["stones"] == 5000 - 240
    assert items(game[1])["forge_ore"] == 20 - 3
    assert bag(game, "fire_fang") == (1, [])
    assert bag(game, "wind_feather") == (0, [(3, 1)])


def test_inheritance_cost_scales_with_the_source_level(game, play):
    account(game, play)
    fund(game)
    seed_bag(game, "fire_fang", 1)
    seed_bag(game, "wind_feather", 0)
    play("inheritance", f"{FIRE} {WIND}", op="inherit-low")
    assert player(game[1])["stones"] == 5000 - 80
    assert items(game[1])["forge_ore"] == 20 - 1
    assert bag(game, "wind_feather") == (0, [(1, 1)])

    seed_bag(game, "fire_fang", 10)
    seed_bag(game, "thunder_horn", 0)
    play("inheritance", f"{FIRE} {THUNDER}", op="inherit-high")
    assert player(game[1])["stones"] == 5000 - 80 - 800
    assert items(game[1])["forge_ore"] == 20 - 1 - 10
    assert bag(game, "thunder_horn") == (0, [(10, 1)])


def test_inheritance_rejects_bad_pairs(game, play):
    account(game, play)
    fund(game)
    seed_bag(game, "fire_fang", 3)
    seed_bag(game, "wind_feather", 0)
    seed_bag(game, "spirit_bell", 0)
    seed_bag(game, "thunder_horn", 2)

    with pytest.raises(GameError, match="格式"):
        play("inheritance", FIRE)
    with pytest.raises(GameError, match="两件不同的装备"):
        play("inheritance", f"{FIRE} {FIRE}")
    with pytest.raises(GameError, match="不是装备灵物"):
        play("inheritance", f"灵粮 {WIND}")
    with pytest.raises(GameError, match="同一部位"):
        play("inheritance", f"{FIRE} {CHARM}")
    with pytest.raises(GameError, match="没有强化过的"):
        play("inheritance", f"{WIND} {THUNDER}")
    with pytest.raises(GameError, match="已有强化等级"):
        play("inheritance", f"{FIRE} {THUNDER}")
    with pytest.raises(GameError, match="没有未强化的"):
        play("inheritance", f"{FIRE} {METAL}")

    sql(game[1], "UPDATE players SET stones=10")
    with pytest.raises(GameError, match="继承需要 240 灵石、锻灵矿 3。"):
        play("inheritance", f"{FIRE} {WIND}")
    sql(game[1], "UPDATE players SET stones=5000")
    sql(game[1], "UPDATE inventory SET quantity=1 WHERE item_id='forge_ore'")
    with pytest.raises(GameError, match="继承需要 240 灵石、锻灵矿 3。"):
        play("inheritance", f"{FIRE} {WIND}")
    assert bag(game, "wind_feather") == (1, [])


def test_inherited_equipment_can_be_equipped(game, play):
    account(game, play)
    fund(game)
    seed_bag(game, "fire_fang", 4)
    seed_bag(game, "wind_feather", 0)
    play("inheritance", f"{FIRE} {WIND}", op="inherit-equip")
    play("equipment", WIND, op="equip-inherited")
    assert sql(
        game[1],
        "SELECT enhancement FROM equipment WHERE slot='weapon'",
    ) == [{"enhancement": 4}]


def test_replay_does_not_charge_twice(game, play):
    account(game, play)
    fund(game)
    seed_bag(game, "fire_fang", 2)
    seed_bag(game, "wind_feather", 0)
    first = play("inheritance", f"{FIRE} {WIND}", op="inherit-replay")
    state = (player(game[1])["stones"], items(game[1]), bag(game, "wind_feather"))
    assert play("inheritance", f"{FIRE} {WIND}", op="inherit-replay") == first
    assert (player(game[1])["stones"], items(game[1]), bag(game, "wind_feather")) == state


def test_help_lists_the_inheritance_entry(game, play):
    guide = play("help", "血脉与道具")
    assert "灵宠强化继承 源装备 目标装备" in guide.text()
