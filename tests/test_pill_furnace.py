import asyncio
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import achievements, counters, pill_furnace
from nonebot_plugin_spirit_pet.gameplay.help import help_link
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .conftest import FixedRandom
from .support import items, pet, player, sql
from .test_alchemy import ready
from .test_commands import onebot_event

NOW = 1_800_000_000
DAY = 86400


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid")
            for table in ("players", "pets", "inventory", "quest_progress", "duel_actions",
                          "battle_records", "team_members", "learned_skills", "active_pet_slots")}


def last_run(store):
    return json.loads(sql(store, "SELECT snapshot FROM duel_actions WHERE "
                          "json_extract(snapshot,'$.kind')='pill_furnace' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


def move(play, name, **kwargs):
    page = play("pill_furnace", now=kwargs.get("now", NOW))
    command = next(link.command for link in page.inline_commands if link.label == name)
    action, arg = handlers._parse(command)
    return play(action, arg, **kwargs)


def finish(play, names=("催灵", "调和", "催灵"), **kwargs):
    for name in names:
        result = move(play, name, **kwargs)
    return result


def test_public_views_and_denials_do_not_create_a_player(game, play):
    before = snapshot(game[1])
    for arg in ("", "预览 回元丹", "预览 蕴灵丹", "预览 同心丹", "预览 破境丹", "成品"):
        page = play("pill_furnace", arg)
        assert handlers._parse(page.commands[0]) is not None
        assert not any(link.label == "开炉" for link in page.inline_commands)
    for arg in ("开炉 回元丹", "催灵", "弃炉"):
        with pytest.raises(GameError):
            play("pill_furnace", arg)
    assert snapshot(game[1]) == before
    assert "尚未结契" in play("pill_furnace").text()


@pytest.mark.parametrize("recipe_id", ["energy_draught", "spirit_elixir", "bond_pill", "breakthrough_elixir"])
def test_every_recipe_is_reachable_from_public_supplies_and_pays_its_real_cost(game, play, recipe_id):
    play("adopt", "青鸾", now=NOW - 2 * DAY)
    for day in range(3):
        play("sign", now=NOW - (2 - day) * DAY)
    recipe = game[0].content.alchemy[recipe_id]
    preview = play("pill_furnace", f"预览 {recipe.name}")
    for item_id, need in recipe.materials.items():
        name = game[0].content.items[item_id].name
        assert any(link.command == f"灵宠商店 {name}" for link in preview.inline_commands)
        play("buy", f"{name} {need}")
    before_items, before_stones, before_pet = items(game[1]), player(game[1])["stones"], pet(game[1])
    preview = play("pill_furnace", f"预览 {recipe.name}")
    start_link = next(link.command for link in preview.inline_commands if link.label == "开炉")
    action, arg = handlers._parse(start_link)
    play(action, arg)
    assert player(game[1])["stones"] == before_stones - recipe.stones
    for item_id, need in recipe.materials.items():
        assert items(game[1])[item_id] == before_items[item_id] - need
    result = finish(play)
    assert items(game[1])[recipe.item_id] == 2 * recipe.yield_
    assert pet(game[1]) == before_pet
    assert not sql(game[1], "SELECT * FROM battle_records")
    assert "本炉计一次成功炼丹" in result.text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_alchemy_brews'") == [{"progress": 1}]


@pytest.mark.parametrize("names,portions,steps", [
    (("温养", "温养", "温养"), 1, 3),
    (("催灵", "调和", "催灵"), 2, 3),
    (("催灵", "催灵"), 0, 2),
    (("调和", "调和", "调和"), 0, 3),
])
def test_decisions_change_real_yield_and_failure_does_not_count_as_a_brew(game, play, names, portions, steps):
    ready(game, play)
    before = items(game[1])
    play("pill_furnace", "开炉 回元丹")
    result = finish(play, names)
    assert last_run(game[1])["status"] == "finished"
    assert last_run(game[1])["step"] == steps
    assert items(game[1]).get("energy_pill", 0) == before.get("energy_pill", 0) + portions
    assert bool(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='stat_alchemy_brews'")) == bool(portions)
    assert ("本炉毁丹" in result.text()) == (portions == 0)
    with pytest.raises(GameError, match="今日已开炉"):
        play("pill_furnace", "开炉 回元丹")


def test_successful_furnace_uses_existing_achievement_and_daily_bounty_metric(game, play):
    ready(game, play)
    play("pill_furnace", "开炉 回元丹")
    finish(play)
    ctx = Context(
        Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng,
        "u1", NOW, "furnace-counter-check",
    )
    assert counters.value(ctx, "alchemy_brews") == 1
    assert counters.today_value(ctx, "alchemy_brews") == 1
    entry = next(row for row in game[0].content.achievements.values() if row.id == "alchemy_first")
    page = list(game[0].content.achievements).index(entry.id) // achievements.ACHIEVEMENT_PAGE_SIZE + 1
    assert "开炉初成 · 可领奖" in play("achievements", str(page)).text()


@pytest.mark.parametrize("recipe,item,field,delta", [
    ("回元丹", "energy_pill", "energy", 50),
    ("蕴灵丹", "exp_pill", "exp", 100),
    ("同心丹", "affinity_pill", "affinity", 20),
])
def test_result_links_consume_actual_pills_and_grow_the_current_pet(game, play, recipe, item, field, delta):
    ready(game, play)
    sql(game[1], "UPDATE pets SET energy=0,energy_updated=?,affinity=0", (NOW,))
    play("pill_furnace", f"开炉 {recipe}")
    result = finish(play)
    before = pet(game[1])
    action, arg = handlers._parse(result.inline_commands[0].command)
    play(action, arg)
    assert pet(game[1])[field] == before[field] + delta
    assert items(game[1])[item] == 1


def test_breakthrough_pill_link_reaches_real_major_breakthrough(game, play):
    ready(game, play)
    sql(game[1], "UPDATE pets SET layer=10,exp=10000")
    play("pill_furnace", "开炉 破境丹")
    result = finish(play)
    action, arg = handlers._parse(result.inline_commands[0].command)
    assert action == "breakthrough"
    play(action, arg)
    assert pet(game[1])["realm"] == 1 and pet(game[1])["layer"] == 1
    assert items(game[1])["breakthrough_pill"] == 1


def test_help_alchemy_and_objectives_reach_the_furnace_and_show_live_progress(game, play):
    ready(game, play)
    guide = play("help", "血脉与道具")
    assert any(help_link(line) == ("灵宠丹炉", "灵宠丹炉") for line in guide.lines)
    for action in ("alchemy", "objectives"):
        assert any(link.command == "灵宠丹炉" for link in play(action).inline_commands)
    play("pill_furnace", "开炉 回元丹")
    move(play, "催灵")
    assert "丹炉：回元丹第2/3段 · 药力3 · 稳定3" in play("objectives").text()
    before = snapshot(game[1])
    page = play("pill_furnace")
    assert "催灵 → 药力6、稳定0，本段会毁丹" in page.text()
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("arg,match", [
    ("预览 不存在", "未找到"), ("开炉 不存在", "未找到"),
    ("开炉 回元丹 2", "格式"), ("开炉", "格式"), ("预览", "格式"),
    ("催灵", "没有正在"), ("弃炉", "没有正在"),
    ("温养 炉 1 步 0", "整数"), ("温养 炉 1 步 4", "整数"),
    ("温养 炉 " + "9" * 5000 + " 步 1", "整数"),
    ("温养 炉 1 步 " + "9" * 5000, "整数"), ("温养 炉 １ 步 1", "整数"),
    ("温养 炉 1", "格式"), ("成品 1", "格式"), ("换方 回元丹", "格式"),
])
def test_invalid_inputs_do_not_change_business_state(game, play, arg, match):
    ready(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=match):
        play("pill_furnace", arg)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("resource,match", [("stones", "灵石不足"), ("seed_blood_herb", "灵血草种缺")])
def test_resource_rejection_hides_start_and_does_not_spend_daily_slot(game, play, resource, match):
    ready(game, play)
    if resource == "stones":
        sql(game[1], "UPDATE players SET stones=0")
    else:
        sql(game[1], "DELETE FROM inventory WHERE item_id=?", (resource,))
    before = snapshot(game[1])
    page = play("pill_furnace", "预览 回元丹")
    assert match in page.text() and not any(link.label == "开炉" for link in page.inline_commands)
    with pytest.raises(GameError, match=match):
        play("pill_furnace", "开炉 回元丹")
    assert snapshot(game[1]) == before


def test_same_day_cap_abandonment_and_independent_instant_alchemy(game, play):
    ready(game, play, stock=6)
    play("pill_furnace", "开炉 回元丹")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已有一炉"):
        play("pill_furnace", "开炉 同心丹")
    assert snapshot(game[1]) == before
    result = move(play, "弃炉")
    assert "不退还" in result.text()
    assert items(game[1]) == {row["item_id"]: row["quantity"] for row in before["inventory"]}
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='stat_alchemy_brews'")
    assert "今日已开炉" in play("pill_furnace").text()
    play("alchemy", "回元丹")
    assert items(game[1])["energy_pill"] == 1
    play("pill_furnace", "开炉 回元丹", now=NOW + DAY)
    assert last_run(game[1])["status"] == "active"


def test_generated_old_step_and_old_run_buttons_cannot_advance_current_furnace(game, play):
    ready(game, play)
    page = play("pill_furnace", "开炉 回元丹")
    old = next(link.command for link in page.inline_commands if link.label == "温养")
    move(play, "温养")
    before = snapshot(game[1])
    action, arg = handlers._parse(old)
    with pytest.raises(GameError, match="步骤已过期"):
        play(action, arg)
    assert snapshot(game[1]) == before
    finish(play, ("温养", "温养"))
    play("pill_furnace", "开炉 回元丹", now=NOW + DAY)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="步骤已过期"):
        play(action, arg, now=NOW + DAY)
    assert snapshot(game[1]) == before


def test_cross_day_restart_and_expired_receipts_never_mutate_a_later_furnace(game, play):
    ready(game, play)
    start = play("pill_furnace", "开炉 回元丹", op="furnace-start")
    first = play("pill_furnace", "催灵", op="furnace-first")
    restarted = Game(game[1], Config(), FixedRandom())
    assert "第2/3段" in restarted.execute("u1", "pill_furnace", "", "view-restart", NOW + DAY).text()
    play("pill_furnace", "调和", now=NOW + DAY)
    done = play("pill_furnace", "催灵", now=NOW + DAY, op="furnace-finish")
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='pill_furnace_day'")[0]["progress"] == 20270115
    play("pill_furnace", "开炉 回元丹", now=NOW + 10 * DAY)
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='furnace-start'")
    before = snapshot(game[1])
    for op, arg, saved in (("furnace-start", "开炉 回元丹", start), ("furnace-first", "催灵", first),
                           ("furnace-finish", "催灵", done)):
        assert restarted.execute("u1", "pill_furnace", arg, op, NOW + 10 * DAY) == saved
        assert snapshot(game[1]) == before
        with pytest.raises(GameError, match="different user"):
            restarted.execute("u2", "pill_furnace", arg, op, NOW + 10 * DAY)


def test_clock_rollback_blocks_actions_and_new_start_without_spending_resources(game, play):
    ready(game, play)
    play("pill_furnace", "开炉 回元丹")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("pill_furnace", "温养", now=NOW - 1)
    assert snapshot(game[1]) == before
    play("pill_furnace", "弃炉")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("pill_furnace", "开炉 回元丹", now=NOW - DAY)
    sql(game[1], "UPDATE quest_progress SET progress=20990101 WHERE quest_id='pill_furnace_day'")
    with pytest.raises(GameError, match="日期早于"):
        play("pill_furnace", "开炉 回元丹", now=NOW + DAY)
    assert items(game[1]) == {row["item_id"]: row["quantity"] for row in before["inventory"]}


def test_original_recipe_and_rules_survive_content_changes_and_missing_products(game, play, monkeypatch):
    ready(game, play)
    play("pill_furnace", "开炉 回元丹")
    first = game[0].content.alchemy["energy_draught"]
    game[0].content = replace(game[0].content, alchemy={first.id: first.model_copy(update={"item_id": "exp_pill", "yield_": 10})})
    monkeypatch.setitem(pill_furnace.RULE, "double", 99)
    play("pill_furnace", "催灵")
    play("pill_furnace", "调和")
    content = game[0].content
    for missing in (True, False):
        altered = dict(content.items)
        if missing:
            altered.pop("energy_pill")
        else:
            altered["energy_pill"] = altered["energy_pill"].model_copy(update={"kind": "material"})
        game[0].content = replace(content, items=altered)
        before = snapshot(game[1])
        with pytest.raises(GameError, match="原丹方产物暂不可用"):
            play("pill_furnace", "催灵", op="retry-product")
        assert snapshot(game[1]) == before
        assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='retry-product'")
    game[0].content = content
    play("pill_furnace", "催灵", op="retry-product")
    assert items(game[1])["energy_pill"] == 2
    assert items(game[1]).get("exp_pill", 0) == 0


@pytest.mark.parametrize("phase,trigger", [
    ("start", "BEFORE UPDATE ON inventory WHEN NEW.item_id='seed_blood_herb'"),
    ("start", "BEFORE INSERT ON quest_progress WHEN NEW.quest_id='pill_furnace_day'"),
    ("start", "BEFORE UPDATE ON players"),
    ("start", "BEFORE INSERT ON duel_actions"),
    ("middle", "BEFORE INSERT ON duel_actions"),
    ("finish", "BEFORE INSERT ON inventory WHEN NEW.item_id='energy_pill'"),
    ("finish", "BEFORE INSERT ON quest_progress WHEN NEW.quest_id='stat_alchemy_brews'"),
    ("finish", "BEFORE INSERT ON duel_actions"),
    ("finish", "BEFORE INSERT ON operations"),
    ("abandon", "BEFORE INSERT ON duel_actions"),
])
def test_every_write_failure_rolls_back_and_same_message_can_retry(game, play, phase, trigger):
    ready(game, play)
    if phase != "start":
        play("pill_furnace", "开炉 回元丹")
    if phase == "finish":
        play("pill_furnace", "催灵")
        play("pill_furnace", "调和")
    arg = {"start": "开炉 回元丹", "middle": "温养", "finish": "催灵", "abandon": "弃炉"}[phase]
    before = snapshot(game[1])
    sql(game[1], f"CREATE TRIGGER fail_furnace {trigger} BEGIN SELECT RAISE(ABORT,'furnace fault'); END")
    with pytest.raises(sqlite3.IntegrityError, match="furnace fault"):
        play("pill_furnace", arg, op="furnace-retry")
    assert snapshot(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='furnace-retry'")
    sql(game[1], "DROP TRIGGER fail_furnace")
    play("pill_furnace", arg, op="furnace-retry")
    assert snapshot(game[1]) != before


@pytest.mark.parametrize("final", [False, True])
def test_concurrent_distinct_messages_pay_or_finish_only_once(game, play, final):
    ready(game, play)
    if final:
        play("pill_furnace", "开炉 回元丹")
        play("pill_furnace", "催灵")
        play("pill_furnace", "调和")
    before = items(game[1])

    def run(index):
        service = Game(game[1], Config(), FixedRandom())
        try:
            return service.execute("u1", "pill_furnace", "催灵" if final else "开炉 回元丹",
                                   f"race-furnace-{index}", NOW).title
        except GameError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(text.startswith("灵宠丹炉") for text in results) == 1
    if final:
        assert items(game[1])["energy_pill"] == 2
    else:
        assert items(game[1])["spirit_food"] == before["spirit_food"] - 2
        assert items(game[1])["seed_blood_herb"] == before["seed_blood_herb"] - 1


def test_concurrent_repeated_message_replays_the_exact_result(game, play):
    ready(game, play)

    def run(_):
        return Game(game[1], Config(), FixedRandom()).execute(
            "u1", "pill_furnace", "开炉 回元丹", "same-furnace-message", NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    assert len(sql(game[1], "SELECT * FROM duel_actions")) == 1
    assert items(game[1])["spirit_food"] == 2


def test_finished_review_is_read_only_and_skips_active_furnace(game, play):
    ready(game, play)
    play("pill_furnace", "开炉 回元丹")
    saved = finish(play)
    play("pill_furnace", "开炉 同心丹", now=NOW + DAY)
    before = snapshot(game[1])
    review = play("pill_furnace", "成品", now=NOW + DAY)
    assert review.lines == saved.lines
    assert not any(" 炉 " in link.command for link in review.inline_commands)
    assert snapshot(game[1]) == before


def test_different_players_own_independent_furnaces_and_no_pet_is_required(game, play):
    ready(game, play)
    play("adopt", "白泽", user="u2")
    play("sign", user="u2")
    play("buy", "灵血草种 1", user="u2")
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    play("pill_furnace", "开炉 回元丹")
    play("pill_furnace", "开炉 同心丹", user="u2")
    play("pill_furnace", "温养", user="u2")
    assert "第1/3段" in play("pill_furnace").text()
    assert "第2/3段" in play("pill_furnace", user="u2").text()
    play("pill_furnace", "弃炉")
    assert "第2/3段" in play("pill_furnace", user="u2").text()


def test_furnace_actions_never_appear_in_duel_state_or_review(game, play):
    ready(game, play)
    play("duel", "松风道人", op="duel-before-furnace")
    with game[1].connect() as conn:
        old_duel = Repository(conn).latest_duel_action("u1")
    play("pill_furnace", "开炉 回元丹", op="private-furnace")
    action_id = sql(game[1], "SELECT action_id FROM duel_actions ORDER BY action_id DESC LIMIT 1")[0]["action_id"]
    with game[1].connect() as conn:
        repo = Repository(conn)
        assert repo.latest_duel_action("u1") == old_duel
        assert repo.duel_operation("private-furnace", "u1") is None
        assert repo.stage_tactic_operation("private-furnace", "u1") is None
        assert repo.cooking_operation("private-furnace", "u1") is None
    assert "丹炉" not in play("duel", "回顾").text()
    with pytest.raises(GameError, match="未找到本人的"):
        play("duel", f"回顾 查看 {action_id}")
    play("duel", "抢攻")
    assert "第1/3段" in play("pill_furnace").text()


@pytest.mark.parametrize("prefix", ["/", "!", ""])
def test_native_template_text_and_onebot_keep_all_choices_reachable(game, play, prefix):
    ready(game, play)
    pages = [play("pill_furnace"), play("pill_furnace", "预览 回元丹"),
             play("pill_furnace", "开炉 回元丹")]
    pages.append(finish(play))
    for reply in pages:
        assert all(0 <= link.line < len(reply.lines) for link in reply.inline_commands)
        config = Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix)
        _, messages = _qq_segments(reply, config)
        markdown = messages["markdown"][0].data["markdown"]
        body = markdown.content if hasattr(markdown, "content") else markdown["content"]
        links = {parse_qs(urlparse(url).query)["command"][0]
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        assert links == {prefix + link.command for link in reply.inline_commands}
        buttons = {button.action.data for segment in messages["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 4 and not buttons & links
        for mode in ("text", "template"):
            _, segments = _qq_segments(reply, Config(spirit_pet_qq_mode=mode, spirit_pet_command_prefix=prefix,
                                                     spirit_pet_qq_template_id="furnace-template"))
            for link in reply.inline_commands:
                assert prefix + link.command in str(segments)
                assert handlers._parse(link.command) is not None
                assert link.command.rstrip() in reply.text()


def test_onebot_full_player_flow_uses_real_parser_transport_and_inventory(game, monkeypatch):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config())
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        for index, command in enumerate(("灵宠丹炉", "灵宠领养 青鸾", "灵宠签到", "灵宠购买 灵血草种 1",
                                         "灵宠丹炉 预览 回元丹", "灵宠丹炉 开炉 回元丹",
                                         "灵宠丹炉 催灵", "灵宠丹炉 调和", "灵宠丹炉 催灵",
                                         "灵宠修炼", "灵宠使用 回元丹 1", "灵宠丹炉 成品")):
            event = onebot_event(command, 900 + index)
            await handlers.handle_command(bot, event, event.get_message())

    asyncio.run(run())
    messages = [str(call.args[1]) for call in bot.send.call_args_list]
    assert "尚未结契" in messages[0]
    assert "回元丹×2已入乾坤袋" in messages[8]
    assert "成品回顾" in messages[-1]
    assert items(game[1], "12345")["energy_pill"] == 1
