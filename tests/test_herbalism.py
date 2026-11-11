import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.herbalism_content import HerbRoute, home_costs
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
DAY = 86400
PATHS = {
    "brook": [[2], [2, 3], [2, 3, 6], [4, 7]],
    "ridge": [[2, 3], [4], [4, 5], [4, 7, 8]],
    "grove": [[2, 3], [4], [4, 7], [4, 7, 8, 9]],
}


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "player_identity", "pets", "active_pet_slots", "inventory",
        "quest_progress", "duel_actions", "team_members", "battle_records",
    )}


def run_of(store, user="u1"):
    return json.loads(sql(store, "SELECT snapshot FROM duel_actions WHERE user_id=? "
                         "AND json_extract(snapshot,'$.kind')='herbalism' ORDER BY action_id DESC LIMIT 1", (user,))[0]["snapshot"])


def walk(play, path, **kwargs):
    for site in path:
        reply = play("herbalism", f"移动 {site}", **kwargs)
    return reply


def prepare_return(play):
    play("herbalism", "出发 brook")
    walk(play, [2])
    play("herbalism", "采集")
    walk(play, [1])


@pytest.mark.parametrize("route_id,path", [(route, path) for route, paths in PATHS.items() for path in paths])
def test_every_harvest_is_reachable_and_return_settles_actual_materials_once(game, play, route_id, path):
    play("adopt", "青鸾")
    original, inventory, stones = pet(game[1]), items(game[1]), player(game[1])["stones"]
    route = game[0].content.herb_routes[route_id]
    material = route.sites[path[-1] - 1].item_id
    play("herbalism", f"出发 {route_id}", op="start-herb")
    walk(play, path)
    play("herbalism", "采集")
    assert items(game[1]) == inventory
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")
    walk(play, [*reversed(path[:-1]), 1])
    final = play("herbalism", "返程", op="settled-herb")
    assert final.title == "采药返程" and "药篓已入袋" in final.text()
    assert items(game[1])[material] == inventory.get(material, 0) + 1
    assert pet(game[1])["energy"] == original["energy"] - 8
    assert player(game[1])["stones"] == stones
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 6}]
    assert not sql(game[1], "SELECT * FROM battle_records")
    before = snapshot(game[1])
    assert play("herbalism", "记录").lines == final.lines
    assert "1/4 处" in play("herbalism", "手记").text()
    assert play("herbalism", "返程", op="settled-herb") == final
    assert snapshot(game[1]) == before


def test_basket_capacity_replacement_and_journal_count_only_carried_sites(game, play):
    play("adopt", "青鸾")
    inventory = items(game[1])
    play("herbalism", "出发 ridge")
    walk(play, [4])
    play("herbalism", "采集")
    walk(play, [5])
    play("herbalism", "采集")
    walk(play, [8])
    before = snapshot(game[1])
    with pytest.raises(GameError, match="药篓已满"):
        play("herbalism", "采集")
    assert snapshot(game[1]) == before
    play("herbalism", "弃置 1")
    play("herbalism", "采集")
    walk(play, [5, 4, 1])
    play("herbalism", "返程")
    assert items(game[1])["seed_blood_herb"] == inventory.get("seed_blood_herb", 0) + 1
    assert items(game[1])["spirit_food"] == inventory.get("spirit_food", 0) + 1
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id GLOB 'herbalism_seen_*' ORDER BY quest_id") == [
        {"quest_id": "herbalism_seen_ridge_5"}, {"quest_id": "herbalism_seen_ridge_8"},
    ]
    assert "2/4 处" in play("herbalism", "手记").text()
    assert "单次最多 2/2" in play("herbalism", "手记").text()


def test_discard_does_not_regrow_and_return_needs_entrance(game, play):
    play("adopt", "青鸾")
    play("herbalism", "出发 brook")
    walk(play, [2])
    play("herbalism", "采集")
    play("herbalism", "弃置 1")
    before = snapshot(game[1])
    for arg, reason in (("采集", "已经采集"), ("返程", "尚未回到"), ("弃置 1", "格为空")):
        with pytest.raises(GameError, match=reason):
            play("herbalism", arg)
        assert snapshot(game[1]) == before


def test_return_budget_prevents_stranding_and_exact_zero_return_is_allowed(game, play):
    play("adopt", "青鸾")
    play("herbalism", "出发 brook")
    walk(play, [2, 1, 2, 3, 6])
    assert run_of(game[1])["remaining"] == 4
    before = snapshot(game[1])
    for arg in ("采集", "移动 9"):
        with pytest.raises(GameError, match="脚程不足"):
            play("herbalism", arg)
        assert snapshot(game[1]) == before
    walk(play, [3, 2, 1])
    assert run_of(game[1])["remaining"] == 0
    assert "空篓返程" in play("herbalism", "返程").text()
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")


@pytest.mark.parametrize("ending", ["撤离", "返程"])
def test_empty_return_or_abandon_does_not_grant_growth_or_items(game, play, ending):
    play("adopt", "青鸾")
    inventory = items(game[1])
    play("herbalism", "出发 brook")
    if ending == "撤离":
        walk(play, [2])
        play("herbalism", "采集")
    play("herbalism", ending)
    assert items(game[1]) == inventory
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'herbalism_seen_*'")
    with pytest.raises(GameError, match="今天已出发"):
        play("herbalism", "出发 ridge")


def test_entry_views_help_objectives_and_adoption_are_read_only(game, play):
    before = snapshot(game[1])
    assert play("herbalism").inline_commands[0].command == "灵宠领养 "
    assert "还没有" in play("herbalism", "记录").text()
    play("herbalism", "手记")
    play("herbalism", "预览 brook")
    with pytest.raises(GameError) as error:
        play("herbalism", "出发 brook")
    assert error.value.reply.inline_commands[0].command == "灵宠领养 "
    assert snapshot(game[1]) == before
    assert "10000" in play("adopt", "青鸾").text()
    assert any(link.command == "灵宠采药" for link in play("objectives").inline_commands)
    assert "灵宠采药" in play("help", "血脉与道具").text()
    sql(game[1], "UPDATE pets SET energy=5,energy_updated=?", (NOW - DAY,))
    before = snapshot(game[1])
    assert len(play("herbalism").commands) == 3
    for route in PATHS:
        assert "最短返程" in play("herbalism", f"预览 {route}").text()
    assert snapshot(game[1]) == before
    play("herbalism", "出发 brook")
    before = snapshot(game[1])
    play("herbalism", "地图", now=NOW + DAY)
    play("herbalism", "手记")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("argument", ["出发", "出发 x", "移动 0", "移动 10", "移动 １", "移动 -1", "移动 x",
                                        "移动 3", "移动 2 3", "采集", "采集 1", "返程 0 1", "弃置 3",
                                        "地图 1", "预览", "手记 1", "记录 1", "撤离 x", "未知"])
def test_bad_arguments_and_ineligible_actions_do_not_write(game, play, argument):
    play("adopt", "青鸾")
    play("herbalism", "出发 brook")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("herbalism", argument)
    assert snapshot(game[1]) == before


def test_stale_steps_and_previous_day_buttons_cannot_act_on_new_state(game, play):
    play("adopt", "青鸾")
    first = play("herbalism", "出发 brook")
    old = next(command for command in first.commands if "移动 2" in command).removeprefix("灵宠采药 ")
    play("herbalism", old)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="旧行程或旧步骤"):
        play("herbalism", old)
    assert snapshot(game[1]) == before
    play("herbalism", "撤离")
    play("herbalism", "出发 ridge", now=NOW + DAY)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="旧行程或旧步骤"):
        play("herbalism", old, now=NOW + DAY)
    assert snapshot(game[1]) == before


def test_active_cross_day_restart_and_expired_receipts_preserve_all_actions(game, play):
    play("adopt", "青鸾")
    first = play("herbalism", "出发 brook", op="start-herb")
    play("herbalism", "移动 2", op="move-herb")
    pick = play("herbalism", "采集", op="pick-herb")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已有一次"):
        play("herbalism", "出发 ridge", now=NOW + DAY)
    assert snapshot(game[1]) == before
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    sql(game[1], "DELETE FROM operations")
    assert restarted.execute("u1", "herbalism", "出发 brook", "start-herb", NOW + 10 * DAY) == first
    assert restarted.execute("u1", "herbalism", "采集", "pick-herb", NOW + 10 * DAY) == pick
    restarted.execute("u1", "herbalism", "移动 1", "restart-move", NOW + 10 * DAY)
    final = restarted.execute("u1", "herbalism", "返程", "return-herb", NOW + 10 * DAY)
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    assert play("herbalism", "返程", op="return-herb", now=NOW + 20 * DAY) == final
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="different user"):
        play("herbalism", "返程", user="u2", op="return-herb", now=NOW + 20 * DAY)


@pytest.mark.parametrize("action", ["移动 2", "采集", "弃置 1", "返程", "撤离"])
def test_clock_rollback_refuses_all_mutations_without_writes(game, play, action):
    play("adopt", "青鸾")
    prepare_return(play)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("herbalism", action, now=NOW - 1)
    assert not play("herbalism", now=NOW - 1).commands
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ["energy", "no_pet", "archived", "expedition"])
def test_start_conditions_refuse_without_quota_or_readiness_changes(game, play, blocked):
    play("adopt", "青鸾")
    if blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0")
    elif blocked == "no_pet":
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif blocked == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    else:
        play("expedition_start", "采灵药")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="精力不足|尚未选择|封存|派遣"):
        play("herbalism", "出发 brook")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ["archived", "expedition"])
def test_bound_partner_can_resume_after_restoration_or_recall(game, play, blocked):
    play("adopt", "青鸾")
    play("summon", "1")
    prepare_return(play)
    if blocked == "archived":
        play("switch", "2")
        play("pet_archive", "1")
    else:
        play("expedition_start", "采灵药")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="封存|派遣"):
        play("herbalism", "返程")
    page = play("herbalism")
    assert not page.commands
    assert {"灵宠行程", "灵宠封存库"} <= {link.command for link in page.inline_commands}
    assert snapshot(game[1]) == before
    if blocked == "archived":
        play("pet_restore", "1")
    else:
        job = sql(game[1], "SELECT job_id FROM expeditions WHERE state='running'")[0]["job_id"]
        play("expedition_cancel", str(job))
    assert "药篓已入袋" in play("herbalism", "返程").text()


def test_original_partner_growth_consumption_and_pet_specific_readiness(game, play):
    play("adopt", "青鸾")
    play("summon", "1")
    play("team_create")
    play("team_ready")
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','bond_exp_1',45,0)")
    play("herbalism", "出发 brook")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}]
    play("switch", "2")
    play("team_ready")
    walk(play, [2])
    play("herbalism", "采集")
    walk(play, [1])
    assert "等级 1 → 2" in play("herbalism", "返程").text()
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": 2}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 51}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_2'")
    assert "有获返程 0 次" in play("herbalism", "手记").lines[-1]
    play("switch", "1")
    assert "有获返程 1 次" in play("herbalism", "手记").lines[-1]
    before = pet(game[1])
    play("use", "灵粮 1")
    assert pet(game[1])["affinity"] > before["affinity"]


def test_collected_herb_and_food_feed_existing_alchemy_then_consumable_growth(game, play):
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM inventory")
    sql(game[1], "UPDATE players SET stones=1000")
    play("herbalism", "出发 brook")
    walk(play, [2])
    play("herbalism", "采集")
    walk(play, [3])
    play("herbalism", "采集")
    walk(play, [2, 1])
    play("herbalism", "返程")
    assert items(game[1]) == {"spirit_food": 1, "seed_blood_herb": 1}
    play("alchemy", "同心丹")
    assert items(game[1]).get("affinity_pill") == 1
    original = pet(game[1])
    play("use", "同心丹 1")
    assert pet(game[1])["affinity"] > original["affinity"]


def test_released_original_pet_can_only_abandon_not_receive_growth(game, play):
    play("adopt", "青鸾")
    play("summon", "1")
    prepare_return(play)
    play("switch", "2")
    play("pet_release", "确认 1")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已归灵"):
        play("herbalism", "返程")
    assert snapshot(game[1]) == before
    assert "已撤离" in play("herbalism", "撤离").text()
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_1'")


def test_route_item_names_and_costs_are_frozen_but_missing_reward_is_explicit(game, play):
    play("adopt", "青鸾")
    prepare_return(play)
    route = game[0].content.herb_routes.pop("brook")
    material = game[0].content.items.pop("spirit_food")
    assert "灵粮" in play("herbalism").text()
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵粮.*暂不可用"):
        play("herbalism", "返程", op="restore-return")
    assert snapshot(game[1]) == before
    game[0].content.items["spirit_food"] = material
    assert "溪谷药坡" in play("herbalism", "返程", op="restore-return").text()
    game[0].content.herb_routes["brook"] = route


@pytest.mark.parametrize("failure", ["item", "receipt", "growth"])
def test_return_failures_roll_back_inventory_growth_journal_and_can_retry(game, play, monkeypatch, failure):
    play("adopt", "青鸾")
    prepare_return(play)
    before = snapshot(game[1])
    method = {"item": "add_item", "receipt": "record_herbalism_action", "growth": "invalidate_pet_ready"}[failure]
    original = getattr(Repository, method)

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected return failure")

    monkeypatch.setattr(Repository, method, broken)
    with pytest.raises(RuntimeError, match="injected return failure"):
        play("herbalism", "返程", op="failed-return")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(Repository, method, original)
    assert "药篓已入袋" in play("herbalism", "返程", op="failed-return").text()


def test_start_receipt_failure_rolls_back_energy_quota_and_readiness(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("team_create")
    play("team_ready")
    before = snapshot(game[1])

    def broken(*args):
        raise RuntimeError("injected start failure")

    monkeypatch.setattr(Repository, "record_herbalism_action", broken)
    with pytest.raises(RuntimeError, match="injected start failure"):
        play("herbalism", "出发 brook")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("same_operation", [True, False])
def test_concurrent_return_has_one_payout(game, play, same_operation):
    play("adopt", "青鸾")
    prepare_return(play)

    def execute(index):
        try:
            return game[0].execute("u1", "herbalism", "返程", "parallel-return" if same_operation else f"return-{index}", NOW)
        except GameError as error:
            return str(error)

    inventory = items(game[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(execute, range(2)))
    if same_operation:
        assert replies[0] == replies[1]
    else:
        assert sum(isinstance(reply, str) and "当前没有" in reply for reply in replies) == 1
    assert items(game[1])["spirit_food"] == inventory.get("spirit_food", 0) + 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [{"progress": 6}]


def test_other_users_and_existing_action_consumers_do_not_see_herbalism(game, play):
    play("adopt", "青鸾")
    play("adopt", "青鸾", user="u2")
    play("duel", "松风道人")
    duel = play("duel")
    play("tracking", "出发 bamboo")
    tracking = play("tracking")
    play("herbalism", "出发 brook", op="private-herb")
    play("herbalism", "出发 ridge", user="u2")
    assert "溪谷药坡" in play("herbalism").text()
    assert "赤岩药岭" in play("herbalism", user="u2").text()
    assert play("duel").lines == duel.lines
    assert play("tracking").lines == tracking.lines
    action_id = sql(game[1], "SELECT action_id FROM duel_actions WHERE operation_id='private-herb'")[0]["action_id"]
    with pytest.raises(GameError, match="未找到本人的"):
        play("duel", f"回顾 查看 {action_id}")
    assert "溪谷药坡" not in play("duel", "回顾").text()
    with game[1].connect() as conn:
        repo = Repository(conn)
        for method in (repo.duel_operation, repo.tracking_operation, repo.cooking_operation, repo.stage_tactic_operation):
            assert method("private-herb", "u1") is None


@pytest.mark.parametrize("change", ["size", "duplicate", "entrance", "no_harvest", "unreachable", "runtime", "cost"])
def test_invalid_route_content_is_rejected(game, change):
    data = game[0].content.herb_routes["brook"].model_dump()
    if change == "size":
        data["sites"].pop()
    elif change == "duplicate":
        data["sites"][1]["name"] = data["sites"][0]["name"]
    elif change == "entrance":
        data["sites"][0]["item_id"] = "spirit_food"
    elif change == "no_harvest":
        for site in data["sites"]:
            site["item_id"] = None
    elif change == "unreachable":
        for site in data["sites"]:
            site["cost"] = 3
    elif change == "cost":
        data["sites"][1]["cost"] = 0
    else:
        data["position"] = 1
    with pytest.raises(ValidationError):
        HerbRoute.model_validate(data)


def test_catalog_requires_existing_harvest_items(game):
    game[0].content.items.pop("seed_blood_herb")
    with pytest.raises(ValueError):
        game[0].content.validate()


def test_return_distances_charge_arrival_cost_and_take_cheaper_detour():
    assert home_costs([1] * 9) == [0, 1, 2, 1, 2, 3, 2, 3, 4]
    assert home_costs([1, 3, 1, 1, 1, 1, 1, 1, 1]) == [0, 1, 4, 1, 2, 3, 2, 3, 4]


@pytest.mark.parametrize("route_id,crop_id", [("ridge", "blood_herb"), ("grove", "aura_ear")])
def test_collected_seeds_reach_existing_plant_growth_and_harvest(game, play, route_id, crop_id):
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM inventory")
    sql(game[1], "UPDATE players SET stones=1000")
    play("herbalism", f"出发 {route_id}")
    walk(play, [4])
    play("herbalism", "采集")
    walk(play, [1])
    play("herbalism", "返程")
    crop = game[0].content.crops[crop_id]
    seed = game[0].content.items[crop.seed_item]
    assert items(game[1])[seed.id] == 1
    play("farm_open", "1")
    play("farm_plant", f"1 {seed.name}")
    assert not items(game[1]).get(seed.id)
    result = play("farm_harvest", "1", now=NOW + crop.duration)
    assert "成熟收获" in result.text()
    for item_id, bounds in crop.reward_items.items():
        assert items(game[1])[item_id] >= bounds.minimum


@pytest.mark.parametrize("phase", ["move", "harvest", "discard", "abandon"])
def test_intermediate_receipt_failure_is_atomic_and_retryable(game, play, monkeypatch, phase):
    play("adopt", "青鸾")
    play("herbalism", "出发 brook")
    if phase in ("harvest", "discard"):
        walk(play, [2])
    if phase == "discard":
        play("herbalism", "采集")
    argument = {"move": "移动 2", "harvest": "采集", "discard": "弃置 1", "abandon": "撤离"}[phase]
    before = snapshot(game[1])
    original = Repository.record_herbalism_action

    def broken(*args):
        original(*args)
        raise RuntimeError("injected action failure")

    monkeypatch.setattr(Repository, "record_herbalism_action", broken)
    with pytest.raises(RuntimeError, match="injected action failure"):
        play("herbalism", argument, op="retry-action")
    assert snapshot(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='retry-action'")
    monkeypatch.setattr(Repository, "record_herbalism_action", original)
    play("herbalism", argument, op="retry-action")


@pytest.mark.parametrize("phase", ["start", "harvest"])
def test_concurrent_distinct_start_or_harvest_only_mutates_once(game, play, phase):
    play("adopt", "青鸾")
    original_energy = pet(game[1])["energy"]
    if phase == "harvest":
        play("herbalism", "出发 brook")
        walk(play, [2])
    argument = "出发 brook" if phase == "start" else "采集"

    def execute(index):
        try:
            return game[0].execute("u1", "herbalism", argument, f"race-{index}", NOW)
        except GameError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(execute, range(2)))
    assert sum(isinstance(reply, str) for reply in replies) == 1
    assert pet(game[1])["energy"] == original_energy - 8
    run = run_of(game[1])
    assert len(run["basket"]) == (1 if phase == "harvest" else 0)


def test_finished_journal_survives_new_run_and_clock_cannot_reopen_previous_day(game, play):
    play("adopt", "青鸾")
    prepare_return(play)
    result = play("herbalism", "返程")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("herbalism", "出发 ridge", now=NOW - DAY)
    assert snapshot(game[1]) == before
    play("herbalism", "出发 ridge", now=NOW + DAY)
    assert play("herbalism", "记录", now=NOW + DAY).lines == result.lines
    assert "溪谷药坡 · 已带回 1/4 处" in play("herbalism", "手记", now=NOW + DAY).text()


def test_return_growth_invalidates_readiness_of_the_bound_partner(game, play):
    play("adopt", "青鸾")
    play("team_create")
    prepare_return(play)
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": 1}]
    play("herbalism", "返程")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}]


def test_qq_native_text_and_keyboard_disabled_preserve_actions_without_tokens_in_labels(game, play):
    play("adopt", "青鸾")
    pages = [play("herbalism"), play("herbalism", "预览 ridge"), play("herbalism", "出发 ridge")]
    pages.append(walk(play, [4, 5]))
    pages.append(play("herbalism", "采集"))
    pages.append(play("herbalism", "撤离"))
    for reply in pages:
        assert len(reply.commands) <= 4
        assert all(not re.search(r"20\d{6}", label) for label, _ in _action_items(reply))
        _, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        body = native["markdown"][0].data["markdown"].content
        linked = {parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        buttons = {button.action.data for segment in native["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert buttons == {"!" + command for command in reply.commands}
        assert linked == {"!" + link.command for link in reply.inline_commands}
        assert not buttons & linked
        for config in (Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"),
                       Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!", spirit_pet_qq_keyboard=False)):
            _, rendered = _qq_segments(reply, config)
            expected = {"!" + command for command in (*reply.commands, *(link.command for link in reply.inline_commands))}
            if config.spirit_pet_qq_mode == "text":
                assert all(command in str(rendered) for command in expected)
            else:
                body = rendered["markdown"][0].data["markdown"].content
                linked = {parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
                assert expected <= linked


def test_onebot_plays_representative_chain_and_qq_only_checks_entry_boundary(game, monkeypatch):
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        for index, command in enumerate(("!灵宠领养 青鸾", "!灵宠采药", "!灵宠采药 出发 溪谷药坡",
                                         "!灵宠采药 移动 2", "!灵宠采药 采集", "!灵宠采药 移动 1", "!灵宠采药 返程")):
            event = onebot_event(command, index + 1)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(run())
    sent = [call.args[1] for call in bot.send.call_args_list]
    assert len(sent) == 7 and "10000" in sent[0] and "药篓已入袋" in sent[-1]
    event = qq_event(user_id="qq-herbalism", text="!灵宠采药", message_id="qq-herbalism-entry")
    assert handlers._parse(event.get_plaintext()) == ("herbalism", "")
    qq_bot = Bot(Adapter(nonebot.get_driver()), "test-app", BotInfo(id="test-app", secret="test-only", token="test-only"))
    qq_bot.post_group_messages = AsyncMock(return_value={})
    asyncio.run(handlers.handle_command(qq_bot, event, event.get_message()))
    assert qq_bot.post_group_messages.await_count == 1
