import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.convoy_content import ConvoyRoute
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import bond_levels, convoy, mastery
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository
from .support import items, pet, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000
ROUTES = ("青山矿车", "灵脉药车", "丰谷粮车")


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in
            ("players", "pets", "inventory", "quest_progress", "learned_skills", "duel_actions", "team_members")}


def saved(store):
    return json.loads(sql(store, "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='convoy' "
                          "ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


def prepare(play, skill=False):
    play("adopt", "青鸾")
    play("sign")
    if skill:
        play("buy", "风刃术诀")
        play("learn", "风刃术")


def complete(play, strategy="绕行"):
    for _ in range(3):
        reply = play("convoy", "行进 " + ("1 绕行" if strategy == "绕行" else "2 " + strategy))
    return reply


def test_public_catalog_preview_and_sources_have_no_business_writes(game, play):
    before = snapshot(game[1])
    page = play("convoy")
    assert "尚未结契" in page.text()
    assert {link.command for link in page.inline_commands} >= {"灵宠护航 预览 " + route for route in ROUTES}
    for route in ROUTES:
        reply = play("convoy", "预览 " + route)
        assert "路损" in reply.text() and "林间傀儡" in reply.text()
        assert "攻击" in reply.text() and "购买灵粮" in {link.label for link in reply.inline_commands}
    assert snapshot(game[1]) == before
    assert not sql(game[1], "SELECT * FROM player_identity")
    prepare(play)
    before = snapshot(game[1])
    play("convoy")
    play("convoy", "预览 青山矿车")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("route", ROUTES)
def test_all_routes_have_a_complete_safe_player_flow(game, play, route):
    prepare(play)
    before_stones = player(game[1])["stones"]
    before_food = items(game[1])["spirit_food"]
    opening = play("convoy", "出发 " + route)
    assert "精力-10、灵粮-1" in opening.text()
    assert pet(game[1])["energy"] == 90 and items(game[1])["spirit_food"] == before_food - 1
    result = complete(play)
    assert "抵达" in result.title and "灵石+60" in result.text()
    assert player(game[1])["stones"] == before_stones + 60
    assert saved(game[1])["status"] == "arrived"
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'")[0]["progress"] == 8
    assert "抵达入袋" in play("convoy", "记录").text()
    with pytest.raises(GameError, match="今天已出发"):
        play("convoy", "出发 " + route)


def test_safe_supply_changes_cargo_and_bonus_with_real_food(game, play):
    prepare(play)
    play("convoy", "出发 青山矿车")
    play("convoy", "行进 1 绕行")
    food = items(game[1])["spirit_food"]
    supply = play("convoy", "补给")
    assert "灵粮-1" in supply.text() and saved(game[1])["cargo"] == 100
    assert items(game[1])["spirit_food"] == food - 1
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经补给"):
        play("convoy", "补给")
    assert snapshot(game[1]) == before
    play("convoy", "行进 1 绕行")
    play("convoy", "补给")
    result = play("convoy", "行进 1 绕行")
    assert "灵石+90" in result.text()


@pytest.mark.parametrize("strategy", ("护卫", "开路"))
def test_battle_road_material_and_skill_use_reach_real_consumers(game, play, strategy):
    prepare(play, skill=True)
    play("sign", now=NOW + 86400)
    execute = play
    play = lambda action, arg="": execute(action, arg, now=NOW + 86400)
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    play("convoy", "出发 青山矿车")
    opening = saved(game[1])
    result = play("convoy", "行进 2 " + strategy)
    assert "第2/3站" in result.text(), result.text()
    progress = saved(game[1])
    assert progress["fighter"]["hp"] < opening["fighter"]["hp"]
    assert progress["history"][0]["battle"] and progress["history"][0]["won"]
    assert progress["items"] == {"forge_ore": 1}
    assert items(game[1]).get("forge_ore", 0) == 0
    play("convoy", "行进 1 绕行")
    reply = play("convoy", "行进 1 绕行")
    assert "抵达" in reply.title and "实际施法" in reply.text()
    assert items(game[1])["forge_ore"] == 1
    skill = sql(game[1], "SELECT level,proficiency FROM learned_skills WHERE pet_id=1 AND skill_id='wind_slash'")[0]
    assert skill["level"] > 1 or skill["proficiency"] > 0
    play("enhance", "灵器")
    assert items(game[1])["forge_ore"] == 0
    assert sql(game[1], "SELECT enhancement FROM equipment WHERE pet_id=1")[0]["enhancement"] == 1


def test_frozen_rules_enemies_loadout_and_original_pet_survive_restart(game, play):
    prepare(play)
    play("convoy", "出发 青山矿车")
    opening = saved(game[1])
    play("summon")
    second = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>1")[0]["pet_id"]
    play("switch", str(second))
    game[0].content.convoy_routes.clear()
    game[0].content.enemies.clear()
    game[0].content.elements.clear()
    resumed = Game(game[1], Config(), content=game[0].content)
    for index in range(3):
        result = resumed.execute("u1", "convoy", "行进 1 绕行", f"resumed-{index}", NOW + 86400)
    assert "抵达" in result.title
    assert saved(game[1])["route"] == opening["route"]
    assert player(game[1])["active_pet_id"] == second
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'")[0]["progress"] == 8
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (f"bond_exp_{second}",))


def test_permanent_replay_step_and_clock_guards(game, play):
    prepare(play)
    first = play("convoy", "出发 青山矿车", op="opening")
    arg = first.commands[0].removeprefix("灵宠护航 ")
    step = play("convoy", arg, op="step", now=NOW + 10)
    before = snapshot(game[1])
    assert play("convoy", arg, op="step", now=NOW + 86400) == step
    with pytest.raises(GameError, match="旧局或旧步骤"):
        play("convoy", arg, op="old-button", now=NOW + 10)
    with pytest.raises(GameError, match="时间早于"):
        play("convoy", "行进 1 绕行", op="rollback", now=NOW)
    assert "时间早于" in play("convoy", now=NOW).text()
    assert snapshot(game[1]) == before
    with closing(game[1].connect()) as conn:
        conn.execute("DELETE FROM operations")
    resumed = Game(game[1], Config())
    assert resumed.execute("u1", "convoy", "", "step", NOW + 86400) == step
    with pytest.raises(GameError, match="different user"):
        resumed.execute("u2", "convoy", "", "opening", NOW)


@pytest.mark.parametrize("argument", ("行进 0 绕行", "行进 3 绕行", "行进 1 护卫", "行进 2 绕行",
                                     "行进 1 绕行 局 1", "补给 局 1 步 " + "9" * 5000))
def test_bad_arguments_are_bounded_and_atomic(game, play, argument):
    prepare(play)
    play("convoy", "出发 青山矿车")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("convoy", argument)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("blocked", ("sealed", "trip", "released", "missing", "forgotten"))
def test_original_partner_pause_and_explicit_exit(game, play, blocked):
    prepare(play, skill=True)
    play("convoy", "出发 青山矿车")
    if blocked == "sealed":
        sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=1")
    elif blocked == "trip":
        play("expedition_start", "采灵药")
    elif blocked == "released":
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1','released_1',1,1)")
    elif blocked == "forgotten":
        sql(game[1], "DELETE FROM learned_skills WHERE pet_id=1")
    else:
        play("adopt", "青鸾", user="other")
        sql(game[1], "DELETE FROM active_pet_slots WHERE pet_id=1")
        sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=1")
    reason = {"sealed": "已封存", "trip": "外出派遣", "released": "已归灵", "missing": "不存在", "forgotten": "已遗忘"}[blocked]
    before = snapshot(game[1])
    assert reason in play("convoy").text()
    assert not play("convoy").commands
    with pytest.raises(GameError, match=reason):
        play("convoy", "行进 1 绕行")
    assert snapshot(game[1]) == before
    if blocked == "sealed":
        play("pet_restore", "1")
    elif blocked == "trip":
        job = sql(game[1], "SELECT job_id FROM expeditions WHERE user_id='u1'")[0]["job_id"]
        play("expedition_cancel", str(job))
    else:
        assert "撤回" in play("convoy", "撤回").title
        return
    assert "第2/3站" in play("convoy", "行进 1 绕行").text()


def test_daily_and_energy_refusals_do_not_mutate_and_abandon_does_not_pay(game, play):
    prepare(play)
    sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=1", (NOW,))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="精力不足"):
        play("convoy", "出发 青山矿车")
    assert snapshot(game[1]) == before
    play("convoy", "出发 青山矿车", now=NOW + 86400)
    before = snapshot(game[1])
    reply = play("convoy", "撤回", now=NOW + 86400)
    assert "不发货物" in reply.text()
    after = snapshot(game[1])
    assert before["inventory"] == after["inventory"] and before["pets"] == after["pets"]
    with pytest.raises(GameError, match="时间早于|日期早于"):
        play("convoy", "出发 青山矿车", now=NOW + 1)


@pytest.mark.parametrize("phase,source,method", (
    ("start", Repository, "consume_item"), ("start", Repository, "invalidate_pet_ready"),
    ("start", Repository, "record_convoy_action"),
    ("supply", Repository, "consume_item"), ("supply", Repository, "record_convoy_action"),
    ("finish", Repository, "add_item"), ("finish", Repository, "invalidate_pet_ready"),
    ("finish", Repository, "record_convoy_action"),
    ("start", Repository, "save"), ("finish", Repository, "save"),
    ("start", convoy, "_write"), ("finish", convoy, "_write"),
    ("finish", bond_levels, "add_exp"), ("finish", mastery, "study"),
))
def test_write_fault_rolls_back_entire_operation_and_retries_once(game, play, monkeypatch, phase, source, method):
    prepare(play, skill=True)
    if phase != "start":
        play("convoy", "出发 青山矿车")
        play("convoy", "行进 2 开路")
    if phase == "finish":
        play("convoy", "行进 1 绕行")
    argument = {"start": "出发 青山矿车", "supply": "补给", "finish": "行进 1 绕行"}[phase]
    before = snapshot(game[1])
    original = getattr(source, method)

    def broken(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("convoy injected write failure")

    monkeypatch.setattr(source, method, broken)
    with pytest.raises(RuntimeError, match="convoy injected"):
        play("convoy", argument, op="fault")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(source, method, original)
    result = play("convoy", argument, op="fault")
    assert play("convoy", argument, op="fault") == result


def test_concurrent_opening_and_final_step_only_apply_once(game, play):
    prepare(play)

    def open_run(op):
        try:
            return play("convoy", "出发 青山矿车", op=op)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(open_run, ("start-a", "start-b")))
    assert sum(not isinstance(reply, GameError) for reply in replies) == 1
    assert pet(game[1])["energy"] == 90
    play("convoy", "行进 1 绕行")
    reply = play("convoy", "行进 1 绕行")
    argument = reply.commands[0].removeprefix("灵宠护航 ")
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: play("convoy", argument, op="final"), range(2)))
    assert replies[0] == replies[1]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='convoy_pet_done_1'")[0]["progress"] == 1


def test_new_action_kind_is_invisible_to_all_duel_consumers(game, play):
    prepare(play)
    play("convoy", "出发 青山矿车", op="convoy-open")
    action_id = sql(game[1], "SELECT action_id FROM duel_actions")[0]["action_id"]
    with closing(game[1].connect()) as conn:
        repo = Repository(conn)
        assert repo.duel_operation("convoy-open", "u1") is None
        assert repo.latest_duel_action("u1") is None
    assert "青山矿车" not in play("duel", "回顾").text()
    with pytest.raises(GameError, match="未找到"):
        play("duel", "回顾 查看 " + str(action_id))


def test_catalog_rejects_missing_sources_and_unreachable_or_unchosen_routes(game):
    content = game[0].content
    with pytest.raises(ValueError, match="exactly three"):
        replace(content, convoy_routes={}).validate()
    data = content.convoy_routes["forge"].model_dump()
    data["stops"][0]["roads"][1]["enemies"] = []
    with pytest.raises(ValidationError, match="rewarded battle"):
        ConvoyRoute.model_validate(data)
    data = content.convoy_routes["forge"].model_dump()
    for stop in data["stops"]:
        stop["roads"][0]["damage"] = 40
    with pytest.raises(ValidationError, match="survivable"):
        ConvoyRoute.model_validate(data)
    bad = dict(content.items)
    bad["spirit_food"] = bad["spirit_food"].model_copy(update={"price": None})
    with pytest.raises(ValueError, match="public shop"):
        replace(content, items=bad).validate()


def test_qq_buttons_links_prefix_and_fallback_are_disjoint(game, play):
    prepare(play)
    reply = play("convoy", "出发 青山矿车")
    for reply in (reply, play("convoy", "行进 1 绕行")):
        assert len(reply.commands) <= 4
        assert not set(reply.commands) & {link.command for link in reply.inline_commands}
        _, payload = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        body = payload["markdown"][0].data["markdown"].content
        links = {parse_qs(urlparse(url).query)["command"][0]
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        buttons = {button.action.data for segment in payload["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert buttons == {"!" + command for _, command in _action_items(reply)}
        assert not buttons & links
        assert "!灵宠护航" in _qq_segments(reply, Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"))[0]


def test_onebot_handler_runs_complete_public_player_chain(game, monkeypatch):
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    monkeypatch.setattr(handlers, "game", game[0])
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    commands = ("灵宠护航 预览 青山矿车", "灵宠领养 青鸾", "灵宠签到", "灵宠护航 出发 青山矿车",
                "灵宠护航 行进 1 绕行", "灵宠护航 补给", "灵宠护航 行进 1 绕行",
                "灵宠护航 行进 1 绕行", "灵宠护航 记录", "灵宠背包")
    for index, command in enumerate(commands, 100):
        event = onebot_event("!" + command, index)
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert bot.send.await_count == len(commands)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='12345' AND quest_id='convoy_pet_done_1'")


@pytest.mark.parametrize("route,item_id", (("青山矿车", "forge_ore"), ("灵脉药车", "bloodline_essence"), ("丰谷粮车", "spirit_food")))
def test_each_route_really_loads_and_delivers_its_own_material(game, play, route, item_id):
    prepare(play, skill=True)
    before = items(game[1]).get(item_id, 0)
    play("convoy", "出发 " + route)
    play("convoy", "行进 2 开路")
    assert saved(game[1])["items"] == {item_id: 1}
    play("convoy", "行进 1 绕行")
    assert "抵达" in play("convoy", "行进 1 绕行").title
    assert items(game[1])[item_id] == before + 1 - (1 if item_id == "spirit_food" else 0)
    if item_id == "spirit_food":
        before_affinity = pet(game[1])["affinity"]
        play("feed", "1")
        assert pet(game[1])["affinity"] > before_affinity


def test_guard_trades_partner_health_for_cargo_against_the_same_real_enemy(game, play):
    prepare(play, skill=True)
    play("convoy", "出发 青山矿车")
    opening = saved(game[1])
    play("convoy", "行进 2 护卫")
    guard = saved(game[1])
    play("convoy", "撤回")
    play("convoy", "出发 青山矿车", now=NOW + 86400)
    play("convoy", "行进 2 开路", now=NOW + 86400)
    lead = saved(game[1])
    assert lead["history"][0]["rounds"] <= guard["history"][0]["rounds"]
    assert guard["cargo"] > lead["cargo"]
    assert guard["fighter"]["hp"] <= lead["fighter"]["hp"]
    assert opening["fighter"]["stats"]["attack"] == guard["fighter"]["stats"]["attack"] == lead["fighter"]["stats"]["attack"]


def test_actual_defeat_retains_receipt_but_does_not_grant_growth_or_materials(game, play):
    prepare(play)
    definition = game[0].content.enemies["wood_guard"]
    game[0].content.enemies["wood_guard"] = definition.model_copy(update={
        "stats": definition.stats.model_copy(update={"attack": 1000, "hp": 10000})})
    play("convoy", "出发 青山矿车")
    before = snapshot(game[1])
    reply = play("convoy", "行进 2 开路", op="defeat")
    assert "败退" in reply.title and saved(game[1])["status"] == "failed"
    assert saved(game[1])["history"][0]["won"] is False
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'convoy_done_%' OR quest_id='bond_exp_1'")
    assert snapshot(game[1])["inventory"] == before["inventory"]
    assert play("convoy", "行进 2 开路", op="defeat") == reply


def test_cargo_loss_and_draw_finish_without_fake_rewards(game, play):
    prepare(play)
    play("convoy", "出发 青山矿车")
    run = saved(game[1])
    run["cargo"] = 1
    with closing(game[1].connect()) as conn:
        conn.execute("UPDATE duel_actions SET snapshot=? WHERE json_extract(snapshot,'$.kind')='convoy'",
                     (json.dumps(run, ensure_ascii=False),))
    reply = play("convoy", "行进 1 绕行")
    assert "货物损毁" in reply.text()
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_1'")
    play("convoy", "出发 青山矿车", now=NOW + 86400)
    run = saved(game[1])
    run["fighter"]["stats"].update(hp=10000, defense=10000, attack=1)
    run["fighter"]["hp"] = 10000
    run["enemies"]["wood_guard"]["stats"].update(hp=10000, defense=10000, attack=1)
    run["enemies"]["wood_guard"]["hp"] = 10000
    with closing(game[1].connect()) as conn:
        conn.execute("UPDATE duel_actions SET snapshot=? WHERE action_id=(SELECT MAX(action_id) FROM duel_actions)",
                     (json.dumps(run, ensure_ascii=False),))
    reply = play("convoy", "行进 2 护卫", now=NOW + 86400)
    assert "败退" in reply.title and saved(game[1])["history"][0]["rounds"] == 40
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='bond_exp_1'")


def test_supply_guard_serializes_distinct_messages_and_old_finish_cannot_touch_new_run(game, play):
    prepare(play)
    play("convoy", "出发 青山矿车")
    reply = play("convoy", "行进 1 绕行")
    argument = next(command for command in reply.commands if "补给" in command).removeprefix("灵宠护航 ")
    food = items(game[1])["spirit_food"]

    def supply(op):
        try:
            return play("convoy", argument, op=op)
        except GameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(supply, ("supply-a", "supply-b")))
    assert sum(not isinstance(reply, GameError) for reply in replies) == 1
    assert items(game[1])["spirit_food"] == food - 1
    play("convoy", "行进 1 绕行")
    final = play("convoy", "行进 1 绕行", op="last-day-final")
    play("convoy", "出发 青山矿车", now=NOW + 86400)
    before = snapshot(game[1])
    with closing(game[1].connect()) as conn:
        conn.execute("DELETE FROM operations WHERE operation_id='last-day-final'")
    assert play("convoy", "行进 1 绕行", op="last-day-final", now=NOW + 86400) == final
    assert snapshot(game[1]) == before


def test_missing_food_full_supply_and_unavailable_rewards_are_atomic(game, play):
    prepare(play, skill=True)
    food = items(game[1])["spirit_food"]
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵粮不足"):
        play("convoy", "出发 青山矿车")
    assert snapshot(game[1]) == before
    sql(game[1], "UPDATE inventory SET quantity=? WHERE item_id='spirit_food'", (food,))
    play("convoy", "出发 青山矿车")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已满"):
        play("convoy", "补给")
    assert snapshot(game[1]) == before
    play("convoy", "行进 2 开路")
    play("convoy", "行进 1 绕行")
    definition = game[0].content.items.pop("forge_ore")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="材料定义暂不可用"):
        play("convoy", "行进 1 绕行", op="missing-reward")
    assert snapshot(game[1]) == before
    game[0].content.items["forge_ore"] = definition
    assert "抵达" in play("convoy", "行进 1 绕行", op="missing-reward").title


def test_new_route_static_runtime_fields_and_missing_references_fail_closed(game):
    content = game[0].content
    for scope in ("route", "stop", "road"):
        data = content.convoy_routes["forge"].model_dump()
        node = data if scope == "route" else data["stops"][0] if scope == "stop" else data["stops"][0]["roads"][0]
        node["updated_at"] = NOW
        with pytest.raises(ValidationError, match="Extra inputs"):
            ConvoyRoute.model_validate(data)
    for field, unknown in (("items", {"ghost_item": 1}), ("enemies", ["ghost_enemy"])):
        data = content.convoy_routes["forge"].model_dump()
        data["stops"][0]["roads"][1][field] = unknown
        routes = dict(content.convoy_routes)
        routes["forge"] = ConvoyRoute.model_validate(data)
        with pytest.raises(ValueError, match="unknown convoy"):
            replace(content, convoy_routes=routes).validate()


@pytest.mark.parametrize("route", ROUTES)
def test_full_risky_routes_are_playable_with_two_real_supplies(game, play, route):
    prepare(play, skill=True)
    play("convoy", "出发 " + route)
    for index in range(3):
        reply = play("convoy", "行进 2 护卫")
        if index < 2:
            assert "第" + str(index + 2) + "/3站" in reply.text(), reply.text()
            play("convoy", "补给")
    assert "抵达" in reply.title, reply.text()
    assert len([entry for entry in saved(game[1])["history"] if entry["action"] == "supply"]) == 2
    assert saved(game[1])["fighter"]["hp"] > 0
    if route == "灵脉药车":
        assert saved(game[1])["items"] == {"bloodline_essence": 1, "spirit_food": 1, "forge_ore": 1}


def test_reward_budget_rejects_cheap_daily_bloodline_inflation(game):
    content = game[0].content
    data = content.convoy_routes["blood"].model_dump()
    for stop in data["stops"]:
        stop["roads"][1]["items"] = {"bloodline_essence": 1}
    routes = dict(content.convoy_routes)
    routes["blood"] = ConvoyRoute.model_validate(data)
    with pytest.raises(ValueError, match="360-stone budget"):
        replace(content, convoy_routes=routes).validate()


def test_delivered_bloodline_materials_are_consumed_by_real_evolution(game, play):
    prepare(play, skill=True)
    for day in range(3):
        now = NOW + day * 86400
        if day:
            play("sign", now=now)
        play("convoy", "出发 灵脉药车", now=now)
        play("convoy", "行进 2 开路", now=now)
        play("convoy", "行进 1 绕行", now=now)
        play("convoy", "行进 1 绕行", now=now)
        play("train", now=now)
    assert items(game[1])["bloodline_essence"] == 3
    play("use", "灵粮 5", now=NOW + 2 * 86400)
    reply = play("evolve", now=NOW + 2 * 86400)
    assert pet(game[1])["bloodline"] == 1, reply.text()
    assert items(game[1])["bloodline_essence"] == 0


@pytest.mark.parametrize("mode,blue,keyboard", (("native", True, False), ("native", False, True),
                                              ("text", True, True), ("template", True, True)))
def test_qq_degraded_delivery_keeps_readable_commands_and_short_labels(game, play, mode, blue, keyboard):
    prepare(play)
    reply = play("convoy", "出发 青山矿车")
    assert all(len(label) <= 10 and "局" not in label for label, _ in _action_items(reply))
    config = Config(spirit_pet_qq_mode=mode, spirit_pet_qq_blue_links=blue,
                    spirit_pet_qq_keyboard=keyboard, spirit_pet_command_prefix="!", spirit_pet_qq_template_id="fixture")
    body, payload = _qq_segments(reply, config)
    assert body
    if mode == "native":
        content = payload["markdown"][0].data["markdown"].content
        assert "!灵宠" in content or "mqqapi://" in content
        if not blue:
            assert "mqqapi://" not in content
        if not keyboard:
            assert not payload["keyboard"]
    else:
        assert "!灵宠护航" in body


def test_players_and_daily_runs_remain_independent(game, play):
    prepare(play)
    play("adopt", "白泽", user="u10")
    play("sign", user="u10")
    play("convoy", "出发 青山矿车", user="u1")
    play("convoy", "出发 丰谷粮车", user="u10")
    assert "青山矿车" in play("convoy", user="u1").text()
    assert "丰谷粮车" in play("convoy", user="u10").text()
    complete(play)
    assert "第1/3站" in play("convoy", user="u10").text()
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u10' AND quest_id LIKE 'convoy_done_%'")


def test_arrival_bond_is_consumed_by_the_existing_combat_loadout(game, play):
    prepare(play)
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','bond_exp_1',49,0)")

    def stats():
        with closing(game[1].connect()) as conn:
            ctx = Context(Repository(conn), game[0].content, Config(), game[0].rng, "u1", NOW, "read-loadout")
            return combatant(ctx, "u1", recover_energy=False, pet_id=1).stats

    before = stats()
    play("convoy", "出发 青山矿车")
    complete(play)
    after = stats()
    assert after.hp == before.hp + 30 and after.attack == before.attack + 5
