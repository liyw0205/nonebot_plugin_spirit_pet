import json

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql
from .test_pet_prep import worn
from .test_targeted_care import snapshot
from .test_targeted_training import NOW, add_pet


def test_exploration_ore_is_spent_on_original_pets_gear_and_captured_in_real_battle(game, play):
    play("adopt", "青鸾")
    target = add_pet(game[1])
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    sql(game[1], "UPDATE players SET stones=2000")
    play("buy", "灵心铃")
    page = play("equipment_catalog", "灵心铃 伙伴 1")
    equip = next(command for command in page.commands if command == "灵宠装备 灵心铃 伙伴 1")
    play(*handlers._parse(equip))
    equipment = play("equipment", "伙伴 1")
    assert "材料缺口：锻灵矿 1" in equipment.text()
    assert any(link.command == "灵宠历练 伙伴 1" for link in equipment.inline_commands)
    explored = play("explore", "星谷采集 伙伴 1", op="resource-explore")
    assert "伏击者被击退" in explored.text()
    assert items(game[1])["forge_ore"] == 1
    prep_link = next(link.command for link in explored.inline_commands if link.command == "灵宠整备 1")
    page = play(*handlers._parse(prep_link))
    enhance = next(link.command for link in page.inline_commands if link.command == "灵宠强化 饰品 伙伴 1")
    play("switch", str(target))
    before = player(game[1])["stones"]
    result = play(*handlers._parse(enhance), op="resource-enhance")
    assert player(game[1])["stones"] == before - 80
    assert items(game[1])["forge_ore"] == 0
    assert worn(game[1], 1)["charm"] == ("spirit_bell", 1)
    assert worn(game[1], target) == {}
    assert player(game[1])["active_pet_id"] == target
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", *handlers._parse(enhance), "resource-enhance", NOW + 86400) == result
    assert snapshot(game[1]) == before
    play("codex_trials", "挑战 青鸾 伙伴 1", op="resource-battle")
    capture = json.loads(sql(game[1], "SELECT snapshot FROM battle_records WHERE operation_id='resource-battle'")[0]["snapshot"])
    assert capture["teams"][0]["members"][0]["equipment"] == [
        {"slot": "charm", "item_id": "spirit_bell", "name": "灵心铃", "enhancement": 1},
    ]


def test_expedition_return_opens_original_pet_preparation_and_replays_after_cache_cleanup(game, play):
    play("adopt", "青鸾")
    target = add_pet(game[1])
    play("expedition_start", "采灵药")
    job = sql(game[1], "SELECT * FROM expeditions")[0]
    play("switch", str(target))
    reply = play("expedition_claim", str(job["job_id"]), now=job["finishes_at"], op="trip-return")
    assert reply.inline_commands[0].command == "灵宠整备 1"
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=1")[0]["exp"] > 0
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (target,)) == [{"exp": 0}]
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    assert play("expedition_claim", str(job["job_id"]), now=job["finishes_at"] + 86400, op="trip-return") == reply
    assert snapshot(game[1]) == before


def test_numbered_resource_pages_do_not_persist_energy_regeneration(game, play):
    play("adopt")
    sql(game[1], "UPDATE pets SET energy=0")
    before = snapshot(game[1])
    for action, argument in (("pet_prep", "1"), ("explore", "伙伴 1"), ("equipment_catalog", "伙伴 1"),
                             ("equipment", "伙伴 1"), ("skills", "伙伴 1"), ("sigils", "伙伴 1")):
        play(action, argument, now=NOW + 86400)
    assert snapshot(game[1]) == before


def test_enhancement_receipt_failure_rolls_back_materials_and_gear(game, play, monkeypatch):
    play("adopt")
    sql(game[1], "UPDATE players SET stones=2000")
    play("buy", "灵心铃")
    play("equipment", "灵心铃 伙伴 1")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',1)")
    before, gear = snapshot(game[1]), worn(game[1], 1)
    original = Repository.record_duel_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("forge receipt failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError, match="forge receipt failure"):
            play("enhance", "饰品 伙伴 1", op="retry-forge")
    assert snapshot(game[1]) == before and worn(game[1], 1) == gear
    assert play("enhance", "饰品 伙伴 1", op="retry-forge").title == "灵物淬炼"


def test_new_settlement_receipts_are_not_duel_rounds(game, play):
    play("adopt")
    play("main_quest_claim", "初结灵契")
    play("summon")
    play("sign")
    play("claim", "晨光初至")
    assert "尚无回合记录" in play("duel", "回顾").text()
    receipt_id = sql(game[1], "SELECT action_id FROM duel_actions LIMIT 1")[0]["action_id"]
    with pytest.raises(GameError, match="未找到本人的斗法"):
        play("duel", f"回顾 查看 {receipt_id}")
    assert play("duel").title
