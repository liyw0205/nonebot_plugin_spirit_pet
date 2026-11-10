"""灵宠垂钓: three realm-gated spots, weighted catches and 鱼获 set bonuses."""

import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, sql

NOW = 1_800_000_000
DAY = 86_400


def snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(
            store,
            "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
            " ORDER BY user_id, quest_id",
        ),
    )


def seed_fish(game, spot, caught, user="u1"):
    for item in caught:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
            " VALUES (?, ?, 1, 1) ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
            (user, f"fish_{spot}_{item}"),
        )


@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def test_content_three_spots_with_real_tables(content_dir):
    catalog = Catalog.load(content_dir)
    assert len(catalog.fishing_spots) == 3
    assert {spot.realm for spot in catalog.fishing_spots.values()} == {0, 2, 4}
    assert sum(len(spot.catches) for spot in catalog.fishing_spots.values()) == 12


def test_content_short_table_is_rejected(content_dir):
    path = content_dir / "fishing_spots.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[0]["catches"] = data[0]["catches"][:2]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="at least three catches"):
        Catalog.load(content_dir)


def test_content_unknown_item_is_rejected(content_dir):
    path = content_dir / "fishing_spots.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[0]["catches"][0]["item"] = "no_such_item"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="fishing spot creek catch"):
        Catalog.load(content_dir)


def test_page_lists_spots_and_gates(game, play):
    play("adopt", "青鸾", now=NOW, op="fish-adopt")
    page = play("fishing", now=NOW, op="fish-page")
    text = page.text()
    assert "溪口 · 需 不限 · 精力 8 · 鱼获 0/4 · 可垂钓" in text
    assert "深潭 · 需 筑基" in text and "未解锁" in text
    assert "鱼获 0/12" in text
    assert [link.command for link in page.inline_commands] == [
        "灵宠垂钓 详情 溪口", "灵宠垂钓 溪口", "灵宠垂钓 详情 深潭", "灵宠垂钓 详情 灵渊",
    ]


def test_first_cast_pays_first_table_row(game, play):
    play("adopt", "青鸾", now=NOW, op="cast-adopt")
    energy = pet(game[1])["energy"]
    food = items(game[1])["spirit_food"]
    result = play("fishing", "溪口", now=NOW, op="cast-1")
    assert result.title == "灵宠垂钓"
    assert "在溪口起了竿：灵粮 ×1" in result.text()
    assert pet(game[1])["energy"] == energy - 8
    assert items(game[1])["spirit_food"] == food + 1
    assert sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE quest_id='fish_creek_spirit_food'",
    )
    assert "今日还剩 2 竿" in result.text()


def test_three_casts_per_day_then_reset(game, play):
    play("adopt", "青鸾", now=NOW, op="cap-adopt")
    for index in range(3):
        play("fishing", "溪口", now=NOW + index, op=f"cap-{index}")
    with pytest.raises(GameError, match="今日垂钓次数已用完"):
        play("fishing", "溪口", now=NOW + 10, op="cap-4")
    assert play("fishing", "溪口", now=NOW + DAY, op="cap-next-day").title == "灵宠垂钓"


def test_locked_spot_and_low_energy_write_nothing(game, play):
    play("adopt", "青鸾", now=NOW, op="lock-adopt")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="需要"):
        play("fishing", "深潭", now=NOW, op="lock-deep")
    assert snapshot(game[1]) == before

    sql(game[1], "UPDATE pets SET energy=5, energy_updated=?", (NOW,))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="精力不足"):
        play("fishing", "溪口", now=NOW + 1, op="lock-energy")
    assert snapshot(game[1]) == before


def test_unknown_spot_refuses(game, play):
    play("adopt", "青鸾", now=NOW, op="unknown-adopt")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("fishing", "不存在的水域", now=NOW, op="unknown")
    assert snapshot(game[1]) == before


def test_spot_set_pays_once(game, play):
    play("adopt", "青鸾", now=NOW, op="set-adopt")
    seed_fish(game, "creek", ["forge_ore", "seed_spirit_rice", "exp_pill"])
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    food = items(game[1])["spirit_food"]
    result = play("fishing", "溪口", now=NOW, op="set-1")
    assert "鱼获「溪口」集齐" in result.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones + 150
    # +1 from the catch itself, +1 from the set bonus
    assert items(game[1])["spirit_food"] == food + 2
    assert sql(
        game[1],
        "SELECT claimed FROM quest_progress WHERE quest_id='fishing_set_creek'",
    )[0]["claimed"] == 1
    # A later duplicate catch must not pay the set bonus again.
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    play("fishing", "溪口", now=NOW + DAY, op="set-2")
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones


def test_all_spots_complete_pays_grand_once(game, play):
    play("adopt", "青鸾", now=NOW, op="all-adopt")
    seed_fish(game, "creek", ["forge_ore", "seed_spirit_rice", "exp_pill"])
    seed_fish(game, "deep_pool", ["forge_ore", "seed_blood_herb", "spirit_food", "bloodline_essence"])
    seed_fish(game, "abyss", ["bloodline_essence", "exp_pill", "seed_blood_herb", "energy_pill"])
    result = play("fishing", "溪口", now=NOW, op="all-1")
    assert "三处水系鱼获全齐" in result.text()
    assert sql(
        game[1], "SELECT claimed FROM quest_progress WHERE quest_id='fishing_set_all'",
    )[0]["claimed"] == 1
    assert "合计 12/12" in result.text()


def test_objectives_and_today_discovery(game, play):
    play("adopt", "青鸾", now=NOW, op="disc-adopt")
    objectives = play("objectives", now=NOW, op="disc-obj")
    assert any(line.startswith("垂钓：") for line in objectives.lines)
    today = play("today", now=NOW, op="disc-today")
    assert "垂钓还剩 3 竿" in today.text()
    play("fishing", "溪口", now=NOW + 1, op="disc-cast")
    assert "垂钓还剩 3 竿" not in play("today", now=NOW + 2, op="disc-today-2").text()
