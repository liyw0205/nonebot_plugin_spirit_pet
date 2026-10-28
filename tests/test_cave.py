"""Cave residence: facility content, upgrades, daily actions and persistence."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86400


def facilities(game):
    return sorted(game[0].content.cave.values(), key=lambda facility: facility.id)


def grant_stones(game, amount, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (amount, user))


def give(game, item_id, amount, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
        (user, item_id, amount),
    )


def add_pet(game, user, species, name, *, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, 0, 1, 0, 0, 0, 100, ?, ?)",
        (user, species, name, NOW, archived),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def set_energy(game, amount, user="u1", now=NOW):
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?", (amount, now, user))


def set_affinity(game, amount, user="u1"):
    sql(game[1], "UPDATE pets SET affinity=? WHERE user_id=?", (amount, user))


def level_rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'cave_%_level'"
        " ORDER BY quest_id",
        (user,),
    )


def test_content_defines_three_facilities_with_five_levels(game):
    entries = facilities(game)
    assert [facility.id for facility in entries] == ["alchemy", "pen", "spring"]
    assert {facility.effect for facility in entries} == {"energy", "affinity", "item"}
    for facility in entries:
        assert facility.max_level == 5
        assert len(facility.yields) == 5 and len(facility.upgrades) == 4
        assert facility.yields == sorted(facility.yields)
        assert [step.stones for step in facility.upgrades] == [300, 700, 1500, 3000]
        assert all(len(step.items) == 1 for step in facility.upgrades)
        assert all(amount in (2, 4, 6, 8) for step in facility.upgrades for amount in step.items.values())
    by_id = {facility.id: facility for facility in entries}
    assert by_id["spring"].item is None and by_id["spring"].yields[0] == 30
    assert by_id["pen"].yields == [3, 5, 7, 9, 12]
    assert by_id["alchemy"].item == "exp_pill" and by_id["alchemy"].yields == [1, 1, 2, 2, 3]
    assert all(
        item in game[0].content.items
        for facility in entries for step in facility.upgrades for item in step.items
    )


def test_page_without_a_pet_is_read_only(game, play):
    page = play("cave", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_levels_effects_and_upgrade_cost(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 5000)
    give(game, "spirit_food", 10)
    page = play("cave")
    assert "洞府总览：3/15 级" in page.text()
    assert "今日剩余 3 次设施行动" in page.text()
    assert "灵泉 · Lv1 · 为一只伙伴恢复 30 精力 · 今日可用" in page.text()
    assert "兽栏 · Lv1 · 为一只伙伴增加 3 亲密 · 今日可用" in page.text()
    assert "丹房 · Lv1 · 获得 蕴灵丹 ×1 · 今日可用" in page.text()
    assert "升级 Lv2：灵石 300、灵粮 2" in page.text()
    linked = {link.label for link in page.inline_commands}
    assert "使用" in linked and "升级" in linked


def test_page_marks_missing_resources_and_hides_the_upgrade_link(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 100)
    page = play("cave")
    assert "升级 Lv2：灵石 300、灵粮 2（资源不足）" in page.text()
    assert "升级" not in {link.label for link in page.inline_commands}


def test_upgrade_spends_exactly_and_raises_the_level(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 5000)
    give(game, "spirit_food", 10)
    reply = play("cave", "升级 灵泉")
    assert "灵泉 提升至 Lv2" in reply.text()
    assert player(game[1])["stones"] == 4700
    assert items(game[1])["spirit_food"] == 8
    assert level_rows(game) == [{"quest_id": "cave_spring_level", "progress": 2}]
    page = play("cave")
    assert "灵泉 · Lv2 · 为一只伙伴恢复 45 精力" in page.text()
    assert "洞府总览：4/15 级" in page.text()


def test_upgrade_at_the_cap_is_refused(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 99999)
    give(game, "spirit_food", 99)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', 'cave_spring_level', 5, 1)",
    )
    with pytest.raises(GameError, match="满级"):
        play("cave", "升级 灵泉")
    assert player(game[1])["stones"] == 99999


def test_upgrade_refuses_without_enough_stones_or_materials(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 100)
    give(game, "spirit_food", 10)
    with pytest.raises(GameError, match="灵石不足"):
        play("cave", "升级 灵泉")
    assert player(game[1])["stones"] == 100 and items(game[1])["spirit_food"] == 10
    grant_stones(game, 5000)
    give(game, "spirit_food", 1)
    with pytest.raises(GameError, match="材料不足"):
        play("cave", "升级 灵泉")
    assert player(game[1])["stones"] == 5000 and items(game[1])["spirit_food"] == 1
    assert level_rows(game) == []


def test_upgrade_rejects_unknown_facilities_and_empty_arguments(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError):
        play("cave", "升级 不存在的设施")
    with pytest.raises(GameError, match="格式"):
        play("cave", "升级")
    with pytest.raises(GameError, match="格式"):
        play("cave", "打扫")


def test_spring_restores_energy_caps_it_and_locks_the_day(game, play):
    play("adopt", "青鸾")
    set_energy(game, 20)
    reply = play("cave", "使用 灵泉")
    assert "灵泉凝神：青鸾精力 +30（50/100）" in reply.text()
    assert pet(game[1])["energy"] == 50
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'cave_spring_day_%'")
    with pytest.raises(GameError, match="今日已经用过"):
        play("cave", "使用 灵泉")
    assert pet(game[1])["energy"] == 50

    set_energy(game, 90, now=NOW + DAY)
    reply = play("cave", "使用 灵泉", now=NOW + DAY)
    assert "精力 +10（100/100）" in reply.text()
    assert pet(game[1])["energy"] == 100


def test_a_full_pet_is_refused_without_spending_the_daily_action(game, play):
    play("adopt", "青鸾")
    set_energy(game, 100)
    with pytest.raises(GameError, match="精力已满"):
        play("cave", "使用 灵泉")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'cave_spring_day_%'")


def test_pen_raises_affinity_and_caps_at_one_hundred(game, play):
    play("adopt", "青鸾")
    set_affinity(game, 99)
    reply = play("cave", "使用 兽栏")
    assert "兽栏抚慰：青鸾亲密 +1（100/100）" in reply.text()
    assert pet(game[1])["affinity"] == 100
    with pytest.raises(GameError, match="亲密已满"):
        play("cave", "使用 兽栏", now=NOW + DAY)


def test_alchemy_produces_the_item_without_a_pet(game, play):
    play("adopt", "青鸾")
    reply = play("cave", "使用 丹房")
    assert "丹房开炉：蕴灵丹 ×1 已入乾坤袋" in reply.text()
    assert items(game[1])["exp_pill"] == 1
    with pytest.raises(GameError, match="不需要指定伙伴"):
        play("cave", "使用 丹房 青鸾")


def test_use_targets_only_owned_pets(game, play):
    play("adopt", "青鸾")
    add_pet(game, "u1", "xuanhu", "旧友", archived=1)
    play("adopt", "青鸾", user="mate")
    sql(game[1], "UPDATE pets SET name='青鸾甲' WHERE user_id='mate'")
    with pytest.raises(GameError, match="没有找到"):
        play("cave", "使用 灵泉 无名")
    with pytest.raises(GameError, match="封存"):
        play("cave", "使用 灵泉 旧友")
    with pytest.raises(GameError, match="没有找到"):
        play("cave", "使用 灵泉 青鸾甲")


def test_an_expedition_pet_cannot_use_the_cave(game, play):
    play("adopt", "青鸾")
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("cave", "使用 灵泉")


def test_using_a_facility_clears_team_readiness(game, play):
    play("adopt", "青鸾")
    set_energy(game, 20)
    sql(game[1], "INSERT INTO teams(leader_id) VALUES ('u1')")
    sql(
        game[1],
        "INSERT INTO team_members(user_id, team_id, ready_pet_id, ready_pet_ids) VALUES ('u1', 1, NULL, '')",
    )
    sql(game[1], "UPDATE team_members SET ready_pet_ids=? WHERE user_id='u1'", (str(pet(game[1])["pet_id"]),))
    play("cave", "使用 灵泉")
    assert sql(game[1], "SELECT ready_pet_ids FROM team_members WHERE user_id='u1'")[0]["ready_pet_ids"] == ""


def test_levels_survive_a_restart(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 5000)
    give(game, "spirit_food", 10)
    play("cave", "升级 灵泉")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "cave", "", "restart-cave", NOW)
    assert "灵泉 · Lv2 · 为一只伙伴恢复 45 精力" in page.text()
    assert "洞府总览：4/15 级" in page.text()


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "成长")
    assert "灵宠洞府" in guide.text() and "灵宠洞府 升级" in guide.text()
    objectives = play("objectives")
    assert "洞府：总 3/15 级 · 今日剩余 3 次设施行动" in objectives.text()
    assert handlers._parse("灵宠洞府") == ("cave", "")
    assert handlers._parse("灵宠洞府 升级 灵泉") == ("cave", "升级 灵泉")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    grant_stones(game, 5000)
    give(game, "spirit_food", 10)
    page = play("cave")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
