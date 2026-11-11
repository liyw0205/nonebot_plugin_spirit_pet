import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.help import help_link
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .conftest import FixedRandom
from .support import items, pet, player, sql
from .test_cuisine import add_items, heat_row, seed_mastery, set_heat

NOW = 1_800_000_000
DAY = 86400


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user, op=f"adopt-cooking-{user}")
    add_items(game, {"spirit_food": 20, "forge_ore": 10, "bloodline_essence": 10,
                     "seed_aura_ear": 5}, user)


def snapshot(store):
    return {
        table: sql(store, f"SELECT * FROM {table} ORDER BY rowid")
        for table in ("players", "pets", "inventory", "quest_progress", "duel_actions",
                      "battle_records", "team_members")
    }


def last_pot(store):
    rows = sql(store, "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cooking' ORDER BY action_id DESC LIMIT 1")
    return json.loads(rows[0]["snapshot"])


def finish(play, moves=("旺火", "旺火", "离火"), prefix="fire", now=NOW):
    for index, move in enumerate(moves):
        reply = play("cooking", move, op=f"{prefix}-{index}", now=now)
    return reply


def test_unregistered_views_do_not_create_account(game, play):
    before = snapshot(game[1])
    assert "尚未结契" in play("cooking").text()
    assert "还没有" in play("cooking", "成品").text()
    with pytest.raises(GameError):
        play("cooking", "开锅 灵米粥")
    assert snapshot(game[1]) == before


def test_kitchen_help_and_objectives_reach_real_cooking(game, play):
    account(game, play)
    assert _parse("灵宠掌勺 开锅 灵米粥") == ("cooking", "开锅 灵米粥")
    for action, arg in (("cuisine", ""), ("objectives", "")):
        reply = play(action, arg)
        assert any(link.command == "灵宠掌勺" for link in reply.inline_commands)
    guide = play("help", "成长")
    assert any(help_link(line) == ("灵宠掌勺", "灵宠掌勺") for line in guide.lines)
    assert "灵宠掌勺 收灶" in guide.text()
    before = snapshot(game[1])
    reply = play("cooking")
    assert sum(link.label == "开锅" for link in reply.inline_commands) == 1
    assert "最高 0/6 分" in reply.text()
    assert snapshot(game[1]) == before


def test_start_charges_original_recipe_and_shares_heat_with_instant_cooking(game, play):
    account(game, play)
    before_stones, before_food = player(game[1])["stones"], items(game[1])["spirit_food"]
    play("cooking", "开锅 灵米粥", op="pot-start")
    assert player(game[1])["stones"] == before_stones - 10
    assert items(game[1])["spirit_food"] == before_food - 2
    assert heat_row(game) == 1
    assert items(game[1]).get("meal_rice", 0) == 0
    assert last_pot(game[1])["turn"] == 1
    assert "第 1/3 段" in play("cooking").text()
    assert "掌勺：灵米粥第 1/3 段" in play("objectives").text()
    play("cuisine_cook", "灵米粥", op="instant-with-pot")
    assert heat_row(game) == 2
    assert last_pot(game[1])["status"] == "active"


@pytest.mark.parametrize("moves,grade,portions", [
    (("旺火", "旺火", "离火"), "佳膳", 2),
    (("旺火", "文火", "文火"), "成膳", 1),
    (("离火", "离火", "离火"), "焦糊", 0),
])
def test_grades_change_actual_yield_and_only_success_grows_mastery(game, play, moves, grade, portions):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    reply = finish(play, moves)
    assert reply.title == "掌勺成品" and grade in reply.text()
    assert items(game[1]).get("meal_rice", 0) == portions
    mastery = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cuisine_dish_rice_porridge'")
    assert mastery == ([{"progress": portions}] if portions else [])
    assert ("厨艺提升：1 级 → 2 级" in reply.text()) == bool(portions)
    assert last_pot(game[1])["status"] == "finished"
    assert heat_row(game) == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cooking_total'") == [{"progress": 1}]
    assert bool(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='cooking_perfect'")) == (portions == 2)
    assert not sql(game[1], "SELECT * FROM battle_records")
    before = snapshot(game[1])
    review = play("cooking", "成品")
    assert review.lines == reply.lines and not review.inline_commands
    play("cooking")
    assert snapshot(game[1]) == before


def test_success_output_is_usable_and_grows_the_pet(game, play):
    account(game, play)
    sql(game[1], "UPDATE pets SET energy=10,energy_updated=?", (NOW,))
    before = pet(game[1])
    play("cooking", "开锅 灵米粥")
    reply = finish(play)
    link = next(link for link in reply.inline_commands if link.label == "享用灵膳")
    action, arg = _parse(link.command)
    play(action, arg, op="enjoy-meal")
    after = pet(game[1])
    assert after["energy"] == before["energy"] + 45
    assert after["exp"] == before["exp"] + 20
    assert after["affinity"] == before["affinity"] + 10
    assert items(game[1])["meal_rice"] == 1


@pytest.mark.parametrize("dish_id", ["rice_porridge", "herb_soup", "lotus_pastry", "grain_cake", "moon_cake"])
def test_every_single_recipe_runs_its_own_cost_and_frozen_output(game, play, dish_id):
    account(game, play)
    seed_mastery(game, *game[0].content.cuisine.keys())
    dish = game[0].content.cuisine[dish_id]
    before_items, before_stones = items(game[1]), player(game[1])["stones"]
    play("cooking", f"开锅 {dish.name}")
    reply = finish(play)
    assert "佳膳" in reply.text()
    assert items(game[1])[dish.item] == 2
    assert heat_row(game) == dish.heat
    assert player(game[1])["stones"] == before_stones - dish.stones
    for item_id, count in dish.ingredients.items():
        assert items(game[1])[item_id] == before_items[item_id] - count


@pytest.mark.parametrize("arg,match", [
    ("开锅 百草羹", "厨艺不足"), ("开锅 百兽羹", "宴席"),
    ("开锅 乱菜", "未找到"), ("开锅 灵米粥 2", "未找到"),
    ("旺火", "没有正在"), ("收灶", "没有正在"),
    ("开锅", "格式"), ("开锅灵米粥", "格式"), ("成品 2", "格式"),
])
def test_invalid_inputs_are_zero_write(game, play, arg, match):
    account(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=match):
        play("cooking", arg)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("resource,match", [("stones", "灵石不足"), ("food", "灵粮不足"), ("heat", "灶火不足")])
def test_insufficient_resources_leave_no_paid_pot(game, play, resource, match):
    account(game, play)
    if resource == "stones":
        sql(game[1], "UPDATE players SET stones=0")
    elif resource == "food":
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    else:
        set_heat(game, 6)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=match):
        play("cooking", "开锅 灵米粥")
    assert snapshot(game[1]) == before


def test_forecast_is_exact_and_active_views_do_not_change_state(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    before = snapshot(game[1])
    preview = play("cooking")
    assert "旺火（+20）：炉温 → 45，本段 +2 分。" in preview.text()
    assert snapshot(game[1]) == before
    reply = play("cooking", "旺火")
    assert "炉温 45，火候 +2" in reply.text()
    assert last_pot(game[1])["temperature"] == 45
    assert "第 2/3 段" in reply.text()


def test_abandon_keeps_cost_and_unblocks_new_pot_without_growth(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已有一锅"):
        play("cooking", "开锅 灵米粥")
    assert snapshot(game[1]) == before
    reply = play("cooking", "收灶", op="abandon")
    assert "不退还" in reply.text()
    after = snapshot(game[1])
    for table in ("players", "pets", "inventory", "quest_progress", "battle_records"):
        assert after[table] == before[table]
    assert last_pot(game[1])["status"] == "abandoned"
    assert "已放弃" in play("cooking", "成品").text()
    play("cooking", "开锅 灵米粥", op="replacement-pot")
    assert heat_row(game) == 2


def test_restart_and_expired_replays_never_mutate_a_later_pot(game, play):
    account(game, play)
    start = play("cooking", "开锅 灵米粥", op="old-start")
    first = play("cooking", "旺火", op="old-first")
    restarted = Game(game[1], Config(), FixedRandom())
    assert "第 2/3 段" in restarted.execute("u1", "cooking", "", "restart-view", NOW).text()
    play("cooking", "旺火", op="old-second")
    done = play("cooking", "离火", op="old-last")
    play("cooking", "开锅 灵米粥", op="new-start", now=NOW + 10 * DAY)
    # Advance beyond normal cache retention using a real command, then restart.
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='old-start'")
    before = snapshot(game[1])
    for operation_id, arg, saved in (("old-start", "开锅 灵米粥", start), ("old-first", "旺火", first),
                                     ("old-last", "离火", done)):
        assert restarted.execute("u1", "cooking", arg, operation_id, NOW + 10 * DAY) == saved
        assert snapshot(game[1]) == before
        sql(game[1], "DELETE FROM operations WHERE operation_id=?", (operation_id,))
        with pytest.raises(GameError, match="different user"):
            restarted.execute("u2", "cooking", arg, operation_id, NOW + 10 * DAY)


def test_cross_day_continuation_charges_heat_only_on_start_and_blocks_clock_rollback(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥", op="cross-day-start")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("cooking", "文火", now=NOW - 1)
    assert snapshot(game[1]) == before
    finish(play, now=NOW + DAY)
    assert heat_row(game) == 1
    assert heat_row(game, day=beijing_day(NOW + DAY)) == 0
    before = snapshot(game[1])
    with pytest.raises(GameError, match="时间早于"):
        play("cooking", "开锅 灵米粥", now=NOW)
    assert snapshot(game[1]) == before


def test_start_and_final_receipt_failure_roll_back_every_business_write(game, play, monkeypatch):
    account(game, play)
    original = Repository.record_cooking_action

    def fail(*args, **kwargs):
        raise RuntimeError("receipt failure")

    before = snapshot(game[1])
    monkeypatch.setattr(Repository, "record_cooking_action", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        play("cooking", "开锅 灵米粥", op="retry-start")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(Repository, "record_cooking_action", original)
    play("cooking", "开锅 灵米粥", op="retry-start")
    play("cooking", "旺火")
    play("cooking", "旺火")
    before = snapshot(game[1])
    monkeypatch.setattr(Repository, "record_cooking_action", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        play("cooking", "离火", op="retry-final")
    assert snapshot(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='retry-final'")
    monkeypatch.setattr(Repository, "record_cooking_action", original)
    assert "佳膳" in play("cooking", "离火", op="retry-final").text()
    assert items(game[1])["meal_rice"] == 2


def test_active_recipe_uses_original_targets_and_output_after_content_changes(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    dish = game[0].content.cuisine["rice_porridge"]
    game[0].content = replace(game[0].content, cuisine={
        **game[0].content.cuisine,
        dish.id: dish.model_copy(update={"item": "meal_herb", "level": 7}),
    })
    assert "佳膳" in finish(play).text()
    assert items(game[1])["meal_rice"] == 2
    assert items(game[1]).get("meal_herb", 0) == 0


def test_concurrent_last_action_pays_once(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    play("cooking", "旺火")
    play("cooking", "旺火")

    def run(index):
        service = Game(game[1], Config(), FixedRandom())
        try:
            return service.execute("u1", "cooking", "离火", f"parallel-{index}", NOW).title
        except GameError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results.count("掌勺成品") == 1
    assert sum("没有正在" in text for text in results) == 1
    assert items(game[1])["meal_rice"] == 2
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cooking_total'") == [{"progress": 1}]


def test_best_score_never_falls_and_finished_review_skips_the_current_pot(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    finish(play, prefix="perfect")
    play("cooking", "开锅 灵米粥")
    burned = finish(play, ("离火",) * 3, prefix="burned")
    play("cooking", "开锅 灵米粥")
    before = snapshot(game[1])
    assert play("cooking", "成品").lines == burned.lines
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cooking_best_rice_porridge'") == [{"progress": 6}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cooking_total'") == [{"progress": 2}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cooking_perfect'") == [{"progress": 1}]


def test_missing_frozen_output_refuses_final_without_losing_the_pot(game, play):
    account(game, play)
    play("cooking", "开锅 灵米粥")
    play("cooking", "旺火")
    play("cooking", "旺火")
    original = game[0].content
    game[0].content = replace(original, items={key: value for key, value in original.items.items() if key != "meal_rice"})
    before = snapshot(game[1])
    with pytest.raises(GameError, match="成膳道具暂不可用"):
        play("cooking", "离火", op="missing-output-final")
    assert snapshot(game[1]) == before
    game[0].content = original
    assert "佳膳" in play("cooking", "离火", op="missing-output-final").text()


def test_cooking_interleaved_with_real_duel_does_not_replace_its_snapshot(game, play):
    account(game, play)
    play("duel", "松风道人", op="duel-start-before-pot")
    duel_page = play("duel")
    play("cooking", "开锅 灵米粥")
    play("cooking", "旺火")
    assert play("duel").lines == duel_page.lines
    assert "青鸾 对 松风道人" in play("duel", "回顾").text()
    play("duel", "认输")
    assert "第 2/3 段" in play("cooking").text()


def test_users_have_separate_pots_and_duel_consumers_exclude_cooking(game, play):
    account(game, play)
    account(game, play, "u2")
    play("cooking", "开锅 灵米粥", op="private-pot")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="没有正在"):
        play("cooking", "旺火", user="u2")
    assert snapshot(game[1]) == before
    assert "尚无回合记录" in play("duel", "回顾").text()
    action_id = sql(game[1], "SELECT action_id FROM duel_actions WHERE operation_id='private-pot'")[0]["action_id"]
    with pytest.raises(GameError, match="未找到本人的"):
        play("duel", f"回顾 查看 {action_id}")
    with game[1].connect() as conn:
        repo = Repository(conn)
        assert repo.latest_duel_action("u1") is None
        assert repo.stage_tactic_operation("private-pot", "u1") is None
    play("cooking", "开锅 灵米粥", user="u2", op="second-owner-pot")
    play("cooking", "离火", user="u2")
    assert "第 1/3 段" in play("cooking").text()


def test_native_and_text_messages_keep_all_moves_reachable_without_duplicate_buttons(game, play):
    account(game, play)
    pages = [play("cooking")]
    pages.append(play("cooking", "开锅 灵米粥"))
    pages.append(finish(play))
    for reply in pages:
        _, messages = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        markdown = messages["markdown"][0].data["markdown"]
        body = markdown.content if hasattr(markdown, "content") else markdown["content"]
        linked = {parse_qs(urlparse(url).query)["command"][0]
                  for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        assert linked == {f"/{link.command}" for link in reply.inline_commands}
        buttons = {button.action.data.removeprefix("/")
                   for segment in messages["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 4 and buttons == set(reply.commands)
        assert not {value.removeprefix("/") for value in linked} & buttons
        _, text_messages = _qq_segments(reply, Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"))
        rendered = str(text_messages)
        for link in reply.inline_commands:
            assert "!" + link.command in rendered
