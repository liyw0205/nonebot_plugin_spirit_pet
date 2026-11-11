import json
import re
import sqlite3

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.equipment_set_resonance import KEY
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql

NOW = 1_800_000_000


def account(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'forge_ore', 20) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
    )
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 5) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
    )


def equip_wind_set(play):
    play("buy", "青岚翎", op="buy-wind-feather")
    play("equipment", "青岚翎", op="equip-wind-feather")
    play("buy", "灵心铃", op="buy-spirit-bell")
    play("equipment", "灵心铃", op="equip-spirit-bell")


def test_content_and_route_are_wired(game, play):
    assert all(len(entry.resonance) == 3 for entry in game[0].content.equipment_sets.values())
    assert handlers._parse("灵宠套装共鸣 青岚风铃") == ("equipment_set_resonate", "青岚风铃")
    assert "灵宠套装共鸣 套装名：" in play("help", "灵物与灵术").text()
    with pytest.raises(GameError, match="灵宠"):
        play("equipment_set_resonate", "", user="u9")


def test_unregistered_resonance_is_read_only(game, play):
    page = play("equipment_sets", user="u9")
    assert all("尚未结契" in line for line in page.lines)
    with pytest.raises(GameError, match="还没有灵宠"):
        play("equipment_set_resonate", "青岚风铃", user="u9")
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_partial_set_refuses_without_writing(game, play):
    account(game, play)
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    before = (player(game[1]), items(game[1]))
    with pytest.raises(GameError, match="必须同时装备"):
        play("equipment_set_resonate", "青岚风铃")
    assert (player(game[1]), items(game[1])) == before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE ?", (f"{KEY}%",)) == []


def test_resonance_consumes_cost_and_changes_combat_stats(game, play):
    account(game, play)
    equip_wind_set(play)
    before = play("status").text()
    result = play("equipment_set_resonate", "青岚风铃", op="wind-resonance-1")
    assert result.title == "套装共鸣"
    assert "提升至 1/3 阶" in result.text()
    assert "攻击 +2 速度 +2" in result.text()
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?", (f"{KEY}sky_wind",)
    ) == [{"progress": 1, "claimed": 1}]
    assert items(game[1])["forge_ore"] == 18
    after = play("status").text()
    before_stats = re.search(r"气血：\d+ · 攻击：(\d+) · 防御：\d+ · 速度：(\d+)", before)
    after_stats = re.search(r"气血：\d+ · 攻击：(\d+) · 防御：\d+ · 速度：(\d+)", after)
    assert before_stats and after_stats
    assert int(after_stats.group(1)) == int(before_stats.group(1)) + 2
    assert int(after_stats.group(2)) == int(before_stats.group(2)) + 2
    assert "套装共鸣：1/3 阶" in play("equipment", "").text()
    battle = play("challenge", "青岚林", op="resonance-battle")
    assert battle.title == "秘境获胜"
    snapshot = json.loads(
        sql(game[1], "SELECT snapshot FROM battle_records WHERE operation_id=?", ("resonance-battle",))[0]["snapshot"]
    )
    member_stats = snapshot["teams"][0]["members"][0]["stats"]
    assert member_stats["attack"] == int(after_stats.group(1))
    assert member_stats["speed"] == int(after_stats.group(2))


def test_each_tier_is_sequential_and_replay_safe(game, play):
    account(game, play)
    equip_wind_set(play)
    first = play("equipment_set_resonate", "青岚风铃", op="wind-resonance-1")
    assert play("equipment_set_resonate", "青岚风铃", op="wind-resonance-1") == first
    stones_after_first = player(game[1])["stones"]
    second = play("equipment_set_resonate", "青岚风铃", op="wind-resonance-2")
    assert "提升至 2/3 阶" in second.text()
    assert player(game[1])["stones"] == stones_after_first - 900
    assert items(game[1])["forge_ore"] == 15
    assert items(game[1])["bloodline_essence"] == 4
    third = play("equipment_set_resonate", "青岚风铃", op="wind-resonance-3")
    assert "提升至 3/3 阶" in third.text()
    with pytest.raises(GameError, match="已达 3 阶"):
        play("equipment_set_resonate", "青岚风铃")


def test_external_pet_and_expedition_are_rejected(game, play):
    account(game, play)
    equip_wind_set(play)
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="行程"):
        play("equipment_set_resonate", "青岚风铃")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE ?", (f"{KEY}%",)) == []


def test_failure_rolls_back_cost_and_allows_retry(game, play):
    account(game, play)
    equip_wind_set(play)
    before = (player(game[1]), items(game[1]))
    sql(
        game[1],
        "CREATE TRIGGER reject_resonance BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{KEY}sky_wind' BEGIN SELECT RAISE(ABORT, 'injected resonance failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected resonance failure"):
        play("equipment_set_resonate", "青岚风铃", op="resonance-rollback")
    assert (player(game[1]), items(game[1])) == before
    sql(game[1], "DROP TRIGGER reject_resonance")
    assert play("equipment_set_resonate", "青岚风铃", op="resonance-rollback").title == "套装共鸣"


def test_resonance_survives_restart_and_activation_changes(game, play):
    account(game, play)
    equip_wind_set(play)
    play("equipment_set_resonate", "青岚风铃", op="resonance-restart")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "equipment_sets", "青岚风铃", "resonance-page", NOW)
    assert "套装共鸣：1/3 阶" in page.text()
    sql(game[1], "DELETE FROM equipment WHERE pet_id=?", (pet(game[1])["pet_id"],))
    assert "需先由当前出战伙伴穿齐" in restarted.execute(
        "u1", "equipment_sets", "青岚风铃", "resonance-unactive", NOW + 1
    ).text()


def test_native_keeps_resonance_link_out_of_buttons(game, play):
    account(game, play)
    equip_wind_set(play)
    page = play("equipment_sets", "青岚风铃")
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert "灵宠套装共鸣 青岚风铃" in links
    assert "灵宠套装共鸣 青岚风铃" not in buttons
