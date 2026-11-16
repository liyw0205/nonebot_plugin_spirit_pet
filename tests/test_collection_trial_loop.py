from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql
from .test_targeted_care import create_ready_team, snapshot
from .test_targeted_training import NOW, add_pet


def test_free_summon_to_numbered_trial_earns_resources_without_changing_active_roster(game, play):
    play("adopt", "青鸾")
    create_ready_team(play, game[1])
    summoned = play("free_summon_claim", op="weekly-ten")
    command = next(link.command for link in summoned.inline_commands if link.label == "挑战同族幻影")
    target = int(command.rsplit(" ", 1)[-1])
    assert target != 1
    sql(game[1], "UPDATE pets SET realm=6,layer=10 WHERE pet_id=?", (target,))
    before = player(game[1])["stones"]
    reply = play(*handlers._parse(command), op="summoned-trial")
    assert reply.title == "图鉴试炼首通"
    assert player(game[1])["stones"] == before + 200
    assert items(game[1])["forge_ore"] == 1
    assert sql(game[1], "SELECT exp,energy FROM pets WHERE pet_id=?", (target,)) == [{"exp": 150, "energy": 90}]
    assert sql(game[1], "SELECT exp,energy FROM pets WHERE pet_id=1") == [{"exp": 0, "energy": 100}]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": 1}]
    assert any(link.command == f"灵宠整备 {target}" for link in reply.inline_commands)
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "free_summon_claim", "", "weekly-ten", NOW + 86400 * 8) == summoned
    assert reopened.execute("u1", *handlers._parse(command), "summoned-trial", NOW + 86400) == reply
    assert snapshot(game[1]) == before


def test_trial_old_link_keeps_same_species_pet_and_restores_backup_energy(game, play):
    play("adopt", "青鸾")
    target = add_pet(game[1], species_id="qingluan", energy=0)
    sql(game[1], "UPDATE pets SET realm=6,layer=10 WHERE pet_id=?", (target,))
    play("switch", str(target))
    page = play("codex_trials", "2")
    command = next(link.command for link in page.inline_commands if f"伙伴 {target}" in link.command)
    play("switch", "1")
    now = NOW + game[0].config.spirit_pet_energy_interval * 10
    result = play(*handlers._parse(command), now=now)
    assert result.title == "图鉴试炼首通"
    assert sql(game[1], "SELECT energy FROM pets WHERE pet_id=?", (target,)) == [{"energy": 0}]
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=1") == [{"exp": 0}]


@pytest.mark.parametrize("blocked", ["archived", "released", "trip", "foreign", "species"])
def test_numbered_trial_rechecks_roster_ownership_and_species(game, play, blocked):
    play("adopt", "青鸾")
    target = add_pet(game[1])
    if blocked in {"archived", "released"}:
        play("pet_archive", str(target))
        if blocked == "released":
            sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
                (f"released_{target}",))
    elif blocked == "trip":
        play("switch", str(target))
        play("expedition_start", "采灵药")
        play("switch", "1")
    elif blocked == "foreign":
        play("adopt", user="other")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=?", (target,))
    else:
        sql(game[1], "UPDATE pets SET species_id='qingluan' WHERE pet_id=?", (target,))
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("codex_trials", f"挑战 玄狐 伙伴 {target}")
    assert snapshot(game[1]) == before


def test_trial_milestone_receipts_do_not_inflate_species_count(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    species = [key for key in game[0].content.species if key != "qingluan"][:16]
    for key in species:
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,3,1)",
            (f"codex_trial_{key}",))
    sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','codex_trial_milestone_9',1,1)")
    reply = play("codex_trials", "挑战 青鸾 伙伴 1")
    assert "里程碑 18" not in reply.text()
    assert "已通关 17/27" in play("codex_trials").text()
    next_species = next(key for key in game[0].content.species if key not in {*species, "qingluan"})
    target = add_pet(game[1], species_id=next_species)
    sql(game[1], "UPDATE pets SET realm=6,layer=10 WHERE pet_id=?", (target,))
    reply = play("codex_trials", f"挑战 {next_species} 伙伴 {target}", now=NOW + 700)
    assert "里程碑 18 族：血脉精华 +4" in reply.text()
    assert items(game[1])["bloodline_essence"] == 4


def test_free_summon_period_capacity_concurrency_and_clock_rollback(game, play):
    play("adopt")
    game[0].config.spirit_pet_max_pets = 10
    page = play("free_summon")
    assert "还差 1 个空位" in page.text()
    assert "灵宠每周召唤领取" not in {link.command for link in page.inline_commands}
    with pytest.raises(GameError, match="名册上限"):
        play("free_summon_claim")
    game[0].config.spirit_pet_max_pets = 50
    command = play("free_summon").inline_commands[0].command
    next_week = beijing_week(NOW)[1] + 3600
    with pytest.raises(GameError, match="跨周"):
        play(*handlers._parse(command), now=next_week)

    def attempt(index):
        try:
            return play("free_summon_claim", op=f"ten-race-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM pets")) == 11
    play("free_summon_claim", now=next_week)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="系统日期"):
        play("free_summon_claim", now=NOW)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("action,arg", [("free_summon_claim", ""), ("summon", "1"),
                                       ("codex_trials", "挑战 青鸾 伙伴 1")])
def test_collection_settlement_receipt_failure_rolls_back_and_retry_succeeds(game, play, monkeypatch, action, arg):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    before = snapshot(game[1])
    original = Repository.record_duel_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("collection failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError, match="collection failure"):
            play(action, arg, op="retry-collection")
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT * FROM battle_records") == []
    reply = play(action, arg, op="retry-collection")
    assert play(action, arg, op="retry-collection") == reply
