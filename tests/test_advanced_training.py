import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import training
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, sql
from .test_targeted_training import add_pet
from .test_training import NOW, snapshot
from .test_travel_revisit import pick, unlock


def setup(game, play):
    play("adopt", "青鸾")
    target = add_pet(game[1], species_id="qingluan", name="青鸾后备")
    sql(game[1], "UPDATE players SET stones=5000")
    play("buy", "风刃术诀")
    play("learn", f"风刃术 伙伴 {target}")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','forge_ore',3)")
    return target


def saved(game):
    return json.loads(sql(game[1], "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='training' ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


def plans(run):
    outcomes = {True: [], False: []}
    def search(current, path):
        if current["player"]["hp"] <= 0 or current["enemy"]["hp"] <= 0 or len(path) == 5:
            passed = current["player"]["hp"] > 0 and current["enemy"]["hp"] <= 0
            outcomes[passed].append(path)
            return
        for _, action in training._choices(current):
            next_run = json.loads(json.dumps(current))
            player, enemy, _ = training._exchange(next_run, action)
            next_run["history"].append({"action": action})
            next_run["player"], next_run["enemy"] = training._pack(player), training._pack(enemy)
            search(next_run, path + (action,))
    search(run, ())
    return outcomes


@pytest.mark.parametrize("trial", ["穿隙破势", "守中求胜"])
def test_advanced_trials_have_real_winning_and_losing_strategies_and_numbered_growth(game, play, trial):
    target = setup(game, play)
    if trial == "守中求胜":
        play("buy", "青木回春诀")
        play("learn", f"青木回春 伙伴 {target}")
    sql(game[1], "UPDATE learned_skills SET proficiency=19 WHERE pet_id=?", (target,))
    before = snapshot(game[1])
    preview = play("training", f"预览 {trial} 伙伴 {target}")
    assert "锻灵矿1份" in preview.text()
    assert snapshot(game[1]) == before
    command = next(command for command in preview.commands if "开始" in command)
    play("switch", str(target))
    play("switch", "1")
    page = play(*handlers._parse(command), op="advanced-start")
    run = saved(game)
    outcomes = plans(run)
    assert outcomes[True] and outcomes[False], trial
    assert run["pet_id"] == target
    assert items(game[1])["forge_ore"] == 2
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (target,)) == [{"energy": 82}]
    winning = next(path for path in outcomes[True] if "wind_slash" in path)
    for index, action in enumerate(winning):
        page = play("training", "出手 " + action, op=f"advanced-{index}")
    assert "通过演练" in page.text()
    assert sql(game[1], "SELECT level FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (target,)) == [{"level": 2}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?", (f"bond_exp_{target}",)) == [{"progress": 6}]
    assert sql(game[1], "SELECT exp,energy FROM pets WHERE pet_id=1") == [{"exp": 0, "energy": 100}]
    before_replay = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    assert restarted.execute("u1", "training", "出手 " + winning[-1], f"advanced-{len(winning)-1}", NOW + 86400) == page
    assert snapshot(game[1]) == before_replay
    # The upgraded skill is captured by the actual battle loadout, not just the training page.
    play("codex_trials", f"挑战 青鸾 伙伴 {target}", now=NOW + 700)
    battle = json.loads(sql(game[1], "SELECT snapshot FROM battle_records")[0]["snapshot"])
    assert battle["teams"][0]["members"][0]["skills"][0]["level"] == 2
    # Choosing only defence consumes another day's materials without earning skill growth.
    before_loss = sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (target,))
    play("training", f"开始 {trial} 伙伴 {target}", now=NOW + 86400)
    for index in range(5):
        lost = play("training", "出手 护持", now=NOW + 86400, op=f"losing-{index}")
        if lost.title == "连携演练结算":
            break
    assert "未通过演练" in lost.text() and "羁绊经验+1" in lost.text()
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (target,)) == before_loss
    assert items(game[1])["forge_ore"] == 1


def test_actual_revisit_supplies_advanced_training_without_switching_pet(game, play):
    unlock(game, play)
    sql(game[1], "UPDATE players SET stones=5000")
    target = add_pet(game[1], species_id="qingluan")
    play("buy", "风刃术诀")
    play("learn", f"风刃术 伙伴 {target}")
    page = play("adventure_travel", f"重游 灵泉修行 伙伴 {target}")
    for option in ("food", "trade", "escort"):
        page = pick(play, page, option)
    assert items(game[1])["forge_ore"] == 2
    hub = next(link.command for link in page.inline_commands if link.label == "灵术演练")
    assert hub.endswith(f"伙伴 {target}")
    trial_page = play(*handlers._parse(hub))
    preview_link = next(link.command for link in trial_page.inline_commands if "预览 穿隙破势" in link.command)
    preview = play(*handlers._parse(preview_link))
    opening = next(command for command in preview.commands if "开始" in command)
    page = play(*handlers._parse(opening))
    plan = plans(saved(game))[True][0]
    for action in plan:
        page = play("training", "出手 " + action)
    assert "通过演练" in page.text()
    assert items(game[1])["forge_ore"] == 1
    assert any(link.command == f"灵宠整备 {target}" for link in page.inline_commands)


@pytest.mark.parametrize("blocked", ["archived", "trip", "energy", "ore", "foreign"])
def test_numbered_start_revalidates_fixed_target_and_resources(game, play, blocked):
    target = setup(game, play)
    command = next(command for command in play("training", f"预览 穿隙破势 伙伴 {target}").commands if "开始" in command)
    if blocked == "archived":
        play("pet_archive", str(target))
    elif blocked == "trip":
        play("switch", str(target))
        play("expedition_start", "采灵药")
    elif blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (target,))
    elif blocked == "ore":
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='forge_ore'")
    else:
        play("adopt", user="u2")
        foreign = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
        command = command.replace(f"伙伴 {target}", f"伙伴 {foreign}")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play(*handlers._parse(command))
    assert snapshot(game[1]) == before


def test_advanced_period_shared_quota_and_competing_starts(game, play):
    target = setup(game, play)
    command = next(command for command in play("training", f"预览 穿隙破势 伙伴 {target}").commands if "开始" in command)
    with pytest.raises(GameError, match="过期"):
        play(*handlers._parse(command), now=NOW + 86400)
    def attempt(index):
        try:
            return play("training", f"开始 {'穿隙破势' if index == 1 else '观势破阵'} 伙伴 {target}", op=f"advanced-race-{index}")
        except GameError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    play("training", "退出")
    with pytest.raises(GameError, match="名额"):
        play("training", f"开始 观势破阵 伙伴 {target}")
    with pytest.raises(GameError, match="时间早于|日期早于"):
        play("training", f"开始 穿隙破势 伙伴 {target}", now=NOW - 86400)


@pytest.mark.parametrize("phase", ["start", "finish"])
def test_advanced_cost_growth_and_receipt_fail_atomically(game, play, monkeypatch, phase):
    target = setup(game, play)
    argument = f"开始 穿隙破势 伙伴 {target}"
    if phase == "finish":
        play("training", argument)
        plan = plans(saved(game))[True][0]
        for action in plan[:-1]:
            play("training", "出手 " + action)
        argument = "出手 " + plan[-1]
    before = snapshot(game[1])
    original = Repository.record_training_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("advanced receipt")
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_training_action", fail)
        with pytest.raises(RuntimeError):
            play("training", argument, op="retry-advanced")
    assert snapshot(game[1]) == before
    assert play("training", argument, op="retry-advanced").title


def test_advanced_run_pauses_restores_and_keeps_frozen_rules_after_restart(game, play):
    from dataclasses import replace
    target = setup(game, play)
    play("training", f"开始 穿隙破势 伙伴 {target}")
    plan = plans(saved(game))[True][0]
    play("training", "出手 " + plan[0])
    play("pet_archive", str(target))
    before = snapshot(game[1])
    assert "已封存" in play("training", now=NOW + 86400).text()
    with pytest.raises(GameError, match="已封存"):
        play("training", "出手 " + plan[1], now=NOW + 86400)
    assert snapshot(game[1]) == before
    play("pet_restore", str(target), now=NOW + 86400)
    restarted = Game(game[0].store, game[0].config, game[0].rng,
                     replace(game[0].content, training_trials={}))
    for index, action in enumerate(plan[1:], 1):
        result = restarted.execute("u1", "training", "出手 " + action, f"resumed-advanced-{index}", NOW + 86400)
    assert "通过演练" in result.text()
    assert "羁绊经验+6" in result.text()
    assert items(game[1])["forge_ore"] == 2


def test_advanced_preview_handles_unregistered_no_active_pet_and_configured_prefix(game, play):
    from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
    from nonebot_plugin_spirit_pet.core.config import Config
    before = snapshot(game[1])
    assert "尚未结契" in play("training", "预览 守中求胜").text()
    assert snapshot(game[1]) == before
    target = setup(game, play)
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    page = play("training", f"预览 穿隙破势 伙伴 {target}")
    assert any("开始 穿隙破势" in command for command in page.commands)
    assert f"灵宠技能 伙伴 {target}" in {link.command for link in page.inline_commands}
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    buttons = {button.action.data for segment in native["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons}
    assert len(buttons) <= 4
    assert not buttons & {"!" + link.command for link in page.inline_commands}
    assert all(handlers._parse(link.command) for link in page.inline_commands)
    command = next(command for command in page.commands if "开始" in command)
    assert play(*handlers._parse(command)).title


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_public_advanced_training_uses_shared_numbered_settlement(game, play, monkeypatch, adapter):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from nonebot_plugin_spirit_pet.core.config import Config
    from .test_commands import onebot_event, qq_event
    play("adopt", "青鸾", user="12345")
    target = add_pet(game[1], user_id="12345", species_id="qingluan")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('12345','forge_ore',1)")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    text = f"!灵宠连携演练 开始 穿隙破势 伙伴 {target}"
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    first = bot.send.call_args.args[1]
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert bot.send.call_args.args[1] == first
    assert sql(game[1], "SELECT energy FROM pets ORDER BY pet_id") == [{"energy": 100}, {"energy": 82}]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='forge_ore'") == [{"quantity": 0}]
