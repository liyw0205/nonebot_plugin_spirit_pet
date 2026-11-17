from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, sql
from .test_adventure_travel import NOW, _command, _run, _snapshot
from .test_targeted_training import add_pet


def unlock(game, play):
    play("adopt", "青鸾", now=NOW)
    for key in game[0].content.exploration_routes["spirit_spring"].encounters:
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)", ("echo_" + key,))


def pick(play, reply, option, **kwargs):
    command = next(command for command in reply.commands if command.endswith(" " + option))
    return play(*handlers._parse(command), **kwargs)


def test_revisit_material_choices_pay_real_costs_and_keep_backup_across_restart(game, play):
    unlock(game, play)
    target = add_pet(game[1])
    before = _snapshot(game)
    preview = play("adventure_travel", f"预览 灵泉修行 伙伴 {target}", now=NOW)
    assert preview.commands[0].endswith(f"伙伴 {target}")
    assert _snapshot(game) == before
    page = play(*handlers._parse(preview.commands[0]), now=NOW, op="revisit-start")
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (target,)) == [{"energy": 55}]
    page = pick(play, page, "food", now=NOW, op="revisit-food")
    assert items(game[1])["spirit_food"] == 5
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    assert restarted.execute("u1", "adventure_travel", "", "resume", NOW + 86400).title.startswith("灵宠山海远行")
    page = pick(play, page, "trade", now=NOW + 86400, op="revisit-trade")
    assert items(game[1])["forge_ore"] == 2
    final = pick(play, page, "essence", now=NOW + 86400, op="revisit-end")
    assert final.title == "山海重游完成"
    assert items(game[1])["forge_ore"] == 0
    assert items(game[1])["bloodline_essence"] == 1
    assert sql(game[1], "SELECT stones FROM players")[0]["stones"] == before["players"][0]["stones"] - 100
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (target,)) == [{"exp": 25}]
    assert sql(game[1], "SELECT exp,energy FROM pets WHERE pet_id=1") == [{"exp": 0, "energy": 100}]
    assert len(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'echo_*'")) == 3
    assert sql(game[1], "SELECT * FROM adventure_discoveries") == []
    sql(game[1], "DELETE FROM operations")
    before = _snapshot(game)
    command = _command(page, "选择")
    assert restarted.execute("u1", *handlers._parse(command), "revisit-end", NOW + 172800) == final
    assert _snapshot(game) == before


def test_revisit_day_guards_concurrency_and_original_echo_mode(game, play):
    unlock(game, play)
    def attempt(index):
        try:
            return play("adventure_travel", "重游 灵泉修行 伙伴 1", now=NOW, op=f"open-{index}")
        except GameError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    page = next(result for result in results if not isinstance(result, GameError))
    assert sum(isinstance(result, GameError) for result in results) == 1
    stale = _command(page, "选择")
    page = pick(play, page, "food", now=NOW)
    with pytest.raises(GameError, match="已经处理"):
        play(*handlers._parse(stale), now=NOW)
    quit_command = next(link.command for link in page.inline_commands if link.label == "退出行程")
    play(*handlers._parse(quit_command), now=NOW)
    with pytest.raises(GameError, match="今日重游"):
        play("adventure_travel", "重游 灵泉修行", now=NOW + 1000)
    with pytest.raises(GameError, match="时间早于|系统日期"):
        play("adventure_travel", "重游 灵泉修行", now=NOW - 86400)
    sql(game[1], "UPDATE pets SET energy=100")
    assert play("adventure_travel", "重游 灵泉修行", now=NOW + 86400).title


@pytest.mark.parametrize("phase", ["start", "choice"])
def test_revisit_failed_receipt_rolls_back_all_costs_and_state(game, play, monkeypatch, phase):
    unlock(game, play)
    argument = "重游 灵泉修行"
    if phase == "choice":
        page = play("adventure_travel", argument, now=NOW)
        argument = handlers._parse(next(command for command in page.commands if command.endswith(" ore")))[1]
    before = _snapshot(game)
    original = Repository.record_adventure_travel_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("revisit receipt failure")
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_adventure_travel_action", fail)
        with pytest.raises(RuntimeError):
            play("adventure_travel", argument, now=NOW, op="retry-revisit")
    assert _snapshot(game) == before
    assert play("adventure_travel", argument, now=NOW, op="retry-revisit").title


@pytest.mark.parametrize("blocked", ["archived", "trip", "stones", "food"])
def test_revisit_choice_revalidates_and_can_recover(game, play, blocked):
    unlock(game, play)
    target = add_pet(game[1])
    page = play("adventure_travel", f"重游 灵泉修行 伙伴 {target}", now=NOW)
    if blocked == "archived":
        play("pet_archive", str(target), now=NOW)
    elif blocked == "trip":
        play("switch", str(target), now=NOW)
        play("expedition_start", "采灵药", now=NOW)
    elif blocked == "stones":
        sql(game[1], "UPDATE players SET stones=0")
    else:
        page = pick(play, page, "food", now=NOW)
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    before = _snapshot(game)
    with pytest.raises(GameError):
        pick(play, page, "trade" if blocked == "food" else "ore", now=NOW)
    assert _snapshot(game) == before
    if blocked in {"stones", "food"}:
        assert pick(play, page, "study" if blocked == "food" else "food", now=NOW).title


def test_revisit_unregistered_locked_route_and_no_active_pet(game, play):
    before = _snapshot(game)
    assert "尚未结契" in play("adventure_travel", "预览 灵泉修行", now=NOW).text()
    assert _snapshot(game) == before
    play("adopt", now=NOW)
    with pytest.raises(GameError, match="全部回响"):
        play("adventure_travel", "重游 灵泉修行", now=NOW)
    for key in game[0].content.exploration_routes["spirit_spring"].encounters:
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)", ("echo_" + key,))
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    assert play("adventure_travel", "重游 灵泉修行 伙伴 1", now=NOW).title


def test_alternate_revisit_strategy_and_period_bound_message_contract(game, play):
    from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
    from nonebot_plugin_spirit_pet.core.config import Config

    unlock(game, play)
    preview = play("adventure_travel", "预览 灵泉修行", now=NOW)
    with pytest.raises(GameError, match="过期"):
        play(*handlers._parse(preview.commands[0]), now=NOW + 86400)
    before = _snapshot(game)
    page = play(*handlers._parse(preview.commands[0]), now=NOW)
    for option in ("ore", "study", "escort"):
        _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        buttons = {button.action.data for segment in message["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 3
        assert not buttons & {"!" + link.command for link in page.inline_commands}
        assert all(handlers._parse(command) for command in page.commands)
        page = pick(play, page, option, now=NOW)
    assert items(game[1])["forge_ore"] == 1
    assert sql(game[1], "SELECT stones FROM players")[0]["stones"] == before["players"][0]["stones"] + 50
    assert sql(game[1], "SELECT exp FROM pets")[0]["exp"] == 130
